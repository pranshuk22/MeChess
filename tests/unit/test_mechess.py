import io
import random
from collections import Counter
from types import SimpleNamespace

import chess
import pytest

from chessme.book import format as bf
from chessme.book.keys import book_key
from chessme.mechess import dial
from chessme.mechess.controller import MATE_CP, BookReader, Choice, MeChess
from chessme.mechess.uci import MechessUci
from chessme.uci_client import GoResult, Line


class StubEngine:
    def __init__(self, lines):
        self.lines, self.calls, self.sent = lines, [], []

    def _send(self, cmd):
        self.sent.append(cmd)

    def ready(self):
        pass

    def go(self, fen, moves=(), *, nodes=None, **kw):
        self.calls.append((fen, list(moves), nodes))
        return GoResult(self.lines[0].move if self.lines else "0000", lines=self.lines)


def L(move, cp, kind="cp"):
    return Line(move, kind, cp, 6, [move])


def prior_of(d):
    return lambda board, elo, opp, platform: {chess.Move.from_uci(k): v for k, v in d.items()}


def table(nodes=100, k=4, window=100, temp=1.0, scale=50.0, book=20):
    return {1200: (nodes, k, window, temp, scale, book), 2600: (nodes, k, window, temp, scale, book)}


def mc(lines, prior, tbl=None, book=None, seed=1):
    return MeChess(StubEngine(lines), prior, book, tbl or table(), seed)


START = chess.Board()
LINES = [L("e2e4", 30), L("d2d4", 20), L("g1f3", 10), L("a2a3", -200)]


# ---- dial --------------------------------------------------------------------------------------------------------

def test_dial_returns_table_rows_at_table_points_and_clamps_outside():
    import dataclasses
    for elo, row in dial.DEFAULT_TABLE.items():
        nodes, k, window, temp, scale, book, blunder, depth = dial._row(row)
        s = dial.settings_for(elo)
        assert (s.nodes, s.multipv, s.window_cp, s.book_plies) == (nodes, k, window, book)
        assert s.temperature == pytest.approx(temp) and s.cp_scale == pytest.approx(scale) and s.blunder_rate == pytest.approx(blunder) and s.depth == depth
    lo, hi = min(dial.DEFAULT_TABLE), max(dial.DEFAULT_TABLE)
    assert dial.settings_for(lo - 500) == dataclasses.replace(dial.settings_for(lo), elo=lo - 500)   # below the table: the weakest row
    assert dial.settings_for(hi + 900).nodes == dial.settings_for(hi).nodes


def test_dial_is_monotone_in_elo():
    prev = None
    for elo in range(1200, 2601, 50):
        s = dial.settings_for(elo)
        if prev:
            assert s.nodes >= prev.nodes and s.window_cp <= prev.window_cp and s.temperature <= prev.temperature + 1e-9
            assert s.cp_scale <= prev.cp_scale + 1e-9 and s.book_plies >= prev.book_plies
        prev = s


def test_dial_interpolates_between_rows():
    a, b = dial.settings_for(1500), dial.settings_for(1800)
    mid = dial.settings_for(1650)
    assert a.nodes < mid.nodes < b.nodes and a.window_cp > mid.window_cp > b.window_cp


# ---- book --------------------------------------------------------------------------------------------------------

def book_file(tmp_path, entries):
    p = tmp_path / "b.bin"
    bf.write_book(p, entries)
    return BookReader(p)


def entry(board, uci, weight):
    m = chess.Move.from_uci(uci)
    return bf.Entry(book_key(board), m.from_square, m.to_square, m.promotion or 0, weight, 1, 500)


def test_book_reader_returns_only_legal_moves(tmp_path):
    reader = book_file(tmp_path, [entry(START, "e2e4", 3.0), entry(START, "d2d4", 1.0), entry(START, "e2e5", 9.0)])
    assert {(m.uci(), w) for m, w in reader.moves(START)} == {("e2e4", 3.0), ("d2d4", 1.0)}
    assert reader.moves(chess.Board("4k3/8/8/8/8/8/8/4K3 w - - 0 1")) == []


