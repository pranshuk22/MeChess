"""Habit rates: how often does a player's move have each feature, with no engine and no filtering by move quality?

Choice-level style (which of several equally good moves) is clean but thin: most decisions are dominated by strength and
the position. Plain rates are the opposite: much more reliable, but they mix taste with the positions a player reaches (their
openings, their rating, the time control). This module measures how reliable the rates are across players (split-half over
alternating games), with and without removing the linear effect of rating, so the two views can be compared."""
from pathlib import Path

import chess
import numpy as np

from . import cohort as CO
from .features import FEATURE_NAMES, move_features


def item_features(items):
    """(features of the played move for every item as (n, F) float32, game index per item)."""
    out = np.zeros((len(items), len(FEATURE_NAMES)), dtype=np.float32)
    for k, it in enumerate(items):
        f = move_features(chess.Board(it.fen), chess.Move.from_uci(it.played))
        out[k] = [f[n] for n in FEATURE_NAMES]
    return out, np.array([it.game for it in items], dtype=np.int32)


def cohort_rates(folder, *, log=print, every=100):
    """{player id: (features, games)} for every fetched player, cached per player under <folder>/rates/ (resumable)."""
    folder = Path(folder)
    cache = folder / "rates"
    cache.mkdir(exist_ok=True)
    out = {}
    files = sorted((folder / "items").glob("*.jsonl"))
    for i, path in enumerate(files, 1):
        c = cache / f"{path.stem}.npz"
        if c.exists():
            with np.load(c) as z:
                out[path.stem] = (z["feats"], z["games"])
        else:
            feats, games = item_features(CO.load_items(path))
            tmp = c.with_name(c.stem + ".partial.npz")
            np.savez_compressed(tmp, feats=feats, games=games)
            tmp.rename(c)  # a killed run never leaves a half-written cache file behind
            out[path.stem] = (feats, games)
        if log and i % every == 0:
            log(f"  {i}/{len(files)} players")
    return out


def half_means(feats, games):
    """(mean of each feature over the even-ranked games, over the odd-ranked ones): alternating halves cover the whole period."""
    order = {g: k for k, g in enumerate(sorted(set(games.tolist())))}
    parity = np.array([order[g] % 2 for g in games.tolist()])
    if parity.min() == parity.max():
        raise ValueError("a player needs at least two games")
    return feats[parity == 0].mean(0), feats[parity == 1].mean(0)


def _corr(a, b):
    return float(np.corrcoef(a, b)[0, 1]) if a.std() > 1e-12 and b.std() > 1e-12 else 0.0


def reliability(rates, ratings=None, min_decisions=100):
    """Per feature: mean rate, between-player SD, split-half reliability r, Spearman-Brown r for the full data (2r / (1 + r)),
    r after removing the linear effect of rating from both halves, and the correlation of the rate with rating."""
    ids = [i for i, (f, g) in rates.items() if len(g) >= min_decisions and len(set(g.tolist())) >= 2]
    WA, WB = (np.array(x) for x in zip(*[half_means(*rates[i]) for i in ids]))
    rows = []
    rating = np.array([ratings[i] for i in ids], dtype=float) if ratings else None
    for j, name in enumerate(FEATURE_NAMES):
        a, b = WA[:, j], WB[:, j]
        r = _corr(a, b)
        row = {"name": name, "mean": float((a.mean() + b.mean()) / 2), "sd": float(np.concatenate([a, b]).std()), "r_half": r,
               "r_full": 2 * r / (1 + r) if r > -0.99 else 0.0}
        if rating is not None:
            slope, icpt = np.polyfit(rating, (a + b) / 2, 1)
            row["r_half_net_of_rating"] = _corr(a - (icpt + slope * rating), b - (icpt + slope * rating))
            row["corr_with_rating"] = _corr((a + b) / 2, rating)
        rows.append(row)
    return rows, len(ids)


def render(rows, n_players):
    has = "r_half_net_of_rating" in rows[0]
    L = [f"Habit rates over {n_players} players (split-half reliability across players; 1 = players differ stably, 0 = noise)", "",
         f"{'feature':22s} {'mean rate':>9s} {'SD':>7s} {'r half':>7s} {'r full':>7s}" + (f" {'net of rating':>14s} {'corr rating':>12s}" if has else "")]
    for r in sorted(rows, key=lambda r: -r["r_half"]):
        L.append(f"{r['name']:22s} {r['mean']:9.3f} {r['sd']:7.3f} {r['r_half']:+7.2f} {r['r_full']:+7.2f}"
                 + (f" {r['r_half_net_of_rating']:+14.2f} {r['corr_with_rating']:+12.2f}" if has else ""))
    return "\n".join(L)


