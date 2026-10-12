import numpy as np
import pytest

from chessme.humanlike import adapter as A
from chessme.humanlike import report as R
from chessme.humanlike import score as S
from chessme.humanlike import testset as T
from tests.unit.test_humanlike_report import FixedScorer, UniformScorer, positions, items  # noqa: F401  (fixtures)


def fake_scores(n=3000, seed=0, sharp_when_low=True):
    """A frozen model that is overconfident when the clock is low: its top move is right less often than it says. Returns (scores, clock)."""
    rng = np.random.default_rng(seed)
    clock = np.where(rng.random(n) < 0.3, rng.uniform(1, 9, n), rng.uniform(40, 150, n))
    k = 16
    logits = rng.normal(size=(n, k)) * 1.0
    logits[:, 0] += 1.5
    p = np.exp(logits) / np.exp(logits).sum(1, keepdims=True)
    # the humans follow a FLATTER distribution when the clock is low (temperature 2), the model's own otherwise
    tau = np.where(clock < 10, 2.5, 1.0)
    q = np.exp(np.log(p) / tau[:, None])
    q /= q.sum(1, keepdims=True)
    pick = np.array([rng.choice(k, p=row) for row in q])
    ps = np.sort(p, axis=1)[:, ::-1]
    order = np.argsort(-p, axis=1)
    rank = np.argmax(order == pick[:, None], axis=1) + 1
    scores = {"topk_p": np.pad(ps, ((0, 0), (0, 0))).astype(np.float32), "p": p[np.arange(n), pick], "rank": rank.astype(np.int32),
              "conf": ps[:, 0], "entropy": -(ps * np.log(ps)).sum(1), "sq_sum": (ps ** 2).sum(1), "top1": rank == 1}
    return scores, clock


def arrays(clock):
    n = len(clock)
    return {"clock": clock, "opp_clock": np.full(n, 100.0), "base": np.full(n, 180), "inc": np.zeros(n), "ply": np.full(n, 30), "me": np.full(n, 1600),
            "opp": np.full(n, 1600), "n_legal": np.full(n, 30)}


def test_untrained_adapter_returns_the_models_own_probabilities():
    scores, clock = fake_scores(500)
    x, sl = A.features(arrays(clock), scores), A.slots(scores)
    net = A.Adapter(x.shape[1])
    out = A.apply(net, np.zeros(x.shape[1], np.float32), np.ones(x.shape[1], np.float32), x, sl)
    assert np.allclose(out["p"], scores["p"], atol=1e-5) and (out["top1"] == scores["top1"]).all() and np.allclose(out["conf"], scores["topk_p"][:, 0], atol=1e-5)


def test_a_move_outside_the_top_16_keeps_its_share_of_the_tail():
    scores, clock = fake_scores(50)
    scores["topk_p"] = scores["topk_p"] * 0.5                              # half of the mass is now in the tail
    scores["rank"] = np.full(50, 20, np.int32)                              # the human's move is the 20th
    scores["p"] = np.full(50, 0.01)
    sl = A.slots(scores)
    assert (sl["target"] == A.K).all()
    assert np.allclose(np.exp(sl["log_within"]), 0.01 / np.exp(sl["log_tail"].astype(np.float64)), rtol=1e-3)       # the move's share of the tail
    net = A.Adapter(len(A.FEATURES))
    x = A.features(arrays(clock), scores)
    out = A.apply(net, np.zeros(x.shape[1], np.float32), np.ones(x.shape[1], np.float32), x, sl)
    assert np.allclose(out["p"], 0.01, atol=1e-4)


def test_training_learns_to_flatten_under_time_pressure_and_leaves_ample_clock_alone():
    scores, clock = fake_scores(12000, seed=1)
    arr = arrays(clock)
    x, sl = A.features(arr, scores), A.slots(scores)
    train, val, test = A.game_split(np.arange(len(clock)) // 4)
    net, mean, std = A.fit(x, sl, train, val, epochs=25, lr=5e-3, log=lambda *a: None)
    out = A.apply(net, mean, std, x, sl)
    low, ample = clock < 10, clock >= 30
    gain = lambda m: float((np.log(out["p"][m & test]) - np.log(scores["p"][m & test])).mean())
    assert gain(low) > 0.02                                                 # NLL improves where the model was overconfident
    assert abs(gain(ample)) < 0.02                                          # and is not made worse where it was right
    over = lambda sc, m: float((sc["conf"][m & test] - sc["top1"][m & test]).mean())
    assert over(out, low) < over(scores, low) - 0.03                        # the overconfidence shrinks


def test_game_split_keeps_games_together_and_is_stable():
    gids = np.repeat(np.arange(500), 4)
    tr, va, te = A.game_split(gids)
    assert (tr | va | te).all() and not (tr & va).any() and not (tr & te).any() and not (va & te).any()
    for g in range(500):
        sel = gids == g
        assert len({bool(tr[sel][0]), bool(va[sel][0]), bool(te[sel][0])}) == 2 and tr[sel].all() == tr[sel][0]
    assert 0.6 < tr.mean() < 0.8 and 0.15 < te.mean() < 0.25
    assert (A.game_split(gids)[2] == te).all()


def test_features_have_the_documented_columns(positions):  # noqa: F811
    arr = R.position_arrays(positions)
    scores = S.score_items(UniformScorer(), T.to_items(positions))
    x = A.features(arr, scores)
    assert x.shape == (len(positions), len(A.FEATURES)) and np.isfinite(x).all()


def test_a_temperature_only_adapter_cannot_change_the_ranking():
    scores, clock = fake_scores(6000, seed=2)
    x, sl = A.features(arrays(clock), scores), A.slots(scores)
    train, val, test = A.game_split(np.arange(len(clock)) // 4)
    net, mean, std = A.fit(x, sl, train, val, epochs=10, lr=5e-3, mode="tau", log=lambda *a: None)
    out = A.apply(net, mean, std, x, sl)
    assert (out["rank"] == np.where(scores["rank"] <= A.K, scores["rank"], A.K + 1)).all() and (out["top1"] == scores["top1"]).all()
    assert not np.allclose(out["p"], scores["p"])                          # but the probabilities did move
    low = clock < 10
    assert out["conf"][low].mean() < scores["conf"][low].mean()            # flatter under time pressure
