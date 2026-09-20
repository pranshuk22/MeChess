"""Putting it together: one player against the population, the cohort, the axes and the anchors.

The cohort is the yardstick. Earlier comparisons used sampling noise only; here a player's preference is measured in units
of how much *players* really differ from each other (the between-player spread from split halves), and only preferences that
are reliable at all (players' two halves agree) are reported as personal. The five hypothesis axes get a reliability of their
own, and the anchors are tested at the level of style poles (a 5-way question) as well as individually."""
import numpy as np

from . import anchors as A
from . import model as M
from .axes import AXES
from .features import FEATURE_NAMES


def _vec(m):
    return np.concatenate([m.w, [m.loss_coef]])


def player_vector(positions, std, l2=1.0):
    return _vec(M.fit(positions, l2=l2, standardise=std))


def bootstrap_se(positions, std, n_boot=20, seed=0, l2=1.0):
    pos = [p for p in positions if p.chosen >= 0 and len(p.cands) >= 2]
    rng = np.random.default_rng(seed)
    boots = [player_vector([pos[i] for i in rng.integers(0, len(pos), len(pos))], std, l2) for _ in range(n_boot)]
    return np.std(boots, axis=0)


def me_vs_cohort(user, sh, *, n_boot=20, l2=1.0, seed=0):
    """Rows for every preference: the player's weight, the cohort's mean and true between-player SD, the reliability,
    z_raw (difference in units of sqrt(between-player variance + the player's own estimation error)) and z_shrunk
    (the reliability-shrunk estimate in units of the between-player SD: how many 'player SDs' from the average)."""
    w = player_vector(user, sh["std"], l2)
    se = bootstrap_se(user, sh["std"], n_boot, seed, l2)
    r, sd, mean = np.clip(sh["reliability"], 0, 1), sh["sd_true"], sh["mean_w"]
    rows = []
    for i, name in enumerate(sh["names"]):
        z_raw = (w[i] - mean[i]) / np.sqrt(sd[i] ** 2 + se[i] ** 2 + 1e-12)
        z_shr = r[i] * (w[i] - mean[i]) / sd[i] if sd[i] > 1e-6 else 0.0
        rows.append({"name": name, "w": float(w[i]), "mean": float(mean[i]), "sd_between": float(sd[i]), "reliability": float(r[i]),
                     "se_player": float(se[i]), "z_raw": float(z_raw), "z_shrunk": float(z_shr)})
    return rows, w


def axis_table(sh, user_w, axes=AXES):
    """Per axis: split-half reliability across the cohort's players and the player's score in cohort SD units."""
    idx = {n: i for i, n in enumerate(sh["names"])}
    WA, WB = sh["WA"], sh["WB"]
    out = {}
    for axis, feats in axes.items():
        cols = [idx[f] for f in feats]
        signs = np.array([feats[f] for f in feats], dtype=float)
        sa, sb = (WA[:, cols] * signs).mean(1), (WB[:, cols] * signs).mean(1)
        rel = float(np.corrcoef(sa, sb)[0, 1]) if sa.std() > 0 and sb.std() > 0 else 0.0
        both = np.concatenate([sa, sb])
        su = float((user_w[cols] * signs).mean())
        z = (su - both.mean()) / both.std() if both.std() > 0 else 0.0
        out[axis] = {"reliability": rel, "user_score": su, "z_observed": float(z), "z_shrunk": float(max(rel, 0.0) * z)}
    return out


# ---- anchors at the level of style poles -----------------------------------------------------------------------------

def pole_models(anchors, pole_of, l2=1.0, min_usable=100):
    """({pole: model fitted on the first half of its anchors' games}, {anchor: held-out second half}, std)."""
    fitted_a, held = {}, {}
    for key, ps in anchors.items():
        if key not in pole_of:
            continue
        a, b = A._halves(ps)
        if len(A._usable(a)) < min_usable or len(A._usable(b)) < min_usable:
            continue
        fitted_a.setdefault(pole_of[key], []).extend(a)
        held[key] = b
    if len(fitted_a) < 2:
        raise ValueError("need at least two poles with usable anchors")
    std = M.standardiser([p for v in fitted_a.values() for p in v])
    return {pole: M.fit(v, l2=l2, standardise=std) for pole, v in fitted_a.items()}, held, std


