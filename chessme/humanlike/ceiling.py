"""How much room is there above a model on positions that many players have faced? The opening explorer has exact counts of every move
played at a position, by rating band, over a whole month. For a position seen T times the best any model can do is predict the empirical
distribution of those T moves; that oracle's top-1 and sampled match are an upper bound on what a move model can score there.

Leave-one-out: the test position's own game is inside the explorer's counts (same month), so it is taken out of the counts before
the oracle predicts its move; otherwise the oracle would be graded on data it was built from.

What is exact and what is bounded. The explorer lists a move at a position only if it was played at least `floor` times in the band (the
floor scales with the band's size); the position's total number of games is exact. So the oracle's top-1 is exact (a missing move can never be
the most played one, because every listed move has at least `floor` games), while its sampled match is a range: a missing played move has
between 0 and floor-1 games. Positions that are not in the database at all were seen fewer times than the floor and carry no oracle.
Only the first plies are in the explorer (24), so recurrence beyond the opening cannot be measured this way."""
import sqlite3

import numpy as np

from ..book import explorer as EX
from . import metrics as M

MAX_PLY = 24
T_EDGES = (1, 10, 100, 1_000, 10_000, 100_000)           # strata of the number of OTHER games that reached the position
T_LABELS = ("1-9", "10-99", "100-999", "1k-10k", "10k-100k", "100k+")


def band_of_ratings(db, white_or_me, opp):
    """The band id of a game from its two ratings, or None when no band holds the average."""
    avg = (white_or_me + opp) / 2.0
    r = db.execute("SELECT id FROM bands WHERE lo <= ? AND ? < hi", (avg, avg)).fetchone()
    return None if r is None else r[0]


def lookup(db_path, positions, max_diff=300):
    """For each position (`testset.Position`) the explorer's counts at it, in the band of the game's average rating.
    Returns arrays (one row per position): `band`, `floor`, `in_db`, `total` (all games that reached it, this game included when it counts),
    `own` (1 when this game is itself in the counts), `c_played` (games that played the human's move, -1 when not listed), `c_other_max`
    (the most played OTHER listed move) and `n_other_max` (how many other moves tie at that count)."""
    import chess
    n = len(positions)
    out = {"band": np.full(n, -1, dtype=np.int32), "floor": np.zeros(n, dtype=np.int64), "in_db": np.zeros(n, dtype=bool),
           "total": np.zeros(n, dtype=np.int64), "own": np.zeros(n, dtype=np.int64), "c_played": np.full(n, -1, dtype=np.int64),
           "c_other_max": np.zeros(n, dtype=np.int64), "n_other_max": np.zeros(n, dtype=np.int64)}
    db = sqlite3.connect(db_path)
    min_games, min_frac = (float(db.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()[0]) for k in ("min_games", "min_frac"))
    games = {r[0]: r[1] for r in db.execute("SELECT id, games FROM bands")}
    cache = {}
    for i, p in enumerate(positions):
        if p.ply >= MAX_PLY:
            continue
        b = band_of_ratings(db, p.me, p.opp)
        if b is None:
            continue
        out["band"][i] = b
        out["floor"][i] = EX.scaled_min(min_games, min_frac, games[b])
        out["own"][i] = 1 if abs(p.me - p.opp) <= max_diff else 0                 # the explorer only counts games between similar players
        board = chess.Board(p.fen)
        key = EX.signed64(EX.pos_key(board))
        if (b, key) not in cache:
            t = db.execute("SELECT games FROM positions WHERE band=? AND pos=?", (b, key)).fetchone()
            rows = db.execute("SELECT uci, games FROM moves WHERE band=? AND pos=?", (b, key)).fetchall() if t else []
            cache[(b, key)] = (t[0] if t else None, rows)
            if len(cache) > 400_000:
                cache.pop(next(iter(cache)))
        total, rows = cache[(b, key)]
        if total is None:
            continue
        out["in_db"][i], out["total"][i] = True, total
        others = [g for uci, g in rows if uci != p.played]
        for uci, g in rows:
            if uci == p.played:
                out["c_played"][i] = g
        if others:
            out["c_other_max"][i] = max(others)
            out["n_other_max"][i] = others.count(max(others))
    db.close()
    return out


