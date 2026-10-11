"""Tables from per-position scores: one model (summary, strata) or two models compared on identical positions (paired intervals)."""
import numpy as np

from ..model.compare import heavy_pieces
from . import metrics as M

ALL = "all positions"


def position_arrays(positions):
    """The per-position covariates the metrics need, as arrays aligned with the scores."""
    n = len(positions)
    a = {"gid": np.array([p.gid for p in positions]), "ply": np.array([p.ply for p in positions]),
         "me": np.array([p.me for p in positions]), "opp": np.array([p.opp for p in positions]),
         "clock": np.array([p.clock for p in positions], dtype=np.float64),
         "after_low": np.array([p.after_low for p in positions], dtype=bool), "late": np.array([p.late for p in positions], dtype=bool),
         "n_legal": np.array([p.n_legal for p in positions]), "heavy": np.array([heavy_pieces(p.fen) for p in positions])}
    a["game_rating"] = (a["me"] + a["opp"]) / 2.0
    assert all(len(v) == n for v in a.values())
    return a


def masks(arr, min_ply=10, drop_forced=False):
    """The named subsets of a test set. 'comparable' is what the published numbers are computed on (past the opening, not after the first
    position where either player was under 30 s); 'full' is every position; the clock regimes use the mover's clock before the move."""
    ok = np.ones(len(arr["ply"]), dtype=bool) if not drop_forced else arr["n_legal"] >= 2
    out = {"full": ok, "comparable": ok & M.comparable_mask(arr["ply"], arr["late"], min_ply)}
    regime = M.clock_regime(arr["clock"])
    for name in M.CLOCK_REGIMES:
        out[f"clock {name}"] = ok & (regime == name)
    return out


def summarize(scores, arr, mask=None, n_boot=500, seed=0, alpha=0.05):
    """Headline numbers of one model on the (masked) positions, with game-level intervals."""
    sel = np.ones(len(scores["p"]), dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    if not sel.any():
        return None
    g = arr["gid"]
    nll = M.nll(scores["p"])
    row = {"n": int(sel.sum()), "games": int(len(np.unique(g[sel])))}
    for key, vals in (("top1", scores["top1"].astype(float)), ("nll", nll), ("sampled_match", scores["p"]),
                      ("entropy", scores["entropy"]), ("sampled_agreement", scores["sq_sum"])):
        mean, lo, hi, _, _ = M.cluster_bootstrap_mean(vals, g, n_boot=n_boot, seed=seed, mask=sel, alpha=alpha)
        row[key] = (mean, lo, hi)
    over = scores["conf"] - scores["top1"].astype(float)                    # mean confidence minus accuracy: > 0 = overconfident
    row["overconf"] = M.cluster_bootstrap_mean(over, g, n_boot=n_boot, seed=seed, mask=sel, alpha=alpha)[:3]
    row["ece"] = M.ece(scores["conf"][sel], scores["top1"][sel])[0]
    row["top3"] = float((scores["rank"][sel] <= 3).mean())
    return row


def strata(scores, arr, mask, by, n_boot=300, seed=0, min_n=200):
    """`summarize` for each value of a stratifier ('rating', 'clock', 'phase') within `mask`."""
    if by == "rating":
        keys = M.rating_bin(arr["game_rating"])
    elif by == "clock":
        keys = M.clock_regime(arr["clock"])
    elif by == "phase":
        keys = M.phase_of(arr["ply"], arr["heavy"])
    else:
        raise ValueError(by)
    out = {}
    for k in sorted(set(keys[mask])):
        sel = mask & (keys == k)
        if sel.sum() >= min_n:
            out[k] = summarize(scores, arr, sel, n_boot=n_boot, seed=seed)
    return out


def compare(scores_a, scores_b, arr, mask, n_boot=1000, seed=0, alpha=0.05):
    """Paired differences A - B on identical positions: top-1, NLL (negative = A is better), sampled match, with game-level intervals."""
    g = arr["gid"]
    res = {}
    for key, va, vb in (("top1", scores_a["top1"].astype(float), scores_b["top1"].astype(float)),
                        ("nll", M.nll(scores_a["p"]), M.nll(scores_b["p"])),
                        ("sampled_match", scores_a["p"], scores_b["p"])):
        d, lo, hi, n, games = M.paired_cluster_bootstrap(va, vb, g, n_boot=n_boot, seed=seed, mask=mask, alpha=alpha)
        res[key] = (d, lo, hi)
    res["n"], res["games"] = int(np.asarray(mask).sum()), int(len(np.unique(g[mask])))
    return res


# ---- text ----------------------------------------------------------------------------------------------------------------

def _ci(t, scale=1.0, digits=2):
    m, lo, hi = t
    return f"{scale * m:.{digits}f} [{scale * lo:.{digits}f}, {scale * hi:.{digits}f}]"


def table(rows, title=""):
    """Markdown table of {label: summary} (top-1 and sampled match in %, NLL in nats)."""
    lines = [title] if title else []
    lines += ["| subset | positions | games | top-1 % | sampled match % | NLL | top-3 % | ECE | confidence - accuracy (points) | entropy |", "|---|---|---|---|---|---|---|---|---|---|"]
    for label, r in rows.items():
        if r is None:
            continue
        lines.append(f"| {label} | {r['n']:,} | {r['games']:,} | {_ci(r['top1'], 100, 1)} | {_ci(r['sampled_match'], 100, 1)} | {_ci(r['nll'], 1, 3)} | "
                     f"{100 * r['top3']:.1f} | {r['ece']:.3f} | {_ci(r['overconf'], 100, 1)} | {r['entropy'][0]:.2f} |")
    return "\n".join(lines)


def comparison_table(rows, title=""):
    """Markdown table of {label: compare() result}: differences A - B with intervals."""
    lines = [title] if title else []
    lines += ["| subset | positions | games | top-1 diff (points) | NLL diff (nats) | sampled-match diff (points) |", "|---|---|---|---|---|---|"]
    for label, r in rows.items():
        lines.append(f"| {label} | {r['n']:,} | {r['games']:,} | {_ci(r['top1'], 100, 2)} | {_ci(r['nll'], 1, 4)} | {_ci(r['sampled_match'], 100, 2)} |")
    return "\n".join(lines)
