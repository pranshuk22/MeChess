"""Metrics and statistics for comparing move models on identical positions.

Everything here is a pure function of arrays, so it is tested without any model. Conventions:
  * a model's output for one position is a probability for every legal move; `p` below is the probability of the move the human played;
  * "paired" statistics compare two models on the SAME positions and resample whole games (positions within a game are correlated),
    so the interval reflects the number of games, not of positions."""
import numpy as np

CLOCK_REGIMES = ("30s+", "10-30s", "<10s", "unknown")
LOW_CLOCK_SECONDS = 30.0                                # the filter used by Maia-1/2/3 and Allie


# ---- per-position quantities ---------------------------------------------------------------------------------------

def nll(p):
    """Negative log-likelihood (nats) of the played move, per position. Probabilities are floored so a zero cannot give infinity."""
    return -np.log(np.maximum(np.asarray(p, dtype=np.float64), 1e-12))


def expected_top1(sq_sum):
    """Probability that a move SAMPLED from the model equals a move sampled from itself: sum_m p(m)^2 (given per position)."""
    return np.asarray(sq_sum, dtype=np.float64)


def ece(confidence, correct, bins=15):
    """Expected calibration error of the top label: |accuracy - mean confidence| averaged over equal-width confidence bins,
    weighted by bin size. Returns (ece, [(bin_lo, bin_hi, n, mean_confidence, accuracy), ...])."""
    conf, ok = np.asarray(confidence, dtype=np.float64), np.asarray(correct, dtype=np.float64)
    if len(conf) == 0:
        return float("nan"), []
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(conf, edges[1:-1]), 0, bins - 1)
    total, rows = 0.0, []
    for b in range(bins):
        sel = idx == b
        n = int(sel.sum())
        if n:
            mc, acc = float(conf[sel].mean()), float(ok[sel].mean())
            total += n * abs(acc - mc)
            rows.append((float(edges[b]), float(edges[b + 1]), n, mc, acc))
    return total / len(conf), rows


# ---- strata --------------------------------------------------------------------------------------------------------

def rating_bin(rating, width=100, lo=600, hi=2600):
    """Lower edge of the rating bin of a game rating; below `lo` and above `hi` share one bin each (as in Maia-3's balancing)."""
    r = np.asarray(rating, dtype=np.float64)
    return np.clip((r // width) * width, lo - width, hi).astype(int)


def clock_regime(clock):
    """'30s+', '10-30s', '<10s' from the mover's seconds left BEFORE the move; 'unknown' when the clock is missing (NaN)."""
    c = np.asarray(clock, dtype=np.float64)
    out = np.full(c.shape, "unknown", dtype=object)
    known = ~np.isnan(c)
    out[known & (c >= LOW_CLOCK_SECONDS)] = "30s+"
    out[known & (c < LOW_CLOCK_SECONDS) & (c >= 10)] = "10-30s"
    out[known & (c < 10)] = "<10s"
    return out


def phase_of(ply, heavy):
    """'opening' (first 20 plies unless already an endgame), 'endgame' (at most 6 knights/bishops/rooks/queens left), else 'middlegame'.
    Same boundaries as the move-comparison groups in `chessme.model.compare`."""
    ply, heavy = np.asarray(ply), np.asarray(heavy)
    out = np.full(ply.shape, "middlegame", dtype=object)
    out[ply < 20] = "opening"
    out[heavy <= 6] = "endgame"
    return out


def comparable_mask(ply, clock, after_low, min_ply=10):
    """The positions that the published Maia/Allie numbers are computed on: past the first `min_ply` plies, and not at or after the first
    time the mover's clock was under 30 s (`after_low` is True from that move on). Positions with an unknown clock are kept."""
    return (np.asarray(ply) >= min_ply) & ~np.asarray(after_low, dtype=bool)


# ---- paired cluster bootstrap --------------------------------------------------------------------------------------

def _group_sums(values, groups, mask=None):
    values = np.asarray(values, dtype=np.float64)
    groups = np.asarray(groups)
    if mask is not None:
        values, groups = values[np.asarray(mask, dtype=bool)], groups[np.asarray(mask, dtype=bool)]
    _, inverse = np.unique(groups, return_inverse=True)
    n = np.bincount(inverse).astype(np.float64)
    s = np.bincount(inverse, weights=values)
    return s, n


def cluster_bootstrap_mean(values, groups, n_boot=2000, seed=0, mask=None, alpha=0.05):
    """Mean of `values` and a (1 - alpha) interval from resampling whole groups (games) with replacement.
    Returns (mean, lo, hi, n_positions, n_groups)."""
    s, n = _group_sums(values, groups, mask)
    return _boot(s, n, n_boot, seed, alpha)


def paired_cluster_bootstrap(values_a, values_b, groups, n_boot=2000, seed=0, mask=None, alpha=0.05):
    """Difference of means (a - b) on identical positions with a (1 - alpha) cluster-bootstrap interval. Returns (diff, lo, hi, n_positions,
    n_groups). The interval excludes 0 when the models differ by more than game-level noise. For m pre-specified comparisons use
    alpha = 0.05 / m (Bonferroni)."""
    d = np.asarray(values_a, dtype=np.float64) - np.asarray(values_b, dtype=np.float64)
    s, n = _group_sums(d, groups, mask)
    return _boot(s, n, n_boot, seed, alpha)


def _boot(s, n, n_boot, seed, alpha=0.05):
    g = len(s)
    if g == 0:
        return float("nan"), float("nan"), float("nan"), 0, 0
    mean = float(s.sum() / n.sum())
    if g == 1:
        return mean, mean, mean, int(n.sum()), 1
    rng = np.random.default_rng(seed)
    stats = np.empty(n_boot)
    for i in range(n_boot):
        w = np.bincount(rng.integers(0, g, size=g), minlength=g)
        stats[i] = (w * s).sum() / (w * n).sum()
    lo, hi = np.percentile(stats, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return mean, float(lo), float(hi), int(n.sum()), g
