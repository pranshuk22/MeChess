"""Anchor players: famous players whose style vectors are the landmarks of the style report.

The anchors are NOT the yardstick for "how unusual are you" (they are a few extreme, hand-picked individuals; the wide
cohort is that yardstick). They give names and coordinates: which anchor's preferences predict your choices best, and
whether the features can tell the anchors apart at all (the validation that must pass before any "Tal-like" claim).

Game files are supplied by the user; the code only reads them. Decisions are written in the cohort layout
(items/<id>.jsonl) so the same engine step (style-cohort-analyze) and reliability tests apply unchanged."""
import io
import json
import random
import re
import unicodedata
import zipfile
from pathlib import Path

import chess
import chess.pgn
import numpy as np

from ..model.data import iter_game_texts, quick_headers
from . import model as M
from .population import PopItem


def normalise(name):
    """Lowercase, accents and punctuation removed, single spaces: 'Tal, Mikhail' -> 'tal mikhail'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s)).strip()


def matches(pgn_name, aliases):
    """True if the PGN name equals an alias, or starts with an alias that has no first name spelled out (e.g. 'Tal, M')."""
    n = normalise(pgn_name)
    return any(n == a or n.startswith(a + " ") for a in map(normalise, aliases))


def read_game_texts(path):
    """Game texts from a .pgn or a .zip that contains one or more .pgn files."""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.lower().endswith(".pgn"):
                    with z.open(name) as f:
                        yield from iter_game_texts(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))
    else:
        with open(path, encoding="utf-8", errors="replace") as f:
            yield from iter_game_texts(f)


# Events whose games are not comparable "serious classical play" (a name or site containing any of these is excluded).
EXCLUDE_WORDS = ("blitz", "rapid", "simul", "exhibition", "armageddon", "bullet", "online", "chess.com", "lichess",
                 "internet", "freestyle", "chess960", "fischerandom", "fischer random", "blindfold", "odds", "speed")


def _year(tags):
    m = re.match(r"(\d{4})", tags.get("Date", "") or tags.get("UTCDate", ""))
    return int(m.group(1)) if m else None


def _serious(tags, exclude):
    text = " ".join(tags.get(k, "") for k in ("Event", "Site", "Round")).lower()
    if any(w in text for w in exclude):
        return False
    tc = tags.get("TimeControl", "")
    if tc and tc[0].isdigit():  # e.g. "300+3": base seconds below 15 minutes is not classical
        try:
            return int(tc.replace("+", "/").split("/")[0].split(":")[-1]) >= 900
        except ValueError:
            return True
    return True


def anchor_games(texts, aliases, *, min_year=None, max_year=None, exclude=EXCLUDE_WORDS, stats=None):
    """[(text, color, own_elo or 0)] for the anchor's serious games (standard chess) dated within [min_year, max_year].
    With a year bound, games without a usable date are excluded. `stats` (a dict, filled in place) counts what was
    seen and why games were dropped: seen, anchor_games, not_serious, variant, no_date, outside_window, kept."""
    out = []
    st = stats if stats is not None else {}
    st.update(seen=0, anchor_games=0, not_serious=0, variant=0, no_date=0, outside_window=0, kept=0)
    for t in texts:
        st["seen"] += 1
        tags = quick_headers(t)
        if matches(tags.get("White", ""), aliases):
            color, key = chess.WHITE, "WhiteElo"
        elif matches(tags.get("Black", ""), aliases):
            color, key = chess.BLACK, "BlackElo"
        else:
            continue
        st["anchor_games"] += 1
        if tags.get("Variant", "Standard") not in ("Standard", "standard"):
            st["variant"] += 1
            continue
        if not _serious(tags, exclude):
            st["not_serious"] += 1
            continue
        year = _year(tags)
        if (min_year or max_year) and year is None:
            st["no_date"] += 1
            continue
        if (min_year and year < min_year) or (max_year and year > max_year):
            st["outside_window"] += 1
            continue
        try:
            elo = int(tags.get(key, 0) or 0)
        except ValueError:
            elo = 0
        st["kept"] += 1
        out.append((t, color, elo))
    return out


def decisions(games, key, *, max_games=400, per_game=8, min_ply=8, min_plies=24, seed=1, used_out=None):
    """Random games are tried in turn until `max_games` valid ones (at least `min_plies` half-moves, parseable) are
    used; from each, a few of the anchor's own decisions -> PopItems (game index for split-half tests).
    `used_out` (a list) receives (year, colour) of every game used, for reporting."""
    rng = random.Random(f"{seed}:{key}")
    order = rng.sample(games, len(games))
    items, used = [], 0
    for text, color, elo in order:
        if used >= max_games:
            break
        game = chess.pgn.read_game(io.StringIO(text))
        if game is None:
            continue
        board, pool, plies = game.board(), [], 0
        try:
            for ply, move in enumerate(game.mainline_moves()):
                if ply >= min_ply and board.turn == color and board.legal_moves.count() >= 2:
                    pool.append(PopItem(board.fen(), move.uci(), elo, ply, 0, key, used))
                board.push(move)
                plies = ply + 1
        except ValueError:
            continue
        if plies < min_plies or not pool:
            continue
        items += rng.sample(pool, min(per_game, len(pool)))
        used += 1
        if used_out is not None:
            used_out.append((_year(quick_headers(text)), color))
    return items


def name_census(texts, aliases, top=None):
    """[(name as spelled in the archive, games, matched?)], most frequent first (all names unless `top`). Archives spell
    the same player differently ('Jobava,Ba', 'Kortschnoj, Viktor', 'Karpov,Ana'); a frequent name that resembles the
    anchor's surname but is NOT matched means games are being silently missed."""
    from collections import Counter
    c = Counter()
    for t in texts:
        tags = quick_headers(t)
        for side in ("White", "Black"):
            if tags.get(side):
                c[tags[side]] += 1
    return [(n, k, matches(n, aliases)) for n, k in c.most_common(top)]


