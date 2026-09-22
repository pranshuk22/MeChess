"""Personal report, step 2: where expected points are lost ("leaks"), and whether that ranking is a stable trait.

Built on top of `chessme analyse`'s per-game JSON files (`runner.analyse_game`): every one of the player's moves already
carries `loss` (expected points given away by that move), `phase` and the game's headers (opening ECO). This module buckets
those losses (by opening, by phase) and ranks the buckets by mean loss - the "leaks".

A ranking from one batch of games could easily be noise. The stability test follows the split-half method already used for
style (`style/reliability.py`): split the games into two halves (alternating, so both cover the whole period), rank the
buckets independently on each half, and correlate the two rankings (Spearman, restricted to buckets with enough decisions in
both halves). Low correlation means the "leaks" are not a stable pattern for this player yet - plan.md 8s says to stop there
rather than build a difficulty model on a ranking that would not replicate.
"""
import json
from pathlib import Path

import numpy as np

STABLE_THRESHOLD = 0.5     # same convention as the style-reliability gate (gamestats.py / plan.md 8n)
MIN_BUCKETS_TO_COMPARE = 3  # a correlation over fewer points is not meaningful; 'phase' only ever HAS 3 buckets, so this must not exceed 3


def load_results(out_dir):
    """[(key, result), ...] for every analysed game under `out_dir/games/`, sorted by key (oldest-looking first)."""
    games = Path(out_dir) / "games"
    return [(p.stem, json.loads(p.read_text())) for p in sorted(games.glob("*.json"))]


def opening_key(headers):
    """The player's opening bucket for a game: the ECO code if there is one, else the opening name, else 'unknown'."""
    eco = (headers or {}).get("ECO", "").strip()
    if eco:
        return eco
    name = (headers or {}).get("Opening", "").strip()
    return name or "unknown"


def player_moves(results, by):
    """One row per move of the player's colour, across all analysed games: {"game", "loss", "key"} where `key` is the
    opening or phase bucket named by `by` ('opening' or 'phase')."""
    key_fn = opening_key if by == "opening" else (lambda h: None)
    rows = []
    for key, res in results:
        color = res.get("player_color")
        if not color:
            continue
        bucket = key_fn(res.get("headers"))
        for m in res["moves"]:
            if m["color"] != color:
                continue
            rows.append({"game": key, "loss": m["loss"], "key": bucket if by == "opening" else m["phase"]})
    return rows


def split_halves(results):
    """(A, B): alternate games (by key order) go to each half, so both cover the whole period analysed."""
    ordered = sorted(results, key=lambda kr: kr[0])
    return ordered[0::2], ordered[1::2]


def bucket_stats(rows, min_n=1):
    """{bucket: {"n", "mean_loss", "total_loss"}} for buckets with at least `min_n` moves."""
    by = {}
    for r in rows:
        by.setdefault(r["key"], []).append(r["loss"])
    return {k: {"n": len(v), "mean_loss": float(np.mean(v)), "total_loss": float(np.sum(v))} for k, v in by.items() if len(v) >= min_n}


def _ranks(xs):
    """Average ranks (ties share the mean rank), for a Spearman correlation with no scipy dependency."""
    order = np.argsort(xs)
    ranks = np.empty(len(xs))
    ranks[order] = np.arange(len(xs))
    xs = np.asarray(xs)
    for v in np.unique(xs):
        idx = np.where(xs == v)[0]
        ranks[idx] = ranks[idx].mean()
    return ranks


def spearman(xs, ys):
    """Spearman rank correlation of two equal-length sequences; NaN if either has no variance."""
    if len(xs) < 2:
        return float("nan")
    ra, rb = _ranks(xs), _ranks(ys)
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def stability(results, by="opening", min_n=8):
    """The leak ranking over all games, plus its split-half stability: {"table": [(bucket, stats), ...] sorted by mean
    loss descending, "correlation", "n_buckets_compared", "n_games", "stable": bool or None (None = not enough data to say)."""
    a, b = split_halves(results)
    stats_a = bucket_stats(player_moves(a, by), min_n=max(1, min_n // 2))
    stats_b = bucket_stats(player_moves(b, by), min_n=max(1, min_n // 2))
    common = sorted(set(stats_a) & set(stats_b))
    enough = len(common) >= MIN_BUCKETS_TO_COMPARE
    corr = spearman([stats_a[k]["mean_loss"] for k in common], [stats_b[k]["mean_loss"] for k in common]) if enough else float("nan")
    full = bucket_stats(player_moves(results, by), min_n=min_n)
    table = sorted(full.items(), key=lambda kv: -kv[1]["mean_loss"])
    return {"by": by, "table": table, "correlation": corr, "n_buckets_compared": len(common), "n_games": len(results),
            "stable": (corr >= STABLE_THRESHOLD) if enough and corr == corr else None}


def render(stab, top=15):
    """Plain-text leak ranking and the stability verdict."""
    L = [f"Personal report - leaks by {stab['by']} ({stab['n_games']} games analysed)", ""]
    L.append(f"{'bucket':22s} {'n':>5s} {'mean loss':>10s} {'total loss':>11s}")
    for k, s in stab["table"][:top]:
        L.append(f"{str(k)[:22]:22s} {s['n']:5d} {s['mean_loss']:10.3f} {s['total_loss']:11.2f}")
    L.append("")
    if stab["stable"] is None:
        L.append(f"Split-half stability: not enough overlapping buckets ({stab['n_buckets_compared']}) to test yet - need more games.")
    else:
        verdict = "stable enough to build on" if stab["stable"] else "NOT stable - do not build a difficulty model on this ranking yet (plan.md 8s)"
        L.append(f"Split-half stability: rank correlation {stab['correlation']:+.2f} over {stab['n_buckets_compared']} buckets ({verdict}).")
    return "\n".join(L) + "\n"


def _bucket_phrase(key, s):
    return f"{key} ({s['mean_loss']:.3f} expected points per move, {s['n']} moves, {s['total_loss']:.1f} total)"


def render_english(stab, top=3):
    """A plain-English paragraph over the same numbers `render` tables - no model, so every sentence is a direct read of
    the computed stats (nothing here can be a claim the data does not support)."""
    label = "opening" if stab["by"] == "opening" else "game phase"
    table = stab["table"]
    if not table:
        return f"Not enough analysed games yet to rank leaks by {label}.\n"
    rows = table[:top]
    lead = f"Across {stab['n_games']} analysed games, the costliest {label} is {_bucket_phrase(*rows[0])}."
    if len(rows) > 1:
        lead += " Next: " + "; then ".join(_bucket_phrase(k, s) for k, s in rows[1:]) + "."
    if stab["stable"] is None:
        verdict = (f"There are not enough games yet to tell whether this ranking is real: only {stab['n_buckets_compared']} {label} "
                   "buckets had enough moves in both halves of a split-half check. Treat it as provisional until more games are analysed.")
    elif stab["stable"]:
        verdict = (f"This ranking held up in a split-half check (games split into two halves, rank correlation "
                   f"{stab['correlation']:+.2f} over {stab['n_buckets_compared']} buckets), so it looks like a real, repeatable pattern "
                   "rather than noise from this particular batch of games.")
    else:
        verdict = (f"This ranking did NOT hold up in a split-half check (rank correlation {stab['correlation']:+.2f} over "
                   f"{stab['n_buckets_compared']} buckets) - the two halves disagree about where the leaks are, so treat this as noise "
                   "for now, not a real pattern.")
    return lead + " " + verdict + "\n"
