"""Does the model know WHERE humans blunder? Per-position calibration of the blunder probability a model implies.

For every judged position the model's implied probability of a blunder is the probability it puts on moves that lose more than 0.20 (`errors.model_values`).
The humans' outcome there is one draw: did the player blunder (1) or not (0). Three questions, none of which an aggregate blunder rate can answer:

* discrimination: do the positions where the model expects blunders more often really have more human blunders? (AUC of the implied probability against the
  outcome; 0.5 = no information beyond the clock regime)
* calibration: when the model says 10%, do humans blunder in 10% of such positions? (reliability table; Brier score; slope of the outcome on the logit)
* skill over a reference: the Brier skill score against predicting the base rate of the subset (and against a position-difficulty-only reference: the
  base rate by number of good moves).

A single human move per position sets a ceiling on all three (the outcome is noisy even for a perfect model), so differences between models on the same
positions matter more than the absolute values. Intervals resample games."""
import numpy as np


def weighted_auc(score, y, w):
    """AUC of `score` for the binary outcome `y` with non-negative weights `w` (ties count one half)."""
    score, y, w = np.asarray(score, dtype=np.float64), np.asarray(y, dtype=bool), np.asarray(w, dtype=np.float64)
    _, inv = np.unique(score, return_inverse=True)
    pos = np.bincount(inv, weights=w * y)
    neg = np.bincount(inv, weights=w * ~y)
    wp, wn = pos.sum(), neg.sum()
    if wp <= 0 or wn <= 0:
        return float("nan")
    below = np.cumsum(neg) - neg
    return float((pos * (below + 0.5 * neg)).sum() / (wp * wn))


def brier(q, y, w):
    q, y, w = np.asarray(q, dtype=np.float64), np.asarray(y, dtype=np.float64), np.asarray(w, dtype=np.float64)
    return float((w * (q - y) ** 2).sum() / w.sum())


def base_rate_reference(y, w, groups=None):
    """Brier score of predicting the (weighted) base rate, within `groups` if given (e.g. the number of good moves)."""
    y, w = np.asarray(y, dtype=np.float64), np.asarray(w, dtype=np.float64)
    if groups is None:
        return brier(np.full(len(y), (w * y).sum() / w.sum()), y, w)
    q = np.zeros(len(y))
    for g in np.unique(groups):
        s = groups == g
        q[s] = (w[s] * y[s]).sum() / max(w[s].sum(), 1e-12)
    return brier(q, y, w)


def logit_slope(q, y, w, eps=1e-4, iters=25):
    """Slope of the outcome on logit(q) (logistic regression with intercept, Newton steps): 1 = calibrated spread, below 1 = the model is too confident
    about where blunders are, above 1 = not confident enough."""
    x = np.log(np.clip(q, eps, 1 - eps) / (1 - np.clip(q, eps, 1 - eps)))
    X = np.stack([np.ones_like(x), x], axis=1)
    beta = np.array([np.log(max((w * y).sum() / w.sum(), 1e-6) / max(1 - (w * y).sum() / w.sum(), 1e-6)), 0.0])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ beta))
        g = X.T @ (w * (y - p))
        H = (X * (w * p * (1 - p))[:, None]).T @ X + 1e-9 * np.eye(2)
        step = np.linalg.solve(H, g)
        beta = beta + step
        if np.abs(step).max() < 1e-8:
            break
    return float(beta[1])


def reliability(q, y, w, bins=10):
    """Equal-weight bins of q: list of (mean q, mean outcome, weight share)."""
    order = np.argsort(q, kind="stable")
    q, y, w = np.asarray(q)[order], np.asarray(y, dtype=np.float64)[order], np.asarray(w, dtype=np.float64)[order]
    cum = np.cumsum(w) / w.sum()
    idx = np.minimum((cum * bins - 1e-12).astype(int), bins - 1)
    out = []
    for b in range(bins):
        s = idx == b
        if s.any() and w[s].sum() > 0:
            out.append((float((w[s] * q[s]).sum() / w[s].sum()), float((w[s] * y[s]).sum() / w[s].sum()), float(w[s].sum() / w.sum())))
    return out


