import json
import threading
import urllib.request

import chess

from chessme.coach import server as CS

PGN = "[Event \"t\"]\n[White \"alice\"]\n[Black \"bob\"]\n[Result \"0-1\"]\n\n1. f3 e5 2. g4 Qh4# 0-1\n"
AFTER_F3_E5 = "rnbqkbnr/pppp1ppp/8/4p3/8/5P2/PPPPP1PP/RNBQKBNR w KQkq - 0 2"


class Line:
    def __init__(self, move, cp):
        self.move, self.cp, self.pv = move, cp, []


def fake_search(board):
    """Scripted: after 1.f3 e5, e2e4 is best and g2g4 loses to mate; in the opening position e2e4; otherwise the legal moves in order."""
    if board.is_checkmate():
        return []
    if board.fen() == AFTER_F3_E5:
        return [Line("e2e4", 40), Line("d2d4", 30)]
    if board.fen().startswith("rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2"):
        return [Line("d8h4", 10000)]
    moves = sorted(m.uci() for m in board.legal_moves)
    return [Line(m, 30 - 3 * i) for i, m in enumerate(moves[:3])]


def test_app_lists_games_starts_a_review_and_runs_the_replay_loop():
    app = CS.CoachApp(fake_search)
    games = app.games_in(PGN + "\n" + PGN)
    assert [g["white"] for g in games] == ["alice", "alice"] and games[0]["plies"] == 4
    started = app.start(PGN, 0, "white")
    assert started["n"] == 1 and started["view"]["fen"] == AFTER_F3_E5 and "explanation" not in json.dumps(started["view"])
    sid = started["session"]
    assert app.act(sid, "hint")["level"] == 1
    bad = app.act(sid, "attempt", {"uci": "g2g4"})
    assert bad["verdict"] == "not yet"
    good = app.act(sid, "attempt", {"uci": "e2e4"})
    assert good["verdict"] == "found" and good["view"]["mode"] == "play" and "reply_uci" in good
    assert app.act(sid, "reset")["view"]["mode"] == "find"
    assert app.act("nope", "hint")["error"].startswith("unknown session")
    assert app.act(sid, "dance")["error"] == "unknown action"
    assert app.act(sid, "next")["view"]["done"] is True


def test_app_reports_errors_and_a_game_without_mistakes():
    app = CS.CoachApp(fake_search)
    assert "color" in app.start(PGN, 0, "green")["error"]
    assert app.start(PGN, 5, "white")["error"] == "no such game in the PGN"
    out = app.start(PGN, 0, "black")                               # black played the mate: nothing to replay
    assert out.get("none") is True and "nothing to replay" in out["message"]


def post(base, path, body):
    req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def test_http_server_serves_the_page_and_the_api_on_localhost_only():
    app = CS.CoachApp(fake_search)
    srv = CS.make_server(app, fetch=lambda platform, user, n: PGN)
    assert srv.server_address[0] == "127.0.0.1"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        page = urllib.request.urlopen(base + "/", timeout=10).read().decode()
        assert "MeChess coach" in page and "http://" not in page.replace("http://www.w3.org", "") and "https://" not in page          # no outside resources
        g = post(base, "/api/games", {"user": "someone", "platform": "chesscom"})                     # fetched through the injected function
        assert g["games"][0]["white"] == "alice"
        s = post(base, "/api/start", {"pgn": g["pgn"], "index": 0, "color": "white"})
        sid = s["session"]
        a = post(base, f"/api/replay/{sid}/attempt", {"uci": "e2e4"})
        assert a["verdict"] == "found"
        assert "error" in post(base, "/api/start", {"pgn": "", "index": 0, "color": "white"})
        try:
            urllib.request.urlopen(base + "/other", timeout=10)
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()
        srv.server_close()


def test_user_names_are_validated_before_any_request_is_made():
    import pytest
    for bad in ("", "a", "x/../y", "name with space", "a" * 40):
        with pytest.raises(ValueError):
            CS.lichess_games(bad)
        with pytest.raises(ValueError):
            CS.chesscom_games(bad)


def test_chesscom_archives_are_read_newest_first_and_only_standard_chess(monkeypatch):
    calls = []

    class Resp:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data
    archives = {"archives": ["https://api.chess.com/a/2026/08", "https://api.chess.com/a/2026/09"]}
    months = {"https://api.chess.com/a/2026/09": {"games": [{"pgn": "[White \"a\"]\n\n1. e4 *", "rules": "chess"}, {"pgn": "[White \"v\"]\n\n1. e4 *", "rules": "chess960"}]},
              "https://api.chess.com/a/2026/08": {"games": [{"pgn": "[White \"old\"]\n\n1. d4 *", "rules": "chess"}]}}

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return Resp(archives if url.endswith("/games/archives") else months[url])
    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    text = CS.chesscom_games("Someone", 5)
    assert text.index('"a"') < text.index('"old"') and "chess960" not in text and '"v"' not in text
    assert calls[0] == "https://api.chess.com/pub/player/someone/games/archives" and len(calls) == 3
    assert len(CS.chesscom_games("Someone", 1).split("\n\n[")) == 1                 # stops at the requested number
