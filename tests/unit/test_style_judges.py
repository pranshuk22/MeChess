import numpy as np

from chessme.style import candidates as C, judges as J
from chessme.style.features import FEATURE_NAMES
from tests.unit.test_style_model import make_positions


def pos(fen, cands, chosen, rating=1800, played_loss=0.0):
    n = len(cands)
    return C.Position(fen, cands[chosen] if chosen >= 0 else "zzzz", rating, 10, cands, np.zeros((n, len(FEATURE_NAMES)), np.float32),
                      np.zeros(n, np.float32), chosen, played_loss)


def ds(*ps):
    return {J._key(p): p for p in ps}


def test_identical_datasets_agree_completely():
    a = ds(pos("f1", ["e2e4", "d2d4"], 0), pos("f2", ["a2a3", "b2b3", "c2c3"], 1))
    r = J.compare(a, a)
    assert r["common"] == 2 and r["all"]["best_move_agreement"] == 1 and r["all"]["approved_set_overlap"] == 1
    assert r["all"]["played_approved_a"] == r["all"]["played_approved_b"] == 1


def test_a_weaker_judge_that_rejects_the_played_move_is_visible():
    a = ds(pos("f1", ["e2e4", "d2d4"], 0), pos("f2", ["a2a3", "b2b3"], 0))
    weak = {("f1", "e2e4"): pos("f1", ["d2d4", "g1f3"], -1),   # played e2e4 not approved by the other judge
            ("f2", "a2a3"): pos("f2", ["a2a3", "c2c3"], 0)}
    b = {k: p for k, p in weak.items()}
    b[("f1", "e2e4")].played = "e2e4"
    r = J.compare(a, b)
    assert r["all"]["played_approved_a"] == 1.0 and r["all"]["played_approved_b"] == 0.5
    assert r["all"]["best_move_agreement"] == 0.5 and 0 < r["all"]["approved_set_overlap"] < 1


def test_only_common_decisions_are_compared_and_counted():
    a = ds(pos("f1", ["e2e4", "d2d4"], 0), pos("f2", ["a2a3", "b2b3"], 0))
    b = ds(pos("f1", ["e2e4", "d2d4"], 0), pos("f3", ["a2a3", "b2b3"], 0))
    r = J.compare(a, b)
    assert (r["common"], r["only_a"], r["only_b"]) == (1, 1, 1)
    assert J.compare(a, ds(pos("zz", ["a2a3", "b2b3"], 0)))["common"] == 0


def test_bands_split_by_rating_and_loss_difference_uses_played_moves_both_scored():
    a = ds(pos("f1", ["e2e4", "d2d4"], 0, rating=1500, played_loss=10), pos("f2", ["a2a3", "b2b3"], 0, rating=2400, played_loss=0))
    b = ds(pos("f1", ["e2e4", "d2d4"], 0, rating=1500, played_loss=50), pos("f2", ["a2a3", "b2b3"], 0, rating=2400, played_loss=0))
    r = J.compare(a, b)
    assert set(r["bands"]) == {"0-1800", "2200-3000"} and r["bands"]["0-1800"]["median_loss_difference_cp"] == 40


def test_style_agreement_high_for_same_data_and_render_is_readable():
    rng = np.random.default_rng(0)
    ps = make_positions(800, {"sacrifice": 1.5}, rng)
    for i, p in enumerate(ps):
        p.fen, p.played = f"f{i}", p.cands[p.chosen]
    a = ds(*ps)
    sty = J.style_agreement(a, a)
    assert sty["weight_correlation"] > 0.999
    text = J.render(J.compare(a, a), sty, "ours", "stockfish")
    assert "800 common decisions" in text and "ours vs stockfish" in text
