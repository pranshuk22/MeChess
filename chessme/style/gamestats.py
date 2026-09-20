"""Analysis of the game-level style features (plan 8m sections 5 and 6): reliability, the pre-fixed quality gates, identification of
players from their features, and factor analysis validated on held-out players.

Every player's games are split into alternating halves A and B (the games arrive newest first, so parity covers the whole period).
A feature is *reliable* when players' values in half A agree with their values in half B; a feature set can *identify* players when the
half-A profile of each player is nearest to that same player's half-B profile among all players."""
import numpy as np

from . import gamefeatures as G

NAMES = list(G.ALL_NAMES)
# Artefacts, excluded from every analysis: the first move's clock reading depends on the time control's increment, not on the player.
EXCLUDED = {"first_think_rel"}
GATE = {"min_coverage": 0.6, "min_r_full": 0.5, "max_abs_rating_corr": 0.5}


# ---- matrices --------------------------------------------------------------------------------------------------------

def player_matrices(players):
    """(ids, X_all, X_A, X_B, ratings): aggregated feature vectors (over G.ALL_NAMES) for all games and for each alternating half."""
    ids = sorted(players)
    XA, XB, XT, R = [], [], [], []
    for pid in ids:
        rating, arr, metas = players[pid]
        a = [i for i in range(len(arr)) if i % 2 == 0]
        b = [i for i in range(len(arr)) if i % 2 == 1]
        XA.append(G.aggregate([arr[i] for i in a], [metas[i] for i in a]))
        XB.append(G.aggregate([arr[i] for i in b], [metas[i] for i in b]))
        XT.append(G.aggregate(list(arr), list(metas)))
        R.append(rating)
    return ids, np.array(XT), np.array(XA), np.array(XB), np.array(R, dtype=float)


def time_control_profile(players):
    """(XA, XB, labels): each player's share of games per time control in the two alternating halves (a baseline: how well does the
    time control alone identify players? Clock features partly carry it)."""
    ids = sorted(players)
    labels = sorted({m.get("time_control", "?") for pid in ids for m in players[pid][2]})
    col = {t: i for i, t in enumerate(labels)}
    XA, XB = np.zeros((len(ids), len(labels))), np.zeros((len(ids), len(labels)))
    for r, pid in enumerate(ids):
        metas = players[pid][2]
        for i, m in enumerate(metas):
            (XA if i % 2 == 0 else XB)[r, col[m.get("time_control", "?")]] += 1
    XA /= np.maximum(XA.sum(1, keepdims=True), 1)
    XB /= np.maximum(XB.sum(1, keepdims=True), 1)
    return XA, XB, labels


def _corr(a, b):
    return float(np.corrcoef(a, b)[0, 1]) if len(a) > 2 and a.std() > 1e-12 and b.std() > 1e-12 else float("nan")


# ---- reliability -----------------------------------------------------------------------------------------------------

def feature_reliability(XA, XB, ratings, names=NAMES, min_players=30):
    """One row per feature: coverage (share of players with the feature in both halves), split-half r, Spearman-Brown r for the full
    data, r after removing the linear effect of rating from both halves, and the correlation of the feature with rating."""
    rows = []
    for j, name in enumerate(names):
        ok = np.isfinite(XA[:, j]) & np.isfinite(XB[:, j])
        row = {"name": name, "family": G.FAMILY.get(name, "opening" if name.startswith("eco") or "eco" in name else "repertoire"),
               "coverage": float(ok.mean()), "r_half": float("nan"), "r_full": float("nan"), "r_net": float("nan"), "rating_corr": float("nan")}
        if name in EXCLUDED:
            row["coverage"] = 0.0          # never usable
        elif ok.sum() >= min_players:
            a, b, r = XA[ok, j], XB[ok, j], ratings[ok]
            row["r_half"] = _corr(a, b)
            row["r_full"] = 2 * row["r_half"] / (1 + row["r_half"]) if row["r_half"] > -0.99 else float("nan")
            mean = (a + b) / 2
            row["rating_corr"] = _corr(mean, r)
            slope, icpt = np.polyfit(r, mean, 1)
            row["r_net"] = _corr(a - (icpt + slope * r), b - (icpt + slope * r))
        rows.append(row)
    return rows


def passes_gate(row, gate=GATE):
    """The pre-fixed keep rule: enough coverage, full-data reliability at least 0.5, and either weakly related to rating or
    still reliable after removing rating."""
    if not all(np.isfinite([row["r_full"], row["coverage"]])):
        return False
    net_ok = np.isfinite(row["r_net"]) and 2 * row["r_net"] / (1 + row["r_net"]) >= gate["min_r_full"]
    rating_ok = np.isfinite(row["rating_corr"]) and abs(row["rating_corr"]) <= gate["max_abs_rating_corr"]
    return row["coverage"] >= gate["min_coverage"] and row["r_full"] >= gate["min_r_full"] and (rating_ok or net_ok)


