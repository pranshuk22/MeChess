"""Sequential probability ratio test on paired games, plus Elo estimates.

Games are played in *pairs* (same opening, colours swapped), so results are summarised as a pentanomial:
counts of pairs scoring 0, 0.5, 1, 1.5 or 2 points for engine A. Pair scores are close to independent, which
makes the normal approximation below much more trustworthy than treating the individual games as independent.
"""
import math

PAIR_SCORES = (0.0, 0.25, 0.5, 0.75, 1.0)  # a pair's points / 2, for penta index 0..4


def expected_score(elo):
    return 1.0 / (1.0 + 10 ** (-elo / 400.0))


def elo_from_score(score):
    score = min(max(score, 1e-9), 1 - 1e-9)
    return -400.0 * math.log10(1.0 / score - 1.0)


def bounds(alpha=0.05, beta=0.05):
    """(lower, upper) LLR thresholds: crossing upper accepts H1, crossing lower accepts H0."""
    return math.log(beta / (1 - alpha)), math.log((1 - beta) / alpha)


def pair_moments(penta):
    """(pairs, mean pair score, variance of the pair score)."""
    n = sum(penta)
    if n == 0:
        return 0, 0.5, 0.0
    mean = sum(c * s for c, s in zip(penta, PAIR_SCORES)) / n
    var = sum(c * (s - mean) ** 2 for c, s in zip(penta, PAIR_SCORES)) / n
    return n, mean, var


def llr(penta, elo0, elo1):
    """Log-likelihood ratio of H1 (true Elo gap = elo1) against H0 (elo0), normal approximation on pair scores."""
    n, mean, var = pair_moments(penta)
    if n == 0:
        return 0.0
    if var <= 0:
        # Every pair scored identically (e.g. a clean sweep): the sample variance says "no spread" and would give
        # 0/0. A tiny prior count in each bucket keeps the statistic finite and points the right way.
        n, mean, var = pair_moments([c + 0.1 for c in penta])
    s0, s1 = expected_score(elo0), expected_score(elo1)
    return n * (s1 - s0) * (2 * mean - s0 - s1) / (2 * var)


def elo_estimate(penta):
    """(elo, 95% margin) of A relative to B, by the delta method on the mean pair score."""
    n, mean, var = pair_moments(penta)
    if n == 0:
        return 0.0, float("inf")
    elo = elo_from_score(mean)
    if var <= 0 or not 0 < mean < 1:
        return elo, float("inf")
    se_score = math.sqrt(var / n)
    se_elo = 400.0 / math.log(10) * se_score / (mean * (1 - mean))
    return elo, 1.96 * se_elo


def los(penta):
    """Likelihood of superiority: probability that A is truly stronger than B (normal approximation)."""
    n, mean, var = pair_moments(penta)
    if n == 0 or var <= 0:
        return 0.5
    z = (mean - 0.5) / math.sqrt(var / n)
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def sprt_status(penta, elo0, elo1, alpha=0.05, beta=0.05):
    """"H1" (A is at least elo1 better), "H0" (A is not better than elo0), or None (keep playing)."""
    lo, hi = bounds(alpha, beta)
    value = llr(penta, elo0, elo1)
    if value >= hi:
        return "H1"
    if value <= lo:
        return "H0"
    return None


def penta_index(points_a):
    """Map a pair's total points for A (0, 0.5, ..., 2) to a pentanomial slot 0..4."""
    idx = int(round(points_a * 2))
    if not 0 <= idx <= 4:
        raise ValueError(f"invalid pair points: {points_a}")
    return idx
