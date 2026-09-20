import io

import chess
import chess.pgn
import pytest

from chessme import match
from chessme.match import Adjudication, EngineSpec, GameResult, SearchLimit
from chessme.uci_client import STARTPOS_FEN, EngineError, GoResult


class StubEngine:
    """Plays the first legal move (or a scripted one) and reports a fixed score, from its own point of view."""

    def __init__(self, name, score=0, kind="cp", script=None, error_at=None, bestmove=None):
        self.name, self.score, self.kind = name, score, kind
        self.script, self.error_at, self.bestmove = list(script or []), error_at, bestmove
        self.calls = 0

    def go(self, fen, moves, timeout=60, **kw):
        self.calls += 1
        if self.error_at is not None and self.calls == self.error_at:
            raise EngineError(f"{self.name} exploded")
        board = chess.Board(fen)
        for m in moves:
            board.push_uci(m)
        if self.bestmove is not None:
            return GoResult(self.bestmove, self.kind, self.score)
        if self.script:
            return GoResult(self.script.pop(0), self.kind, self.score)
        return GoResult(sorted(m.uci() for m in board.legal_moves)[0], self.kind, self.score)


NO_ADJ = Adjudication(resign_cp=0, draw_cp=0)
LIMIT = SearchLimit(nodes=100)


# ---- helpers -----------------------------------------------------------------------------------------------

def test_white_pov_conversion():
    assert match.white_pov("cp", 50, True) == 50
    assert match.white_pov("cp", 50, False) == -50
    assert match.white_pov("mate", 3, True) > 9900
    assert match.white_pov("mate", 3, False) < -9900
    assert match.white_pov("mate", -2, True) < -9900
    assert match.white_pov(None, None, True) is None
    assert match.white_pov("mate", 1, True) > match.white_pov("mate", 5, True)  # nearer mate is better


def test_search_limit_kwargs_only_include_set_fields():
    assert SearchLimit(nodes=500).kwargs() == {"nodes": 500}
    assert SearchLimit(depth=4, movetime=10).kwargs() == {"depth": 4, "movetime": 10}
    assert SearchLimit().kwargs() == {}


def test_engine_spec_is_hashable_and_orders_options():
    a = EngineSpec.make("x", "/bin/e", {"B": 1, "A": 2})
    b = EngineSpec.make("x", "/bin/e", {"A": 2, "B": 1})
    assert a == b and hash(a) == hash(b) and a.options == (("A", 2), ("B", 1))
    assert EngineSpec.make("y", ["/bin/e", "--flag"]).command == ("/bin/e", "--flag")


@pytest.mark.parametrize("evals,expected", [
    ([1200] * 6, ("1-0", "winning")),
    ([-1200] * 6, ("0-1", "winning")),
    ([1200] * 5, None),                          # not long enough
    ([1200] * 5 + [900], None),                  # streak broken
    ([1200] * 5 + [None], None),                 # missing score breaks it
    ([-1200, 1200] * 3, None),                   # evaluations disagree
])
def test_resign_adjudication(evals, expected):
    got = match.check_adjudication(evals, Adjudication(resign_cp=1000, resign_plies=6, draw_cp=0))
    assert (got is None) if expected is None else (got[0] == expected[0] and expected[1] in got[1])


def test_draw_adjudication_needs_min_ply_and_a_flat_streak():
    adj = Adjudication(resign_cp=0, draw_cp=10, draw_plies=4, draw_min_ply=8)
    assert match.check_adjudication([0] * 7, adj) is None                        # too early
    assert match.check_adjudication([0] * 8, adj)[0] == "1/2-1/2"
    assert match.check_adjudication([0] * 7 + [40], adj) is None                # streak broken
    assert match.check_adjudication([300] * 4 + [0] * 4, adj)[0] == "1/2-1/2"   # only the tail matters


def test_max_plies_ends_the_game_as_a_draw():
    got = match.check_adjudication([50] * 40, Adjudication(resign_cp=0, draw_cp=0, max_plies=40))
    assert got[0] == "1/2-1/2" and "max plies" in got[1]


def test_disabled_adjudication_never_fires():
    assert match.check_adjudication([5000] * 100, Adjudication(resign_cp=0, draw_cp=0, max_plies=10**6)) is None


def game(result, **kw):
    return GameResult(STARTPOS_FEN, [], [], result, "x", **kw)