def test_book_moves_are_played_in_proportion_and_only_inside_book_depth(tmp_path):
    reader = book_file(tmp_path, [entry(START, "e2e4", 3.0), entry(START, "d2d4", 1.0)])
    m = mc(LINES, prior_of({}), table(temp=1.0, book=4), book=reader, seed=7)
    picks = Counter(m.choose(START, 1500).move.uci() for _ in range(800))
    assert set(picks) == {"e2e4", "d2d4"} and 0.68 < picks["e2e4"] / 800 < 0.82
    assert m.choose(START, 1500).source == "book" and m.engine.calls == []  # no search when the book answers
    deep = chess.Board()
    for u in ("g1f3", "g8f6", "f3g1", "f6g8"):
        deep.push_uci(u)  # back at the start position but 4 plies deep: outside book depth
    assert len(deep.move_stack) >= 4 and m.choose(deep, 1500).source == "search"


def test_zero_temperature_plays_the_heaviest_book_move(tmp_path):
    reader = book_file(tmp_path, [entry(START, "e2e4", 3.0), entry(START, "d2d4", 5.0)])
    m = mc(LINES, prior_of({}), table(temp=0), book=reader)
    assert {m.choose(START, 1500).move.uci() for _ in range(20)} == {"d2d4"}


def test_positions_outside_the_book_go_to_search(tmp_path):
    reader = book_file(tmp_path, [entry(START, "e2e4", 1.0)])
    b = chess.Board()
    b.push_uci("a2a3")
    assert mc(LINES, prior_of({}), book=reader).choose(b, 1500).source == "search"


# ---- candidates and choice ----------------------------------------------------------------------------------------

def test_candidates_are_the_moves_inside_the_window():
    # losses below the best (30cp): d2d4 10, g1f3 20, a2a3 230
    tight = mc(LINES, prior_of({"e2e4": 0.4, "d2d4": 0.3, "g1f3": 0.2, "a2a3": 0.1}), table(window=15)).choose(START, 1500)
    assert [(x.move.uci(), x.loss) for x in tight.candidates] == [("e2e4", 0), ("d2d4", 10)]
    wide = mc(LINES, prior_of({"e2e4": 0.4, "d2d4": 0.3, "g1f3": 0.2, "a2a3": 0.1}), table(window=25)).choose(START, 1500)
    assert [(x.move.uci(), x.loss) for x in wide.candidates] == [("e2e4", 0), ("d2d4", 10), ("g1f3", 20)]  # 20 <= 25


def test_window_keeps_at_least_the_best_move():
    m = mc([L("e2e4", 30), L("d2d4", -300)], prior_of({"e2e4": 0.5, "d2d4": 0.5}), table(window=0))
    c = m.choose(START, 1500)
    assert [x.move.uci() for x in c.candidates] == ["e2e4"] and c.move.uci() == "e2e4"


def test_a_single_candidate_never_consults_the_prior():
    def boom(*a):
        raise AssertionError("prior must not be called")

    m = mc([L("e2e4", 30), L("d2d4", -300)], boom, table(window=50))
    assert m.choose(START, 1500).move.uci() == "e2e4"


def test_a_sharp_prior_and_a_forgiving_scale_follow_the_prior():
    pr = prior_of({"e2e4": 0.05, "d2d4": 0.9, "g1f3": 0.05})
    m = mc(LINES[:3], pr, table(window=100, temp=0.2, scale=1e9), seed=3)
    assert Counter(m.choose(START, 1500).move.uci() for _ in range(60)) == {"d2d4": 60}


