"""Tactical motifs from the board and the move."""
import chess
import pytest

from chessme.analysis import motifs as M


def fen(*moves):
    b = chess.Board()
    for m in moves:
        b.push_uci(m)
    return b.fen()


@pytest.mark.parametrize("position,uci,expected", [
    (fen("e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6"), "h5f7", "mate"),                      # Qxf7#
    ("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", "a1a8", "back-rank"),
    ("r3k3/8/8/3N4/8/8/8/4K3 w - - 0 1", "d5c7", "fork"),                                       # the knight checks the king and attacks the rook
    ("4k3/8/8/8/8/8/P7/4K3 w - - 0 1", "a2a4", "quiet"),
    ("r1bqkbnr/pppp1ppp/2n5/4p3/3PP3/8/PPP2PPP/RNBQKBNR b KQkq - 0 1", "e5d4", "trade"),         # a pawn takes a pawn that can be taken back
    ("4k3/8/8/8/8/2n5/8/R3K3 w - - 0 1", "a1a3", "quiet"),
    ("7k/P7/8/8/8/8/8/4K3 w - - 0 1", "a7a8q", "promotion"),
    ("4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1", "d1d5", "hanging"),                                    # the queen is taken and the rook cannot be taken back
])
def test_the_motif_of_a_move(position, uci, expected):
    assert M.motif_of(position, uci) == expected


def test_a_pin_and_a_discovered_attack_are_named():
    assert M.motif_of("4k3/8/4n3/8/8/8/8/4R1K1 w - - 0 1", "e1e5") == "pin"                      # the rook pins the knight to the king along the file
    assert M.motif_of("4k3/8/8/8/4B3/8/8/4R1K1 w - - 0 1", "e4b7") == "discovery"                # the bishop leaves the file: the rook gives check
    assert M.NAMES[M.motif_of(fen("e2e4"), "e7e5")] == "a quiet move"


def test_a_mate_in_the_engine_line_is_a_mate_motif_and_bad_input_is_quiet():
    start = fen("e2e4", "e7e5", "d1h5", "b8c6", "f1c4")
    assert M.tactic_of_line(start, []) == "quiet"
    assert M.motif_of(start, "zz") == "quiet" and M.motif_of(start, "a1a8") == "quiet"
    after_nf6 = fen("e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6")
    assert M.tactic_of_line(after_nf6, ["h5f7"]) == "mate"
