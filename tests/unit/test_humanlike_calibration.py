import numpy as np
import pytest

from chessme.humanlike import calibration as K


def brute_auc(s, y):
    pos, neg = s[y == 1], s[y == 0]
    return np.mean([(a > b) + 0.5 * (a == b) for a in pos for b in neg])


def test_weighted_auc_matches_brute_force_including_ties_and_weights():
    rng = np.random.default_rng(0)
    s = np.round(rng.random(60), 1)                                   # many ties
    y = (rng.random(60) < 0.3 + 0.4 * s).astype(int)
    assert K.weighted_auc(s, y, np.ones(60)) == pytest.approx(brute_auc(s, y))
    w = rng.integers(0, 3, 60).astype(float)
    rep_s, rep_y = np.repeat(s, w.astype(int)), np.repeat(y, w.astype(int))
    assert K.weighted_auc(s, y, w) == pytest.approx(brute_auc(rep_s, rep_y))
    assert np.isnan(K.weighted_auc(s, np.ones(60), np.ones(60)))


def test_a_calibrated_model_has_slope_one_and_beats_the_base_rate_a_flat_one_does_not():
    rng = np.random.default_rng(1)
    q = rng.beta(0.6, 4, 40000)                                       # the true blunder probability of each position
    y = (rng.random(40000) < q).astype(float)
    w = np.ones(40000)
    good = K.measures(q, y, w)
    flat = K.measures(np.full(40000, y.mean()), y, w)
    assert good["slope"] == pytest.approx(1.0, abs=0.08) and good["auc"] > 0.7 and good["bss"] > 0.05
    assert flat["auc"] == pytest.approx(0.5) and flat["bss"] == pytest.approx(0.0, abs=1e-9)
    overconfident = 1 / (1 + np.exp(-3 * np.log(q / (1 - q))))
    assert K.measures(overconfident, y, w)["slope"] < 0.6              # too sure where blunders are
    rel = K.reliability(q, y, w, bins=5)
    assert len(rel) == 5 and all(abs(a - b) < 0.05 for a, b, _ in rel)


def test_bootstrap_ranks_a_better_model_and_gives_paired_differences():
    rng = np.random.default_rng(2)
    n = 6000
    gids = np.repeat(np.arange(n // 4), 4)
    q = rng.beta(0.6, 4, n)
    y = (rng.random(n) < q).astype(float)
    noisy = np.clip(q + rng.normal(0, 0.15, n), 0.001, 0.999)
    res = K.bootstrap({"good": q, "noisy": noisy}, y, gids, np.ones(n, bool), n_boot=60, difficulty=rng.integers(1, 4, n))
    assert res["n"] == n and res["good"]["auc"][0] > res["noisy"]["auc"][0]
    d = res["noisy"]["auc diff vs good"]
    assert d[0] < 0 and d[2] < 0.01
    text = K.render({"all": res})
    assert "good" in text and "noisy" in text and "skill vs difficulty-only" in text
