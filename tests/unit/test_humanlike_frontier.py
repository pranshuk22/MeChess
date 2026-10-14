import numpy as np
import pytest

from chessme.humanlike import frontier as F


def toy(n=200, k=6, seed=0):
    rng = np.random.default_rng(seed)
    p = rng.dirichlet(np.ones(k), size=n)
    loss = np.sort(rng.random((n, k)) * 0.5, axis=1)[:, ::-1]               # the likeliest moves are not the best
    loss = np.take_along_axis(loss, np.argsort(rng.random((n, k)), axis=1), axis=1)
    rank = rng.integers(1, k + 2, size=n)                                        # some human moves outside the candidates (rank k + 1)
    return {"p": p, "cand_loss": loss}, rank, np.repeat(np.arange(n // 4), 4)


def test_beta_zero_is_the_prior_and_every_policy_is_a_distribution():
    prep, _, _ = toy()
    q = F.prior(prep)
    assert np.allclose(F.policy(prep, "engine-reweighted", 0.0), q)
    for fam, vals in (("engine-reweighted", (-10, 5, 100)), ("temperature", (0.3, 1.0, 3.0)), ("mixture", (0.0, 0.4, 1.0))):
        for v in vals:
            pi = F.policy(prep, fam, v)
            assert np.allclose(pi.sum(axis=1), 1.0) and (pi >= -1e-12).all()


def test_more_beta_means_a_smaller_expected_loss_and_negative_beta_a_larger_one():
    prep, _, _ = toy()
    loss = lambda b: (F.policy(prep, "engine-reweighted", b) * prep["cand_loss"]).sum(axis=1).mean()
    assert loss(-10) > loss(0) > loss(5) > loss(50) > loss(500) - 1e-9
    assert loss(500) == pytest.approx(prep["cand_loss"].min(axis=1).mean(), abs=2e-3)         # the engine's choice in the limit


def test_mixture_one_is_the_best_candidate_and_zero_the_prior():
    prep, _, _ = toy()
    q = F.prior(prep)
    assert np.allclose(F.policy(prep, "mixture", 0.0), q)
    full = F.policy(prep, "mixture", 1.0)
    assert np.allclose((full * prep["cand_loss"]).sum(axis=1), prep["cand_loss"].min(axis=1))


def test_moves_without_prior_mass_are_never_chosen():
    prep, _, _ = toy()
    prep["p"][:, -1] = 0.0
    prep["cand_loss"][:, -1] = 0.0                                                # a free move that has no prior mass
    for fam, v in (("engine-reweighted", 100.0), ("mixture", 1.0)):
        assert (F.policy(prep, fam, v)[:, -1] == 0).all()


def test_the_human_move_must_be_a_judged_candidate_to_count():
    prep, rank, groups = toy()
    k = prep["cand_loss"].shape[1]
    idx = F.human_index(rank, k, prep["p"] > 0)
    assert (idx[rank > k] == -1).all() and (idx[rank <= k] == rank[rank <= k] - 1).all()
    rows = F.sweep(prep, rank, groups, np.ones(len(rank), dtype=bool), [("engine-reweighted", 0.0)], n_boot=20)
    assert rows[0]["covered"] == pytest.approx((rank <= k).mean())
    q = F.prior(prep)
    manual = -np.log(q[np.arange(len(rank)), np.clip(rank - 1, 0, k - 1)])[rank <= k].mean()
    assert rows[0]["nll"][0] == pytest.approx(manual, rel=1e-9)


def test_the_engine_reweighted_policy_loses_less_likelihood_than_sharpening_for_the_same_strength():
    rng = np.random.default_rng(1)
    n, k = 4000, 8
    loss = rng.random((n, k)) * 0.4
    p = rng.dirichlet(np.ones(k) * 0.7, size=n)
    human = np.array([rng.choice(k, p=pp) for pp in p])                           # the human plays the prior
    prep, rank, groups = {"p": p, "cand_loss": loss}, human + 1, np.repeat(np.arange(n // 4), 4)
    mask = np.ones(n, dtype=bool)
    eng = F.sweep(prep, rank, groups, mask, [("engine-reweighted", b) for b in (0, 5, 10, 20)], n_boot=10)
    tmp = F.sweep(prep, rank, groups, mask, [("temperature", t) for t in (1.0, 0.8, 0.6, 0.4)], n_boot=10)
    # match the strength of the temperature policy at tau = 0.6 with the engine-reweighted one by interpolation
    target = tmp[2]["expected loss"][0]
    xs = [r["expected loss"][0] for r in eng]
    ys = [r["nll"][0] for r in eng]
    nll_at_target = np.interp(target, xs[::-1], ys[::-1])
    assert nll_at_target < tmp[2]["nll"][0]                                         # engine information buys strength more cheaply here


def test_render_lists_every_setting():
    prep, rank, groups = toy()
    rows = F.sweep(prep, rank, groups, np.ones(len(rank), dtype=bool), [("temperature", 0.5), ("mixture", 0.3)], n_boot=10)
    text = F.render(rows, "## test")
    assert "temperature 0.5" in text and "mixture 0.3" in text and "NLL of the human's move" in text
    with pytest.raises(ValueError):
        F.policy(prep, "nope", 1.0)


def test_a_policy_that_gives_the_human_move_no_mass_costs_a_finite_floor():
    prep, rank, groups = toy()
    rows = F.sweep(prep, rank, groups, np.ones(len(rank), dtype=bool), [("engine-reweighted", 5000.0)], n_boot=10)
    assert np.isfinite(rows[0]["nll"][0]) and rows[0]["nll"][0] <= -np.log(F.FLOOR) + 1e-9


def test_equal_strength_interpolation_and_table():
    rng = np.random.default_rng(2)
    n, k = 3000, 8
    loss = rng.random((n, k)) * 0.4
    z = np.exp(-4 * loss + rng.normal(0, 1.0, size=(n, k)))                        # good moves are likelier, with noise: sharpening helps a little
    prep = {"p": z / z.sum(axis=1, keepdims=True), "cand_loss": loss}
    human = np.array([rng.choice(k, p=pp) for pp in prep["p"]])
    rank, groups, mask = human + 1, np.repeat(np.arange(n // 3), 3), np.ones(n, dtype=bool)
    settings = [("engine-reweighted", b) for b in (0, 2, 5, 10, 20, 50)] + [("temperature", t) for t in (1.0, 0.7, 0.5, 0.35)] + [("mixture", a) for a in (0.0, 0.3, 0.6)]
    rows = F.sweep(prep, rank, groups, mask, settings, n_boot=10)
    ref = rows[0]["expected loss"][0]
    eng = F.at_equal_strength([r for r in rows if r["family"] == "engine-reweighted"], ref, fractions=(0.9,))
    tmp = F.at_equal_strength([r for r in rows if r["family"] == "temperature"], ref, fractions=(0.9,))
    assert eng[0.9] is not None and tmp[0.9] is not None and eng[0.9] < tmp[0.9]              # the same strength gain costs less likelihood with the engine's information
    text = F.render_equal_strength(rows, "### t")
    assert "engine-reweighted" in text and "75% of the prior" in text
    assert F.at_equal_strength([r for r in rows if r["family"] == "temperature"][:1], ref, fractions=(0.1,))[0.1] is None          # a curve that does not reach the strength
