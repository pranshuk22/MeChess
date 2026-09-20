import numpy as np
import pytest
import torch

from chessme.jobs import Stopped
from chessme.style import embed as E
from chessme.style import gamefeatures as G

NF = len(G.FEATURE_NAMES)


def players(n=48, games=40, seed=0, noise=0.5):
    """Each player has a stable personal profile over a few features; per-game values add noise; some values are missing."""
    rng = np.random.default_rng(seed)
    out = {}
    for i in range(n):
        prof = rng.normal(size=NF) * (np.arange(NF) < 12)
        g = prof + noise * rng.normal(size=(games, NF))
        g[rng.random(g.shape) < 0.05] = np.nan
        out[f"p{i:03d}"] = (1500 + 10 * i, g, [{"color": "white", "eco": "C50"}] * games)
    return out


class StopAt:
    def __init__(self, n):
        self.n, self.calls = n, 0

    def checkpoint(self):
        if self.calls >= self.n:
            raise Stopped("test stop")
        self.calls += 1


def test_normaliser_standardises_flags_missing_and_drops_artefact_columns():
    P = players(n=10)
    games = [np.asarray(v[1], np.float32) for v in P.values()]
    n = E.Normaliser(games)
    assert G.FEATURE_NAMES.index("first_think_rel") not in n.keep
    z = n(games[0])
    assert z.shape == (len(games[0]), n.dim) and np.isfinite(z).all()
    half = len(n.keep)
    assert ((z[:, half:] == 1) == ~np.isfinite(games[0][:, n.keep])).all()          # the indicator half marks missing values
    assert (z[:, half:][z[:, half:] == 1].size > 0) and (z[:, :half][~np.isfinite(games[0][:, n.keep])] == 0).all()
    assert E.Normaliser.from_state(n.state())(games[0]).tolist() == z.tolist()


def test_info_nce_is_lower_for_aligned_pairs_than_for_shuffled_pairs():
    a = torch.nn.functional.normalize(torch.randn(16, 8), dim=-1)
    assert E.info_nce(a, a.clone()) < E.info_nce(a, a.roll(1, 0))


def test_sample_batch_uses_disjoint_bags_and_distinct_players():
    P = players(n=10, games=30)
    games = [np.asarray(v[1], np.float32) for v in P.values()]
    n = E.Normaliser(games)
    gn = [n(g) for g in games]
    A, mA, B, mB = E.sample_batch(gn, np.arange(10), np.random.default_rng(0), batch=6, bag=10)
    assert A.shape == (6, 10, n.dim) and mA.sum() == 60
    # a very short player gets a smaller, padded bag
    gn[0] = gn[0][:6]
    A, mA, B, mB = E.sample_batch(gn, np.array([0, 1]), np.random.default_rng(1), batch=2, bag=10)
    assert sorted(mA.sum(1).tolist()) == [3.0, 10.0]


def test_training_learns_to_identify_held_out_players(tmp_path):
    res = E.train(players(), tmp_path, steps=250, batch=24, bag=15, ckpt_every=50, eval_every=0, log=lambda *_: None)
    ev = res["eval"]
    assert ev["embedding_top1"] > 5 * ev["chance"] and ev["embedding_top5"] >= ev["embedding_top1"]
    assert (tmp_path / "eval.json").exists() and (tmp_path / "ckpt.pt").exists()


def test_stop_and_resume_matches_an_uninterrupted_run(tmp_path):
    P = players(n=40)
    kw = dict(steps=40, batch=16, bag=10, ckpt_every=10, eval_every=0, log=lambda *_: None)
    full = E.train(P, tmp_path / "full", **kw)
    first = E.train(P, tmp_path / "split", ctl=StopAt(17), **kw)
    assert first["stopped"] and first["step"] == 17
    second = E.train(P, tmp_path / "split", **kw)
    assert not second["stopped"] and second["step"] == 40
    for a, b in zip(full["model"].parameters(), second["model"].parameters()):
        assert torch.allclose(a, b, atol=1e-6)


def test_resume_refuses_a_different_configuration(tmp_path):
    P = players(n=30)
    E.train(P, tmp_path, steps=10, batch=8, bag=8, ckpt_every=5, eval_every=0, log=lambda *_: None)
    with pytest.raises(ValueError, match="different configuration"):
        E.train(P, tmp_path, steps=10, batch=8, bag=9, ckpt_every=5, eval_every=0, log=lambda *_: None)


def test_evaluation_reports_rating_leakage_and_baselines(tmp_path):
    ev = E.train(players(n=40), tmp_path, steps=30, batch=16, bag=10, eval_every=0, log=lambda *_: None)["eval"]
    assert {"embedding_top1", "raw_top1", "chance", "rating_r2", "n_heldout"} <= set(ev)
    assert ev["n_heldout"] == 10 and ev["chance"] == pytest.approx(0.1)
