import math

import pytest

from chessme import sprt


def test_expected_score_and_elo_are_inverse():
    assert sprt.expected_score(0) == pytest.approx(0.5)
    assert sprt.expected_score(400) == pytest.approx(10 / 11)
    for elo in (-300, -50, 0, 25, 200):
        assert sprt.elo_from_score(sprt.expected_score(elo)) == pytest.approx(elo)


def test_elo_from_extreme_scores_is_finite():
    assert math.isfinite(sprt.elo_from_score(0.0)) and math.isfinite(sprt.elo_from_score(1.0))


def test_standard_bounds():
    lo, hi = sprt.bounds(0.05, 0.05)
    assert hi == pytest.approx(2.944, abs=1e-3) and lo == pytest.approx(-2.944, abs=1e-3)
    assert sprt.bounds(0.01, 0.01)[1] > hi  # stricter error rates need more evidence


def test_moments_of_known_distribution():
    n, mean, var = sprt.pair_moments([0, 0, 10, 0, 10])  # ten draws-pairs (0.5) and ten 2-0 pairs (1.0)
    assert n == 20 and mean == pytest.approx(0.75) and var == pytest.approx(0.0625)
    assert sprt.pair_moments([0, 0, 0, 0, 0]) == (0, 0.5, 0.0)


def test_penta_index_mapping():
    assert [sprt.penta_index(p) for p in (0, 0.5, 1, 1.5, 2)] == [0, 1, 2, 3, 4]
    with pytest.raises(ValueError):
        sprt.penta_index(2.5)


def test_llr_is_zero_without_data():
    assert sprt.llr([0] * 5, 0, 5) == 0.0


def test_degenerate_samples_still_give_the_right_evidence():
    # Every pair identical => zero sample variance. That is not "no information": a clean sweep is strong
    # evidence for H1, and nothing but draws is evidence against any improvement.
    sweep = sprt.llr([0, 0, 0, 0, 30], 0, 10)
    draws = sprt.llr([0, 0, 30, 0, 0], 0, 10)
    assert math.isfinite(sweep) and sweep > sprt.bounds()[1]
    assert math.isfinite(draws) and draws < 0
    assert sprt.sprt_status([0, 0, 0, 0, 30], 0, 10) == "H1"
    assert sprt.sprt_status([30, 0, 0, 0, 0], 0, 10) == "H0"
    assert sprt.sprt_status([0, 0, 0, 0, 2], 0, 10) is None  # two pairs are not enough even for a sweep


def test_llr_sign_follows_the_evidence():
    winning = [2, 5, 20, 30, 25]
    losing = list(reversed(winning))
    assert sprt.llr(winning, 0, 10) > 0
    assert sprt.llr(losing, 0, 10) < 0


def test_llr_grows_with_more_of_the_same_evidence():
    base = [2, 5, 20, 30, 25]
    assert sprt.llr([3 * c for c in base], 0, 10) == pytest.approx(3 * sprt.llr(base, 0, 10))


def test_status_decisions():
    assert sprt.sprt_status([0, 0, 5, 30, 200], 0, 10) == "H1"    # crushing win
    assert sprt.sprt_status([200, 30, 5, 0, 0], 0, 10) == "H0"    # crushing loss
    assert sprt.sprt_status([2, 3, 4, 3, 2], 0, 10) is None       # dead even and few games: keep playing


def test_elo_estimate_direction_and_margin_shrinks_with_data():
    even = sprt.elo_estimate([10, 20, 40, 20, 10])
    assert even[0] == pytest.approx(0, abs=1e-6)
    better = sprt.elo_estimate([5, 10, 30, 35, 20])
    assert better[0] > 0
    small, large = sprt.elo_estimate([1, 2, 4, 2, 1]), sprt.elo_estimate([10, 20, 40, 20, 10])
    assert large[1] < small[1]
    assert sprt.elo_estimate([0] * 5) == (0.0, float("inf"))


def test_los():
    assert sprt.los([0] * 5) == 0.5
    assert sprt.los([10, 20, 40, 20, 10]) == pytest.approx(0.5)
    assert sprt.los([2, 5, 20, 30, 25]) > 0.99
    assert sprt.los([25, 30, 20, 5, 2]) < 0.01
