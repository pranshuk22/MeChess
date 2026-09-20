"""A cohort of individual players (many games each), to measure how much players differ and whether style is stable.

Pipeline (each stage is resumable and writes small files under one folder):
  1. collect candidates: stream a Lichess dump (headers only) and remember players per rating bin;
  2. fetch: for each candidate, ask the Lichess API for their recent rated blitz/rapid games, keep ~50 that are
     eligible, and sample a few decisions per game. Raw games are NOT stored; only the sampled decisions
     (position, played move, rating, game number) are written, under a hashed player id;
  3. analyse: run the engine on the decisions (parallel) -> candidate datasets per player (see reliability.py).

Privacy: only public games; the folder holds hashed ids (salted, salt kept locally); usernames stay in
`candidates.json` on the local disk only and must not be published. Bots and accounts flagged for ToS violations are
skipped where the data says so (BOT title in the game headers)."""
import io
import json
import os
import random
import time
from pathlib import Path

import chess
import chess.pgn

from ..ingest import http
from ..ingest.normalize import time_class_from_tc
from ..model.data import CountingReader, iter_game_texts, open_source, quick_headers, text_lines
from .population import PopItem

API = "https://lichess.org/api/games/user/{user}"


def player_id(user, salt):
    import hashlib

    return hashlib.sha256((salt + user.lower()).encode()).hexdigest()[:12]


def rating_bin(elo, lo, bin_width=100, merge_from=2400):
    """Bin index; everything at or above `merge_from` shares the top bin (few players are that strong)."""
    return (min(elo, merge_from) - lo) // bin_width


def n_bins(lo, hi, bin_width=100, merge_from=2400):
    return rating_bin(hi - 1, lo, bin_width, merge_from) + 1


def _ok_headers(tags, time_classes):
    # the dump writes "Rated Blitz game", the games API "rated blitz game": compare case-insensitively
    if tags.get("Variant", "Standard") != "Standard" or not tags.get("Event", "").lower().startswith("rated"):
        return False
    if tags.get("Termination") in ("Abandoned", "Rules infraction"):
        return False
    if "BOT" in (tags.get("WhiteTitle"), tags.get("BlackTitle")):
        return False
    return time_class_from_tc(tags.get("TimeControl", "-")) in time_classes


def collect_candidates(source, *, lo, hi, per_bin, bin_width=100, merge_from=2400, time_classes=("blitz", "rapid"),
                       budget_bytes=None, stats=None):
    """{username: rating seen} with about `per_bin` distinct players per rating bin, from game headers only."""
    nb = n_bins(lo, hi, bin_width, merge_from)
    counts, cand = [0] * nb, {}
    stats = {} if stats is None else stats
    stats.update(games_seen=0, stop_reason="end_of_data")
    binary, close = open_source(source)
    reader = CountingReader(binary, budget_bytes)
    try:
        for text in iter_game_texts(text_lines(reader, str(source).endswith(".zst"))):
            stats["games_seen"] += 1
            tags = quick_headers(text)
            if not _ok_headers(tags, time_classes):
                continue
            for side in ("White", "Black"):
                try:
                    elo = int(tags[f"{side}Elo"])
                except (KeyError, ValueError):
                    continue
                name = tags.get(side, "")
                if not name or name in cand or not lo <= elo < hi:
                    continue
                b = rating_bin(elo, lo, bin_width, merge_from)
                if counts[b] < per_bin:
                    counts[b] += 1
                    cand[name] = elo
            if all(c >= per_bin for c in counts):
                stats["stop_reason"] = "quota"
                break
        else:
            if budget_bytes is not None and reader.count >= budget_bytes:
                stats["stop_reason"] = "budget"
    finally:
        close()
    stats.update(bytes_read=reader.count, per_bin=counts)
    return cand


def fetch_player_games(user, *, want=80, getter=None):
    """PGN texts (newest first) of the player's rated blitz/rapid games, or None if the request failed."""
    getter = getter or http.get
    headers = {"Accept": "application/x-chess-pgn"}
    token = os.environ.get("LICHESS_TOKEN")  # optional; only ever read from the environment
    if token:
        headers["Authorization"] = f"Bearer {token}"
    params = {"max": want, "rated": "true", "perfType": "blitz,rapid", "moves": "true", "tags": "true",
              "clocks": "false", "opening": "false", "evals": "false"}
    try:
        r = getter(API.format(user=user), headers=headers, params=params)
    except (SystemExit, Exception):
        return None
    if r.status_code != 200:
        return None
    return list(iter_game_texts(io.StringIO(r.text)))


