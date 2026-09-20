"""How much does the choice of judge engine change the style data? Compare two candidate datasets built from the same
decisions (same seed and limit): candidate sets, the 'played move was approved' rate, losses, and the fitted style."""
from pathlib import Path

import numpy as np

from . import candidates as SC
from . import model as M


def _key(p):
    return (p.fen, p.played)


def load_dir(folder):
    """{(fen, played): Position} over train+test of a dataset folder, plus its judge label."""
    out, judge = {}, ""
    for name in ("train", "test"):
        f = Path(folder) / f"{name}.npz"
        if f.exists():
            judge = SC.judge_of(f) or judge
            for p in SC.load(f):
                out[_key(p)] = p
    return out, judge


def compare(a, b, bands=((0, 1800), (1800, 2200), (2200, 3000))):
    """Agreement statistics between datasets a and b (dicts from load_dir) on their common decisions."""
    common = sorted(set(a) & set(b))
    rows = []
    for k in common:
        pa, pb = a[k], b[k]
        sa, sb = set(pa.cands), set(pb.cands)
        rows.append({"rating": pa.rating, "best_same": pa.cands[0] == pb.cands[0], "jaccard": len(sa & sb) / len(sa | sb),
                     "ok_a": pa.chosen >= 0, "ok_b": pb.chosen >= 0, "n_a": len(sa), "n_b": len(sb),
                     "lossdiff": abs(pa.played_loss - pb.played_loss) if not (np.isnan(pa.played_loss) or np.isnan(pb.played_loss)) else np.nan})
    if not rows:
        return {"common": 0}

    def agg(rs):
        return {"n": len(rs), "best_move_agreement": float(np.mean([r["best_same"] for r in rs])),
                "approved_set_overlap": float(np.mean([r["jaccard"] for r in rs])),
                "played_approved_a": float(np.mean([r["ok_a"] for r in rs])),
                "played_approved_b": float(np.mean([r["ok_b"] for r in rs])),
                "mean_candidates_a": float(np.mean([r["n_a"] for r in rs])),
                "mean_candidates_b": float(np.mean([r["n_b"] for r in rs])),
                "median_loss_difference_cp": float(np.nanmedian([r["lossdiff"] for r in rs])) if any(r["lossdiff"] == r["lossdiff"] for r in rs) else float("nan")}

    out = {"common": len(rows), "only_a": len(set(a) - set(b)), "only_b": len(set(b) - set(a)), "all": agg(rows), "bands": {}}
    for lo, hi in bands:
        rs = [r for r in rows if lo <= r["rating"] < hi]
        if rs:
            out["bands"][f"{lo}-{hi}"] = agg(rs)
    return out


def style_agreement(a, b, l2=1.0):
    """Fit the style model on each judge's data for the common decisions; how similar are the fitted preferences?
    Returns {"weight_correlation", "top_a", "top_b"} (correlation across the standardised weights, common scale)."""
    common = sorted(set(a) & set(b))
    pa, pb = [a[k] for k in common], [b[k] for k in common]
    std = M.standardiser(pa + pb)
    wa, wb = M.fit(pa, l2=l2, standardise=std), M.fit(pb, l2=l2, standardise=std)
    corr = float(np.corrcoef(wa.w, wb.w)[0, 1])
    return {"weight_correlation": corr, "loss_coef_a": wa.loss_coef, "loss_coef_b": wb.loss_coef,
            "top_a": [n for n, _ in M.profile(wa, 5)], "top_b": [n for n, _ in M.profile(wb, 5)]}


def render(cmp, sty, label_a, label_b):
    if not cmp["common"]:
        return "no common decisions"
    def block(name, s):
        return (f"{name}: {s['n']} decisions | best move same {100 * s['best_move_agreement']:.0f}% | approved-set overlap "
                f"{100 * s['approved_set_overlap']:.0f}% | played move approved: {label_a} {100 * s['played_approved_a']:.1f}% vs "
                f"{label_b} {100 * s['played_approved_b']:.1f}% | mean candidates {s['mean_candidates_a']:.1f} vs "
                f"{s['mean_candidates_b']:.1f} | median loss difference {s['median_loss_difference_cp']:.0f} cp")
    lines = [f"{cmp['common']} common decisions ({cmp['only_a']} only in {label_a}, {cmp['only_b']} only in {label_b})",
             block("all", cmp["all"])] + [block(f"rating {k}", v) for k, v in cmp["bands"].items()]
    lines += ["", f"fitted style, {label_a} vs {label_b}: correlation of the weights across features {sty['weight_correlation']:+.2f}; "
              f"strength weight {sty['loss_coef_a']:.2f} vs {sty['loss_coef_b']:.2f}",
              f"  strongest preferences under {label_a}: {', '.join(sty['top_a'])}",
              f"  strongest preferences under {label_b}: {', '.join(sty['top_b'])}"]
    return "\n".join(lines)