def measures(q, y, w, difficulty=None):
    ref = base_rate_reference(y, w)
    out = {"auc": weighted_auc(q, y, w), "brier": brier(q, y, w), "bss": 1.0 - brier(q, y, w) / ref if ref > 0 else float("nan"),
           "slope": logit_slope(np.asarray(q, dtype=np.float64), np.asarray(y, dtype=np.float64), np.asarray(w, dtype=np.float64))}
    if difficulty is not None:
        ref_d = base_rate_reference(y, w, difficulty)
        out["bss_difficulty_ref"] = 1.0 - brier(q, y, w) / ref_d if ref_d > 0 else float("nan")
    return out


def bootstrap(qs, y, gids, mask, n_boot=500, seed=0, difficulty=None):
    """{name: {measure: (value, lo, hi)}} for the implied probabilities `qs` ({name: array}) on the masked positions, plus 'diff vs <first>' paired
    differences of the AUC and the Brier score, with game-level bootstrap intervals (the same resamples for every model)."""
    sel = np.asarray(mask, dtype=bool)
    y = np.asarray(y, dtype=np.float64)[sel]
    qs = {k: np.asarray(v, dtype=np.float64)[sel] for k, v in qs.items()}
    diff = None if difficulty is None else np.asarray(difficulty)[sel]
    _, inv = np.unique(np.asarray(gids)[sel], return_inverse=True)
    n_g = inv.max() + 1
    names = list(qs)
    point = {k: measures(qs[k], y, np.ones(len(y)), diff) for k in names}
    rng = np.random.default_rng(seed)
    draws = {k: {m: [] for m in point[k]} for k in names}
    paired = {k: {"auc": [], "brier": []} for k in names[1:]}
    for _ in range(n_boot):
        w = np.bincount(rng.integers(0, n_g, n_g), minlength=n_g)[inv].astype(np.float64)
        if w.sum() == 0:
            continue
        res = {k: measures(qs[k], y, w, diff) for k in names}
        for k in names:
            for m, v in res[k].items():
                draws[k][m].append(v)
        for k in names[1:]:
            paired[k]["auc"].append(res[k]["auc"] - res[names[0]]["auc"])
            paired[k]["brier"].append(res[k]["brier"] - res[names[0]]["brier"])

    def ci(vals, centre):
        v = np.asarray(vals, dtype=np.float64)
        v = v[~np.isnan(v)]
        return (centre, float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))) if len(v) else (centre, float("nan"), float("nan"))
    out = {k: {m: ci(draws[k][m], point[k][m]) for m in point[k]} for k in names}
    for k in names[1:]:
        out[k]["auc diff vs " + names[0]] = ci(paired[k]["auc"], point[k]["auc"] - point[names[0]]["auc"])
        out[k]["brier diff vs " + names[0]] = ci(paired[k]["brier"], point[k]["brier"] - point[names[0]]["brier"])
    out["n"] = int(sel.sum())
    out["base_rate"] = float(y.mean())
    return out


def render(rows, title=""):
    """Markdown: {label: bootstrap() result} for one subset each."""
    lines = [title] if title else []
    lines += ["| subset | positions | human blunder rate % | model | AUC | Brier x100 | skill vs base rate | skill vs difficulty-only | slope |", "|---|---|---|---|---|---|---|---|---|"]
    for label, r in rows.items():
        for name in [k for k in r if k not in ("n", "base_rate")]:
            v = r[name]
            f = lambda t, s=1.0, d=3: f"{s * t[0]:.{d}f} [{s * t[1]:.{d}f}, {s * t[2]:.{d}f}]"
            dskill = f(v["bss_difficulty_ref"]) if "bss_difficulty_ref" in v else "-"
            lines.append(f"| {label} | {r['n']:,} | {100 * r['base_rate']:.1f} | {name} | {f(v['auc'])} | {f(v['brier'], 100, 2)} | {f(v['bss'])} | {dskill} | {f(v['slope'], 1.0, 2)} |")
    return "\n".join(lines)
