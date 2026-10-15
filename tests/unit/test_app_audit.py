"""Regression tests for the findings of the 2026-10-15 audit (AUDIT-2026-10-15.md): time zones, same-day order, the access key, per-site import lock, cancellable waits,
sparkline, odd data folders, games from another start position, search wildcards, one app per data folder."""
import os
import threading
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from chessme.app.config import AppConfig
from chessme.app.main import create_app
from chessme.app.services import games as G
from tests.unit.test_app_import import pgn, wait

BASE = "http://127.0.0.1:8765"
HOST = {"Host": "127.0.0.1:8765"}


def cfg_for(tmp_path, **kw):
    return AppConfig(data_dir=tmp_path / "data", research_dir=tmp_path / "research", legacy_coach_dir=tmp_path / "coach", port=8765, **kw)


@pytest.fixture()
def client(tmp_path):
    with TestClient(create_app(cfg_for(tmp_path), static=False), base_url=BASE) as c:
        yield c


# 1 ---- time zones -------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("zone", ["Asia/Kolkata", "America/New_York", "UTC"])
def test_job_times_are_utc_whatever_the_machines_time_zone(tmp_path, monkeypatch, zone):
    monkeypatch.setenv("TZ", zone)
    time.tzset()
    try:
        with TestClient(create_app(cfg_for(tmp_path), static=False), base_url=BASE) as c:
            job_id = c.app.state.jobs.submit("t", "t", lambda ctx: "ok")
            wait(c, {"id": job_id})
            j = c.app.state.jobs.get(job_id)
            for k in ("createdAt", "startedAt", "finishedAt"):
                t = datetime.fromisoformat(j[k])
                assert t.tzinfo is not None and abs((datetime.now(timezone.utc) - t).total_seconds()) < 120, (zone, k, j[k])
            assert j["createdAt"] <= j["startedAt"] <= j["finishedAt"]
    finally:
        monkeypatch.undo()
        time.tzset()


# 2 ---- same-day order ---------------------------------------------------------------------------------------------------------------------------------

def test_games_of_one_day_are_listed_newest_first_by_their_time(client):
    text = "\n".join(pgn(site=f"https://lichess.org/{n}", extra=f'[UTCDate "2026.10.14"]\n[UTCTime "{t}"]') for n, t in [("EVENING1", "20:00:00"), ("NOON0001", "12:00:00"), ("MORNING1", "09:00:00")])
    wait(client, client.post("/api/import/pgn", json={"text": text}).json())                       # inserted in the order Lichess returns them: newest first
    order = [g["id"] for g in client.get("/api/games").json()["items"]]
    assert order == ["lichess:EVENING1", "lichess:NOON0001", "lichess:MORNING1"]
    from chessme.app import analysis_job
    with client.app.state.sessions() as s:
        assert analysis_job.unanalysed_ids(s) == order                                              # and so is "newest first" for the analysis


# 3 ---- the access key ---------------------------------------------------------------------------------------------------------------------------------

def test_without_the_key_only_the_health_check_and_the_page_are_open(tmp_path):
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<html>app</html>")
    with TestClient(create_app(cfg_for(tmp_path, token="s3cret-key"), static=static), base_url=BASE) as c:
        assert c.get("/api/health").json() == {"ok": True, "auth": False}
        assert c.get("/").text == "<html>app</html>"                                                  # the page itself is not secret: it asks for the key
        for path in ("/api/games", "/api/workspace", "/api/settings", "/api/jobs", "/api/events", "/api/cache", "/api/stats"):
            assert c.get(path).status_code == 401, path
        assert c.patch("/api/settings", json={"nodes": 5000}).status_code == 401
        assert c.post("/api/session", json={"token": "wrong"}).status_code == 403 and c.get("/api/games").status_code == 401
        assert c.get("/api/games", headers={"X-MeChess-Token": "s3cret-key"}).status_code == 200      # tools and tests may send the key as a header
        assert c.get("/api/games", headers={"X-MeChess-Token": "s3cret-kez"}).status_code == 401
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/api/ws/analysis", headers=HOST) as ws:                           # a WebSocket needs the key too
                ws.receive_json()
        r = c.post("/api/session", json={"token": "s3cret-key"})
        assert r.status_code == 204 and "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
        assert c.get("/api/games").status_code == 200 and c.get("/api/health").json()["auth"] is True       # now the cookie opens everything


def test_pages_cannot_be_framed_and_may_only_load_their_own_files(tmp_path):
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<html>app</html>")
    with TestClient(create_app(cfg_for(tmp_path), static=static), base_url=BASE) as c:
        for path in ("/", "/api/health"):
            h = c.get(path).headers
            assert "frame-ancestors 'none'" in h["content-security-policy"] and "default-src 'self'" in h["content-security-policy"] and h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"


def test_the_engine_path_is_checked_when_set_and_a_plain_get_starts_nothing(client, tmp_path):
    marker = tmp_path / "ran"
    evil = tmp_path / "evil"
    evil.write_text(f"#!/bin/sh\ntouch {marker}\n")
    evil.chmod(0o755)
    assert client.patch("/api/settings", json={"engine_path": str(evil)}).status_code == 422        # it was started once, to ask, and did not answer as an engine
    marker.unlink()
    client.get("/api/workspace")
    client.get("/api/workspace")
    assert not marker.exists()


