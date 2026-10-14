import numpy as np
import pytest

from chessme.humanlike import elo


def simulate(true, pairs, n, seed=0, draw=0.2):
    rng = np.random.default_rng(seed)
    out = []
    for k in range(n):
        for a, b in pairs:
            e = 1 / (1 + 10 ** (-(true[a] - true[b]) / 400))
            u = rng.random()
            win = max(0.0, e - draw / 2)
            s = 1.0 if u < win else (0.5 if u < win + draw else 0.0)
            out.append((a, b, s, k))
    return out


def test_ratings_are_recovered_from_simulated_matches():
    true = {"a": 0.0, "b": 150.0, "c": 400.0, "d": -200.0}
    pairs = [(x, y) for i, x in enumerate(true) for y in list(true)[i + 1:]]
    res = simulate(true, pairs, 300)
    r = elo.fit(list(true), res, anchor="a")
    for p in true:
        assert r[p] == pytest.approx(true[p], abs=40)
    assert r["a"] == 0.0


def test_the_interval_covers_the_truth_and_widens_with_fewer_games():
    true = {"a": 0.0, "b": 200.0}
    res = simulate(true, [("a", "b")], 400, seed=2)
    lo, hi = elo.bootstrap(["a", "b"], res, anchor="a", boot=150)["b"]
    assert lo < 200 < hi
    lo2, hi2 = elo.bootstrap(["a", "b"], res[:60], anchor="a", boot=150)["b"]
    assert hi2 - lo2 > hi - lo


def test_a_perfect_score_is_finite_and_ordering_is_kept():
    res = [("a", "b", 1.0, k) for k in range(40)] + [("b", "c", 0.5, k) for k in range(40)]
    r = elo.fit(["a", "b", "c"], res, anchor="c")
    assert np.isfinite(list(r.values())).all() and r["a"] > r["b"] and abs(r["b"] - r["c"]) < 30 and r["a"] - r["b"] > 300


def test_colour_symmetry_and_score_table():
    res = [("a", "b", 1.0, 0), ("b", "a", 0.0, 0), ("a", "b", 0.5, 1)]
    t = elo.score_table(res)
    assert t[("a", "b")] == (2, 1.5) and t[("b", "a")] == (1, 0.0)
    r = elo.fit(["a", "b"], res)
    assert r["a"] > r["b"] and r["a"] + r["b"] == pytest.approx(0, abs=1e-6)