def test_a_points_depends_on_colour():
    assert match.a_points(game("1-0"), True) == 1 and match.a_points(game("1-0"), False) == 0
    assert match.a_points(game("0-1"), True) == 0 and match.a_points(game("0-1"), False) == 1
    assert match.a_points(game("1/2-1/2"), True) == match.a_points(game("1/2-1/2"), False) == 0.5


def test_record_pair_updates_counts_and_pentanomial():
    r = match.MatchResult("A", "B")
    match.record_pair(r, [game("1-0"), game("1-0")])          # A white wins, then B (white) wins -> A: 1 + 0
    match.record_pair(r, [game("1-0"), game("0-1")])          # A wins both
    match.record_pair(r, [game("1/2-1/2"), game("1/2-1/2")])  # two draws
    match.record_pair(r, [game("0-1"), game("1-0")])          # A loses both
    assert (r.wins, r.draws, r.losses) == (3, 2, 3)
    assert r.penta == [1, 0, 2, 0, 1] and r.pairs == 4
    assert len(r.games) == 8


def test_record_pair_collects_engine_faults():
    r = match.MatchResult("A", "B")
    g = game("0-1")
    g.error = "boom"
    match.record_pair(r, [g, game("1-0")])
    assert r.errors == ["boom"]


# ---- play_game ---------------------------------------------------------------------------------------------

def test_checkmate_ends_the_game():
    w = StubEngine("w", script=["f2f3", "g2g4"])
    b = StubEngine("b", script=["e7e5", "d8h4"])
    g = match.play_game(w, b, STARTPOS_FEN, LIMIT, NO_ADJ)
    assert g.result == "0-1" and g.reason == "checkmate" and g.error is None
    assert g.moves == ["f2f3", "e7e5", "g2g4", "d8h4"]
    assert (g.white, g.black) == ("w", "b")


def test_illegal_move_loses_the_game():
    g = match.play_game(StubEngine("w", bestmove="e2e5"), StubEngine("b"), STARTPOS_FEN, LIMIT, NO_ADJ)
    assert g.result == "0-1" and g.reason == "illegal move" and "e2e5" in g.error and g.moves == []


def test_null_move_from_an_engine_counts_as_illegal():
    g = match.play_game(StubEngine("w"), StubEngine("b", bestmove="0000"), STARTPOS_FEN, LIMIT, NO_ADJ)
    assert g.result == "1-0" and g.reason == "illegal move"


def test_engine_error_loses_for_the_faulty_side():
    g = match.play_game(StubEngine("w"), StubEngine("b", error_at=2), STARTPOS_FEN, LIMIT, NO_ADJ)
    assert g.result == "1-0" and g.reason == "engine error" and "b exploded" in g.error


def test_unparsable_bestmove_is_an_engine_error():
    g = match.play_game(StubEngine("w", bestmove="zzzz"), StubEngine("b"), STARTPOS_FEN, LIMIT, NO_ADJ)
    assert g.result == "0-1" and g.error


def test_resign_adjudication_in_play():
    w, b = StubEngine("w", score=1500), StubEngine("b", score=-1500)  # both agree White is winning
    g = match.play_game(w, b, STARTPOS_FEN, LIMIT, Adjudication(resign_cp=1000, resign_plies=6, draw_cp=0))
    assert g.result == "1-0" and "winning" in g.reason and len(g.moves) == 6


def test_draw_adjudication_in_play():
    adj = Adjudication(resign_cp=0, draw_cp=10, draw_plies=4, draw_min_ply=4)
    g = match.play_game(StubEngine("w", score=0), StubEngine("b", score=0), STARTPOS_FEN, LIMIT, adj)
    assert g.result == "1/2-1/2" and "drawn" in g.reason


def test_evals_are_recorded_from_whites_point_of_view():
    w, b = StubEngine("w", score=30), StubEngine("b", score=30)  # each thinks *it* is +30
    g = match.play_game(w, b, STARTPOS_FEN, LIMIT, Adjudication(resign_cp=0, draw_cp=0, max_plies=4))
    assert g.evals == [30, -30, 30, -30]


def test_game_from_a_custom_start_position():
    fen = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"  # black is already checkmated
    g = match.play_game(StubEngine("w"), StubEngine("b"), fen, LIMIT, NO_ADJ)
    assert g.result == "1-0" and g.reason == "checkmate" and g.moves == []


def test_threefold_repetition_is_a_draw():
    w = StubEngine("w", script=["g1f3", "f3g1"] * 4)
    b = StubEngine("b", script=["g8f6", "f6g8"] * 4)
    g = match.play_game(w, b, STARTPOS_FEN, LIMIT, NO_ADJ)
    assert g.result == "1/2-1/2" and "repetition" in g.reason


