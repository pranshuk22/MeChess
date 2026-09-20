"""Conditional-logit style model: P(choose move m | candidates) = softmax over candidates of  w . z(f(m)) - c * loss(m).

`z` standardises each feature with the pooled candidate statistics, so a weight reads as "how many standard deviations
of that feature the player is willing to pay for", and `c` (per 100 cp) is how much they care about strength among the
approved moves. Only positions where the played move was a candidate take part (see candidates.py)."""
from dataclasses import dataclass

import numpy as np
import torch

from .candidates import Position
from .features import FEATURE_NAMES


@dataclass
class StyleModel:
    mean: np.ndarray
    std: np.ndarray
    w: np.ndarray
    loss_coef: float  # per 100 cp
    names: tuple = FEATURE_NAMES


def _usable(positions):
    return [p for p in positions if p.chosen >= 0 and len(p.cands) >= 2]


def _pack(positions, mean, std):
    feats = np.concatenate([(p.feats - mean) / std for p in positions]).astype(np.float32)
    loss = np.concatenate([p.loss / 100.0 for p in positions]).astype(np.float32)
    sizes = [len(p.cands) for p in positions]
    seg = np.repeat(np.arange(len(positions)), sizes)
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]])
    chosen = starts + np.array([p.chosen for p in positions])
    return torch.from_numpy(feats), torch.from_numpy(loss), torch.from_numpy(seg), torch.from_numpy(chosen)


def _log_probs(scores, seg, n):
    m = torch.full((n,), -1e9).scatter_reduce(0, seg, scores, "amax")
    e = torch.exp(scores - m[seg])
    z = torch.zeros(n).index_add(0, seg, e)
    return scores - m[seg] - torch.log(z[seg])


def _scores(w, c, feats, loss):
    return feats @ w - c * loss


def standardiser(positions):
    """(mean, std) of the candidate features, so different players can be fitted on one common scale."""
    allf = np.concatenate([p.feats for p in _usable(positions)])
    std = allf.std(0)
    return allf.mean(0), np.where(std < 1e-6, 1.0, std)


def fit(positions, l2=1.0, iters=200, weights=None, standardise=None):
    """Maximum-likelihood fit with an L2 penalty on w (per position, so it matters less with more data).

    `standardise=(mean, std)` fixes the feature scale (use the population's for every player so weights compare)."""
    pos = _usable(positions)
    if not pos:
        raise ValueError("no positions where the played move was one of several good candidates")
    mean, std = standardise if standardise is not None else standardiser(pos)
    feats, loss, seg, chosen = _pack(pos, mean, std)
    wt = torch.ones(len(pos)) if weights is None else torch.tensor(weights, dtype=torch.float32)
    w = torch.zeros(feats.shape[1], requires_grad=True)
    c = torch.zeros(1, requires_grad=True)
    opt = torch.optim.LBFGS([w, c], max_iter=iters, line_search_fn="strong_wolfe")

    def closure():
        opt.zero_grad()
        lp = _log_probs(_scores(w, c, feats, loss), seg, len(pos))[chosen]
        obj = -(wt * lp).sum() / wt.sum() + l2 * (w ** 2).sum() / len(pos)
        obj.backward()
        return obj

    opt.step(closure)
    return StyleModel(mean, std, w.detach().numpy().copy(), float(c.detach()))


def evaluate(model, positions):
    """Held-out choice metrics among approved moves: NLL and top-1 for the model, uniform choice, and loss-only."""
    pos = _usable(positions)
    if not pos:
        return {"n": 0}
    feats, loss, seg, chosen = _pack(pos, model.mean, model.std)
    n = len(pos)
    sizes = np.array([len(p.cands) for p in pos])
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]])

    def score(scores):
        lp = _log_probs(scores, seg, n)
        top1 = np.mean([int(np.argmax(scores[s:s + k].numpy())) == p.chosen for s, k, p in zip(starts, sizes, pos)])
        return {"nll": float(-lp[chosen].mean()), "top1": float(top1)}

    out = {"n": n,
           "style": score(_scores(torch.tensor(model.w), model.loss_coef, feats, loss)),
           "loss_only": score(-loss * 10.0),
           "uniform": {"nll": float(np.mean(np.log(sizes))), "top1": float(np.mean(1.0 / sizes))}}
    return out


def profile(model, top=None):
    """[(feature, weight)] sorted by absolute weight: the readable preferences."""
    pairs = sorted(zip(model.names, model.w.tolist()), key=lambda t: -abs(t[1]))
    return pairs[:top] if top else pairs


def bootstrap_weights(positions, standardise, n=30, seed=0, l2=1.0):
    """(n, F) weight vectors from resampling positions with replacement: the spread is the uncertainty of each weight."""
    pos = _usable(positions)
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        idx = rng.integers(0, len(pos), len(pos))
        out.append(fit([pos[i] for i in idx], l2=l2, standardise=standardise).w)
    return np.array(out)


