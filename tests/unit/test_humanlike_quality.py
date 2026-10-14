import json
import shutil

import chess
import chess.engine
import numpy as np
import pytest

from chessme.humanlike import c2st as C
from chessme.humanlike import quality as Q
from tests.unit.test_humanlike_c2st import random_game

VALUES = {chess.PAWN: 100, chess.KNIGHT: 300, chess.BISHOP: 300, chess.ROOK: 500, chess.QUEEN: 900}


class GreedyEngine:
    """A stand-in for Stockfish with a one-move horizon: it plays the move that leaves the most material and evaluates the position as that material."""

    def __init__(self):
        self.calls = 0

    def analyse(self, board, limit):
        self.calls += 1
        best, best_cp = None, -10 ** 6
        for m in sorted(board.legal_moves, key=lambda x: x.uci()):
            board.push(m)
            cp = -sum(VALUES.get(p.piece_type, 0) * (1 if p.color == board.turn else -1) for p in board.piece_map().values())
            board.pop()
            if cp > best_cp:
                best, best_cp = m, cp
        return {"score": chess.engine.PovScore(chess.engine.Cp(best_cp), board.turn), "pv": [best]}


def record(start, moves, gid="g@2"):
    return {"gid": gid, "start": start, "moves": moves, "plies": len(start.split()) + len(moves.split()), "spent": [], "clock_after": []}


HANGING_QUEEN = "e2e4 d7d5 e4d5 d8d5 b1c3 d5a5 c3b5 a5b5"                 # black's queen takes a knight that is guarded by the bishop on f1


def test_taking_the_hanging_queen_loses_nothing_and_missing_it_gives_points_away():
    eng = GreedyEngine()
    took = Q.annotate(eng, record(HANGING_QUEEN, "f1b5"))
    missed = Q.annotate(eng, record(HANGING_QUEEN, "a2a3"))
    assert took.shape == missed.shape == (1, len(Q.QUALITY_FEATURES))
    loss, error, blunder, best, mover = took[0]
    assert loss == 0.0 and not error and not blunder and best == 1.0
    assert mover > 0.85                                                       # white is a queen for a knight up before the move
    loss, error, blunder, best, _ = missed[0]
    assert loss > Q.BLUNDER and error == 1.0 and blunder == 1.0 and best == 0.0


def test_a_checkmating_move_loses_nothing_and_games_end_without_searching_the_finished_position():
    eng = GreedyEngine()
    rows = Q.annotate(eng, record("f2f3 e7e5 g2g4", "d8h4"))                 # fool's mate
    assert rows.shape == (1, 5) and rows[0, 0] == 0.0
    assert eng.calls == 1                                                     # only the position before the move was searched


def test_only_max_moves_moves_are_judged_and_a_search_is_one_per_position():
    eng = GreedyEngine()
    rng = __import__("random").Random(1)
    rec = random_game(rng, "g@8", plies=30)
    rows = Q.annotate(eng, rec, max_moves=6)
    assert len(rows) == 6 and eng.calls == 7                                  # moves + 1 searches
    assert (rows[:, :2] >= 0).all()


def test_annotate_games_in_process_and_the_file_round_trip(tmp_path):
    rng = __import__("random").Random(2)
    recs = [random_game(rng, f"g{i}@8", plies=10) for i in range(3)]
    done = Q.annotate_games(recs, engine=GreedyEngine(), max_moves=5)
    assert list(done) == ["g0@8", "g1@8", "g2@8"] and all(len(v) == 5 for v in done.values())
    Q.write(tmp_path / "q.jsonl", done)
    back = Q.read(tmp_path / "q.jsonl")
    assert list(back) == list(done) and all(np.allclose(back[k], done[k], atol=1e-3) for k in done)
    assert "start" not in (tmp_path / "q.jsonl").read_text()                  # only the id and the numbers are kept


@pytest.mark.skipif(not shutil.which("stockfish"), reason="Stockfish not installed")
def test_with_the_real_engine_in_worker_processes():
    rng = __import__("random").Random(5)
    recs = [random_game(rng, f"g{i}@8", plies=8) for i in range(4)]
    done = Q.annotate_games(recs, workers=2, max_moves=6, nodes=200)
    assert list(done) == [r["gid"] for r in recs]
    for v in done.values():
        assert v.shape == (6, 5) and (v[:, 0] >= 0).all() and (v[:, 4] >= 0).all() and (v[:, 4] <= 1).all()


def test_classifier_features_gain_the_quality_columns_and_a_fragment_cut():
    rng = __import__("random").Random(4)
    human = [random_game(rng, f"g{i}@8", plies=30) for i in range(4)]
    gen = [random_game(rng, f"g{i}@8", plies=30) for i in range(4)]
    eng = GreedyEngine()
    quality = {"human": Q.annotate_games(human, engine=eng, max_moves=10), "m": Q.annotate_games(gen, engine=eng, max_moves=10)}
    gids, X_h, X = C.feature_table(human, {"m": gen}, quality=quality, max_moves=10)
    assert X_h.shape == (4, 3 * (len(C.MOVE_FEATURES) + 5)) == X["m"].shape and len(C.feature_names(True)) == X_h.shape[1]
    j = C.feature_names(True).index("whole stretch: engine_loss")
    expected = np.mean([Q.annotate(eng, human[0], max_moves=10)[:, 0].mean()])
    assert X_h[0, j] == pytest.approx(expected, abs=1e-4)
    with pytest.raises(ValueError, match="no engine-judged quality"):
        C.feature_table(human, {"m": gen}, quality={"human": quality["human"], "m": {}}, max_moves=10)
    with pytest.raises(ValueError):                                           # judged fewer moves than the cut needs
        C.feature_table(human, {"m": gen}, quality=quality, max_moves=20)


def test_a_set_that_blunders_more_is_found_by_the_quality_features_and_reported():
    rng = __import__("random").Random(6)
    n = 160
    human = [random_game(rng, f"g{i}@8", plies=24) for i in range(n)]
    gen = [random_game(rng, f"g{i}@8", plies=24) for i in range(n)]
    eng = GreedyEngine()
    qh = Q.annotate_games(human, engine=eng, max_moves=16)
    qg = {k: v.copy() for k, v in Q.annotate_games(gen, engine=eng, max_moves=16).items()}
    for v in qg.values():                                                     # the generated games blunder: the same moves, judged worse
        v[:, 0] += 0.3
        v[:, 1:3] = (v[:, :1] > Q.BLUNDER)
    res = C.run(human, {"m": gen}, folds=4, boot=30, epochs=30, quality={"human": qh, "m": qg}, max_moves=16)
    assert res["models"]["m"]["linear"]["auc"] > 0.8 and res["engine_features"] and res["max_moves"] == 16
    blind = C.run(human, {"m": gen}, folds=4, boot=30, epochs=30, max_moves=16)                # the same games, moves only: nothing to find
    assert blind["models"]["m"]["linear"]["auc"] < 0.65 and not blind["engine_features"]
    top = res["features"]["m"][0][0]
    assert "engine_loss" in top or "blunder" in top or "error" in top
    text = C.report(res)
    assert "engine-judged quality" in text and "first 16 moves" in text
