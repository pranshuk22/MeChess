"""Preparing against an opponent through the API: fetch (with a fake site), analyse (with a fake engine), report, plan saved as a repertoire, delete."""
import time

import chess
import pytest
from fastapi.testclient import TestClient

from chessme.app.config import AppConfig
from chessme.app.main import create_app
from tests.unit.prep_helpers import search as material_search

BASE = "http://127.0.0.1:8765"


def pgn(white, black, sans, result, i, opening="Italian Game", clocks=True):
    board = chess.Board()
    out = []
    for k, san in enumerate(sans.split()):
        mv = board.parse_san(san)
        out.append(f"{k // 2 + 1}. " * (k % 2 == 0) + san + (" { [%%clk 0:02:%02d] }" % (50 - k % 40) if clocks else ""))
        board.push(mv)
    return (f'[Event "Rated Blitz game"]\n[Site "https://lichess.org/Game{i:04d}x"]\n[White "{white}"]\n[Black "{black}"]\n[Result "{result}"]\n[UTCDate "2026.09.{1 + i % 27:02d}"]\n[UTCTime "10:00:00"]\n'
            f'[WhiteElo "{1800 if white == "Rival" else 1750}"]\n[BlackElo "{1800 if black == "Rival" else 1750}"]\n[TimeControl "180+0"]\n[Opening "{opening}"]\n\n' + " ".join(out) + f" {result}\n")


def fake_site(name, max_games, sleep=None, rated_only=True, timeout=0):
    texts = [pgn("someone", "Rival", "e4 e5 Qh5 Nc6 Bc4 Nf6 Qxf7#", "1-0", i, "Bishop's Opening") for i in range(8)]
    texts += [pgn("Rival", "other", "e4 e5 Nf3 Nc6 Bb5 a6", "1/2-1/2", 10 + i) for i in range(6)]
    texts += [pgn("Rival", "other", "e4 e5 Nf3 Nc6", "1-0", 30 + i, clocks=False) for i in range(3)]
    return iter(texts[:max_games])


@pytest.fixture()
def client(tmp_path):
    cfg = AppConfig(data_dir=tmp_path / "data", research_dir=tmp_path / "research", legacy_coach_dir=tmp_path / "coach", port=8765)
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        c.app.state.fetchers["lichess"] = fake_site
        c.app.state.prep_search_factory = lambda nodes, multipv: (material_search, lambda: None)
        yield c


def wait(client, job_id, seconds=60):
    end = time.time() + seconds
    while time.time() < end:
        j = next(j for j in client.get("/api/jobs").json() if j["id"] == job_id)
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.1)
    raise AssertionError("the job did not finish")


def test_a_preparation_downloads_analyses_and_reports_with_a_plan_and_traps(client):
    r = client.post("/api/prep", json={"handles": [{"site": "lichess", "name": "Rival"}], "depth": "quick", "max_games": 50})
    assert r.status_code == 202
    pid, job = r.json()["id"], r.json()["jobId"]
    assert wait(client, job)["status"] == "done"
    p = client.get(f"/api/prep/{pid}").json()
    assert p["status"] == "done" and p["games"] == 17 and p["downloaded"] == 17 and p["analysed"] == 17 and p["title"] == "Prepare against Rival" and p["rating"] == 1800
    rep = p["report"]
    assert rep["opponent"]["white"] == 9 and rep["opponent"]["black"] == 8 and rep["headline"] and rep["plan"]["white"]["tree"]["children"] and rep["plan"]["black"]["tree"]["children"]
    assert rep["traps"]["black"][0]["move"] == "Nf6" and rep["traps"]["black"][0]["games"] == 8
    assert {f["name"] for f in rep["openings"]["black"]["families"]} == {"Bishop's Opening"} and rep["recent"][0]["url"].startswith("https://lichess.org/")
    assert rep["made"]["depth"] == "quick" and rep["weakness"]["games"] == 0                       # quick: no whole-game analysis, and the report says so
    assert any("analysed in full" in n for n in rep["notes"])
    assert [x["id"] for x in client.get("/api/prep").json()] == [pid]
    with client.app.state.sessions() as s:                                                        # their games are kept for this preparation, never in the player's library
        from chessme.app.models import Game
        assert s.query(Game).count() == 0


