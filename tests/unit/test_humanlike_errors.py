import os
import shutil
import subprocess
import sys
from pathlib import Path

import chess
import chess.engine
import numpy as np
import pytest

from chessme.humanlike import errors as E
from chessme.humanlike import judge as J
from chessme.humanlike import metrics as M

VALUES = {chess.PAWN: 100, chess.KNIGHT: 300, chess.BISHOP: 300, chess.ROOK: 500, chess.QUEEN: 900}


class MaterialEngine:
    """A stand-in for Stockfish: the evaluation is the material balance for the side to move (no search)."""

    def __init__(self):
        self.calls = 0

    def analyse(self, board, limit):
        self.calls += 1
        cp = sum(VALUES.get(p.piece_type, 0) * (1 if p.color == board.turn else -1) for p in board.piece_map().values())
        return {"score": chess.engine.PovScore(chess.engine.Cp(cp), board.turn)}


# White to move; the rook on d2 can take the queen on d5 (Rxd5), or white can play a quiet move
FEN = "4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1"


def test_a_move_that_misses_a_free_queen_has_a_large_loss():
    eng = MaterialEngine()
    best, human, cands = J.judge_position(eng, FEN, human="e1e2", candidates=["d2d5", "e1e2", "", "d2d3"])
    assert human == pytest.approx(-400.0)                        # Ke2 leaves white a queen against a rook
    assert np.isnan(cands[2]) and cands[0] == pytest.approx(500.0)
    assert best == pytest.approx(500.0)
    loss = J.losses(best, np.array([cands[0], human]))
    assert loss[0] == 0.0 and loss[1] > 0.3                      # the best move gives nothing away; the miss gives away a lot


def test_checkmate_and_stalemate_are_judged_without_the_engine():
    eng = MaterialEngine()
    board = chess.Board("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1")
    assert J.eval_after(eng, board, chess.Move.from_uci("f7g7"), 100) == J.MATE         # Qg7# mates
    assert J.eval_after(eng, board, chess.Move.from_uci("f7e7"), 100) < J.MATE
    stale = chess.Board("7k/8/6K1/5Q2/8/8/8/8 w - - 0 1")
    assert J.eval_after(eng, stale, chess.Move.from_uci("f5f7"), 100) == 0.0             # Qf7 is stalemate
    assert eng.calls <= 1


def test_losses_are_never_negative_and_keep_missing_values():
    l = J.losses(np.array([0.0, 100.0]), np.array([[0.0, 50.0, np.nan], [300.0, 100.0, np.nan]]))
    assert (l[~np.isnan(l)] >= 0).all() and np.isnan(l[:, 2]).all() and l[0, 0] == 0.0
    assert l[1, 0] == 0.0 and J.losses(np.array([200.0]), np.array([-200.0]))[0] > 0.3   # clamped cp, probabilities


def test_judge_positions_in_process_matches_single_calls():
    eng = MaterialEngine()
    items = [(FEN, "e1e2", ["d2d5", "e1e2"]), (FEN, "d2d5", ["d2d5"])]
    r = J.judge_positions(items, engine=eng)
    assert r["human_cp"].tolist() == [-400.0, 500.0] and r["best_cp"].tolist() == [500.0, 500.0]
    assert r["cand_cp"].shape == (2, J.K_CAND) and np.isnan(r["cand_cp"][1, 1:]).all()


