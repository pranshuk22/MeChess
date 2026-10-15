import io

import chess
import chess.pgn

from chessme.coach import exercises as X
from chessme.coach import facts as F

AFTER_F3_E5 = "rnbqkbnr/pppp1ppp/8/4p3/8/5P2/PPPPP1PP/RNBQKBNR w KQkq - 0 2"
QUEEN_ATTACKED = "4k3/8/8/3n4/8/2Q5/P7/4K3 w - - 0 1"        # the knight on d5 attacks the queen on c3


def test_threats_against_name_the_attacked_piece_and_describe_move_says_what_a_move_does():
    board = chess.Board(QUEEN_ATTACKED)
    threats = F.threats_against(board, chess.WHITE)
    assert [chess.square_name(sq) for _, sq, _ in threats] == ["c3"]
    saving = F.describe_move(board, chess.Move.from_uci("c3d3"))
    assert any("moves the attacked queen out of danger" in s for s in saving)
    capture = F.describe_move(board, chess.Move.from_uci("c3d5"))
    assert any("captures the knight on d5" in s for s in capture)
    check = F.describe_move(chess.Board("4k3/8/8/8/8/8/8/4KQ2 w - - 0 1"), chess.Move.from_uci("f1f8"))
    assert "gives check" in check or "gives checkmate" in check
    assert F.describe_move(chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"), chess.Move.from_uci("a1a8")) == ["gives checkmate"]


def test_a_threat_created_by_a_move_is_reported():
    # a rook move that attacks an undefended queen
    board = chess.Board("4k3/8/8/3q4/8/8/8/R3K3 w - - 0 1")
    out = F.describe_move(board, chess.Move.from_uci("a1d1"))
    assert any(s.startswith("threatens to win material with Rxd5") for s in out)


def test_exercise_for_a_move_that_allows_mate_has_the_kind_the_explanation_and_a_hint_ladder():
    ex = X.exercise(AFTER_F3_E5, "g2g4", "e2e4", 0.9, 0.55, 0.0, ply=3, phase="opening", cls="blunder")
    assert ex["kind"] == "mate in 1" and ex["played_san"] == "g4" and ex["best_san"] == "e4" and ex["color"] == "white"
    assert "checkmate with Qh4#" in ex["explanation"] and "A better move was e4" in ex["explanation"]
    assert len(ex["hints"]) == 3 and ex["hints"][2] == "The move is e4." and "pawn" in ex["hints"][1]


def test_hints_name_the_attacked_piece_or_the_chance_to_win_material():
    board = chess.Board(QUEEN_ATTACKED)
    assert "queen on c3 is under attack" in X.hints(board, chess.Move.from_uci("c3d3"))[0]
    board = chess.Board("4k3/8/8/3q4/8/8/8/R3K3 w - - 0 1")
    board.turn = chess.WHITE
    quiet = X.hints(chess.Board("4k3/8/8/8/8/8/P7/4K3 w - - 0 1"), chess.Move.from_uci("a2a4"))
    assert "Nothing is hanging" in quiet[0]


def test_walks_into_a_capture_explanation_names_the_capture_and_the_victim():
    board = chess.Board("4k3/8/8/3p4/8/8/3Q4/4K3 w - - 0 1")
    ex = X.exercise(board.fen(), "d2c4", "d2d5", 0.5, 0.9, 0.4)
    assert ex["kind"] == "walks into a capture" and "dxc4" in ex["explanation"] and "queen" in ex["explanation"]


def _game(pgn):
    return chess.pgn.read_game(io.StringIO(pgn))


def test_from_analysis_takes_the_biggest_fair_mistakes_apart_from_each_other_in_game_order():
    game = _game("1. f3 e5 2. g4 Qh4#")
    base = {"color": "white", "class": "blunder", "phase": "opening", "win_before": 0.5, "win_after": 0.0}
    moves = [{**base, "ply": 1, "uci": "f2f3", "best_move": "e2e4", "loss": 0.12, "win_before": 0.5, "win_after": 0.38},
             {**base, "ply": 3, "uci": "g2g4", "best_move": "e2e4", "loss": 0.9},
             {"color": "black", "ply": 2, "uci": "e7e5", "best_move": "e7e5", "loss": 0.0, "win_before": 0.5, "win_after": 0.5, "class": "best", "phase": "opening"}]
    out = X.from_analysis(game, {"moves": moves}, "white", max_n=5, min_gap=4)
    assert [e["ply"] for e in out] == [3]                                   # ply 1 is too close to ply 3 (gap 2 < 4) and smaller
    out2 = X.from_analysis(game, {"moves": moves}, "white", max_n=5, min_gap=2)
    assert [e["ply"] for e in out2] == [1, 3] and out2[1]["fen"] == AFTER_F3_E5
    lost = [{**moves[1], "win_before": 0.05}]
    assert X.from_analysis(game, {"moves": lost}, "white") == []           # already lost: no exercise
    assert X.from_analysis(game, {"moves": moves}, "black") == []          # black made no mistake