# ---- identification --------------------------------------------------------------------------------------------------

def _standardise(XA, XB, idx):
    both = np.vstack([XA[:, idx], XB[:, idx]])
    mean = np.nanmean(both, axis=0)
    sd = np.nanstd(both, axis=0)
    sd = np.where(sd < 1e-9, 1.0, sd)
    prep = lambda X: np.nan_to_num((X[:, idx] - mean) / sd, nan=0.0)      # a missing value is "average"
    return prep(XA), prep(XB)


def identification(XA, XB, idx, top_k=5):
    """Nearest-profile identification among all players: reference = half A, query = half B (and the reverse, averaged).
    Returns accuracy, top-k accuracy and the chance level."""
    if len(idx) == 0:
        return {"top1": float("nan"), "topk": float("nan"), "chance": 1.0 / len(XA), "n_features": 0}
    A, B = _standardise(XA, XB, idx)
    n = len(A)
    hits1 = hitsk = 0
    for ref, qry in ((A, B), (B, A)):
        d = ((qry[:, None, :] - ref[None, :, :]) ** 2).sum(-1)               # query i vs reference j
        true = d[np.arange(n), np.arange(n)][:, None]
        rank = (d < true).sum(1)                                             # how many references are closer than the true one
        ties = (d == true).sum(1) - 1                                        # identical distance: the true one is picked at random
        hits1 += ((rank == 0) / (1.0 + ties)).sum()
        hitsk += (rank + ties / 2.0 < top_k).sum()
    return {"top1": hits1 / (2 * n), "topk": hitsk / (2 * n), "chance": 1.0 / n, "n_features": len(idx)}


def identification_by_family(XA, XB, rows, gated_only=False):
    """{label: identification result} for each family and for everything, using all features with data (or only gated ones)."""
    out = {}
    usable = [j for j, r in enumerate(rows) if r["coverage"] >= 0.6 and r["name"] not in EXCLUDED and (not gated_only or passes_gate(r))]
    for fam in ("opening", "shape", "clock", "repertoire"):
        idx = [j for j in usable if rows[j]["family"] == fam]
        if idx:
            out[fam] = identification(XA, XB, idx)
    out["all"] = identification(XA, XB, usable)
    return out


# ---- factor analysis -------------------------------------------------------------------------------------------------

def _residualise(X, ratings, coef=None):
    """Remove the linear effect of rating from every column; `coef` (from a development set) is applied unchanged to new data."""
    if coef is None:
        coef = []
        for j in range(X.shape[1]):
            ok = np.isfinite(X[:, j])
            coef.append(np.polyfit(ratings[ok], X[ok, j], 1) if ok.sum() > 3 else np.array([0.0, np.nanmean(X[:, j]) if ok.any() else 0.0]))
    out = X.copy()
    for j, (s, c) in enumerate(coef):
        out[:, j] = X[:, j] - (c + s * ratings)
    return out, coef