def compare_to_baseline(player, baseline, n_boot=30, seed=0, l2=1.0):
    """How the player's preferences differ from a baseline population's, on the population's feature scale.

    Returns {"names", "w_player", "w_base", "z"}: z = (w_player - w_base) / sqrt(se_player^2 + se_base^2), the standard
    error coming from bootstrap resampling of positions (the baseline's own noise is included)."""
    std = standardiser(baseline)
    wp = fit(player, l2=l2, standardise=std).w
    wb = fit(baseline, l2=l2, standardise=std).w
    se_p = bootstrap_weights(player, std, n_boot, seed, l2).std(0)
    se_b = bootstrap_weights(baseline, std, n_boot, seed + 1, l2).std(0)
    z = (wp - wb) / np.sqrt(se_p ** 2 + se_b ** 2 + 1e-12)
    return {"names": FEATURE_NAMES, "w_player": wp, "w_base": wb, "z": z}


# ---- rating-dependent style ---------------------------------------------------------------------------------------

RATING_CENTER, RATING_SCALE = 1900, 400.0


def _rt(rating):
    return (rating - RATING_CENTER) / RATING_SCALE


def with_rating_terms(positions):
    """Copies whose features are [f, f * rt] (rt = rating centred at 1900, in units of 400), so one fit learns both a
    base style w0 and how each preference changes with rating (w1): w(rating) = w0 + w1 * rt."""
    return [Position(**{**p.__dict__, "feats": np.concatenate([p.feats, p.feats * _rt(p.rating)], axis=1)})
            for p in positions]


def fit_by_rating(positions, l2=1.0):
    """StyleModel with 2F weights (see with_rating_terms)."""
    aug = with_rating_terms(positions)
    m = fit(aug, l2=l2)
    m.names = tuple(FEATURE_NAMES) + tuple(f"{n}*rating" for n in FEATURE_NAMES)
    return m


def expected_weights(model, rating, std_of=None):
    """The population's weight vector (F,) at `rating`, on the augmented model's own feature scale for the base terms.

    Weights of the interaction block are per (feature * rt) standardised unit, so the result is only comparable with a
    player's weights fitted with the same standardisation; use `compare_to_rating_baseline` for that."""
    F = len(FEATURE_NAMES)
    return model.w[:F] + model.w[F:] * _rt(rating)


def compare_to_rating_baseline(player, baseline, n_boot=30, seed=0, l2=1.0):
    """Like compare_to_baseline, but the baseline is the population's expected style at the PLAYER's own ratings.

    The player's positions are given the population's rating-dependent weights by evaluating both on the same
    augmented scale: the player is fitted with the same augmented features, and the comparison is made at the player's
    mean rating, w0 + w1 * rt_mean, for both."""
    F = len(FEATURE_NAMES)
    base_aug, player_aug = with_rating_terms(baseline), with_rating_terms(player)
    std = standardiser(base_aug)
    rt = float(np.mean([_rt(p.rating) for p in player]))

    def at_rating(w):
        return w[:F] + w[F:] * rt

    wp = at_rating(fit(player_aug, l2=l2, standardise=std).w)
    wb = at_rating(fit(base_aug, l2=l2, standardise=std).w)
    se_p = np.array([at_rating(w) for w in bootstrap_weights(player_aug, std, n_boot, seed, l2)]).std(0)
    se_b = np.array([at_rating(w) for w in bootstrap_weights(base_aug, std, n_boot, seed + 1, l2)]).std(0)
    z = (wp - wb) / np.sqrt(se_p ** 2 + se_b ** 2 + 1e-12)
    return {"names": FEATURE_NAMES, "w_player": wp, "w_base": wb, "z": z, "rating": RATING_CENTER + rt * RATING_SCALE}


def style_gain_by_band(positions, edges, seed=0, l2=1.0):
    """[(lo, hi, n, gain_nll, gain_top1)]: how much the style features add over a strength-only model within each
    rating band, on held-out positions (random half/half). Tests "style hardens with rating"."""
    from .candidates import Position as _P  # noqa: F401  (type only)
    rng = np.random.default_rng(seed)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        band = [p for p in _usable(positions) if lo <= p.rating < hi]
        if len(band) < 200:
            out.append((lo, hi, len(band), float("nan"), float("nan")))
            continue
        idx = rng.permutation(len(band))
        cut = len(band) // 2
        train, test = [band[i] for i in idx[:cut]], [band[i] for i in idx[cut:]]
        std = standardiser(train)
        full = evaluate(fit(train, l2=l2, standardise=std), test)["style"]
        base = evaluate(fit(train, l2=1e6, standardise=std), test)["style"]
        out.append((lo, hi, len(band), base["nll"] - full["nll"], full["top1"] - base["top1"]))
    return out
