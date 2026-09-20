import numpy as np
import pytest

from chessme.style import model as M
from chessme.style.candidates import Position
from chessme.style.features import FEATURE_NAMES, INDEX

F = len(FEATURE_NAMES)


def make_positions(n, taste, rng, loss_care=0.0, k=4):
    """Positions whose chooser prefers feature values in proportion to `taste` (dict name -> utility)."""
    out = []
    for i in range(n):
        feats = np.zeros((k, F), np.float32)
        for name in ("capture", "sacrifice", "pawn_storm", "trade"):
            feats[:, INDEX[name]] = rng.integers(0, 2, k)
        loss = rng.integers(0, 60, k).astype(np.float32)
        u = sum(v * feats[:, INDEX[name]] for name, v in taste.items()) - loss_care * loss / 100
        p = np.exp(u - u.max()); p /= p.sum()
        out.append(Position("", "", 1800, 10, [str(j) for j in range(k)], feats, loss, int(rng.choice(k, p=p)), 0.0))
    return out


def test_fit_recovers_the_sign_and_ranking_of_a_players_taste():
    rng = np.random.default_rng(0)
    pos = make_positions(3000, {"sacrifice": 1.5, "trade": -1.5}, rng)
    m = M.fit(pos)
    w = dict(M.profile(m))
    assert w["sacrifice"] > 0.5 and w["trade"] < -0.5
    assert abs(w["capture"]) < 0.25 and abs(w["pawn_storm"]) < 0.25
    assert M.profile(m, top=2)[0][0] in ("sacrifice", "trade")


def test_fit_recovers_care_about_strength():
    rng = np.random.default_rng(1)
    m = M.fit(make_positions(3000, {}, rng, loss_care=3.0))
    assert m.loss_coef > 1.5
    assert M.fit(make_positions(3000, {}, rng, loss_care=0.0)).loss_coef < 0.6


def test_style_beats_uniform_and_loss_only_on_held_out_data():
    rng = np.random.default_rng(2)
    taste = {"sacrifice": 2.0, "trade": -2.0}
    train, test = make_positions(2000, taste, rng), make_positions(1000, taste, rng)
    r = M.evaluate(M.fit(train), test)
    assert r["style"]["nll"] < r["uniform"]["nll"] - 0.1
    assert r["style"]["nll"] < r["loss_only"]["nll"]
    assert r["style"]["top1"] > r["uniform"]["top1"] + 0.05


def test_a_player_without_taste_gains_nothing_over_uniform():
    rng = np.random.default_rng(3)
    train, test = make_positions(2000, {}, rng), make_positions(2000, {}, rng)
    r = M.evaluate(M.fit(train), test)
    assert abs(r["style"]["nll"] - r["uniform"]["nll"]) < 0.03


def test_positions_where_the_played_move_was_not_a_candidate_are_ignored():
    rng = np.random.default_rng(4)
    pos = make_positions(200, {"sacrifice": 1.0}, rng)
    junk = [Position("", "", 1800, 10, ["a", "b"], np.ones((2, F), np.float32), np.zeros(2, np.float32), -1, 500.0)] * 50
    assert M.evaluate(M.fit(pos + junk), pos + junk)["n"] == 200


def test_fit_without_usable_data_is_an_error():
    with pytest.raises(ValueError):
        M.fit([])


def test_constant_features_do_not_break_standardisation():
    rng = np.random.default_rng(5)
    m = M.fit(make_positions(300, {"sacrifice": 1.0}, rng))
    assert np.all(np.isfinite(m.w)) and np.all(m.std > 0)