def test_a_strict_scale_follows_the_engine_whatever_the_prior_says():
    pr = prior_of({"e2e4": 0.01, "d2d4": 0.98, "g1f3": 0.01})
    m = mc(LINES[:3], pr, table(window=100, temp=1.0, scale=0.1), seed=3)  # a 10cp loss costs a factor e^-100
    assert Counter(m.choose(START, 1500).move.uci() for _ in range(60)) == {"e2e4": 60}


def test_zero_temperature_is_deterministic_argmax():
    pr = prior_of({"e2e4": 0.2, "d2d4": 0.5, "g1f3": 0.3})
    m = mc(LINES[:3], pr, table(window=100, temp=0, scale=1e9))
    assert {m.choose(START, 1500).move.uci() for _ in range(20)} == {"d2d4"}


def test_probabilities_sum_to_one_and_weights_are_reported():
    c = mc(LINES[:3], prior_of({"e2e4": 0.5, "d2d4": 0.3, "g1f3": 0.2}), table(window=100)).choose(START, 1500)
    assert sum(x.prob for x in c.candidates) == pytest.approx(1.0) and all(x.weight > 0 for x in c.candidates)
    assert sum(x.prior for x in c.candidates) == pytest.approx(1.0)


def test_a_zero_prior_move_can_still_be_chosen_if_the_engine_likes_it():
    m = mc(LINES[:2], prior_of({"e2e4": 0.0, "d2d4": 0.0}), table(window=100))  # prior floored, never a division by zero
    assert m.choose(START, 1500).move.uci() in ("e2e4", "d2d4")


def test_forced_mates_are_followed_and_being_mated_is_avoided():
    mate = [L("e2e4", 1, "mate"), L("a2a3", 40), L("h2h3", 30)]  # (moves are legal from the start; the mate is scripted)
    c = mc(mate, prior_of({"a2a3": 0.9, "h2h3": 0.05, "e2e4": 0.05}), table(window=1000)).choose(START, 1500)
    assert c.move.uci() == "e2e4" and len(c.candidates) == 1
    doomed = [L("e2e4", 20), L("d2d4", -2, "mate"), L("g1f3", 10)]  # d2d4 gets us mated
    seen = {mc(doomed, prior_of({"e2e4": 0.3, "d2d4": 0.4, "g1f3": 0.3}), table(window=100000), seed=s).choose(START, 1500).move.uci()
            for s in range(40)}
    assert seen <= {"e2e4", "g1f3"} and MATE_CP > 1000


def test_illegal_engine_lines_are_ignored_and_no_analysis_falls_back_to_bestmove():
    m = mc([L("e2e5", 90), L("e2e4", 30), L("d2d4", 25)], prior_of({"e2e4": 0.5, "d2d4": 0.5}), table(window=100))
    assert all(c.move.uci() != "e2e5" for c in m.choose(START, 1500).candidates)

    class NoLines(StubEngine):
        def go(self, *a, **k):
            return GoResult("g1f3")

    fb = MeChess(NoLines([]), prior_of({}), None, table())
    c = fb.choose(START, 1500)
    assert c.move.uci() == "g1f3" and c.source == "search"


def test_the_engine_gets_the_root_position_and_the_move_history_and_multipv_is_set_once():
    b = chess.Board()
    for u in ("e2e4", "e7e5"):
        b.push_uci(u)
    m = mc(LINES, prior_of({"e2e4": 1.0}), table(nodes=777, k=3))
    m.choose(b, 1500)
    m.choose(b, 1500)
    fen, moves, nodes = m.engine.calls[0]
    assert fen == chess.STARTING_FEN and moves == ["e2e4", "e7e5"] and nodes == 777
    assert m.engine.sent.count("setoption name MultiPV value 3") == 1


def test_choices_are_reproducible_with_a_seed_and_vary_across_seeds():
    pr = prior_of({"e2e4": 0.4, "d2d4": 0.35, "g1f3": 0.25})
    pick = lambda seed: [mc(LINES[:3], pr, table(window=100), seed=seed).choose(START, 1500).move.uci() for _ in range(1)]
    seq = lambda seed: (lambda m: [m.choose(START, 1500).move.uci() for _ in range(30)])(mc(LINES[:3], pr, table(window=100), seed=seed))
    assert seq(5) == seq(5) and seq(5) != seq(6) and pick(1)