def pole_confusion(anchors, pole_of, chunk=30, l2=1.0, min_usable=100):
    """Can the features tell the style poles apart? Held-out chunks of each anchor's other games are assigned to the pole
    model with the highest likelihood. Returns the confusion matrix, accuracy, and two baselines (uniform and majority)."""
    models, held, _ = pole_models(anchors, pole_of, l2, min_usable)
    poles = sorted(models)
    conf = np.zeros((len(poles), len(poles)), dtype=int)
    for key, b in held.items():
        us = A._usable(b)
        t = poles.index(pole_of[key])
        for s in range(0, len(us) - chunk + 1, chunk):
            part = us[s:s + chunk]
            conf[t, int(np.argmax([A._loglik(models[q], part) for q in poles]))] += 1
    total = int(conf.sum())
    return {"poles": poles, "confusion": conf, "chunks": total, "accuracy": float(np.trace(conf) / total) if total else float("nan"),
            "chance": 1.0 / len(poles), "majority": float(conf.sum(1).max() / total) if total else float("nan")}


def user_vs_poles(anchors, pole_of, user_train, user_test, l2=1.0, min_usable=100):
    """Held-out log-loss of the player's choices under each pole model, their own style and the uniform baseline."""
    models, _, std = pole_models(anchors, pole_of, l2, min_usable)
    own = M.evaluate(M.fit(user_train, l2=l2, standardise=std), user_test)
    rows = sorted(((q, M.evaluate(m, user_test)["style"]["nll"]) for q, m in models.items()), key=lambda t: t[1])
    return {"poles": rows, "own": own["style"]["nll"], "uniform": own["uniform"]["nll"], "n": own["n"]}


# ---- the report -------------------------------------------------------------------------------------------------------

def render(*, label, n_user, n_cohort, me_rows, axes, poles=None, user_poles=None, population=None, shrunk=None,
           min_reliability=0.10):
    L = [f"# Style summary: {label}", "",
         f"Compared with the cohort ({n_cohort} players, several hundred decisions each) using {n_user:,} of the player's own decisions.", "",
         "## 1. Against the cohort: what is reliably personal", "",
         "A preference counts as personal only if players' two halves agree on it (reliability). z_shrunk = how many *between-player*",
         "standard deviations the player is from the average player, after shrinking by reliability.", "",
         "| preference | reliability | between-player SD | z_shrunk | z_raw |", "|---|---|---|---|---|"]
    rel = [r for r in me_rows if r["reliability"] >= min_reliability]
    for r in sorted(rel, key=lambda r: -abs(r["z_shrunk"])):
        L.append(f"| {r['name']} | {r['reliability']:.2f} | {r['sd_between']:.3f} | {r['z_shrunk']:+.2f} | {r['z_raw']:+.1f} |")
    L += ["", f"{len(me_rows) - len(rel)} of {len(me_rows)} preferences have reliability below {min_reliability}: players do not differ "
              "reliably on them, so nothing is claimed.", "",
          "## 2. The five hypothesis axes", "", "| axis | reliability across players | player score (cohort SD) | shrunk |", "|---|---|---|---|"]
    for a, d in axes.items():
        L.append(f"| {a} | {d['reliability']:+.2f} | {d['z_observed']:+.2f} | {d['z_shrunk']:+.2f} |")
    L += ["", "An axis with reliability near zero does not measure a stable difference between players and should not be reported."]
    if population:
        L += ["", "## 3. Against the rating-matched population (sampling noise only)", ""]
        L += [f"- {n}: z {z:+.1f}" for n, z in population[:6]]
        L += ["", "These z-scores ignore how much players differ from each other; section 1 is the honest version."]
    if poles:
        L += ["", "## 4. Anchors at the level of style poles", "",
              f"Held-out chunks assigned to the right pole: {100 * poles['accuracy']:.0f}% (chance {100 * poles['chance']:.0f}%, "
              f"majority {100 * poles['majority']:.0f}%, {poles['chunks']} chunks). Rows = true pole:", "",
              "| pole | " + " | ".join(poles["poles"]) + " |", "|---|" + "---|" * len(poles["poles"])]
        for i, p in enumerate(poles["poles"]):
            L.append(f"| {p} | " + " | ".join(str(int(x)) for x in poles["confusion"][i]) + " |")
    if user_poles:
        L += ["", "Which pole's preferences predict the player's choices best (held-out log-loss, lower is better):", ""]
        L += [f"- {p}: {v:.4f}" for p, v in user_poles["poles"]]
        L += [f"- the player's own fit: {user_poles['own']:.4f}", f"- uniform: {user_poles['uniform']:.4f}"]
    if shrunk:
        m, se = shrunk["gain"]
        L += ["", "## 5. Is there personal signal at all?", "",
              f"Reliability-shrunk personal style predicts a player's other games better than the population style by {m:+.4f} "
              f"+/- {se:.4f} log-loss per decision ({shrunk['n_players']} players): "
              + ("a real but small signal." if m > 3 * se else "no detectable signal.")]
    L += ["", "## Reading this", "",
          "- Trust section 1 for what is personal, and only for the listed preferences.",
          "- If the axes and poles are at chance, these move features cannot describe style; use the opening repertoire, the fine-tuned "
          "move-prediction model, time use and strength focus instead.", ""]
    return "\n".join(L)
