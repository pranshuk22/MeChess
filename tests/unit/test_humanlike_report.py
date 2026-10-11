import chess
import numpy as np
import pytest

from chessme.humanlike import report as R
from chessme.humanlike import score as S
from chessme.humanlike import testset as T
from chessme.model.compare import Scorer
from tests.unit.test_humanlike_testset import LINE, make_game


class UniformScorer(Scorer):
    name = "uniform"

    def probs(self, items):
        out = []
        for it in items:
            legal = [m.uci() for m in chess.Board(it.fen).legal_moves]
            out.append({m: 1.0 / len(legal) for m in legal})
        return out


class FixedScorer(Scorer):
    """Gives the human's move probability q and spreads the rest evenly (an 'oracle' that knows the answer, with a chosen confidence)."""

    def __init__(self, q, name="fixed"):
        self.q, self.name = q, name

    def probs(self, items):
        out = []
        for it in items:
            legal = [m.uci() for m in chess.Board(it.fen).legal_moves]
            rest = (1.0 - self.q) / max(len(legal) - 1, 1)
            out.append({m: (self.q if m == it.played else rest) for m in legal} if len(legal) > 1 else {legal[0]: 1.0})
        return out


@pytest.fixture(scope="module")
def positions():
    ps = []
    for i in range(80):
        ps += T.game_positions(make_game(site=f"g{i:07d}", clocks=[170 - 5 * (j // 2) if j % 2 == 0 else 170 for j in range(len(LINE))]),
                               per_game=4, seed=3)
    return ps


@pytest.fixture(scope="module")
def items(positions):
    return T.to_items(positions)


def test_the_scores_match_hand_computed_values(items):
    s = S.score_items(UniformScorer(), items)
    n = np.array([len(list(chess.Board(it.fen).legal_moves)) for it in items])
    assert np.allclose(s["p"], 1.0 / n) and np.allclose(s["sq_sum"], 1.0 / n) and np.allclose(s["entropy"], np.log(n))
    assert (s["n_legal"] == n).all() and np.allclose(s["conf"], 1.0 / n)
    assert np.allclose(s["topk_p"].sum(axis=1), np.minimum(n, S.TOPK) / n)         # the stored top moves hold the right share of the mass
    assert s["topk_move"][0, 0] != "" and s["topk_move"].shape == (len(items), S.TOPK)


def test_rank_and_top1_for_a_confident_model(items):
    s = S.score_items(FixedScorer(0.9), items)
    assert (s["rank"] == 1).all() and s["top1"].all() and np.allclose(s["p"], 0.9)
    s = S.score_items(FixedScorer(0.01), items)
    assert (s["rank"] > 1).all() and not s["top1"].any()


def test_an_illegal_played_move_is_an_error(items):
    from dataclasses import replace
    bad = [replace(items[0], played="a1a8")]
    with pytest.raises(ValueError, match="not legal"):
        S.score_items(UniformScorer(), bad)


def test_scores_round_trip(tmp_path, items, positions):
    s = S.score_items(UniformScorer(), items)
    S.save_scores(tmp_path / "s.npz", s, "uniform", "abc", {"positions_sha": S.positions_hash(positions)})
    back, meta = S.load_scores(tmp_path / "s.npz")
    assert meta["model"] == "uniform" and meta["testset_sha256"] == "abc" and meta["positions_sha"] == S.positions_hash(positions)
    assert np.array_equal(back["p"], s["p"]) and np.array_equal(back["topk_move"], s["topk_move"])
    assert S.positions_hash(positions) != S.positions_hash(positions[:-1])


def test_summary_of_a_known_model(positions, items):
    arr = R.position_arrays(positions)
    s = S.score_items(FixedScorer(0.5), items)
    r = R.summarize(s, arr, n_boot=200)
    assert r["n"] == len(items) and r["games"] == 80
    assert r["top1"][0] == pytest.approx(1.0) and r["sampled_match"][0] == pytest.approx(0.5)
    assert r["nll"][0] == pytest.approx(np.log(2)) and r["ece"] == pytest.approx(0.5, abs=1e-9)     # right every time but says 50%
    lo, hi = r["nll"][1], r["nll"][2]
    assert lo <= r["nll"][0] <= hi
    assert "50.0" in R.table({"x": r}) and "| x |" in R.table({"x": r})


def test_masks_apply_the_published_filters(positions):
    arr = R.position_arrays(positions)
    m = R.masks(arr)
    assert m["full"].all()
    assert not m["comparable"][arr["ply"] < 10].any() and not m["comparable"][arr["after_low"]].any()
    assert m["comparable"].sum() < m["full"].sum()
    assert (m["clock 30s+"] | m["clock 10-30s"] | m["clock <10s"] | m["clock unknown"]).all()
    assert R.masks(arr, drop_forced=True)["full"].sum() == (arr["n_legal"] >= 2).sum()


def test_stratified_tables(positions, items):
    arr = R.position_arrays(positions)
    s = S.score_items(UniformScorer(), items)
    by_phase = R.strata(s, arr, R.masks(arr)["full"], "phase", n_boot=50, min_n=1)
    assert set(by_phase) <= {"opening", "middlegame", "endgame"} and by_phase
    by_rating = R.strata(s, arr, R.masks(arr)["full"], "rating", n_boot=50, min_n=1)
    assert set(by_rating) == {1600}                                            # binned by the GAME's average rating, (1700 + 1650) / 2 = 1675, whoever moves
    with pytest.raises(ValueError):
        R.strata(s, arr, R.masks(arr)["full"], "difficulty")


def test_a_better_model_is_detected_by_the_paired_comparison(positions, items):
    arr = R.position_arrays(positions)
    good, bad = S.score_items(FixedScorer(0.8), items), S.score_items(UniformScorer(), items)
    r = R.compare(good, bad, arr, R.masks(arr)["full"], n_boot=300)
    assert r["top1"][1] > 0 and r["nll"][2] < 0 and r["sampled_match"][1] > 0       # intervals exclude zero, in the right directions
    same = R.compare(bad, bad, arr, R.masks(arr)["full"], n_boot=100)
    assert same["top1"][:3] == (0.0, 0.0, 0.0) and same["nll"][0] == 0.0
    assert "| full |" in R.comparison_table({"full": r})