def select_games(texts, user, *, n_games, window=150, time_classes=("blitz", "rapid")):
    """[(text, color, own_elo)] for up to `n_games` eligible games where `user` played, near their usual rating."""
    rows = []
    for t in texts:
        tags = quick_headers(t)
        if not _ok_headers(tags, time_classes):
            continue
        low = user.lower()
        if tags.get("White", "").lower() == low:
            color, key = chess.WHITE, "WhiteElo"
        elif tags.get("Black", "").lower() == low:
            color, key = chess.BLACK, "BlackElo"
        else:
            continue
        try:
            rows.append((t, color, int(tags[key])))
        except (KeyError, ValueError):
            continue
    if not rows:
        return []
    med = sorted(r[2] for r in rows)[len(rows) // 2]
    return [r for r in rows if abs(r[2] - med) <= window][:n_games]


def game_decisions(text, color, elo, user, game_idx, *, per_game, min_ply, rng):
    """Up to `per_game` random decisions of the player's own moves in one game."""
    game = chess.pgn.read_game(io.StringIO(text))
    if game is None:
        return []
    board, pool = game.board(), []
    for ply, move in enumerate(game.mainline_moves()):
        if ply >= min_ply and board.turn == color and board.legal_moves.count() >= 2:
            pool.append(PopItem(board.fen(), move.uci(), elo, ply, 0, user, game_idx))
        board.push(move)
    return rng.sample(pool, min(per_game, len(pool)))


def fetch_cohort(candidates, out_dir, salt, *, players, lo, hi, n_games=50, per_game=10, min_ply=8, min_games=30,
                 bin_width=100, merge_from=2400, want=80, pause=1.0, seed=1, getter=None, log=print, max_failures=5):
    """Fetch candidates round-robin over rating bins until `players` are accepted (or candidates run out).

    Writes items/<id>.jsonl per accepted player, plus players.json (id -> bin, rating, games, decisions) and
    rejected.json (ids that failed, so a rerun does not ask again). Safe to interrupt and rerun."""
    out = Path(out_dir)
    (out / "items").mkdir(parents=True, exist_ok=True)
    idx_path, rej_path = out / "players.json", out / "rejected.json"
    index = json.loads(idx_path.read_text()) if idx_path.exists() else {}
    rejected = set(json.loads(rej_path.read_text())) if rej_path.exists() else set()
    nb = n_bins(lo, hi, bin_width, merge_from)
    target = -(-players // nb)
    queues = [[] for _ in range(nb)]
    for name, elo in candidates.items():
        queues[rating_bin(elo, lo, bin_width, merge_from)].append(name)
    have = [sum(1 for v in index.values() if v["bin"] == b) for b in range(nb)]
    tried = {b: 0 for b in range(nb)}
    t0 = time.time()
    failures, tries = 0, {}

    def save():
        idx_path.write_text(json.dumps(index, indent=1))
        rej_path.write_text(json.dumps(sorted(rejected)))

    progress = True
    while progress and sum(have) < players:
        progress = False
        for b in range(nb):
            if have[b] >= target or not queues[b]:
                continue
            user = queues[b].pop(0)
            pid = player_id(user, salt)
            if pid in index or pid in rejected:
                progress = True
                continue
            progress = True
            tried[b] += 1
            texts = fetch_player_games(user, want=want, getter=getter)
            if texts is None:  # the request FAILED (network, rate limit): not the player's fault, so do not reject them
                failures += 1
                tries[user] = tries.get(user, 0) + 1
                log(f"  request for a candidate failed ({failures} in a row); will retry later" if tries[user] < 3 else
                    "  request failed 3 times for a candidate; giving up on them")
                if tries[user] < 3:
                    queues[b].append(user)
                if failures >= max_failures:
                    log(f"  {failures} failed requests in a row: stopping (network down or rate limited); rerun to resume")
                    save()
                    return {"players": len(index), "per_bin": have, "rejected": len(rejected), "stopped": "network"}
                time.sleep(min(60, 5 * failures) if pause else 0)
                continue
            failures = 0
            sel = select_games(texts, user, n_games=n_games) if texts else []
            if len(sel) < min_games:
                rejected.add(pid)
                log(f"  bin {lo + b * bin_width}: rejected a candidate ({len(sel)} eligible games)")
            else:
                rng = random.Random(f"{seed}:{pid}")
                rows = []
                for gi, (text, color, elo) in enumerate(sel):
                    rows += [vars(d) for d in game_decisions(text, color, elo, user, gi, per_game=per_game,
                                                             min_ply=min_ply, rng=rng)]
                for r in rows:
                    r["player"] = pid  # the username never reaches disk in the items
                (out / "items" / f"{pid}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
                index[pid] = {"bin": b, "rating": sorted(g[2] for g in sel)[len(sel) // 2], "games": len(sel),
                              "decisions": len(rows)}
                have[b] += 1
                log(f"  [{time.time() - t0:5.0f}s] {sum(have)}/{players} players "
                    f"(bin {lo + b * bin_width}: {have[b]}/{target}), {len(sel)} games, {len(rows)} decisions")
            save()
            if pause:
                time.sleep(pause)
    save()
    return {"players": len(index), "per_bin": have, "rejected": len(rejected)}


def load_items(path):
    return [PopItem(**json.loads(line)) for line in Path(path).read_text().splitlines() if line.strip()]


def analyse_player(args):
    """Worker (top level so it can be pickled): engine candidates for one player's decisions -> cands/<id>.npz."""
    items_path, out_path, engine, nodes, multipv, window = args
    from ..uci_client import UciEngine
    from . import candidates as SC

    items = load_items(items_path)
    positions = []
    with UciEngine(engine, options=SC.engine_options(engine, multipv)) as eng:
        for it in items:
            p = SC.candidates_for(eng, it, nodes=nodes, multipv=multipv, window=window)
            if p is not None:
                positions.append(p)
    SC.save(positions, out_path, judge=SC.judge_label(engine, nodes))
    return Path(items_path).stem, len(items), len(positions)


def analyse_cohort(out_dir, engine, *, nodes=20000, multipv=8, window=60, workers=4, log=print):
    """Run the engine over every fetched player that has no candidate file yet (parallel, resumable)."""
    import multiprocessing

    out = Path(out_dir)
    (out / "cands").mkdir(exist_ok=True)
    todo = [(str(p), str(out / "cands" / f"{p.stem}.npz"), str(engine), nodes, multipv, window)
            for p in sorted((out / "items").glob("*.jsonl")) if not (out / "cands" / f"{p.stem}.npz").exists()]
    log(f"{len(todo)} players to analyse with {workers} engines")
    t0, done = time.time(), 0
    with multiprocessing.get_context("spawn").Pool(workers) as pool:
        for pid, n, k in pool.imap_unordered(analyse_player, todo):
            done += 1
            log(f"  [{time.time() - t0:5.0f}s] {done}/{len(todo)} {pid}: {k} of {n} decisions had a choice")
    return len(todo)
