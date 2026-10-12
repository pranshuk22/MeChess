"""Axis A3: do the errors a model would make when it SAMPLES its moves look like the errors humans made, position by position?

Inputs: a model's stored top moves with probabilities (`score.py`), and an engine's losses for the human's move and for those candidate moves
(`judge.py`). For each position the human's loss is one observed draw; the model's expected loss is the probability-weighted loss of its candidates.
Averaged over many positions (grouped in games), the two are directly comparable: if the model chose like the humans, the average of its expected loss
equals the average of the humans' realised loss, in every stratum. The model's probabilities are renormalised over the judged candidates (the
`tail` share outside them is reported; for the top 8 moves it is small).

Positive controls: the same model with its probabilities sharpened or flattened by a temperature, which is a known amount of behavioural change; a
benchmark is only useful if it detects these. Null: the human mean loss of two random halves of the games, which sets the noise floor."""
import numpy as np

from . import judge as J
from . import metrics as M

THRESHOLDS = {"error (loss > 0.10)": 0.10, "blunder (loss > 0.20)": 0.20}
GOOD = 0.02                      # a candidate within this much of the best counts as a good move (position difficulty = how few there are)


def prepare(scores, judged, k=J.K_CAND):
    """Candidate probabilities (renormalised) and losses, and the human's loss, aligned with the positions."""
    pc = scores["topk_p"][:, :k].astype(np.float64)
    cand_loss = J.losses(judged["best_cp"], judged["cand_cp"][:, :k])
    human_loss = J.losses(judged["best_cp"], judged["human_cp"])
    valid = ~np.isnan(cand_loss)
    pc = np.where(valid, pc, 0.0)
    mass = pc.sum(axis=1)
    return {"p": pc, "cand_loss": np.nan_to_num(cand_loss), "human_loss": human_loss, "mass": mass,
            "tail": 1.0 - scores["topk_p"][:, :k].sum(axis=1), "n_good": ((cand_loss <= GOOD) & valid).sum(axis=1)}


def tempered(p, tau):
    """Probabilities with temperature `tau` (< 1 sharper, > 1 flatter), renormalised over the candidates."""
    if tau == 1.0:
        q = p
    else:
        with np.errstate(divide="ignore"):
            q = np.where(p > 0, p ** (1.0 / tau), 0.0)
    s = q.sum(axis=1, keepdims=True)
    return q / np.maximum(s, 1e-300)


def model_values(prep, tau=1.0):
    """Per position: the model's expected loss and its probability of an error / blunder, under temperature tau."""
    q = tempered(prep["p"], tau)
    out = {"mean loss": (q * prep["cand_loss"]).sum(axis=1)}
    for name, thr in THRESHOLDS.items():
        out[name] = (q * (prep["cand_loss"] > thr)).sum(axis=1)
    return out


def human_values(prep):
    out = {"mean loss": prep["human_loss"]}
    for name, thr in THRESHOLDS.items():
        out[name] = (prep["human_loss"] > thr).astype(float)
    return out


def compare(prep, arr, mask, tau=1.0, n_boot=500, seed=0):
    """Per measure: (human mean, model mean, model - human with a game-level interval) on the masked positions."""
    mv, hv = model_values(prep, tau), human_values(prep)
    out = {}
    for name in mv:
        h = M.cluster_bootstrap_mean(hv[name], arr["gid"], n_boot=n_boot, seed=seed, mask=mask)
        m = M.cluster_bootstrap_mean(mv[name], arr["gid"], n_boot=n_boot, seed=seed, mask=mask)
        d = M.paired_cluster_bootstrap(mv[name], hv[name], arr["gid"], n_boot=n_boot, seed=seed, mask=mask)
        out[name] = {"human": h[:3], "model": m[:3], "diff": d[:3]}
    out["n"] = int(np.asarray(mask).sum())
    return out


def null_halves(prep, arr, mask, n_split=200, seed=0):
    """Noise floor: the difference of the humans' mean loss between two random halves of the games, over many random splits.
    Returns the standard deviation of that difference (in loss units)."""
    sel = np.asarray(mask, dtype=bool)
    gids, inv = np.unique(arr["gid"][sel], return_inverse=True)
    loss = prep["human_loss"][sel]
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n_split):
        half = rng.random(len(gids)) < 0.5
        a, b = half[inv], ~half[inv]
        if a.any() and b.any():
            diffs.append(loss[a].mean() - loss[b].mean())
    return float(np.std(diffs)) if diffs else float("nan")


def by_difficulty(prep, arr, mask, tau=1.0, bins=((1, 1), (2, 2), (3, 4), (5, 8))):
    """Error rate (loss > 0.10) of humans and of the model against the number of good candidate moves: both should fall as good moves become
    plentiful, at the same rate."""
    mv, hv = model_values(prep, tau)["error (loss > 0.10)"], human_values(prep)["error (loss > 0.10)"]
    out = {}
    for lo, hi in bins:
        sel = np.asarray(mask, dtype=bool) & (prep["n_good"] >= lo) & (prep["n_good"] <= hi)
        if sel.sum() >= 30:
            out[f"{lo}" if lo == hi else f"{lo}-{hi}"] = {"n": int(sel.sum()), "human": float(hv[sel].mean()), "model": float(mv[sel].mean())}
    return out


def _ci(t, scale=100.0, digits=2):
    return f"{scale * t[0]:.{digits}f} [{scale * t[1]:.{digits}f}, {scale * t[2]:.{digits}f}]"


def render(rows, floor=None, title=""):
    """Markdown: {label: compare() result}; values in points (loss and rates x 100)."""
    lines = [title] if title else []
    lines += ["| subset | positions | measure | humans | model | model - humans | gap / noise floor |", "|---|---|---|---|---|---|---|"]
    for label, r in rows.items():
        for name in [k for k in r if k != "n"]:
            z = ""
            if floor and name == "mean loss" and floor.get(label):
                z = f"{r[name]['diff'][0] / floor[label]:+.1f}"
            lines.append(f"| {label} | {r['n']:,} | {name} | {_ci(r[name]['human'])} | {_ci(r[name]['model'])} | {_ci(r[name]['diff'])} | {z} |")
    return "\n".join(lines)