def test_the_standard_depth_also_analyses_whole_games_for_the_middlegame_findings(client):
    pid = client.post("/api/prep", json={"handles": [{"site": "lichess", "name": "Rival"}], "depth": "standard"}).json()
    wait(client, pid["jobId"])
    p = client.get(f"/api/prep/{pid['id']}").json()
    assert p["status"] == "done" and p["report"]["made"]["fullGames"] == 17                       # (these games are short, but all were analysed whole)


def test_the_plan_is_saved_as_a_repertoire_and_a_preparation_can_be_refreshed_and_deleted(client):
    pid = client.post("/api/prep", json={"handles": [{"site": "lichess", "name": "Rival"}], "depth": "quick"}).json()
    wait(client, pid["jobId"])
    saved = client.post(f"/api/prep/{pid['id']}/repertoire", json={"colour": "white"}).json()
    assert client.get("/api/coach/repertoires").json()[0]["id"] == saved["id"] and "Against Rival" in saved["name"]
    assert client.post(f"/api/prep/{pid['id']}/repertoire", json={"colour": "green"}).status_code == 422
    r = client.post(f"/api/prep/{pid['id']}/refresh")
    assert r.status_code == 202 and wait(client, r.json()["jobId"])["status"] == "done"
    assert client.get(f"/api/prep/{pid['id']}").json()["downloaded"] == 17                         # nothing is stored twice
    assert client.delete(f"/api/prep/{pid['id']}").status_code == 204
    assert client.get(f"/api/prep/{pid['id']}").status_code == 404 and client.get("/api/prep").json() == []
    with client.app.state.sessions() as s:
        from chessme.app.models import PrepGame
        assert s.query(PrepGame).count() == 0


def test_bad_requests_and_empty_results_are_explained(client):
    assert client.post("/api/prep", json={"handles": []}).status_code == 422
    assert client.post("/api/prep", json={"handles": [{"site": "lichess", "name": "bad name!"}]}).status_code == 422
    assert client.post("/api/prep", json={"handles": [{"site": "elsewhere", "name": "rival"}]}).status_code == 422
    assert client.post("/api/prep", json={"handles": [{"site": "lichess", "name": "rival"}], "speeds": ["fast"]}).status_code == 422
    client.app.state.fetchers["lichess"] = lambda *a, **k: iter([])
    pid = client.post("/api/prep", json={"handles": [{"site": "lichess", "name": "Nobody"}], "depth": "quick"}).json()
    j = wait(client, pid["jobId"])
    p = client.get(f"/api/prep/{pid['id']}").json()
    assert j["status"] == "failed" and p["status"] == "failed" and "No games" in p["error"]


def test_games_can_come_from_a_pasted_pgn_and_the_speed_filter_applies(client):
    text = "\n\n".join(pgn("Rival", "other", "e4 e5 Nf3 Nc6", "1-0", i) for i in range(5)) + "\n\n" + pgn("someone", "Rival", "d4 d5 c4 e6", "0-1", 9)
    pid = client.post("/api/prep", json={"handles": [{"site": "lichess", "name": "Rival"}], "pgn": text, "depth": "quick", "speeds": ["blitz"]}).json()
    wait(client, pid["jobId"])
    assert client.get(f"/api/prep/{pid['id']}").json()["downloaded"] == 6
    only = client.post("/api/prep", json={"handles": [{"site": "lichess", "name": "Rival"}], "pgn": text, "depth": "quick", "speeds": ["rapid"]}).json()
    wait(client, only["jobId"])
    assert client.get(f"/api/prep/{only['id']}").json()["status"] == "failed"                       # blitz games filtered out: nothing left


def test_a_preparation_left_running_by_a_closed_app_is_marked_failed(tmp_path):
    cfg = AppConfig(data_dir=tmp_path / "data", research_dir=tmp_path / "r", legacy_coach_dir=tmp_path / "c", port=8765)
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        from chessme.app.models import Prep
        with c.app.state.sessions() as s:
            s.add(Prep(id="x", title="t", status="running", handles=[], params={}))
            s.commit()
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        assert c.get("/api/prep/x").json()["status"] == "failed" and "interrupted" in c.get("/api/prep/x").json()["error"]
