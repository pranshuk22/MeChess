"""Cohort v2: refetch each cohort player's recent games WITH clocks and opening tags, compute the game-level features (opening,
clock use, game shape) at fetch time and store them, plus a compressed local copy of the moves and clocks.

Resumable at every player: a finished player is one file (written atomically), a rerun skips them. Pause / resume / stop through
`chessme.jobs` (files in data/control/), checked before every player. Public games only; players are stored under the same salted hashed
ids as the v1 cohort (usernames are looked up from the local candidates file and never written to the output); the output stays under
data/ (git-ignored) and must not be published."""
import gzip
import io
import json
import time
from pathlib import Path

import chess
import chess.pgn

from ..ingest import http
from ..jobs import JobControl, Stopped
from . import cohort as CO
from . import gamefeatures as G

API = CO.API


def fetch_games(user, *, want=80, getter=None):
    """PGN texts (newest first) with clocks and opening tags, or None if the request failed."""
    getter = getter or http.get
    headers = {"Accept": "application/x-chess-pgn"}
    params = {"max": want, "rated": "true", "perfType": "blitz,rapid", "moves": "true", "tags": "true", "clocks": "true",
              "opening": "true", "evals": "false"}
    try:
        r = getter(API.format(user=user), headers=headers, params=params)
    except (SystemExit, Exception):
        return None
    if r.status_code != 200:
        return None
    return list(CO.iter_game_texts(io.StringIO(r.text)))


def game_record(text, color, elo):
    """Per-game record: feature list (None for NaN), meta, the moves as one UCI string, and the clock after every ply."""
    out = G.game_features(text, color)
    if out is None:
        return None
    feat, meta = out
    game = chess.pgn.read_game(io.StringIO(text))
    moves, clocks, node = [], [], game
    while node.variations:
        node = node.variations[0]
        moves.append(node.move.uci())
        c = node.clock()
        clocks.append(None if c is None else round(c, 2))
    return {"feat": [None if v != v else round(float(v), 5) for v in (feat[n] for n in G.FEATURE_NAMES)], "meta": meta,
            "moves": " ".join(moves), "clocks": clocks, "elo": elo}


def write_player(path, payload):
    """Atomic gzip-JSON write: a killed run never leaves a half-written player file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".partial")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    tmp.rename(path)


def read_player(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def usernames_by_id(cohort_dir):
    """{hashed id: username} for the players of a v1 cohort (from its local candidates file and salt)."""
    d = Path(cohort_dir)
    salt = (d / "salt").read_text().strip()
    ids = json.loads((d / "players.json").read_text())
    cands = json.loads((d / "candidates.json").read_text())
    by_id = {CO.player_id(u, salt): u for u in cands}
    return {pid: by_id[pid] for pid in ids if pid in by_id}, ids


def run(cohort_dir, out_dir, *, n_games=50, min_games=30, want=80, pause=1.0, getter=None, control_dir="data/control", log=print,
        max_failures=5, job="fetch2", limit=None):
    """Fetch and process every v1 cohort player not yet done. Returns a summary dict; `stopped` is set if a stop was requested."""
    out = Path(out_dir)
    (out / "games").mkdir(parents=True, exist_ok=True)
    users, ids = usernames_by_id(cohort_dir)
    todo = [pid for pid in sorted(ids) if pid in users and not (out / "games" / f"{pid}.json.gz").exists()]
    if limit:
        todo = todo[:limit]
    log(f"{len(todo)} players to fetch ({len(ids) - len(users)} have no username on record and are skipped); {n_games} games each")
    ctl = JobControl(job, control_dir, log=log)
    stats = {"done": 0, "short": 0, "failed": 0, "stopped": False, "network": False}
    failures, t0 = 0, time.time()
    with ctl.signals():
        for i, pid in enumerate(todo, 1):
            try:
                ctl.checkpoint()
            except Stopped as e:
                log(f"stopped ({e}); {stats['done']} done in this run, rerun the same command to resume")
                stats["stopped"] = True
                break
            user = users[pid]
            texts = fetch_games(user, want=want, getter=getter)
            if texts is None:
                failures += 1
                stats["failed"] += 1
                log(f"  request failed ({failures} in a row)")
                if failures >= max_failures:
                    log("too many failed requests in a row: stopping (network down or rate limited); rerun to resume")
                    stats["network"] = True
                    break
                time.sleep(min(60, 5 * failures) if pause else 0)
                continue
            failures = 0
            sel = CO.select_games(texts, user, n_games=n_games)
            if len(sel) < min_games:
                write_player(out / "games" / f"{pid}.json.gz", {"pid": pid, "short": True, "n": len(sel), "games": []})
                stats["short"] += 1
                log(f"  [{time.time() - t0:5.0f}s] {i}/{len(todo)}: only {len(sel)} eligible games, kept as short")
            else:
                recs = [r for r in (game_record(t, c, e) for t, c, e in sel) if r is not None]
                rating = sorted(g["elo"] for g in recs)[len(recs) // 2]
                write_player(out / "games" / f"{pid}.json.gz", {"pid": pid, "short": False, "rating": rating, "n": len(recs),
                                                                 "names": list(G.FEATURE_NAMES), "games": recs})
                stats["done"] += 1
                log(f"  [{time.time() - t0:5.0f}s] {i}/{len(todo)}: {len(recs)} games, rating ~{rating}")
            if pause:
                time.sleep(pause)
    return stats


def load_players(out_dir, min_games=30):
    """{pid: (rating, features array (n, F) with NaN, metas)} for every finished, non-short player."""
    import numpy as np

    out = {}
    for path in sorted((Path(out_dir) / "games").glob("*.json.gz")):
        d = read_player(path)
        if d.get("short") or len(d["games"]) < min_games:
            continue
        arr = np.array([[float("nan") if v is None else v for v in g["feat"]] for g in d["games"]], dtype=float)
        out[d["pid"]] = (d["rating"], arr, [g["meta"] for g in d["games"]])
    return out