def synthetic(n=4000, k=4, seed=0, tau_human=1.0):
    """Positions with 4 candidate moves of known loss; the 'humans' sample their move from the model's distribution at temperature tau_human."""
    rng = np.random.default_rng(seed)
    loss = np.sort(rng.random((n, k)) * 0.4, axis=1)            # candidate 0 is the best, later ones are worse
    logits = -loss * 8 + rng.normal(size=(n, k)) * 0.5          # the model prefers the better moves, with noise
    p = np.exp(logits) / np.exp(logits).sum(1, keepdims=True)
    q = E.tempered(p, tau_human)
    pick = np.array([rng.choice(k, p=row) for row in q])
    scores = {"topk_p": np.pad(p, ((0, 0), (0, 16 - k))).astype(np.float32)}
    prep = {"p": np.pad(p, ((0, 0), (0, 4))), "cand_loss": np.pad(loss, ((0, 0), (0, 4))), "human_loss": loss[np.arange(n), pick],
            "mass": np.ones(n), "tail": np.zeros(n), "n_good": (loss <= E.GOOD).sum(1)}
    arr = {"gid": np.arange(n) // 4}
    return prep, arr


def test_tempering_sharpens_and_flattens():
    p = np.array([[0.6, 0.3, 0.1, 0.0]])
    assert E.tempered(p, 1.0)[0] == pytest.approx(p[0])
    assert E.tempered(p, 0.05)[0, 0] > 0.99 and E.tempered(p, 20.0)[0, 3] == 0.0       # zero stays zero
    assert E.tempered(p, 20.0)[0, 0] == pytest.approx(1 / 3, abs=0.05)
    assert E.tempered(p, 3.0).sum() == pytest.approx(1.0)


def test_expected_values_by_hand():
    prep = {"p": np.array([[0.5, 0.5]]), "cand_loss": np.array([[0.0, 0.3]]), "human_loss": np.array([0.3]), "mass": np.ones(1), "tail": np.zeros(1),
            "n_good": np.array([1])}
    mv = E.model_values(prep)
    assert mv["mean loss"][0] == pytest.approx(0.15) and mv["error (loss > 0.10)"][0] == pytest.approx(0.5) and mv["blunder (loss > 0.20)"][0] == pytest.approx(0.5)
    assert E.human_values(prep)["blunder (loss > 0.20)"][0] == 1.0


def test_the_benchmark_sees_a_known_change_and_not_a_null_one():
    prep, arr = synthetic(tau_human=1.0)
    mask = np.ones(len(arr["gid"]), dtype=bool)
    same = E.compare(prep, arr, mask, tau=1.0, n_boot=200)["mean loss"]["diff"]
    assert same[1] <= 0.0 <= same[2]                                       # humans ARE the model: the interval covers 0
    sharper = E.compare(prep, arr, mask, tau=0.4, n_boot=200)["mean loss"]["diff"]
    assert sharper[2] < 0                                                  # a model that is too sharp makes fewer errors: detected
    flatter = E.compare(prep, arr, mask, tau=2.5, n_boot=200)["mean loss"]["diff"]
    assert flatter[1] > 0                                                  # too flat: more errors: detected
    floor = E.null_halves(prep, arr, mask)
    assert 0 < floor < abs(sharper[0]) and 0 < floor < abs(flatter[0])      # the effects stand clearly above the human-vs-human noise


def test_difficulty_table_and_rendering():
    prep, arr = synthetic()
    mask = np.ones(len(arr["gid"]), dtype=bool)
    rows = E.by_difficulty(prep, arr, mask)
    assert rows and all(0 <= v["human"] <= 1 and 0 <= v["model"] <= 1 for v in rows.values())
    text = E.render({"all": E.compare(prep, arr, mask, n_boot=50)}, floor={"all": 0.01})
    assert "| all |" in text and "mean loss" in text and "blunder" in text


def test_prepare_renormalises_over_judged_candidates():
    scores = {"topk_p": np.array([[0.5, 0.3, 0.1, 0.05] + [0.0] * 12], dtype=np.float32)}
    judged = {"best_cp": np.array([100.0]), "human_cp": np.array([100.0]), "cand_cp": np.array([[100.0, 0.0, np.nan, np.nan] + [np.nan] * 4])}
    prep = E.prepare(scores, judged)
    assert prep["mass"][0] == pytest.approx(0.8) and prep["tail"][0] == pytest.approx(1 - 0.95, abs=1e-6)     # only two candidates were judged
    assert E.tempered(prep["p"], 1.0).sum() == pytest.approx(1.0) and prep["n_good"][0] == 1


def test_the_models_mass_outside_the_judged_moves_is_added_back_at_the_humans_tail_cost():
    n = 100
    prep = {"p": np.tile([0.5, 0.4, 0, 0], (n, 1)), "cand_loss": np.tile([0.0, 0.3, 0, 0], (n, 1)), "human_loss": np.where(np.arange(n) < 50, 0.5, 0.0),
            "mass": np.ones(n), "tail": np.full(n, 0.2), "n_good": np.ones(n, int)}
    rank = np.where(np.arange(n) < 50, 20, 1)                                  # half of the humans played outside the judged moves, at loss 0.5
    regime = np.array(["<10s"] * n)
    stats = E.tail_stats(prep, rank, regime, k=4)
    assert stats["<10s"]["mean loss"] == pytest.approx(0.5) and stats["<10s"]["blunder (loss > 0.20)"] == 1.0
    plain = E.model_values(prep)
    fixed = E.model_values(prep, tail=E.tail_arrays(stats, regime))
    q_blunder = 0.4 / 0.9                                                      # renormalised: the 0.3-loss move is a blunder
    assert plain["blunder (loss > 0.20)"][0] == pytest.approx(q_blunder)
    assert fixed["blunder (loss > 0.20)"][0] == pytest.approx(0.8 * q_blunder + 0.2 * 1.0)
    assert fixed["mean loss"][0] == pytest.approx(0.8 * (0.4 / 0.9 * 0.3) + 0.2 * 0.5)
    assert E.tail_stats(prep, rank, regime, k=4) and E.tail_stats(prep, np.ones(n, int), regime, k=4) == {}      # too few tail moves: no correction


def test_a_regime_without_tail_data_gets_no_correction():
    prep = {"p": np.array([[1.0, 0, 0, 0]]), "cand_loss": np.zeros((1, 4)), "human_loss": np.array([0.0]), "mass": np.ones(1), "tail": np.array([0.1]), "n_good": np.ones(1, int)}
    arrays_ = E.tail_arrays({}, np.array(["30s+"]))
    assert np.isnan(E.model_values(prep, tail=arrays_)["mean loss"][0])         # NaN, visibly: never a silent zero


@pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish")
def test_the_engine_pool_returns_and_leaves_no_engine_behind():
    """Regression: with close()+join() the workers never exited on Python 3.13 (an engine reader thread keeps the worker alive) and a Kaggle run hung
    for hours after its work was done. Run in a subprocess so that a hang fails the test instead of the suite."""
    code = ("from chessme.humanlike import judge as J\n"
            "if __name__ == '__main__':\n"
            "    items = [('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1', 'e2e4', ['e2e4', 'd2d4'])] * 6\n"
            "    r = J.judge_positions(items, workers=2, nodes_child=100, nodes_root=100)\n"
            "    print('done', len(r['best_cp']))\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=Path(__file__).resolve().parents[2])
    assert r.returncode == 0 and "done 6" in r.stdout, r.stderr[-500:]


def test_more_candidates_can_be_judged_and_the_analysis_follows_their_number():
    eng = MaterialEngine()
    items = [(FEN, "e1e2", ["d2d5", "e1e2", "d2d3", "d2d4", "e1f1"])]
    r = J.judge_positions(items, engine=eng, k=5)
    assert r["cand_cp"].shape == (1, 5) and not np.isnan(r["cand_cp"]).any()
    assert J.judge_positions(items, engine=eng, k=3)["cand_cp"].shape == (1, 3)                 # fewer than offered: only the first k are judged
    scores = {"topk_p": np.array([[0.4, 0.3, 0.1, 0.1, 0.05] + [0.0] * 11], dtype=np.float32)}
    prep = E.prepare(scores, r)
    assert prep["cand_loss"].shape == (1, 5) and prep["tail"][0] == pytest.approx(0.05, abs=1e-6)     # the mass beyond the judged five
    stats = E.tail_stats({**prep, "human_loss": np.full(30, 0.5), "cand_loss": np.zeros((30, 5))}, np.full(30, 9), np.array(["<10s"] * 30))
    assert stats["<10s"]["mean loss"] == 0.5                                                      # 'outside' is rank > 5 here, from the file's own width