def unmatched_variants(census, aliases, *, min_games=20, similarity=0.75):
    """Unmatched names (with at least `min_games` games) whose surname equals or closely resembles the anchor's:
    likely spelling or transliteration variants that should be added to the aliases."""
    from difflib import SequenceMatcher
    sur = normalise(aliases[0].split(",")[0])
    out = []
    for n, k, ok in census:
        if ok or k < min_games:
            continue
        first = normalise(n.split(",")[0]) if "," in n else normalise(n).split(" ")[0]
        if first == sur or SequenceMatcher(None, first, sur).ratio() >= similarity:
            out.append((n, k))
    return out


def games_in_peak(paths, spec, *, want, widen_step=2, widen_max=6, attempts=None, census_out=None):
    """Serious games of the anchor inside the configured peak years (`years: [a, b]`); if fewer than `want` exist the
    window is widened by `widen_step` years on each side, up to `widen_max`. Returns (games, window_used, last_stats);
    `attempts` (a list) receives [window, games kept, stats] per try."""
    lo, hi = (spec.get("years") or [None, None])
    texts = [t for p in paths for t in read_game_texts(p)]
    if census_out is not None:
        census_out.extend(name_census(texts, spec["aliases"]))
    for extra in range(0, widen_max + 1, widen_step):
        w = (lo - extra if lo else None, hi + extra if hi else None)
        st = {}
        games = anchor_games(texts, spec["aliases"], min_year=w[0], max_year=w[1], stats=st)
        if attempts is not None:
            attempts.append([list(w), len(games), dict(st)])
        if len(games) >= want or not lo:
            break
    return games, w, st


def build_one(key, spec, paths, out_dir, *, max_games, per_game, seed=1):
    """Write items/anchor_<key>.jsonl from the given game files; returns the index entry (with the numbers to log)."""
    attempts = []
    census = []
    games, window, st = games_in_peak(paths, spec, want=max_games, attempts=attempts, census_out=census)
    used_out = []
    items = decisions(games, key, max_games=max_games, per_game=per_game, seed=seed, used_out=used_out)
    Path(out_dir, "items").mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "items" / f"anchor_{key}.jsonl").write_text("\n".join(json.dumps(vars(i)) for i in items))
    years = [y for y, _ in used_out if y]
    elos = [g[2] for g in games if g[2]]
    return {"games_available": len(games), "games_used": len(used_out), "decisions": len(items), "window": list(window),
            "peak_years": spec.get("years"), "hypothesis": spec.get("hypothesis", ""), "filter_counts": st,
            "attempts": attempts, "used_years": [min(years), max(years)] if years else None,
            "used_white": sum(1 for _, c in used_out if c == chess.WHITE), "used_black": sum(1 for _, c in used_out if c == chess.BLACK),
            "mean_elo": round(sum(elos) / len(elos)) if elos else None, "census": census[:8],
            "unmatched_variants": unmatched_variants(census, spec["aliases"])}


def build_anchors(config, files_dir, out_dir, *, max_games=100, per_game=10, only_selected=True, log=print):
    """For every (selected) anchor with a game file (<key>.pgn / .zip) in files_dir, sample decisions from the peak years."""
    out = Path(out_dir)
    (out / "items").mkdir(parents=True, exist_ok=True)
    index = {}
    for key, spec in config["anchors"].items():
        if only_selected and not spec.get("selected", True):
            continue
        paths = [p for p in Path(files_dir).glob("*") if p.suffix.lower() in (".pgn", ".zip") and key in p.stem.lower()]
        if not paths:
            log(f"  {key}: no game file in {files_dir} (skipped)")
            continue
        index[f"anchor_{key}"] = build_one(key, spec, paths, out, max_games=max_games, per_game=per_game)
        e = index[f"anchor_{key}"]
        log(f"  {key}: {e['games_available']} games in {e['window']}, {e['games_used']} used, {e['decisions']} decisions")
    (out / "players.json").write_text(json.dumps(index, indent=1))
    return index