# 7 ---- imports: one at a time per site, waits can be cancelled ----------------------------------------------------------------------------------------

def test_two_imports_from_one_site_run_one_after_the_other(client):
    gate, started = threading.Event(), []

    def fetch(user, n, **kw):
        started.append(user)
        gate.wait(10)
        yield pgn(site=f"https://lichess.org/{user.upper()[:8].ljust(8, 'X')}", white=user)
    client.app.state.fetchers["lichess"] = fetch
    first = client.post("/api/import/lichess", json={"username": "alpha", "max": 5}).json()
    deadline = time.time() + 5
    while not started and time.time() < deadline:
        time.sleep(0.02)
    second = client.post("/api/import/lichess", json={"username": "bravo", "max": 5}).json()
    time.sleep(1.2)
    jobs = {j["id"]: j for j in client.get("/api/jobs").json()}
    assert started == ["alpha"] and jobs[second["id"]]["status"] == "running" and "Waiting for the other import" in jobs[second["id"]]["message"]
    gate.set()
    assert wait(client, first)["status"] == "done" and wait(client, second)["status"] == "done" and started == ["alpha", "bravo"]


def test_a_long_wait_ends_at_once_when_the_job_is_cancelled(client):
    def slow(ctx):
        ctx.sleep(60)
    job_id = client.app.state.jobs.submit("t", "waiting", slow)
    time.sleep(0.3)
    t0 = time.time()
    client.post(f"/api/jobs/{job_id}/cancel")
    assert wait(client, {"id": job_id}, timeout=5)["status"] == "cancelled" and time.time() - t0 < 3


def test_the_rated_only_choice_reaches_the_fetcher(client):
    seen = {}

    def fetch(user, n, **kw):
        seen.update(kw)
        return iter(())
    client.app.state.fetchers["lichess"] = fetch
    wait(client, client.post("/api/import/lichess", json={"username": "someone", "max": 5}).json())
    assert seen["rated_only"] is True
    wait(client, client.post("/api/import/lichess", json={"username": "someone", "max": 5, "rated_only": False}).json())
    assert seen["rated_only"] is False


# 10 ---- the sparkline covers the whole game ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("n", [1, 30, 41, 60, 79, 100, 250])
def test_the_sparkline_always_ends_with_the_last_move(n):
    moves = [{"cp": i} for i in range(n)]
    sp = G.spark(moves)
    assert sp[0] == 0 and sp[-1] == n - 1 and len(sp) <= 41 and sp == sorted(sp)


# 11 ---- odd data folders -------------------------------------------------------------------------------------------------------------------------------

def test_a_data_folder_with_a_percent_sign_works(tmp_path):
    cfg = AppConfig(data_dir=tmp_path / "my 100% data", research_dir=tmp_path / "r", legacy_coach_dir=tmp_path / "c", port=8765)
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        assert c.get("/api/games").json()["total"] == 0 and (tmp_path / "my 100% data" / "mechess.db").exists()


def test_a_second_app_on_the_same_data_folder_is_refused(tmp_path):
    with TestClient(create_app(cfg_for(tmp_path), static=False), base_url=BASE):
        with pytest.raises(RuntimeError, match="already using"):
            with TestClient(create_app(cfg_for(tmp_path), static=False), base_url=BASE):
                pass


# 16, 23 ---- games, dates, search ------------------------------------------------------------------------------------------------------------------------

def test_games_from_another_start_position_are_skipped_not_imported_broken(client):
    fen = "[Variant \"From Position\"]\n[FEN \"4k3/8/8/8/8/8/4P3/4K3 w - - 0 1\"]\n[SetUp \"1\"]"
    j = wait(client, client.post("/api/import/pgn", json={"text": pgn(site="https://lichess.org/FROMPOS1", extra=fen, moves="1. e4 Kd7 *")}).json())
    assert "0 new games" in j["message"] and "1 skipped" in j["message"] and client.get("/api/games").json()["total"] == 0


def test_a_partly_unknown_date_keeps_what_is_known(client):
    wait(client, client.post("/api/import/pgn", json={"text": pgn(site="https://lichess.org/DATEQQ01").replace("2026.06.01", "2024.??.??")}).json())
    assert client.get("/api/games/lichess:DATEQQ01").json()["date"] == "2024"


def test_a_search_for_a_percent_or_underscore_matches_only_those_characters(client):
    text = pgn(site="https://lichess.org/UNDER001", white="a_b") + "\n" + pgn(site="https://lichess.org/PLAIN001", white="ab") + "\n" + pgn(site="https://lichess.org/PCT00001", white="100%")
    wait(client, client.post("/api/import/pgn", json={"text": text}).json())
    assert [g["id"] for g in client.get("/api/games", params={"q": "_"}).json()["items"]] == ["lichess:UNDER001"]
    assert [g["id"] for g in client.get("/api/games", params={"q": "%"}).json()["items"]] == ["lichess:PCT00001"]
    assert client.get("/api/games", params={"q": "a_b"}).json()["total"] == 1 and client.get("/api/games", params={"q": "zzz"}).json()["total"] == 0
