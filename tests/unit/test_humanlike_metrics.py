import numpy as np
import pytest

from chessme.humanlike import metrics as M


def test_nll_is_minus_log_probability_and_never_infinite():
    assert M.nll([1.0, 0.5, 0.25]) == pytest.approx([0.0, np.log(2), np.log(4)])
    assert np.isfinite(M.nll([0.0])).all()


def test_ece_is_zero_for_a_perfectly_calibrated_model_and_large_for_an_overconfident_one():
    rng = np.random.default_rng(0)
    conf = rng.uniform(0.2, 1.0, 200_000)
    calibrated = rng.uniform(size=conf.size) < conf                      # correct with exactly the stated probability
    e, rows = M.ece(conf, calibrated)
    assert e < 0.01 and sum(r[2] for r in rows) == conf.size
    over = rng.uniform(size=conf.size) < conf - 0.2                      # claims 20 points more than it delivers
    assert M.ece(np.clip(conf, 0, 1), over)[0] == pytest.approx(0.2, abs=0.02)


def test_ece_edge_cases():
    assert np.isnan(M.ece([], [])[0])
    e, rows = M.ece([1.0, 1.0], [True, False])                           # confidence 1.0 lands in the last bin, not out of range
    assert e == pytest.approx(0.5) and len(rows) == 1


def test_rating_bins_follow_the_maia3_balancing():
    assert list(M.rating_bin([550, 599, 600, 1749, 2599, 2600, 2999])) == [500, 500, 600, 1700, 2500, 2600, 2600]


def test_clock_regimes_and_missing_clocks():
    got = M.clock_regime([120.0, 30.0, 29.9, 10.0, 9.9, np.nan])
    assert list(got) == ["30s+", "30s+", "10-30s", "10-30s", "<10s", "unknown"]


def test_phase_matches_the_comparison_groups():
    got = M.phase_of([5, 25, 25, 5], [12, 12, 5, 4])
    assert list(got) == ["opening", "middlegame", "endgame", "endgame"]


def test_comparable_mask_reproduces_the_published_filters():
    ply = np.array([4, 10, 30, 30, 50])
    after_low = np.array([False, False, False, True, True])
    assert list(M.comparable_mask(ply, None, after_low)) == [False, True, True, False, False]


def test_cluster_bootstrap_interval_reflects_the_number_of_games_not_positions():
    rng = np.random.default_rng(1)
    games = np.repeat(np.arange(40), 50)                                 # 40 games x 50 correlated positions
    game_effect = rng.normal(0, 1, 40)[games]
    values = game_effect + rng.normal(0, 0.01, games.size)
    mean, lo, hi, n, g = M.cluster_bootstrap_mean(values, games, n_boot=500)
    assert (n, g) == (2000, 40) and lo < mean < hi
    # treating the 2000 positions as independent would give an interval about 7x narrower than the cluster one
    naive = 1.96 * values.std() / np.sqrt(values.size)
    assert (hi - lo) / 2 > 3 * naive


def test_paired_bootstrap_detects_a_real_difference_and_not_a_null_one():
    rng = np.random.default_rng(2)
    games = np.repeat(np.arange(300), 10)
    base = rng.uniform(size=games.size)
    better = base + 0.1 + rng.normal(0, 0.05, games.size)
    d, lo, hi, _, _ = M.paired_cluster_bootstrap(better, base, games, n_boot=500)
    assert d == pytest.approx(0.1, abs=0.01) and lo > 0
    noise = rng.normal(0, 0.05, games.size // 2)
    same = base + np.concatenate([noise, -noise])                        # zero-mean noise with an exactly zero overall difference: a true null
    d, lo, hi, _, _ = M.paired_cluster_bootstrap(same, base, games, n_boot=500)
    assert d == pytest.approx(0.0, abs=1e-9) and lo < 0 < hi


def test_the_interval_coverage_is_about_95_percent():
    """Simulation: the true mean is 0; the 95% interval should contain it in roughly 95% of repeated experiments."""
    rng = np.random.default_rng(3)
    hits, trials = 0, 150
    for t in range(trials):
        games = np.repeat(np.arange(60), 5)
        values = rng.normal(0, 1, 60)[games] + rng.normal(0, 1, games.size)
        _, lo, hi, _, _ = M.cluster_bootstrap_mean(values, games, n_boot=300, seed=t)
        hits += lo <= 0 <= hi
    assert 0.88 <= hits / trials <= 1.0


def test_a_mask_restricts_the_positions_and_alpha_widens_the_interval():
    rng = np.random.default_rng(4)
    games = np.repeat(np.arange(100), 4)
    v = rng.normal(0, 1, games.size)
    mask = np.arange(games.size) % 2 == 0
    _, _, _, n, g = M.cluster_bootstrap_mean(v, games, n_boot=100, mask=mask)
    assert n == mask.sum() and g == 100
    _, lo5, hi5, _, _ = M.cluster_bootstrap_mean(v, games, n_boot=800, alpha=0.05)
    _, lo01, hi01, _, _ = M.cluster_bootstrap_mean(v, games, n_boot=800, alpha=0.01)
    assert hi01 - lo01 > hi5 - lo5


def test_degenerate_inputs():
    assert np.isnan(M.cluster_bootstrap_mean([], [])[0])
    m, lo, hi, n, g = M.cluster_bootstrap_mean([1.0, 3.0], ["a", "a"])
    assert (m, lo, hi, n, g) == (2.0, 2.0, 2.0, 2, 1)
