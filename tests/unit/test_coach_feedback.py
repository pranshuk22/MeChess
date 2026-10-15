import chess
import pytest

from chessme.analysis.runner import SimpleLine
from chessme.coach import feedback as FB
from tests.unit.prep_helpers import search as material_search


def stub(table):
    """A scripted engine: {fen position key: [(uci, cp for the side to move, pv)]}, best first."""
    def search(board):
        key = " ".join(board.fen().split()[:4])
        return [SimpleLine(u, cp, pv) for u, cp, pv in table.get(key, [])]
    return search


START = chess.STARTING_FEN
AFTER = {}


def key(fen):
    return " ".join(fen.split()[:4])


def after(fen, uci):
    b = chess.Board(fen)
    b.push_uci(uci)
    return b.fen()


def table_for(played_cp_by_move):
    """The start position with e4 best (cp 40); the replies' evaluations (for Black) make each played move's value as given (cp for White after the move)."""
    t = {key(START): [("e2e4", 40, ["e2e4", "e7e5"])]}
    for uci, cp_white in played_cp_by_move.items():
        t[key(after(START, uci))] = [("e7e5", -cp_white, ["e7e5", "g1f3"])]
    t[key(after(START, "e2e4"))] = [("e7e5", -40, ["e7e5", "g1f3"])]
    return t


def test_the_best_move_is_explained_not_just_accepted():
    fb = FB.feedback(START, "e2e4", stub(table_for({})))
    assert fb["grade"] == "best" and fb["solved"] and fb["title"] == "Best move" and fb["loss"] == 0.0 and fb["bestSan"] == "e4"
    assert "first choice" in fb["reasons"][0] and any("engine expects" in r for r in fb["reasons"]) and fb["bestWhy"]


def test_a_move_as_good_as_the_best_is_called_great():
    t = table_for({"d2d4": 15})
    t[key(START)] = [("e2e4", 40, ["e2e4"]), ("d2d4", 15, ["d2d4"])]
    fb = FB.feedback(START, "d2d4", stub(t))
    assert fb["grade"] == "great" and fb["solved"] and "same as the engine's choice e4" in fb["reasons"][0]
    assert FB.feedback(START, "e2e4", stub(t))["alternatives"] == ["d4"]                      # the best move's feedback names the other good move


def test_a_sound_but_weaker_move_is_good_with_a_reason_and_an_invitation_to_try_again():
    fb = FB.feedback(START, "c2c4", stub(table_for({"c2c4": -10})))                          # 40 -> -10 cp for White: about 4.5 expected points
    assert fb["grade"] == "good" and fb["solved"] and fb["title"] == "Good move, not the best"
    assert "e4 is about" in fb["reasons"][0] and any("try again for the best" in r for r in fb["reasons"])


def test_a_bad_move_says_why_it_loses_and_what_the_engine_expects():
    fb = FB.feedback(START, "f2f3", stub(table_for({"f2f3": -900})))
    assert fb["grade"] == "blunder" and not fb["solved"] and fb["title"] == "That loses" and fb["loss"] > 0.2
    text = " ".join(fb["reasons"])
    assert "engine expects" in text and "fall from" in text and fb["bestSan"] == "e4" and fb["kind"]
    inacc = FB.feedback(START, "g2g3", stub(table_for({"g2g3": -175})))
    assert inacc["grade"] in ("inaccuracy", "mistake") and not inacc["solved"] and inacc["title"] in ("Inaccurate", "That is a mistake")


def test_allowing_checkmate_and_hanging_a_piece_are_named():
    fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
    b = chess.Board(fen)
    b.push_uci("d1h5")
    b.push_uci("b8c6")
    b.push_uci("f1c4")
    f2 = b.fen()                                                                              # black to move, Nf6?? allows Qxf7#
    fb = FB.feedback(f2, "g8f6", material_search)
    assert fb["grade"] == "blunder" and "checkmate" in " ".join(fb["reasons"]) and "Qxf7#" in " ".join(fb["reasons"])
    hang = FB.feedback("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "e2e4", material_search)
    assert hang["grade"] in ("best", "great")                                                  # a sound opening move is never called a mistake


def test_illegal_moves_and_missing_engine_lines_do_not_crash():
    assert FB.feedback(START, "e2e5", stub({}))["grade"] == "illegal" and FB.feedback(START, "zz", stub({}))["grade"] == "illegal"
    fb = FB.feedback(START, "e2e4", stub({}))
    assert fb["grade"] == "good" and fb["reasons"]