# ---- PGN ---------------------------------------------------------------------------------------------------

def test_pgn_round_trip_with_eval_comments():
    g = GameResult(STARTPOS_FEN, ["e2e4", "e7e5", "g1f3"], [35, -20, None], "1-0", "adjudicated", "Alpha", "Beta")
    parsed = chess.pgn.read_game(io.StringIO(match.game_to_pgn(g)))
    assert [m.uci() for m in parsed.mainline_moves()] == g.moves
    assert parsed.headers["White"] == "Alpha" and parsed.headers["Result"] == "1-0"
    assert [n.comment for n in parsed.mainline()][:2] == ["+0.35", "-0.20"]
    assert "FEN" not in parsed.headers


def test_pgn_records_custom_start_position():
    fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
    g = GameResult(fen, ["e2e4"], [10], "1/2-1/2", "x", "a", "b")
    parsed = chess.pgn.read_game(io.StringIO(match.game_to_pgn(g)))
    assert parsed.headers["FEN"] == fen and parsed.board().fen() == fen


# ---- run_match with a stubbed pair player -------------------------------------------------------------------

def fake_pair_player(outcomes):
    """outcomes: pair index -> (result for game 1, result for game 2)."""
    def play(job):
        idx = job[0]
        r1, r2 = outcomes(idx)
        return idx, [game(r1), game(r2)]
    return play


def test_run_match_respects_max_pairs_and_opening_count(monkeypatch):
    monkeypatch.setattr(match, "play_pair", fake_pair_player(lambda i: ("1/2-1/2", "1/2-1/2")))
    spec = EngineSpec.make("a", "x")
    r = match.run_match(spec, spec, ["f"] * 10, LIMIT, max_pairs=4)
    assert r.pairs == 4
    r = match.run_match(spec, spec, ["f"] * 3, LIMIT, max_pairs=99)
    assert r.pairs == 3  # cannot play more pairs than openings


def test_run_match_stops_early_when_sprt_decides(monkeypatch):
    monkeypatch.setattr(match, "play_pair", fake_pair_player(lambda i: ("1-0", "0-1")))  # A sweeps every pair
    spec = EngineSpec.make("a", "x")
    r = match.run_match(spec, spec, ["f"] * 200, LIMIT, sprt=(0, 10))
    assert r.status == "H1" and r.pairs < 30  # a clean sweep is decisive quickly
    # a mixed but clearly favourable sequence also stops early, well before the opening list is used up
    seq = [("1-0", "0-1"), ("1-0", "0-1"), ("1-0", "1-0"), ("1/2-1/2", "0-1")]
    monkeypatch.setattr(match, "play_pair", fake_pair_player(lambda i: seq[i % 4]))
    r = match.run_match(spec, spec, ["f"] * 400, LIMIT, sprt=(0, 10))
    assert r.status == "H1" and r.pairs < 400


def test_run_match_writes_pgn_and_reports_progress(monkeypatch, tmp_path):
    def play(job):
        g = GameResult(STARTPOS_FEN, ["e2e4", "e7e5"], [10, -10], "1/2-1/2", "x", "a", "b")
        return job[0], [g, g]
    monkeypatch.setattr(match, "play_pair", play)
    seen = []
    spec = EngineSpec.make("a", "x")
    r = match.run_match(spec, spec, ["f"] * 3, LIMIT, pgn_path=tmp_path / "m.pgn", progress=lambda res: seen.append(res.pairs))
    assert seen == [1, 2, 3]
    games = []
    with open(tmp_path / "m.pgn") as f:
        while (g := chess.pgn.read_game(f)):
            games.append(g)
    assert len(games) == 6 == len(r.games)


def test_summary_mentions_the_key_numbers():
    r = match.MatchResult("new", "old")
    match.record_pair(r, [game("1-0"), game("0-1")])
    text = r.summary(0, 5)
    assert "new  vs  old" in text and "W 2 / D 0 / L 0" in text and "SPRT [0, 5]" in text


def test_pgn_output_folder_is_created_if_missing(monkeypatch, tmp_path):
    """Regression: a finished match was lost because the PGN's folder did not exist."""
    monkeypatch.setattr(match, "play_pair", fake_pair_player(lambda i: ("1-0", "0-1")))
    spec = EngineSpec.make("a", "x")
    target = tmp_path / "does" / "not" / "exist" / "m.pgn"
    r = match.run_match(spec, spec, ["f"] * 2, LIMIT, pgn_path=target)
    assert target.exists() and r.pairs == 2
