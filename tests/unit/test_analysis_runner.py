import io
from types import SimpleNamespace

import chess
import chess.pgn
import pytest

from chessme.analysis import classify as C
from chessme.analysis import runner as R


def line(move, cp, pv=()):
    return SimpleNamespace(move=move, cp=cp, pv=list(pv) or [move])


def game(moves, result="*"):
    pgn = f'[Result "{result}"]\n\n' + moves + f" {result}"
    return chess.pgn.read_game(io.StringIO(pgn))


def scripted(evals):
    """A search that answers from {fen-prefix (placement + turn): [(move, cp), ...]}; unknown positions are equal."""
    def search(board):
        key = " ".join(board.fen().split()[:2])
        return [line(m, cp) for m, cp in evals.get(key, [])] or [line(next(iter(board.legal_moves)).uci(), 0)]
    return search


def test_phase_by_move_number_and_material():
    assert R.phase(chess.Board()) == "opening"
    b = chess.Board(); b.fullmove_number = 15
    assert R.phase(b) == "middlegame"
    assert R.phase(chess.Board("8/5k2/8/8/8/8/4PK2/8 w - - 0 40")) == "endgame"
    assert R.phase(chess.Board("4k3/8/8/8/8/8/8/R3K2R w - - 0 40")) == "endgame"    # 10 points of pieces


def test_material_given_counts_a_real_sacrifice_but_not_a_trade():
    b = chess.Board("4k3/8/8/3p4/8/2N5/8/4K3 w - - 0 1")      # White knight, Black pawn
    assert R.material_given(b, chess.Move.from_uci("c3d5"), []) == 0                    # knight takes pawn: gains
    b2 = chess.Board("4k3/8/2p5/3p4/8/2N5/8/4K3 w - - 0 1")
    # Nd5?? cxd5: knight lost for a pawn = 2 pawns down after the reply
    assert R.material_given(b2, chess.Move.from_uci("c3d5"), ["c6d5"]) == 2.0
    # Nxd5 exd5: takes a knight, loses a knight: a trade, not a sacrifice
    b3 = chess.Board("4k3/8/4p3/3n4/8/2N5/8/4K3 w - - 0 1")
    assert R.material_given(b3, chess.Move.from_uci("c3d5"), ["e6d5"]) == 0.0


def test_a_perfect_game_has_only_best_moves_and_full_accuracy():
    g = game("1. e4 e5", "1/2-1/2")
    res = R.analyse_game(g, scripted({}))
    assert [m["class"] for m in res["moves"]] == ["best", "best"]
    assert res["summary"]["white"]["accuracy"] == 100.0


def test_a_blunder_is_found_measured_and_reported_as_critical():
    # after 1.e4 the engine says Black is fine (0); after 1...f6?? 2.Qh5+ mate-ish: we script the position after f6 as +900 for White
    g = game("1. e4 f6", "1-0")
    after_f6 = "rnbqkbnr/ppppp1pp/5p2/8/4P3/8/PPPP1PPP/RNBQKBNR w"
    after_e4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b"
    search = scripted({after_e4: [("e7e5", 0), ("f7f6", -900)], after_f6: [("d1h5", 900)]})
    res = R.analyse_game(g, search)
    black = res["moves"][1]
    assert black["class"] == "blunder" and black["loss"] > 0.4 and black["best_move"] == "e7e5"
    assert res["summary"]["critical"][0]["move"] == "f6"
    assert res["summary"]["black"]["classes"]["blunder"] == 1
    assert res["summary"]["black"]["was_losing"] is True and res["summary"]["black"]["saved"] is False


def test_conversion_is_won_after_a_winning_moment():
    moves = [{"ply": 1, "color": "white", "class": "best", "loss": 0.0, "accuracy": 100.0, "phase": "opening", "win_before": 0.8, "win_after": 0.8,
              "move": "e4", "best_move": "e2e4"},
             {"ply": 2, "color": "black", "class": "best", "loss": 0.0, "accuracy": 100.0, "phase": "opening", "win_before": 0.2, "win_after": 0.2,
              "move": "e5", "best_move": "e7e5"}]
    s = R.summarise(moves, {"Result": "1-0"})
    assert s["white"]["had_winning_chance"] and s["white"]["converted"] is True
    assert s["black"]["was_losing"] and s["black"]["saved"] is False
    s = R.summarise(moves, {"Result": "1/2-1/2"})
    assert s["white"]["converted"] is False and s["black"]["saved"] is True                    # a draw saves, but does not convert


def test_opportunism_and_luck_follow_the_next_reply():
    def m(ply, color, loss):
        return {"ply": ply, "color": color, "class": "x", "loss": loss, "accuracy": 50.0, "phase": "opening", "win_before": 0.5, "win_after": 0.5,
                "move": "m", "best_move": "b"}
    # black errs (ply 2), white punishes (ply 3, small loss); white errs (ply 5), black does not punish (ply 6, big loss)
    moves = [m(1, "white", 0.0), m(2, "black", 0.3), m(3, "white", 0.0), m(4, "black", 0.0), m(5, "white", 0.3), m(6, "black", 0.2)]
    s = R.summarise(moves)
    assert s["white"]["opportunism"] == 1.0 and s["black"]["opportunism"] == 0.0
    assert s["white"]["luck"] == 1.0            # white's slip at ply 5 was not punished
    assert s["black"]["luck"] == 0.0


def test_book_moves_are_labelled_book():
    res = R.analyse_game(game("1. e4 e5"), scripted({}), book=lambda b, mv: b.fullmove_number == 1)
    assert [m["class"] for m in res["moves"]] == ["book", "book"]


def test_forced_move_is_never_great():
    # White king in check with a single legal reply
    g = game("1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#", "1-0")
    res = R.analyse_game(g, scripted({}))
    assert res["moves"][-1]["ply"] == 7 and res["moves"][-1]["class"] in ("best", "great", "brilliant")
