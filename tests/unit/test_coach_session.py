import chess

from chessme.coach import exercises as X
from chessme.coach import session as S

AFTER_F3_E5 = "rnbqkbnr/pppp1ppp/8/4p3/8/5P2/PPPPP1PP/RNBQKBNR w KQkq - 0 2"


class Line:
    def __init__(self, move, cp, pv=()):
        self.move, self.cp, self.pv = move, cp, list(pv)


def fake_search(board):
    """A scripted 'engine': in the test position e2e4 is best; g2g4 loses to mate; everything else is slightly worse; elsewhere the first legal move is best."""
    moves = sorted(board.legal_moves, key=lambda m: m.uci())
    if board.fen() == AFTER_F3_E5:
        return [Line("e2e4", 40), Line("d2d4", 30), Line("b1c3", 25)]
    if board.is_checkmate():
        return []
    if board.fen().startswith("rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2"):         # after g4: black mates
        return [Line("d8h4", 10000)]
    return [Line(m.uci(), 20 - 5 * i) for i, m in enumerate(moves[:3])]


def make():
    ex = X.exercise(AFTER_F3_E5, "g2g4", "e2e4", 0.9, 0.55, 0.0, ply=3, phase="opening", cls="blunder")
    return S.Replay([ex], S.Judge(fake_search), S.EngineOpponent(fake_search, seed=1))


def test_judge_measures_loss_against_the_best_move_and_a_mate_is_a_big_loss():
    j = S.Judge(fake_search)
    assert j.loss(AFTER_F3_E5, "e2e4") == 0.0
    assert j.loss(AFTER_F3_E5, "g2g4") > 0.4
    assert 0 < j.loss(AFTER_F3_E5, "d2d4") < 0.08


def test_the_replay_asks_for_a_move_gives_hints_and_rejects_the_original_mistake():
    r = make()
    v = r.view()
    assert v["mode"] == "find" and v["fen"] == AFTER_F3_E5 and v["color"] == "white" and "best_uci" not in v and "explanation" not in v
    assert r.hint()["level"] == 1 and r.hint()["level"] == 2 and r.hint()["level"] == 3 and r.hint()["level"] == 3
    assert "error" in r.attempt("a1a5") and "error" in r.attempt("zzzz")
    out = r.attempt("g2g4")
    assert out["verdict"] == S.NOT_YET and "from your game" in out["message"]
    assert r.mode == "find" and r.tries == 1


def test_finding_the_better_move_explains_it_and_lets_the_player_play_on_then_reset():
    r = make()
    out = r.attempt("e2e4")
    assert out["verdict"] == "found" and out["message"].startswith("Yes.") and "checkmate with Qh4#" in out["message"]
    assert r.mode == "play" and "reply_uci" in out and chess.Board(out["fen"]).turn == chess.WHITE          # the opponent has answered: the player is to move
    moved = r.play(next(iter(r.board.legal_moves)).uci())
    assert "san" in moved and "fen" in moved and moved["game_over"] in (True, False)
    r.reset()
    assert r.mode == "find" and r.view()["fen"] == AFTER_F3_E5 and r.hints_used == 0 and r.tries == 1


def test_a_playable_alternative_is_accepted_with_a_note_and_the_log_records_every_attempt():
    r = make()
    out = r.attempt("d2d4")
    assert out["verdict"] == "ok" and "first choice was e4" in out["message"]
    assert [a["verdict"] for a in r.log] == ["ok"] and r.log[0]["kind"] == "mate in 1" and r.log[0]["phase"] == "opening"


def test_reveal_after_failures_and_moving_on_to_the_end():
    r = make()
    for _ in range(S.MAX_TRIES_BEFORE_OFFER):
        out = r.attempt("g2g4")
    assert out["can_reveal"] is True
    shown = r.reveal()
    assert shown["verdict"] == "revealed" and shown["best_uci"] == "e2e4" and r.mode == "play"
    assert r.log[-1]["verdict"] == "revealed"
    assert r.next() == {"done": True, "mode": "done", "attempts": 4}
