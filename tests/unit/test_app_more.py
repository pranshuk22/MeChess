"""More app tests (audit 2026-10-15, #20): static serving driven below the HTTP client (which normalises paths), the job event stream, the Lichess and Chess.com fetchers."""
import asyncio
import os

import pytest

from chessme.app import importers
from chessme.app.config import AppConfig
from chessme.app.jobs import JobManager
from chessme.app.main import create_app


# ---- static files: the handler itself must refuse ".." (the HTTP client would have removed it before sending) ---------------------------------------------

def asgi_get(app, path: str):
    async def run():
        sent = []

        first = []

        async def receive():
            if not first:
                first.append(1)
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.Event().wait()                                                        # the client stays connected until the response is done

        async def send(message):
            sent.append(message)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
                 "scheme": "http", "headers": [(b"host", b"127.0.0.1:8765")], "server": ("127.0.0.1", 8765), "client": ("127.0.0.1", 5000)}
        await app(scope, receive, send)
        status = next(m["status"] for m in sent if m["type"] == "http.response.start")
        return status, b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return asyncio.run(run())


def test_the_static_handler_never_serves_a_file_outside_its_folder(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>app</html>")
    (root / "assets" / "a.js").write_text("1")
    (tmp_path / "secret.txt").write_text("SECRET")
    os.symlink(tmp_path / "secret.txt", root / "assets" / "link.txt")
    app = create_app(AppConfig(data_dir=tmp_path / "d"), static=root)
    for path in ("/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt", "/assets/link.txt", "//etc/passwd", "/..\\secret.txt"):
        status, body = asgi_get(app, path)
        assert b"SECRET" not in body and b"root:" not in body, path
    assert asgi_get(app, "/assets/a.js") == (200, b"1")
    assert asgi_get(app, "/library")[1] == b"<html>app</html>"


# ---- the job event stream ------------------------------------------------------------------------------------------------------------------------

def make_manager(tmp_path):
    from chessme.app import db as DB
    url = f"sqlite:///{tmp_path / 'j.db'}"
    DB.migrate(url)
    return JobManager(DB.session_factory(DB.make_engine(url)))


def test_listeners_see_every_state_of_a_job_in_order(tmp_path):
    jobs = make_manager(tmp_path)

    async def run():
        q = jobs.subscribe(asyncio.get_running_loop())

        def work(ctx):
            ctx.progress(0.5, "half way")
            return "finished"
        jid = jobs.submit("t", "work", work)
        seen = []
        while True:
            ev = await asyncio.wait_for(q.get(), 10)
            seen.append((ev["status"], ev["progress"], ev["message"]))
            if ev["status"] == "done":
                break
        jobs.unsubscribe(q)
        return jid, seen
    jid, seen = asyncio.run(run())
    jobs.shutdown()
    statuses = [s for s, _, _ in seen]
    assert statuses[0] == "queued" and statuses[-1] == "done" and "running" in statuses
    assert any(p == 0.5 and m == "half way" for _, p, m in seen) and seen[-1][1:] == (1.0, "finished")


def test_a_slow_listener_loses_old_updates_and_never_blocks_a_job(tmp_path):
    jobs = make_manager(tmp_path)

    async def run():
        q = jobs.subscribe(asyncio.get_running_loop())

        def spam(ctx):
            for i in range(500):
                ctx.progress(i / 500, f"step {i}")
        jobs.submit("t", "spam", spam)
        for _ in range(200):                                                                          # give the job time to finish while nobody reads
            await asyncio.sleep(0.05)
            if any(j["status"] == "done" for j in jobs.list()):
                break
        await asyncio.sleep(0.2)
        return q.qsize(), [q.get_nowait() for _ in range(q.qsize())]
    size, items = asyncio.run(run())
    jobs.shutdown()
    assert size <= 200 and items[-1]["status"] == "done"                                              # bounded, and the newest event is kept


# ---- the fetchers ---------------------------------------------------------------------------------------------------------------------------------

class Resp:
    def __init__(self, status=200, lines=(), json_data=None):
        self.status_code, self._lines, self._json, self.encoding = status, list(lines), json_data, None

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


GAME = '[Event "x"]\n[Site "https://lichess.org/AAAAAAAA"]\n[Result "1-0"]\n\n1. e4 e5 1-0'


def test_lichess_games_stream_waits_after_a_429_and_reports_a_missing_user(monkeypatch):
    import requests
    calls, waits = [], []

    def fake_get(url, params=None, headers=None, stream=False, timeout=None):
        calls.append((url, params, headers))
        return Resp(429) if len(calls) == 1 else Resp(200, GAME.split("\n") + [""] + GAME.replace("AAAAAAAA", "BBBBBBBB").split("\n"))
    monkeypatch.setattr(requests, "get", fake_get)
    games = list(importers.lichess_games("someone", 2, sleep=waits.append))
    assert waits == [65] and len(calls) == 2 and len(games) == 2 and "BBBBBBBB" in games[1]
    assert calls[1][1]["max"] == 2 and calls[1][1]["rated"] == "true" and calls[1][1]["clocks"] == "true" and calls[1][2]["Accept"] == "application/x-chess-pgn"
    list(importers.lichess_games("someone", 2, sleep=waits.append, rated_only=False))
    assert "rated" not in calls[-1][1]
    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp(404))
    with pytest.raises(ValueError, match="no user"):
        list(importers.lichess_games("ghost", 5))
    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp(429))
    with pytest.raises(RuntimeError, match="busy"):
        list(importers.lichess_games("someone", 5, sleep=lambda s: None))
    for bad in ("", "a", "x" * 31, "bad name", "a/b"):
        with pytest.raises(ValueError):
            list(importers.lichess_games(bad, 5))


def test_chesscom_games_come_newest_first_standard_chess_only_and_stop_at_the_limit(monkeypatch):
    import requests
    archives = ["https://api.chess.com/pub/player/x/games/2026/04", "https://api.chess.com/pub/player/x/games/2026/05"]
    months = {archives[0]: [{"pgn": "OLD1", "rules": "chess", "rated": True}],
              archives[1]: [{"pgn": "A", "rules": "chess", "rated": True}, {"pgn": "B", "rules": "bughouse", "rated": True}, {"pgn": "C", "rules": "chess", "rated": False}, {"pgn": "D", "rules": "chess", "rated": True}]}

    def fake_get(url, headers=None, timeout=None, **kw):
        return Resp(200, json_data={"archives": archives} if url.endswith("/archives") else {"games": months[url]})
    monkeypatch.setattr(requests, "get", fake_get)
    assert list(importers.chesscom_games("XX", 10, sleep=lambda s: None)) == ["D", "A", "OLD1"]                  # newest first, bughouse and the unrated game left out
    assert list(importers.chesscom_games("XX", 10, sleep=lambda s: None, rated_only=False)) == ["D", "C", "A", "OLD1"]
    assert list(importers.chesscom_games("XX", 1, sleep=lambda s: None)) == ["D"]
    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp(404))
    with pytest.raises(ValueError, match="no user"):
        list(importers.chesscom_games("ghost", 5, sleep=lambda s: None))