def test_no_legal_moves_is_an_error():
    mated = chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
    with pytest.raises(ValueError):
        mc(LINES, prior_of({})).choose(mated, 1500)


# ---- UCI front-end ------------------------------------------------------------------------------------------------

class FakeController:
    def __init__(self):
        self.elo_seen, self.rng = [], random.Random(0)

    def choose(self, board, elo, opp_elo=None, platform=0):
        from chessme.mechess.controller import Candidate, Choice
        self.elo_seen.append((elo, opp_elo, platform))
        m = next(iter(board.legal_moves))
        return Choice(m, "search", [Candidate(m, 0, prob=1.0)])


def session(script, elo=1800):
    fc = FakeController()
    out = io.StringIO()
    MechessUci(fc, io.StringIO(script), out, elo=elo).run()
    return fc, out.getvalue()


def test_uci_handshake_and_options():
    _, out = session("uci\nisready\nquit\n")
    assert "id name MeChess" in out and "option name Elo type spin default 1800" in out and "uciok" in out and "readyok" in out


def test_go_answers_with_a_legal_move_for_the_given_position():
    fc, out = session("position startpos moves e2e4 e7e5\ngo\nquit\n")
    bm = [l for l in out.splitlines() if l.startswith("bestmove")][0].split()[1]
    b = chess.Board()
    b.push_uci("e2e4"); b.push_uci("e7e5")
    assert chess.Move.from_uci(bm) in b.legal_moves and "info string search" in out


def test_elo_option_reaches_the_controller_and_is_clamped():
    fc, _ = session("setoption name Elo value 2000\nposition startpos\ngo\nsetoption name Elo value 99999\ngo\nquit\n")
    assert [e[0] for e in fc.elo_seen] == [2000, 4000]   # clamped to the option range (0..4000)
    fc, _ = session("setoption name OppElo value 1500\nsetoption name Platform value 1\nposition startpos\ngo\n")
    assert fc.elo_seen[0][1:] == (1500, 1)


def test_bad_positions_are_ignored_and_a_mated_position_gives_a_null_move():
    fc, out = session("position startpos moves e2e5\ngo\nquit\n")  # illegal move: position stays at the start
    assert "bestmove" in out and fc.elo_seen
    _, out = session("position fen 7k/6Q1/6K1/8/8/8/8/8 b - - 0 1\ngo\nquit\n")
    assert "bestmove 0000" in out
    _, out = session("position fen garbage\ngo\nquit\n")
    assert "bestmove" in out


# ---- weak-end knobs: blunder rate and table files -------------------------------------------------------------------