def oracle(look):
    """Leave-one-out oracle on each position that has one (`ok`): top-1 chance (ties split), the range of its sampled match, and the stratum.
    Returns arrays: ok, t_other (games other than this one that reached the position), top1, sampled_lo, sampled_hi, stratum (-1 = none)."""
    t_other = look["total"] - look["own"]
    ok = look["in_db"] & (t_other >= 1)
    listed = look["c_played"] >= 0
    cp = np.where(listed, np.maximum(look["c_played"] - look["own"], 0), 0)
    top1 = np.zeros(len(t_other))
    ahead, tie = cp > look["c_other_max"], (cp == look["c_other_max"]) & listed & (look["c_other_max"] > 0)
    top1[ok & listed & ahead] = 1.0
    top1[ok & tie] = 1.0 / (1 + look["n_other_max"][ok & tie])
    denom = np.maximum(t_other, 1)
    sampled_lo = cp / denom
    sampled_hi = np.where(listed, cp, np.minimum(look["floor"] - 1, t_other)) / denom
    stratum = np.where(ok, np.digitize(t_other, T_EDGES) - 1, -1)
    return {"ok": ok, "t_other": t_other, "top1": top1, "sampled_lo": sampled_lo, "sampled_hi": sampled_hi, "stratum": stratum}


def table(scores, arr, orc, n_boot=500, seed=0, min_n=100):
    """Per recurrence stratum: positions, the model's top-1 and sampled match, the oracle's, and the paired gap (model - oracle) with a game-level
    interval. A gap near zero means the model already predicts these positions as well as the counts of everyone else; a large negative gap is
    headroom for a better model (up to the position's irreducible randomness)."""
    g = arr["gid"]
    rows = {}
    labels = [("all positions with an oracle", orc["ok"])] + [(f"seen by {T_LABELS[k]} other games", orc["ok"] & (orc["stratum"] == k)) for k in range(len(T_LABELS))]
    for label, sel in labels:
        if sel.sum() < min_n:
            continue
        mt = scores["top1"].astype(float)
        row = {"n": int(sel.sum()), "games": int(len(np.unique(g[sel]))),
               "model_top1": M.cluster_bootstrap_mean(mt, g, n_boot=n_boot, seed=seed, mask=sel)[:3],
               "oracle_top1": M.cluster_bootstrap_mean(orc["top1"], g, n_boot=n_boot, seed=seed, mask=sel)[:3],
               "gap_top1": M.paired_cluster_bootstrap(mt, orc["top1"], g, n_boot=n_boot, seed=seed, mask=sel)[:3],
               "model_sampled": M.cluster_bootstrap_mean(scores["p"], g, n_boot=n_boot, seed=seed, mask=sel)[:3],
               "oracle_sampled_lo": float(orc["sampled_lo"][sel].mean()), "oracle_sampled_hi": float(orc["sampled_hi"][sel].mean())}
        rows[label] = row
    return rows


def _ci(t, digits=1):
    return f"{100 * t[0]:.{digits}f} [{100 * t[1]:.{digits}f}, {100 * t[2]:.{digits}f}]"


def render(rows, title=""):
    lines = [title] if title else []
    lines += ["| positions seen before by | positions | games | model top-1 % | oracle top-1 % | gap (model - oracle) | model sampled match % | oracle sampled match % (range) |",
              "|---|---|---|---|---|---|---|---|"]
    for label, r in rows.items():
        lines.append(f"| {label} | {r['n']:,} | {r['games']:,} | {_ci(r['model_top1'])} | {_ci(r['oracle_top1'])} | {_ci(r['gap_top1'])} | "
                     f"{_ci(r['model_sampled'])} | {100 * r['oracle_sampled_lo']:.1f} to {100 * r['oracle_sampled_hi']:.1f} |")
    return "\n".join(lines)