# ---- who is who: anchors and a player, by habit rates ---------------------------------------------------------------

def reliable_features(rows, min_r=0.2):
    """Features whose split-half reliability across the COHORT is at least `min_r` (chosen on the cohort only, so no
    peeking at the anchors or the player being compared)."""
    return [r["name"] for r in rows if r["r_half"] >= min_r]


def _vector(feats, names, mean, sd):
    idx = [FEATURE_NAMES.index(n) for n in names]
    return (feats[:, idx].mean(0) - mean[idx]) / sd[idx]


def cohort_scale(rows):
    """(mean, sd) per feature over cohort players, aligned with FEATURE_NAMES."""
    by = {r["name"]: r for r in rows}
    mean = np.array([by[n]["mean"] for n in FEATURE_NAMES])
    sd = np.array([max(by[n]["sd"], 1e-6) for n in FEATURE_NAMES])
    return mean, sd


def anchor_classification(anchor_rates, pole_of, rows, chunk_games=10, min_r=0.2):
    """Can habit rates tell the anchors apart? Each anchor's centroid comes from half of its games; chunks of `chunk_games`
    games from the other half are assigned to the nearest centroid (in cohort SD units, reliable features only).
    Returns anchor-level and pole-level accuracy with their baselines."""
    names = reliable_features(rows, min_r)
    mean, sd = cohort_scale(rows)
    cent, chunks = {}, []
    for key, (feats, games) in anchor_rates.items():
        order = sorted(set(games.tolist()))
        rank = {g: k for k, g in enumerate(order)}
        parity = np.array([rank[g] % 2 for g in games.tolist()])
        if (parity == 0).sum() < 30 or (parity == 1).sum() < 30:
            continue
        cent[key] = _vector(feats[parity == 0], names, mean, sd)
        bg = [g for g in order if rank[g] % 2 == 1]
        for s in range(0, len(bg) - chunk_games + 1, chunk_games):
            sel = np.isin(games, bg[s:s + chunk_games])
            chunks.append((key, _vector(feats[sel], names, mean, sd)))
    keys = sorted(cent)
    if len(keys) < 2 or not chunks:
        raise ValueError("need at least two anchors with enough games")
    hit = hit_pole = 0
    per = {k: [0, 0] for k in keys}
    for true, v in chunks:
        pred = keys[int(np.argmin([np.linalg.norm(v - cent[k]) for k in keys]))]
        hit += pred == true
        hit_pole += pole_of.get(pred) == pole_of.get(true)
        per[true][0] += pred == true
        per[true][1] += 1
    poles = [pole_of.get(k) for k, _ in chunks]
    maj = max(poles.count(p) for p in set(poles)) / len(poles)
    return {"n_chunks": len(chunks), "n_anchors": len(keys), "features": names, "anchor_accuracy": hit / len(chunks),
            "anchor_chance": 1.0 / len(keys), "pole_accuracy": hit_pole / len(chunks), "pole_majority": maj,
            "per_anchor": {k: v[0] / v[1] for k, v in per.items() if v[1]}}


def player_profile(feats, rows, min_r_full=0.3):
    """A player's habit rates in cohort SD units, for the features reliable enough (Spearman-Brown r >= min_r_full),
    most extreme first: [(feature, rate, cohort mean, z)]."""
    mean, sd = cohort_scale(rows)
    m = feats.mean(0)
    out = [(r["name"], float(m[FEATURE_NAMES.index(r["name"])]), r["mean"],
            float((m[FEATURE_NAMES.index(r["name"])] - mean[FEATURE_NAMES.index(r["name"])]) / sd[FEATURE_NAMES.index(r["name"])]))
           for r in rows if r["r_full"] >= min_r_full]
    return sorted(out, key=lambda t: -abs(t[3]))


def render_who(cls, profile):
    L = ["", "Can habit rates tell the anchors apart?",
         f"  anchor level: {100 * cls['anchor_accuracy']:.0f}% of {cls['n_chunks']} held-out chunks (chance {100 * cls['anchor_chance']:.1f}%)",
         f"  pole level:   {100 * cls['pole_accuracy']:.0f}% (majority baseline {100 * cls['pole_majority']:.0f}%)",
         f"  features used (cohort reliability >= 0.2): {', '.join(cls['features'])}"]
    if profile:
        L += ["", "The player's habit rates against the cohort (reliable features only; z in cohort SD units):"]
        L += [f"  {n:20s} rate {r:.3f}  cohort {m:.3f}  z {z:+.2f}" for n, r, m, z in profile]
    return "\n".join(L)