# ---- comparison ---------------------------------------------------------------------------------------------------

def _usable(ps):
    return [p for p in ps if p.chosen >= 0 and len(p.cands) >= 2]


def _halves(positions):
    games = sorted({p.game for p in positions})
    a = set(games[0::2])
    return [p for p in positions if p.game in a], [p for p in positions if p.game not in a]


def fit_anchors(anchors, l2=1.0, min_usable=100):
    """({key: model fitted on the anchor's first half of games}, {key: second half}, common standardiser)."""
    keep = {k: _halves(v) for k, v in anchors.items()}
    keep = {k: h for k, h in keep.items() if len(_usable(h[0])) >= min_usable and len(_usable(h[1])) >= min_usable}
    if len(keep) < 2:
        raise ValueError("need at least two anchors with enough usable decisions in both halves")
    std = M.standardiser([p for a, _ in keep.values() for p in a])
    fitted = {k: M.fit(a, l2=l2, standardise=std) for k, (a, _) in keep.items()}
    held = {k: b for k, (_, b) in keep.items()}
    return fitted, held, std


def _loglik(model, positions):
    """Total log-likelihood of the chosen moves under `model` (natural log)."""
    return -M.evaluate(model, positions)["style"]["nll"] * len(_usable(positions))


def anchor_confusion(anchors, chunk=30, l2=1.0, min_usable=100):
    """Can the features tell the anchors apart? Held-out decisions (other half of each anchor's games) are cut into
    chunks of `chunk` decisions; each chunk is assigned to the anchor model that gives it the highest likelihood.
    Returns {"keys", "confusion" (rows = true anchor), "accuracy", "chance"}."""
    fitted, held, _ = fit_anchors(anchors, l2, min_usable)
    keys = sorted(fitted)
    conf = np.zeros((len(keys), len(keys)), dtype=int)
    for i, k in enumerate(keys):
        us = _usable(held[k])
        for s in range(0, len(us) - chunk + 1, chunk):
            part = us[s:s + chunk]
            conf[i, int(np.argmax([_loglik(fitted[j], part) for j in keys]))] += 1
    total = conf.sum()
    return {"keys": keys, "confusion": conf, "accuracy": float(np.trace(conf) / total) if total else float("nan"),
            "chance": 1.0 / len(keys), "chunks": int(total)}


def rank_anchors(anchors, player_positions, l2=1.0, min_usable=100, player_test=None):
    """Which anchor's preferences predict the player's choices best? [(key, NLL per decision)], best first, plus the
    player's own-style NLL and the uniform baseline, all on held-out decisions. With `player_test` the player's own
    style is fitted on `player_positions` and everything is scored on `player_test` (e.g. a time split of their games);
    otherwise the player's games are split into alternating halves."""
    fitted, _, std = fit_anchors(anchors, l2, min_usable)
    a, b = (player_positions, player_test) if player_test is not None else _halves(player_positions)
    own = M.evaluate(M.fit(a, l2=l2, standardise=std), b)
    rows = sorted(((k, M.evaluate(m, b)["style"]["nll"]) for k, m in fitted.items()), key=lambda t: t[1])
    return {"anchors": rows, "own": own["style"]["nll"], "uniform": own["uniform"]["nll"], "n": own["n"]}


def render(conf, rank=None, hypotheses=None):
    keys = conf["keys"]
    lines = [f"Can the features tell the anchors apart? {conf['chunks']} held-out chunks; accuracy {100 * conf['accuracy']:.0f}% "
             f"(chance {100 * conf['chance']:.0f}%). Rows = true anchor, columns = assigned:", "",
             "  " + " " * 12 + " ".join(f"{k[:9]:>9s}" for k in keys)]
    for i, k in enumerate(keys):
        lines.append(f"  {k:12s}" + " ".join(f"{conf['confusion'][i, j]:9d}" for j in range(len(keys))))
    if rank:
        lines += ["", f"Which anchor's preferences predict your choices best? ({rank['n']} decisions; lower log-loss is better)"]
        for k, v in rank["anchors"]:
            lines.append(f"  {k:12s} {v:.3f}" + (f"   ({hypotheses[k]})" if hypotheses and k in hypotheses else ""))
        lines += [f"  {'your own style':12s} {rank['own']:.3f}", f"  {'uniform':12s} {rank['uniform']:.3f}"]
    return "\n".join(lines)
