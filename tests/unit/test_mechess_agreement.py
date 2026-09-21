from types import SimpleNamespace

import chess

from chessme.mechess import agreement as AG
from chessme.mechess.priors import UniformPrior
from chessme.uci_client import GoResult
from tests.unit.test_mechess import L, StubEngine, prior_of, table


class Fixed:
    """A book that knows one position's moves, whatever the Elo."""

    def __init__(self, fen, options):
        self.fen, self.options = fen, options

    def moves(self, board, elo=None):
        return [(chess.Move.from_uci(u), w) for u, w in self.options] if board.fen() == self.fen else []


def row(moves, color="white", platform="lichess", usable=True, rating=1800):
    return {"platform": platform, "usable": usable, "color": color, "my_rating": rating, "moves": moves}


def test_book_agreement_numbers_exactly():
    start = chess.Board().fen()
    book = Fixed(start, [("e2e4", 3.0), ("d2d4", 1.0)])
    res = AG.book_agreement({"b": book}, [row("e4 e5"), row("d4 d5"), row("c4 e5")], max_ply=1)
    b = res["b"]
    assert res["games"] == 3 and b["moves"] == 3
    assert abs(b["coverage"] - 1.0) < 1e-9                                   # the start position is in the book for all three
    assert abs(b["top1"] - 1 / 3) < 1e-9                                     # only the first game's e4 is the book's heaviest move
    assert abs(b["sampled"] - (0.75 + 0.25 + 0.0) / 3) < 1e-9 and abs(b["sampled_when_in_book"] - b["sampled"]) < 1e-9


def test_book_agreement_counts_only_the_players_own_moves_and_skips_other_platforms():
    start = chess.Board().fen()
    res = AG.book_agreement({"b": Fixed(start, [("e2e4", 1.0)])}, [row("e4 e5 Nf3 Nc6", color="black"), row("e4", platform="chesscom")], max_ply=10)
    assert res["games"] == 1 and res["b"]["moves"] == 2 and res["b"]["coverage"] == 0.0     # black's moves: the start position is never black's


def test_shared_search_runs_each_search_once():
    eng = StubEngine([L("e2e4", 10), L("d2d4", 5)])
    s = AG.SharedSearch(eng)
    s._send("setoption name MultiPV value 3")
    a = s.go(chess.Board().fen(), [], nodes=100)
    b = s.go(chess.Board().fen(), [], nodes=100)
    assert a is b and len(eng.calls) == 1 and eng.sent == ["setoption name MultiPV value 3"]
    s._send("setoption name MultiPV value 5")
    s.go(chess.Board().fen(), [], nodes=100)
    assert len(eng.calls) == 2                                               # another MultiPV is another search


def positions(played, n=6):
    return [SimpleNamespace(fen=chess.Board().fen(), played=played, rating=1800) for _ in range(n)]


def test_a_prior_that_favours_the_played_move_scores_higher_than_uniform():
    eng = StubEngine([L("e2e4", 0), L("d2d4", 0), L("g1f3", 0)])
    priors = {"uniform": UniformPrior(), "likes d4": prior_of({"e2e4": 0.1, "d2d4": 0.8, "g1f3": 0.1})}
    res = AG.move_agreement(positions("d2d4"), eng, priors, table=table(scale=1e9), seed=1)
    assert abs(res["uniform"]["expected_match"] - 1 / 3) < 1e-6
    assert res["likes d4"]["expected_match"] > 0.5 and res["likes d4"]["top1"] == 1.0 and res["uniform"]["in_candidates"] == 1.0
    assert len(eng.calls) == 1                                               # identical positions: one search in total


def test_played_move_outside_the_candidates_scores_zero_and_illegal_moves_are_skipped():
    eng = StubEngine([L("e2e4", 0), L("d2d4", 0)])
    res = AG.move_agreement(positions("a2a3") + positions("e2e5"), eng, {"u": UniformPrior()}, table=table(scale=1e9))
    assert res["u"]["positions"] == 6 and res["u"]["in_candidates"] == 0.0 and res["u"]["expected_match"] == 0.0


def test_render_names_the_baseline():
    text = AG.render({"games": 5, "b": {"moves": 10, "coverage": 0.5, "top1": 0.4, "sampled": 0.2, "sampled_when_in_book": 0.4}},
                     {"u": {"positions": 4, "in_candidates": 0.9, "top1": 0.45, "expected_match": 0.31}})
    assert "baseline" in text and "| u | 4 |" in text and "| b | 10 |" in text


def test_widen_scales_the_window_and_adds_lines_without_touching_other_knobs():
    from chessme.mechess import dial
    t = {1800: (4000, 6, 120, 1.1, 80, 22), 1000: (363, 7, 251, 1.61, 177.1, 12, 0.23, 4)}
    w = dial.widen(t, 2.0, 3)
    assert w[1800][:3] == (4000, 9, 240.0) and w[1800][3:6] == (1.1, 80, 22) and w[1800][6:] == (0.0, 0.0)
    assert w[1000][1] == 10 and w[1000][2] == 502 and w[1000][6:] == (0.23, 4)
    assert dial.widen(t) == {k: dial._row(v) for k, v in t.items()}          # scale 1 and no extra lines: the same table


def test_expected_loss_and_the_sweep_reach_more_of_the_players_moves():
    tbl = {1200: (100, 2, 50, 1.0, 1e9, 20), 2600: (100, 2, 50, 1.0, 1e9, 20)}

    class Wide(StubEngine):                                                 # answers with as many lines as MultiPV asks for
        def go(self, fen, moves=(), *, nodes=None, **kw):
            k = int(self.sent[-1].rsplit(" ", 1)[1])
            return GoResult(self.lines[0].move, lines=self.lines[:k])

    wide = Wide([L("e2e4", 0), L("d2d4", -40), L("g1f3", -90), L("a2a3", -300)])
    pos = positions("g1f3")
    rows = AG.sweep(pos, wide, {"uniform": UniformPrior()}, [(1.0, 0), (3.0, 2)], table=tbl)
    (w0, k0, r0), (w1, k1, r1) = rows
    assert r0["uniform"]["in_candidates"] == 0.0 and r1["uniform"]["in_candidates"] == 1.0     # the played third-best move is reached only by the wider setting
    assert r1["uniform"]["expected_loss_cp"] > r0["uniform"]["expected_loss_cp"] >= 0
    assert "Wider candidate windows" in AG.render_sweep(rows)
