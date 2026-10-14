"""Ratings from match results (track S, S1). Each result is (player a, player b, score of a: 1, 0.5 or 0, cluster id). A rating is fitted by maximum
likelihood of the logistic Elo model with fractional scores (a draw is half a point): expected score = 1 / (1 + 10^(-(ra - rb) / 400)). A weak ridge keeps
players with a perfect or empty score finite (they are then reported as 'at least' by the interval, not as exact values). Intervals resample whole clusters
(a cluster = one starting position, with both colours and all players), because games from the same opening are not independent."""
import numpy as np

SCALE = 400.0 / np.log(10.0)


def fit(players, results, anchor=None, iters=200, ridge=1e-3):
    """Returns {player: rating} with the `anchor` player at 0 (default: the mean of all ratings at 0)."""
    idx = {p: i for i, p in enumerate(players)}
    a = np.array([idx[r[0]] for r in results])
    b = np.array([idx[r[1]] for r in results])
    s = np.array([r[2] for r in results], dtype=np.float64)
    x = np.zeros(len(players))                                   # natural-log units: expected score = sigmoid(xa - xb)
    for _ in range(iters):
        e = 1.0 / (1.0 + np.exp(-(x[a] - x[b])))
        grad = np.bincount(a, weights=s - e, minlength=len(x)) - np.bincount(b, weights=s - e, minlength=len(x)) - ridge * x
        w = e * (1 - e)
        hess = np.zeros((len(x), len(x)))
        np.add.at(hess, (a, a), w)
        np.add.at(hess, (b, b), w)
        np.add.at(hess, (a, b), -w)
        np.add.at(hess, (b, a), -w)
        hess += ridge * np.eye(len(x))
        step = np.linalg.solve(hess, grad)
        x = x + np.clip(step, -2, 2)
        if np.abs(step).max() < 1e-9:
            break
    x = x - (x[idx[anchor]] if anchor is not None else x.mean())
    return {p: float(SCALE * x[idx[p]]) for p in players}


def bootstrap(players, results, anchor=None, boot=200, seed=0):
    """95% intervals {player: (lo, hi)} by resampling clusters (the fourth element of each result)."""
    rng = np.random.default_rng(seed)
    clusters = {}
    for r in results:
        clusters.setdefault(r[3], []).append(r)
    keys = list(clusters)
    draws = []
    for _ in range(boot):
        pick = rng.integers(0, len(keys), len(keys))
        sample = [r for k in pick for r in clusters[keys[k]]]
        draws.append(fit(players, sample, anchor))
    return {p: (float(np.percentile([d[p] for d in draws], 2.5)), float(np.percentile([d[p] for d in draws], 97.5))) for p in players}


def score_table(results):
    """{(a, b): (games, points of a)} for the pairs that played."""
    out = {}
    for a, b, s, _ in results:
        g, p = out.get((a, b), (0, 0.0))
        out[(a, b)] = (g + 1, p + s)
    return out
