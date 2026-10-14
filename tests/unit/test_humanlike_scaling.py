import numpy as np
import pytest

from chessme.humanlike import scaling as SC


def synthetic(n_games=300, per=5, slope=-0.4, noise=1.0, seed=0):
    rng = np.random.default_rng(seed)
    groups = np.repeat(np.arange(n_games), per)
    base = rng.normal(0, noise, size=n_games)[groups]                    # a game effect shared by every size
    sizes = {"s": 4.0, "m": 16.0, "l": 64.0}
    per_size = {n: base + 1.0 + slope * np.log2(p) / 2 + rng.normal(0, noise, size=len(groups)) for n, p in sizes.items()}
    return per_size, sizes, groups


def test_the_slope_gaps_and_differences_are_recovered_with_honest_intervals():
    per_size, params, groups = synthetic(slope=-0.4)
    r = SC.gaps(per_size, params, groups, np.ones(len(groups), dtype=bool), "x", n_boot=300)
    lo, hi = r["slope"][1:]
    assert lo < -0.2 < hi and hi < 0                                      # -0.2 per doubling (the generator halves the slope), interval excludes 0
    assert r["diff"][("l", "s")][0] < 0 and r["diff"][("l", "s")][2] < 0
    assert abs(r["gap"]["s"][0] - np.mean(per_size["s"])) < 1e-9 and r["games"] == 300


def test_no_trend_gives_an_interval_around_zero():
    per_size, params, groups = synthetic(slope=0.0, seed=3)
    r = SC.gaps(per_size, params, groups, np.ones(len(groups), dtype=bool), "x", n_boot=300)
    assert r["slope"][1] < 0 < r["slope"][2] and r["diff"][("l", "s")][1] < 0 < r["diff"][("l", "s")][2]


def test_the_mask_restricts_the_positions_and_the_order_of_sizes_is_checked():
    per_size, params, groups = synthetic()
    mask = np.arange(len(groups)) % 2 == 0
    r = SC.gaps(per_size, params, groups, mask, "x", n_boot=50)
    assert r["positions"] == int(mask.sum())
    with pytest.raises(ValueError, match="increasing"):
        SC.gaps({"l": per_size["l"], "s": per_size["s"]}, params, groups, mask, "x")
    with pytest.raises(ValueError, match="two sizes"):
        SC.gaps({"s": per_size["s"]}, params, groups, mask, "x")


def test_same_seed_same_intervals():
    per_size, params, groups = synthetic()
    a = SC.gaps(per_size, params, groups, np.ones(len(groups), dtype=bool), "x", n_boot=100, seed=4)
    b = SC.gaps(per_size, params, groups, np.ones(len(groups), dtype=bool), "x", n_boot=100, seed=4)
    assert a == b


def test_a_mask_without_positions_gives_nan_not_a_crash():
    per_size, params, groups = synthetic()
    r = SC.gaps(per_size, params, groups, np.zeros(len(groups), dtype=bool), "x", n_boot=10)
    assert r["positions"] == 0 and np.isnan(r["slope"][0]) and np.isnan(r["gap"]["s"][0])