def factor_analysis(XA, XB, ratings, idx, *, dev_frac=0.5, max_components=6, seed=0, min_reliability=0.6, min_congruence=0.85):
    """PCA on rating-residualised, standardised features of a development half of the players; each component is then scored on
    the held-out players' two halves separately. A component is *kept* when its held-out split-half reliability (Spearman-Brown)
    is at least `min_reliability` and its loadings agree (Tucker congruence) with a PCA fitted on the held-out players alone."""
    n = len(XA)
    rng = np.random.default_rng(seed)
    order = rng.permutation(n)
    dev, test = order[: int(n * dev_frac)], order[int(n * dev_frac):]
    both = np.vstack([XA[dev][:, idx], XB[dev][:, idx]])
    mean, sd = np.nanmean(both, axis=0), np.nanstd(both, axis=0)
    sd = np.where(sd < 1e-9, 1.0, sd)

    def prep(X, r, coef=None):
        res, coef = _residualise(X[:, idx], r, coef)
        Z = np.nan_to_num((res - (np.nanmean(res, axis=0) if coef is None else 0)) / 1.0, nan=0.0)
        return Z, coef

    Rdev = ratings[dev]
    Xdev = (XA[dev][:, idx] + XB[dev][:, idx]) / 2
    res_dev, coef = _residualise(np.where(np.isfinite(Xdev), Xdev, np.nan), Rdev)
    m2 = np.nanmean(res_dev, axis=0)
    s2 = np.where(np.nanstd(res_dev, axis=0) < 1e-9, 1.0, np.nanstd(res_dev, axis=0))
    Zdev = np.nan_to_num((res_dev - m2) / s2, nan=0.0)
    _, S, Vt = np.linalg.svd(Zdev, full_matrices=False)
    k = min(max_components, len(S))
    V = Vt[:k]                                                                # (k, features)
    explained = (S[:k] ** 2) / (S ** 2).sum()

    def score(X, r):
        res, _ = _residualise(X[:, idx], r, coef)
        return np.nan_to_num((res - m2) / s2, nan=0.0) @ V.T

    Rt = ratings[test]
    SA, SB = score(XA[test], Rt), score(XB[test], Rt)
    # a PCA on the held-out players alone, for loading stability
    Xt = (XA[test][:, idx] + XB[test][:, idx]) / 2
    res_t, _ = _residualise(np.where(np.isfinite(Xt), Xt, np.nan), Rt)
    st = np.where(np.nanstd(res_t, axis=0) < 1e-9, 1.0, np.nanstd(res_t, axis=0))
    Zt = np.nan_to_num((res_t - np.nanmean(res_t, axis=0)) / st, nan=0.0)
    Vt_test = np.linalg.svd(Zt, full_matrices=False)[2][:k]
    comps = []
    for c in range(k):
        r_half = _corr(SA[:, c], SB[:, c])
        r_full = 2 * r_half / (1 + r_half) if r_half > -0.99 else float("nan")
        cong = max(abs(float(V[c] @ v / (np.linalg.norm(V[c]) * np.linalg.norm(v) + 1e-12))) for v in Vt_test)
        load = V[c]
        top = np.argsort(-np.abs(load))[:6]
        comps.append({"component": c + 1, "explained": float(explained[c]), "reliability": r_full, "congruence": cong,
                      "kept": bool(np.isfinite(r_full) and r_full >= min_reliability and cong >= min_congruence),
                      "top_loadings": [(NAMES[idx[j]], float(load[j])) for j in top]})
    return {"components": comps, "n_dev": len(dev), "n_test": len(test), "V": V, "idx": list(idx)}


# ---- report ----------------------------------------------------------------------------------------------------------

def render(rows, ident_all, ident_gated, fa, n_players, tc_ident=None):
    L = [f"Game-level style features: {n_players} players, games split into alternating halves.", "",
         "RELIABILITY (r_full = Spearman-Brown; net = after removing the linear effect of rating; gate = the pre-fixed keep rule)",
         f"  {'feature':22s} {'family':10s} {'cover':>6s} {'r_full':>7s} {'net':>6s} {'rating r':>9s} gate"]
    for r in sorted(rows, key=lambda r: -(r["r_full"] if np.isfinite(r["r_full"]) else -9)):
        L.append(f"  {r['name']:22s} {r['family']:10s} {r['coverage']:6.2f} {r['r_full']:+7.2f} {r['r_net']:+6.2f} {r['rating_corr']:+9.2f} "
                 + ("KEEP" if passes_gate(r) else ""))
    kept = [r["name"] for r in rows if passes_gate(r)]
    L += ["", f"{len(kept)} of {len(rows)} features pass the gate.", "",
          f"IDENTIFICATION (nearest profile among {n_players} players; chance {100 / n_players:.2f}%)"]
    for label, res in (("all features with data", ident_all), ("gated features only", ident_gated)):
        L.append(f"  {label}:")
        for fam, r in res.items():
            L.append(f"    {fam:10s} top-1 {100 * r['top1']:5.1f}%   top-5 {100 * r['topk']:5.1f}%   ({r['n_features']} features)")
    if tc_ident:
        L += ["", f"  baseline, the time control alone (share of games per time control): top-1 {100 * tc_ident['top1']:.1f}%, "
                  f"top-5 {100 * tc_ident['topk']:.1f}% -- clock features partly carry this; read their identification with it in mind"]
    if fa:
        L += ["", f"FACTORS (development players {fa['n_dev']}, held-out {fa['n_test']}; kept = reliability >= 0.6 and loading agreement >= 0.85 on held-out players)"]
        for c in fa["components"]:
            top = ", ".join(f"{n}{'+' if v > 0 else '-'}" for n, v in c["top_loadings"][:5])
            L.append(f"  component {c['component']}: explains {100 * c['explained']:4.1f}%  reliability {c['reliability']:+.2f}  agreement {c['congruence']:.2f}  "
                     f"{'KEPT' if c['kept'] else 'dropped'}   {top}")
    return "\n".join(L)
