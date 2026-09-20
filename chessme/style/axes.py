"""Named style axes: groups of features with a sign, defined BEFORE looking at any player (plan 8f-3).

An axis score is the mean of sign * z over its features, where z is the feature's difference from the baseline
population in standard errors. They are hypotheses: an axis is kept only if the anchor players sort as the literature
says (e.g. Tal above Petrosian on aggression); until that check is done, results are reported as "hypothesis axes"."""
import numpy as np

AXES = {
    "aggression": {"king_zone_delta": 1, "pawn_storm": 1, "check": 1, "sacrifice": 1, "exchange_sacrifice": 1},
    "risk_taking": {"sacrifice": 1, "exchange_sacrifice": 1, "weakens_own_king": 1, "concedes_bishop_pair": 1,
                    "own_doubled_delta": 1, "own_isolated_delta": 1},
    "simplification": {"trade": 1, "queen_trade": 1, "capture": 1, "pawn_push": -1},
    "structural_care": {"own_doubled_delta": -1, "own_isolated_delta": -1, "takes_bishop_pair": 1,
                        "concedes_bishop_pair": -1, "rook_open_file": 1, "rook_semi_open_file": 1},
    "activity": {"mobility_delta": 1, "to_center": 1, "rook_seventh": 1, "retreat": -1},
}


def axis_scores(names, z):
    """{axis: mean sign * z over the axis's features}; features missing from `names` are an error (no silent skips)."""
    index = {n: i for i, n in enumerate(names)}
    out = {}
    for axis, feats in AXES.items():
        missing = [f for f in feats if f not in index]
        if missing:
            raise KeyError(f"axis {axis!r} uses unknown features {missing}")
        out[axis] = float(np.mean([sign * z[index[f]] for f, sign in feats.items()]))
    return out
