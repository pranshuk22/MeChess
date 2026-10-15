import collections

import chess
import pytest

from chessme.coach import steering as ST


class Line:
    def __init__(self, move, cp):
        self.move, self.cp, self.pv = move, cp, []


def search_for(lines):
    return lambda board: [Line(m, cp) for m, cp in lines]


def test_threats_trades_defend_and_sharp_scores_come_from_the_board():
    # white queen takes a knight that is defended: a trade; after Bb5 pinning... use simple positions
    b = chess.Board("4k3/8/8/3n4/8/2Q5/P7/4K3 b - - 0 1")            # black to move: Nxc3? knight takes queen
    cap = chess.Move.from_uci("d5c3")
    after = b.copy(stack=False)
    after.push(cap)
    assert ST.score("trades", b, cap, after, chess.WHITE) == 1.0       # a capture that reduces the pieces on the board
    quiet = chess.Move.from_uci("e8e7")
    a2 = b.copy(stack=False)
    a2.push(quiet)
    assert ST.score("trades", b, quiet, a2, chess.WHITE) == 0.0
    assert ST.score("threats", b, quiet, a2, chess.WHITE) == 1.0       # the knight on d5 still attacks the queen on c3: a threat against white
    check_board = chess.Board("4k3/8/8/8/8/8/4R3/K7 w - - 0 1")
    chk = chess.Move.from_uci("e2e7")
    a3 = check_board.copy(stack=False)
    a3.push(chk)
    assert ST.score("defend", check_board, chk, a3, chess.BLACK) == 1.0
    assert 0.0 <= ST.score("sharp", b, quiet, a2, chess.WHITE) <= 1.0


def test_the_opponent_never_plays_outside_the_budget_and_prefers_the_focus_among_the_allowed_moves():
    b = chess.Board("4k3/8/8/3n4/8/2Q5/P7/4K3 b - - 0 1")
    # best Nxc3 (cp 900 for black), e7 quiet is a near-best alternative, e8f8 is far worse (outside the budget)
    lines = [("d5c3", 900), ("e8e7", 880), ("e8f8", -300)]
    opp = ST.SteeredOpponent(search_for(lines), {"threats": 1.0}, chess.WHITE, seed=1)
    picks = collections.Counter(opp.move(b) for _ in range(300))
    assert "e8f8" not in picks                                          # outside the budget
    assert picks["e8e7"] > 0 and picks["d5c3"] > 0
    plain = ST.SteeredOpponent(search_for(lines), {}, chess.WHITE, seed=1)
    base = collections.Counter(plain.move(b) for _ in range(300))
    assert picks["e8e7"] > base["e8e7"]                                 # the focus makes the threat-keeping move likelier than without it
    assert opp.hits and opp.hits[0]["scores"]["threats"] in (0.0, 1.0)


def test_convert_prefers_weaker_acceptable_moves_with_a_larger_budget_and_unknown_foci_are_rejected():
    b = chess.Board()
    lines = [("e2e4", 40), ("d2d4", 30), ("g1f3", 0)]
    conv = ST.SteeredOpponent(search_for(lines), {"convert": 1.0}, chess.BLACK, seed=2)
    assert conv.budget == ST.FOCI["convert"]["budget"] > ST.FOCI["threats"]["budget"]
    picks = collections.Counter(conv.move(b) for _ in range(400))
    base_opp = ST.SteeredOpponent(search_for(lines), {}, chess.BLACK, seed=2)
    plain = collections.Counter(base_opp.move(b) for _ in range(400))
    assert picks["g1f3"] > plain["g1f3"] and picks["e2e4"] < plain["e2e4"]       # convert shifts the choice toward the weaker acceptable moves
    with pytest.raises(ValueError):
        ST.SteeredOpponent(search_for(lines), {"fly": 1}, chess.BLACK)
    assert ST.SteeredOpponent(lambda board: [], {"threats": 1}, chess.WHITE).move(b) is None


def _fake_game_search():
    def search(board):
        if board.is_checkmate() or board.is_game_over():
            return []
        moves = sorted(m.uci() for m in board.legal_moves)
        return [Line(m, 30 - 4 * i) for i, m in enumerate(moves[:4])]
    return search


def test_a_steered_game_plays_to_the_end_makes_a_pgn_and_a_focus_report():
    import io

    import chess.pgn

    from chessme.analysis import runner as AR
    g = ST.SteeredGame(_fake_game_search(), "white", {"threats": 1.0, "trades": 0.5}, seed=3, max_plies=12)
    assert g.view()["color"] == "white" and g.view()["legal"]
    n = 0
    while not g.is_over() and n < 20:
        out = g.move(g.view()["legal"][0])
        assert "error" not in out
        n += 1
    assert g.is_over() and g.move("e2e4")["error"] == "the game is over"
    game = chess.pgn.read_game(io.StringIO(g.pgn()))
    assert game.headers["White"] == "You" and sum(1 for _ in game.mainline_moves()) == len(g.board.move_stack)
    analysis = AR.analyse_game(game, _fake_game_search())
    stats, lines = ST.focus_report(game, analysis, "white", g.opponent.hits, g.foci)
    assert set(stats) == {"threats", "trades"} and all("situations" in v for v in stats.values()) and len(lines) == 2


def test_playing_black_lets_the_opponent_move_first_and_the_app_runs_the_steered_flow():
    from chessme.coach import server as CS
    g = ST.SteeredGame(_fake_game_search(), "black", {"defend": 1.0}, seed=1)
    assert g.board.turn == chess.BLACK and len(g.board.move_stack) == 1
    app = CS.CoachApp(_fake_game_search())
    assert "at least one" in app.steer_start("white", {})["error"] and app.steer_start("white", {"fly": 1})["error"] == "unknown focus"
    started = app.steer_start("white", {"threats": 1}, seed=2)
    sid = started["session"]
    assert started["tips"] and app.steer_move("nope", "e2e4")["error"] == "unknown session"
    for _ in range(3):
        v = app.steered[sid].view()
        app.steer_move(sid, v["legal"][0])
    done = app.steer_finish(sid)
    assert "focus_lines" in done and done["result"] in ("*", "1-0", "0-1", "1/2-1/2") and ("session" in done or done.get("none"))
    assert app.steer_finish("nope")["error"] == "unknown session"
