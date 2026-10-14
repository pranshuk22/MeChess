"""Does the gap between a model and the humans change with the model's size? (P2 of the strengthening plan)

For models scored and judged on the SAME positions, the gap of a measure (blunder rate, error rate, mean loss) is the model's expected value minus what the
humans did, averaged over the positions of one clock regime. The humans are the same for every size, so the difference of the gaps of two sizes is just the
difference of the two models' expected values on identical positions. Intervals resample whole games (positions of a game are correlated), and every
resample gives all gaps, all pairwise differences and the slope of the gap against log2(parameters) together, so they are mutually consistent."""
import numpy as np

from . import errors as E
from . import metrics as M


def prepared(scores, judged, regime):
    """Model-minus-human value per position for every measure, with the tail correction of `errors.tail_stats` (as in the error profile)."""
    prep = E.prepare(scores, judged)
    tail = E.tail_arrays(E.tail_stats(prep, scores["rank"], regime), regime)
    mv, hv = E.model_values(prep, tail=tail), E.human_values(prep)
    return {name: mv[name] - hv[name] for name in mv}, mv


def gaps(per_size, params, groups, mask, measure, n_boot=2000, seed=0):
    """`per_size` = {name: model-minus-human array}, `params` = {name: parameters}. Returns {"gap": {name: (mean, lo, hi)}, "diff": {(a, b): (mean, lo, hi)} for a larger than b,
    "slope": (mean, lo, hi)} in the units of the arrays, the slope per doubling of the parameters. Sizes must be given in increasing order of parameters."""
    names = list(per_size)
    if len(names) < 2:
        raise ValueError("at least two sizes are needed")
    if [params[n] for n in names] != sorted(params[n] for n in names):
        raise ValueError("sizes must be in increasing order of parameters")
    mask = np.asarray(mask, dtype=bool)
    if not mask.any():                                                    # a clock regime without positions
        nan = (float("nan"),) * 3
        return {"gap": {n: nan for n in names}, "diff": {(names[j], names[i]): nan for j in range(len(names)) for i in range(j)}, "slope": nan, "positions": 0, "games": 0}
    gid = np.asarray(groups)[mask]
    _, inv = np.unique(gid, return_inverse=True)
    g = inv.max() + 1
    cnt = np.bincount(inv).astype(np.float64)
    sums = np.stack([np.bincount(inv, weights=np.asarray(per_size[n], dtype=np.float64)[mask]) for n in names], axis=1)       # games x sizes
    x = np.log2([params[n] for n in names])
    xc = x - x.mean()

    def stats(w):
        gap = (w[:, None] * sums).sum(0) / (w * cnt).sum()
        slope = float((xc * (gap - gap.mean())).sum() / (xc ** 2).sum())
        return gap, slope
    gap, slope = stats(np.ones(g))
    rng = np.random.default_rng(seed)
    boots = [stats(np.bincount(rng.integers(0, g, size=g), minlength=g).astype(np.float64)) for _ in range(n_boot)]
    bg = np.array([b[0] for b in boots])
    bs = np.array([b[1] for b in boots])
    ci = lambda v: (float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5)))
    out = {"gap": {n: (float(gap[i]), *ci(bg[:, i])) for i, n in enumerate(names)}, "diff": {}, "slope": (slope, *ci(bs)), "positions": int(mask.sum()), "games": int(g)}
    for j in range(len(names)):
        for i in range(j):
            out["diff"][(names[j], names[i])] = (float(gap[j] - gap[i]), *ci(bg[:, j] - bg[:, i]))
    return out
