import chess
import pytest

from chessme.humanlike import blunders as B


def test_see_counts_defenders_and_xrays():
    # pawn takes a knight that a pawn defends: wins 3, loses the pawn back (1) -> 2
    b = chess.Board("4k3/8/2p5/3n4/4P3/8/8/4K3 w - - 0 1")
    assert B.see(b, chess.Move.from_uci("e4d5")) == 2
    # queen takes a pawn defended by a pawn: wins 1, loses the queen -> negative
    b = chess.Board("4k3/8/2p5/3p4/8/8/3Q4/4K3 w - - 0 1")
    assert B.see(b, chess.Move.from_uci("d2d5")) < 0
    # rook takes an undefended rook: +5
    b = chess.Board("4k3/8/8/3r4/8/8/3R4/4K3 w - - 0 1")
    assert B.see(b, chess.Move.from_uci("d2d5")) == 5
    # x-ray: a second rook behind the first: Rxd5 Rxd5 Rxd5 nets the pawn
    b = chess.Board("3r2k1/8/8/3p4/8/8/3R4/3RK3 w - - 0 1")
    assert B.see(b, chess.Move.from_uci("d2d5")) == 1


def test_a_hung_queen_is_walking_into_a_capture_and_an_ignored_threat_is_named():
    # white queen moves next to the black pawn that takes it for free
    board = chess.Board("4k3/8/8/3p4/8/8/3Q4/4K3 w - - 0 1")
    t, d = B.classify(board.fen(), "d2c4")
    assert t == "walks into a capture" and d["piece"] == "queen" and not d["capture"]
    # white's queen is attacked by a knight; white plays a pawn move instead of moving it: ignores a threat
    board = chess.Board("4k3/8/8/3n4/8/2Q5/P7/4K3 w - - 0 1")
    # knight on d5 attacks c3 (queen)
    t, _ = B.classify(board.fen(), "a2a3")
    assert t == "ignores a threat"
    # moving the queen to safety is not a blunder of that type
    t, _ = B.classify(board.fen(), "c3d3")
    assert t != "ignores a threat"


def test_allowing_mate_in_one_comes_first_and_quiet_moves_are_deeper():
    # 1.f3 e5 2.g4?? Qh4#
    board = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/8/5P2/PPPPP1PP/RNBQKBNR w KQkq - 0 2")
    t, _ = B.classify(board.fen(), "g2g4")
    assert t == "mate in 1"
    t, _ = B.classify(chess.Board().fen(), "e2e4")
    assert t == "deeper"


def test_capture_and_check_descriptors_are_reported():
    board = chess.Board("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    t, d = B.classify(board.fen(), "e4d5")
    assert d["capture"] and d["piece"] == "pawn" and not d["check"]
    board = chess.Board("4k3/8/8/8/8/8/8/4KQ2 w - - 0 1")
    assert B.classify(board.fen(), "f1f8")[1]["check"] is True


def test_type_mix_of_humans_and_model_with_the_tail_added_back():
    import numpy as np

    from chessme.humanlike import errors as E

    fens = [chess.Board().fen(), "rnbqkbnr/pppp1ppp/8/4p3/8/5P2/PPPPP1PP/RNBQKBNR w KQkq - 0 2", "rnbqkbnr/pppp1ppp/8/4p3/8/5P2/PPPPP1PP/RNBQKBNR w KQkq - 0 2"]
    played = ["e2e4", "g2g4", "e2e4"]
    cand_moves = [["e2e4", ""], ["g2g4", "e2e4"], ["g2g4", "e2e4"]]
    cand_loss = np.array([[0.0, 0.0], [0.9, 0.0], [0.9, 0.0]])
    human_loss = np.array([0.0, 0.9, 0.0])
    human, cand, desc = B.type_arrays(fens, played, cand_moves, cand_loss, human_loss)
    assert list(human) == [-1, B.TYPES.index("mate in 1"), -1] and cand[1, 0] == B.TYPES.index("mate in 1") and cand[1, 1] == -1 and desc[0] is None
    prep = {"p": np.array([[0.5, 0.5], [0.5, 0.5], [0.0, 1.0]]), "tail": np.array([0.0, 0.0, 0.0])}
    regime = np.array(["30s+"] * 3)
    model, hum = B.type_rates(prep, cand, human, regime)
    m = B.TYPES.index("mate in 1")
    assert model[:, m].tolist() == [0.0, 0.5, 0.0] and hum[:, m].tolist() == [0.0, 1.0, 0.0]
    tail = B.tail_type_rates(human, np.array([20, 20, 3]), regime, 16, min_n=1)
    assert tail["30s+"][m] == pytest.approx(0.5)
    model_t, _ = B.type_rates({**prep, "tail": np.array([0.5, 0.5, 0.5])}, cand, human, regime, tail=tail)
    assert model_t[1, m] == pytest.approx(0.5 * 0.5 + 0.5 * 0.5)
    arr = {"gid": np.array(["a", "b", "c"])}
    res = B.compare_types(model, hum, arr, np.ones(3, bool), n_boot=20)
    assert res["n"] == 3 and res["share"]["mate in 1"] == (1.0, 1.0)
    assert "mate in 1" in B.render_types({"all": res})


def test_an_even_trade_is_not_counted_as_walking_into_a_capture():
    # regression: Rxf5+ takes a rook and is retaken by a pawn (rook for rook); the opponent's recapture gains 5 but the move itself captured 5
    board = chess.Board("8/p4p2/Pp2p3/2k2r1R/2P5/3K4/2P3P1/8 w - - 4 42")
    t, d = B.classify(board.fen(), "h5f5")
    assert d["capture"] and t == "deeper"
    # but taking a pawn with the queen next to a knight that retakes it is
    board = chess.Board("3r4/1pn3k1/7p/1p3pp1/4p3/1Q4PP/2Pr1P1K/8 w - - 2 38")
    assert B.classify(board.fen(), "b3b5")[0] == "walks into a capture"
