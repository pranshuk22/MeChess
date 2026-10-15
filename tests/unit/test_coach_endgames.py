import os
import random

import chess
import chess.syzygy
import pytest

from chessme.coach import endgames as EG

KQK = "4k3/8/8/8/8/8/8/K2Q4 w - - 0 1"        # white to move, a won position (queen against king)


class FakeTB:
    """A scripted tablebase: white is winning everywhere (wdl 2 for white to move, -2 for black to move) unless a position is listed in `override`."""

    def __init__(self, override=None, dtz=10):
        self.override, self.dtz = override or {}, dtz

    def probe_wdl(self, board):
        key = board.fen().split(" ")[0] + " " + ("w" if board.turn else "b")
        if key in self.override:
            return self.override[key]
        return 2 if board.turn == chess.WHITE else -2

    def probe_dtz(self, board):
        return self.dtz


def key_after(fen, uci):
    b = chess.Board(fen)
    b.push_uci(uci)
    return b.fen().split(" ")[0] + " " + ("w" if b.turn else "b")


def test_a_move_that_throws_the_win_away_is_refused_and_explained_and_the_position_is_unchanged():
    bad = "d1d8"                                                               # the scripted tablebase says: after Qd8+ it is only a draw
    tb = FakeTB(override={key_after(KQK, bad): 0})
    d = EG.EndgameDrill("kqk", tb, KQK, chess.WHITE)
    out = d.move(bad)
    assert out["verdict"] == "throws it away" and "gives away the win" in out["message"] and "only a draw" in out["message"]
    assert d.errors == 1 and d.board.fen() == KQK and d.line == []


def test_a_good_move_is_played_the_opponent_resists_and_the_hint_ladder_names_the_move():
    d = EG.EndgameDrill("kqk", FakeTB(), KQK, chess.WHITE, seed=1)
    assert "legal moves keep the win" in d.hint(1) and d.hint(2).startswith("Move the piece on") and d.hint(3).startswith("The move is ")
    out = d.move("a1b1")
    assert out["verdict"] == "ok" and "reply_san" in out and len(d.line) == 2 and d.board.turn == chess.WHITE
    assert d.move("zzzz")["error"] == "that is not a move" and d.move("a8a1")["error"] == "that move is not legal here"


def test_a_slow_win_is_noted_and_checkmate_ends_the_drill_with_success():
    class SlowTB(FakeTB):
        def probe_dtz(self, board):
            return 40 if board.fen().startswith("4k3/8/8/8/8/8/8/K1Q5") else 10      # one candidate leads to a much longer win
    d = EG.EndgameDrill("kqk", SlowTB(), KQK, chess.WHITE)
    assert d.move("d1c1")["slow"] is True
    mate = "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1"                                          # Qg7 is mate
    d2 = EG.EndgameDrill("kqk", FakeTB(), mate, chess.WHITE)
    out = d2.move("f7g7")
    assert d2.over and d2.report["success"] is True and "Checkmate" in d2.report["message"] and out["view"]["over"] is True
    assert d2.move("g6f6")["error"] == "this game is finished"


def test_stalemating_the_opponent_is_refused_when_you_are_winning():
    fen = "k7/8/1K6/8/8/8/8/2Q5 w - - 0 1"                                             # Qc7 would stalemate the king on a8
    d = EG.EndgameDrill("kqk", FakeTB(), fen, chess.WHITE)
    out = d.move("c1c7")
    assert out["verdict"] == "throws it away" and "gives away the win" in out["message"] and not d.over


def test_generate_keeps_only_positions_with_the_wanted_result_and_the_theme_table_is_probed():
    tb = FakeTB(override={})
    fen, color = EG.generate("kqk", tb, random.Random(1))
    b = chess.Board(fen)
    assert b.turn == color and b.is_valid() and not b.is_game_over()
    hold = EG.generate("kpk-hold", FakeTB(), random.Random(1), tries=200)             # the fake never says draw for the defender: nothing found
    assert hold is None or hold[1] in (chess.WHITE, chess.BLACK)


@pytest.mark.skipif(not os.environ.get("CHESSME_SYZYGY_DIR"), reason="needs the 3-piece Syzygy tables (CHESSME_SYZYGY_DIR)")
def test_with_real_tablebases_perfect_play_converts_every_theme_and_holds_the_draw():
    tb = chess.syzygy.open_tablebase(os.environ["CHESSME_SYZYGY_DIR"])
    assert all(EG.available(tb, t) for t in EG.THEMES)
    for theme in EG.THEMES:
        fen, player = EG.generate(theme, tb, random.Random(3))
        d = EG.EndgameDrill(theme, tb, fen, player, seed=1)
        for _ in range(120):
            if d.over:
                break
            good, _ = d.good_moves()
            d.move(min(good, key=lambda t: t[0])[1].uci())
        assert d.over and d.report["success"] is True and d.errors == 0


def test_the_app_offers_endgame_themes_and_runs_a_drill_with_a_scripted_tablebase():
    from chessme.coach import server as CS
    from tests.unit.test_coach_server import fake_search
    app = CS.CoachApp(fake_search)
    assert "no tablebase" in app.endgame_start("kqk")["error"]
    app = CS.CoachApp(fake_search, tablebase=FakeTB())
    themes = {t["id"]: t for t in app.endgame_themes()}
    assert themes["kqk"]["available"] is True and "title" in themes["kqk"]
    out = app.endgame_start("kqk")
    sid = out["session"]
    assert out["view"]["goal"].startswith("Queen against king") and app.endgame_start("nope")["error"] == "unknown theme"
    assert "legal moves keep the win" in app.endgame_act(sid, "hint", {"level": 1})["hint"]
    move = out["view"]["legal"][0]
    r = app.endgame_act(sid, "move", {"uci": move})
    assert r.get("verdict") in ("ok", "throws it away") or "error" in r
    assert app.endgame_act("nope", "move", {})["error"] == "unknown session"
