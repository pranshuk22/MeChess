"""Strength against human-likeness (track S, S0): how much human-likeness does a policy lose when it is pushed toward better moves?

On judged positions we know, for the model's most probable moves, the human prior over them and the engine's loss of each (expected points given away).
A policy is any distribution over those moves built from the prior and the losses. Three families, each with one knob:
  * engine-reweighted: prior(m) * exp(-beta * loss(m)), renormalised (beta = 0: the prior; large: the engine's choice; negative: weaker than the prior);
  * temperature: the prior sharpened or flattened (tau), which does not use the engine (the baseline to beat);
  * mixture: (1 - alpha) * prior + alpha * the engine's best candidate.
For each policy and each position we take the expected loss (the strength proxy: lower is stronger), the probability of an error or blunder, and the probability
the policy gives to the move the human played. The human-likeness proxy is the negative log-probability of the human's move (nats), only over positions where
that move is among the judged candidates, so every family is judged on the same support. Probabilities are renormalised over the judged candidates (the mass outside
them is not modelled here), so absolute numbers differ from the error profile that adds the tail back; comparisons between policies are on equal footing."""
import numpy as np

from . import errors as E
from . import metrics as M

ERROR, BLUNDER = E.THRESHOLDS["error (loss > 0.10)"], E.THRESHOLDS["blunder (loss > 0.20)"]
FLOOR = 1e-9                     # smallest probability counted for the human's move (20.7 nats)


def prior(prep):
    p = np.asarray(prep["p"], dtype=np.float64)
    return p / np.maximum(p.sum(axis=1, keepdims=True), 1e-300)


def reweighted(q, cand_loss, beta):
    """prior * exp(-beta * loss), renormalised; moves with zero prior stay at zero."""
    with np.errstate(divide="ignore"):
        logit = np.where(q > 0, np.log(np.maximum(q, 1e-300)) - beta * cand_loss, -np.inf)
    logit = logit - logit.max(axis=1, keepdims=True)
    w = np.exp(logit)
    return w / w.sum(axis=1, keepdims=True)


def mixture(q, cand_loss, alpha):
    """(1 - alpha) * prior + alpha * all mass on the candidate with the smallest loss among those with prior mass."""
    masked = np.where(q > 0, cand_loss, np.inf)
    best = masked.argmin(axis=1)
    one = np.zeros_like(q)
    one[np.arange(len(q)), best] = 1.0
    return (1.0 - alpha) * q + alpha * one


def policy(prep, family, value):
    q = prior(prep)
    if family == "engine-reweighted":
        return reweighted(q, prep["cand_loss"], value)
    if family == "temperature":
        return E.tempered(q, value)
    if family == "mixture":
        return mixture(q, prep["cand_loss"], value)
    raise ValueError(f"unknown family {family}")


def measures(pi, prep, human_index):
    """Per position: expected loss, probability of an error, of a blunder, and -log of the probability of the human's move (NaN where it is not a judged candidate)."""
    cl = prep["cand_loss"]
    ok = human_index >= 0
    ph = np.where(ok, pi[np.arange(len(pi)), np.clip(human_index, 0, pi.shape[1] - 1)], np.nan)
    nll = -np.log(np.maximum(ph, FLOOR))                                    # a policy that gives the human's move no mass costs FLOOR's log, not infinity
    return {"expected loss": (pi * cl).sum(axis=1), "error": (pi * (cl > ERROR)).sum(axis=1), "blunder": (pi * (cl > BLUNDER)).sum(axis=1), "nll": nll, "p_human": ph}


def human_index(rank, k, valid):
    """Index of the human's move among the judged candidates (rank is 1-based over all moves), -1 when it is outside them or not a valid candidate."""
    idx = np.asarray(rank, dtype=np.int64) - 1
    ok = (idx >= 0) & (idx < k)
    ok &= valid[np.arange(len(idx)), np.clip(idx, 0, k - 1)]
    return np.where(ok, idx, -1)


def sweep(prep, rank, groups, mask, settings, n_boot=500, seed=0):
    """`settings` = [(family, value)]. For each: means with game-level intervals of the measures over the masked positions (the likelihood only where the human's move is a candidate).
    Returns a list of dicts with the family, value and, per measure, (mean, lo, hi)."""
    k = prep["cand_loss"].shape[1]
    hidx = human_index(rank, k, prep["p"] > 0)
    mask = np.asarray(mask, dtype=bool)
    rows = []
    for family, value in settings:
        m = measures(policy(prep, family, value), prep, hidx)
        out = {"family": family, "value": value}
        for name in ("expected loss", "error", "blunder"):
            out[name] = M.cluster_bootstrap_mean(m[name], groups, n_boot=n_boot, seed=seed, mask=mask)[:3]
        cover = mask & (hidx >= 0)
        out["nll"] = M.cluster_bootstrap_mean(np.nan_to_num(m["nll"]), groups, n_boot=n_boot, seed=seed, mask=cover)[:3]
        out["p_human"] = M.cluster_bootstrap_mean(np.nan_to_num(m["p_human"]), groups, n_boot=n_boot, seed=seed, mask=cover)[:3]
        out["covered"] = float(cover.sum() / max(mask.sum(), 1))
        rows.append(out)
    return rows


def render(rows, title):
    f = lambda t, s=100.0, d=2: f"{s * t[0]:.{d}f} [{s * t[1]:.{d}f}, {s * t[2]:.{d}f}]"
    lines = [title, "", "| policy | expected loss (points x100) | error rate % | blunder rate % | NLL of the human's move (nats) | probability of the human's move % |", "|---|---|---|---|---|---|"]
    for r in rows:
        label = f"{r['family']} {r['value']:g}"
        lines.append(f"| {label} | {f(r['expected loss'])} | {f(r['error'])} | {f(r['blunder'])} | {f(r['nll'], 1.0, 3)} | {f(r['p_human'])} |")
    return "\n".join(lines)


def at_equal_strength(rows, reference, fractions=(0.75, 0.5)):
    """For one family's settings, the human-move NLL at the expected loss that is `fraction` of the reference (the prior's) expected loss, by linear interpolation along the
    family's curve between the settings that are at least as strong as the reference. Returns {fraction: nll or None when the curve does not reach that strength}."""
    pts = sorted((r["expected loss"][0], r["nll"][0]) for r in rows if r["expected loss"][0] <= reference + 1e-12)
    out = {}
    for f in fractions:
        target = f * reference
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        out[f] = float(np.interp(target, xs, ys)) if xs and xs[0] <= target <= xs[-1] else None
    return out


def render_equal_strength(rows, title):
    ref = next(r["expected loss"][0] for r in rows if r["family"] == "engine-reweighted" and r["value"] == 0)
    lines = [title, "", f"Prior's expected loss: {100 * ref:.2f} points x100. NLL of the human's move (nats) when each family is pushed to a fraction of that loss (interpolated; '-' = not reached):", "",
             "| family | 75% of the prior's expected loss | 50% |", "|---|---|---|"]
    for fam in ("engine-reweighted", "temperature", "mixture"):
        r = at_equal_strength([x for x in rows if x["family"] == fam], ref)
        lines.append(f"| {fam} | " + " | ".join("-" if r[f] is None else f"{r[f]:.3f}" for f in (0.75, 0.5)) + " |")
    return "\n".join(lines)