class TestBlunderKnobAndTables:
    def test_rows_may_have_a_blunder_rate_and_it_interpolates_and_is_clamped(self):
        t = {1000: (100, 4, 200, 1.5, 100.0, 6, 0.4), 2000: (100, 4, 200, 1.5, 100.0, 6, 0.0)}
        assert dial.settings_for(1000, t).blunder_rate == 0.4 and dial.settings_for(2000, t).blunder_rate == 0.0
        assert dial.settings_for(1500, t).blunder_rate == pytest.approx(0.2)
        assert dial.settings_for(1000, {1000: (100, 4, 200, 1.5, 100.0, 6, 3.0)}).blunder_rate == 1.0   # clamped to a probability

    def test_six_column_rows_still_work_and_never_blunder(self):
        assert dial.settings_for(1800).blunder_rate == 0.0 and dial.settings_for(1200, table(), None).blunder_rate == 0.0

    def test_table_files_round_trip_and_accept_string_keys(self, tmp_path):
        t = {800: (100, 8, 300, 2.0, 200.0, 6, 0.3), 1800: (4000, 6, 120, 1.1, 80.0, 22)}
        dial.save_table(t, tmp_path / "sub" / "t.json")
        back = dial.load_table(tmp_path / "sub" / "t.json")
        assert back == {800: (100, 8, 300, 2.0, 200.0, 6, 0.3), 1800: (4000, 6, 120, 1.1, 80.0, 22)}
        assert list(back) == sorted(back) and all(isinstance(k, int) for k in back)

    def blunder_table(self, rate):
        return {1200: (100, 4, 100, 1.0, 50.0, 0, rate), 2600: (100, 4, 100, 1.0, 50.0, 0, rate)}

    def test_a_certain_blunder_plays_a_random_other_legal_move_and_says_so(self):
        m = mc(LINES, prior_of({"e2e4": 1, "d2d4": 1, "g1f3": 1}), self.blunder_table(1.0), seed=3)
        c = m.choose(START, 1500)
        assert c.source == "blunder" and c.move in START.legal_moves
        seen = {m.choose(START, 1500).move for _ in range(60)}
        assert len(seen) > 5                                             # random legal moves, not just the few candidates

    def test_no_blunder_rate_never_blunders(self):
        m = mc(LINES, prior_of({"e2e4": 1, "d2d4": 1, "g1f3": 1}), self.blunder_table(0.0), seed=4)
        assert all(m.choose(START, 1500).source == "search" for _ in range(100))

    def test_the_blunder_rate_is_the_frequency_of_blunders(self):
        m = mc(LINES, prior_of({"e2e4": 1, "d2d4": 1, "g1f3": 1}), self.blunder_table(0.3), seed=5)
        n = sum(m.choose(START, 1500).source == "blunder" for _ in range(600))
        assert 0.22 < n / 600 < 0.38

    def test_book_moves_and_forced_moves_are_never_blundered(self, tmp_path):
        book = book_file(tmp_path, [entry(START, "e2e4", 1)])
        t = {1200: (100, 4, 100, 1.0, 50.0, 20, 1.0), 2600: (100, 4, 100, 1.0, 50.0, 20, 1.0)}
        assert mc(LINES, prior_of({"e2e4": 1}), t, book=book).choose(START, 1500).source == "book"
        forced = SimpleNamespace(legal_moves=[chess.Move.from_uci("e2e4")])
        only = Choice(chess.Move.from_uci("e2e4"), "search", [])
        s = dial.settings_for(1500, self.blunder_table(1.0))
        assert mc(LINES, prior_of({}), self.blunder_table(1.0))._with_blunder(forced, only, s) is only   # nothing else to play

    def test_the_uci_front_end_uses_a_table_file(self, tmp_path):
        path = tmp_path / "t.json"
        dial.save_table(self.blunder_table(1.0), path)
        m = MeChess(StubEngine(LINES), prior_of({"e2e4": 1, "d2d4": 1}), None, dial.load_table(path), 1)
        out = io.StringIO()
        u = MechessUci(m, inp=io.StringIO("position startpos\ngo\nquit\n"), out=out, elo=1500)
        u.run()
        assert "info string blunder" in out.getvalue()


def test_the_uci_elo_option_accepts_labels_below_800():
    """Regression: the Elo option was clamped to 800..2800, so dial labels 400 and 600 silently played as 800."""
    from chessme.mechess.uci import OPTIONS
    assert OPTIONS["Elo"][1] <= 0 and OPTIONS["Elo"][2] >= 3500
    m = mc(LINES, prior_of({"e2e4": 1, "d2d4": 1}), {400: (60, 4, 100, 1.0, 50.0, 0), 1800: (60, 4, 100, 1.0, 50.0, 0)})
    u = MechessUci(m, inp=io.StringIO("setoption name Elo value 400\nquit\n"), out=io.StringIO(), elo=1800)
    u.run()
    assert u.opts["Elo"] == 400
