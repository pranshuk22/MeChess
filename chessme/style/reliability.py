"""Is style a stable trait of a player? And how much do players differ?

Split-half test: each player's games are split into two halves (alternating games); a style vector is fitted on each
half. Noise in the two halves is independent, so across players
    cov(half A weight, half B weight)  =  the TRUE between-player variance of that preference,
    corr(half A, half B)               =  its reliability (how much of the variation between players is real).
Then the trait test: does a player's half-A vector predict their half-B choices better than the population's vector?
"""
import numpy as np

from . import candidates as SC
from . import model as M
from .features import FEATURE_NAMES


def load_cohort(out_dir):
    """{player id: [Position]} from the cands/ folder of a cohort."""
    from pathlib import Path

    return {p.stem: SC.load(p) for p in sorted((Path(out_dir) / "cands").glob("*.npz"))}


def split_games(positions):
    """(A, B): alternate games go to each half, so both cover the whole period."""
    games = sorted({p.game for p in positions})
    a = set(games[0::2])
    return [p for p in positions if p.game in a], [p for p in positions if p.game not in a]


def _usable(ps):
    return [p for p in ps if p.chosen >= 0 and len(p.cands) >= 2]


def _vec(m):
    return np.concatenate([m.w, [m.loss_coef]])


def usable_players(players, min_usable=60):
    out = {}
    for pid, ps in players.items():
        a, b = split_games(ps)
        if len(_usable(a)) >= min_usable and len(_usable(b)) >= min_usable:
            out[pid] = (a, b)
    return out


def split_half(players, l2=1.0, min_usable=60):
    """{"names", "sd_true", "reliability", "n_players", "usable_per_half"} over players with enough usable decisions."""
    halves = usable_players(players, min_usable)
    if len(halves) < 10:
        raise ValueError(f"only {len(halves)} players have >= {min_usable} usable decisions per half")
    std = M.standardiser([p for a, _ in halves.values() for p in a])
    WA, WB = [], []
    for a, b in halves.values():
        WA.append(_vec(M.fit(a, l2=l2, standardise=std)))
        WB.append(_vec(M.fit(b, l2=l2, standardise=std)))
    WA, WB = np.array(WA), np.array(WB)
    cov = ((WA - WA.mean(0)) * (WB - WB.mean(0))).sum(0) / (len(WA) - 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        rel = cov / (WA.std(0, ddof=1) * WB.std(0, ddof=1))
    return {"names": tuple(FEATURE_NAMES) + ("strength_weight",), "sd_true": np.sqrt(np.maximum(cov, 0)),
            "reliability": np.nan_to_num(rel), "n_players": len(halves),
            "usable_per_half": float(np.mean([len(_usable(a)) for a, _ in halves.values()])),
            "std": std, "mean_w": (WA.mean(0) + WB.mean(0)) / 2}


def personal_vs_population(players, alphas=(0.0, 0.5, 1.0), l2=1.0, min_usable=60):
    """Held-out NLL of blend  w_pop + alpha * (w_player - w_pop)  on the player's other half (both directions).

    alpha = 0 is the population style, 1 the player's own fitted style. Returns {alpha: (mean NLL improvement over
    alpha=0, standard error over players)}; positive = the player's own style predicts their other games better."""
    halves = usable_players(players, min_usable)
    std = M.standardiser([p for a, _ in halves.values() for p in a])
    pooled = M.fit([p for a, b in halves.values() for p in a + b], l2=l2, standardise=std)
    diffs = {al: [] for al in alphas}
    for a, b in halves.values():
        for train, test in ((a, b), (b, a)):
            own = M.fit(train, l2=l2, standardise=std)
            nll = {}
            for al in alphas:
                blend = M.StyleModel(std[0], std[1], pooled.w + al * (own.w - pooled.w),
                                     pooled.loss_coef + al * (own.loss_coef - pooled.loss_coef))
                nll[al] = M.evaluate(blend, test)["style"]["nll"]
            for al in alphas:
                diffs[al].append(nll[alphas[0]] - nll[al])
    return {al: (float(np.mean(d)), float(np.std(d, ddof=1) / np.sqrt(len(d)))) for al, d in diffs.items()}, len(halves)


def render(sh, trait):
    """Plain-text summary of the two tests."""
    res, n = trait
    lines = [f"players analysed: {sh['n_players']} (about {sh['usable_per_half']:.0f} usable decisions per half)", "",
             "Is style a stable trait? Held-out log-loss improvement over the population style (higher = better):"]
    for al, (m, se) in res.items():
        lines.append(f"  alpha {al:.1f}: {m:+.4f} +/- {se:.4f}" + ("  (population style)" if al == 0 else ""))
    order = np.argsort(-sh["reliability"])
    lines += ["", "Per preference: reliability (agreement of the two halves across players) and the true spread between players",
              "  (standardised units; reliability near 0 = players do not differ reliably on it):"]
    for i in order:
        lines.append(f"  {sh['names'][i]:22s} reliability {sh['reliability'][i]:+.2f}   between-player SD {sh['sd_true'][i]:.3f}")
    return "\n".join(lines)
