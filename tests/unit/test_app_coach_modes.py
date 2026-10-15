"""Opening practice with saved repertoires, endgames with a (fake) tablebase, and steered games that end up in the library with their mistakes as practice positions."""
import chess
import pytest
from fastapi.testclient import TestClient

from chessme.app.config import AppConfig
from chessme.app.main import create_app
from tests.unit.test_coach_endgames import KQK, FakeTB
from tests.unit.test_coach_openings import REP, explorer
from tests.unit.test_coach_steering import _fake_game_search

BASE = "http://127.0.0.1:8765"


@pytest.fixture()
def client(tmp_path):
    cfg = AppConfig(data_dir=tmp_path / "data", research_dir=tmp_path / "research", legacy_coach_dir=tmp_path / "coach", port=8765)
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        yield c


def with_explorer(client, monkeypatch):
    """A database file that exists, and replies from the fake explorer of the opening tests."""
    from chessme.book import explorer as E
    from chessme.coach import openings as O
    client.app.state.config.explorer_path.write_bytes(b"x") if hasattr(client.app.state.config.explorer_path, "write_bytes") else None
    replies = explorer()
    monkeypatch.setattr(E, "query_position", lambda path, fen, rating=None, band=None: {"moves": [{"uci": u, "share": s} for u, s in replies(fen)]})
    monkeypatch.setattr(O, "explorer_replies", lambda path, rating: replies)


def test_the_status_says_which_modes_have_their_data(client, tmp_path):
    assert client.get("/api/coach/status").json() == {"explorer": False, "tablebase": False}
    (tmp_path / "data" / "explorer.db").write_bytes(b"x")
    client.app.state.modes._app = None
    assert client.get("/api/coach/status").json()["explorer"] is True


def test_repertoires_are_saved_listed_practised_covered_and_deleted(client, monkeypatch, tmp_path):
    (tmp_path / "data" / "explorer.db").write_bytes(b"x")
    with_explorer(client, monkeypatch)
    assert client.get("/api/coach/repertoires").json() == []
    assert client.post("/api/coach/repertoires", json={"name": "x", "colour": "green", "pgn": REP}).status_code == 422
    assert client.post("/api/coach/repertoires", json={"name": "x", "colour": "black", "pgn": "1. e4 *"}).status_code == 422            # no black move in it
    rid = client.post("/api/coach/repertoires", json={"name": "Ruy Lopez", "colour": "white", "pgn": REP}).json()["id"]
    assert client.post("/api/coach/repertoires", json={"name": "Ruy Lopez", "colour": "white", "pgn": REP}).json()["id"] == rid         # the same one twice is stored once
    assert [r["name"] for r in client.get("/api/coach/repertoires").json()] == ["Ruy Lopez"]
    s = client.post(f"/api/coach/repertoires/{rid}/start", params={"rating": 1600}).json()
    assert s["moves"] == 5 and s["view"]["color"] == "white" and "e2e4" in s["view"]["legal"]
    bad = client.post(f"/api/coach/openings/{s['session']}/move", json={"uci": "d2d4"}).json()
    assert bad["verdict"] == "not in your repertoire" and bad["expected"] == ["e4"]
    ok = client.post(f"/api/coach/openings/{s['session']}/move", json={"uci": "e2e4"}).json()
    assert ok["verdict"] == "ok" and len(ok["view"]["line"]) == 2
    assert client.post("/api/coach/openings/nope/move", json={"uci": "e2e4"}).status_code == 404
    cov = client.get(f"/api/coach/repertoires/{rid}/coverage").json()
    assert 0 <= cov["covered"] <= 1 and isinstance(cov["gaps"], list)
    assert client.post("/api/coach/openings/coverage", json={"pgn": REP, "colour": "white"}).json()["covered"] == cov["covered"]
    assert client.delete(f"/api/coach/repertoires/{rid}").status_code == 204 and client.delete(f"/api/coach/repertoires/{rid}").status_code == 404
    assert client.post("/api/coach/repertoires/zzz/start").status_code == 404


def test_opening_practice_says_when_the_explorer_is_missing(client):
    r = client.post("/api/coach/openings/start", json={"pgn": REP, "colour": "white"})
    assert r.status_code == 422 and "explorer" in r.json()["detail"]


def test_endgames_list_their_themes_and_a_drill_judges_moves_with_the_tablebase(client):
    client.app.state.modes.tablebase_override = FakeTB()
    themes = client.get("/api/coach/endgames").json()["themes"]
    assert {t["id"] for t in themes} >= {"kpk-win", "krk", "kqk"}
    s = client.post("/api/coach/endgames/start", json={"theme": "kqk"}).json()
    assert s["view"]["goal"] and s["view"]["legal"] and s["view"]["color"] in ("white", "black")
    hint = client.post(f"/api/coach/endgames/{s['session']}/hint", json={"level": 3}).json()["hint"]
    assert hint.startswith("The move is ")
    first = client.post(f"/api/coach/endgames/{s['session']}/move", json={"uci": s["view"]["legal"][0]}).json()
    assert first["verdict"] in ("ok", "throws it away") or first.get("view")
    assert client.post("/api/coach/endgames/start", json={"theme": "nope"}).status_code == 422
    assert client.post("/api/coach/endgames/zzz/move", json={"uci": "a1a2"}).status_code == 404


def test_endgames_without_tablebase_files_explain_what_is_missing(client):
    r = client.post("/api/coach/endgames/start", json={"theme": "kqk"})
    assert r.status_code == 422 and "tablebase" in r.json()["detail"]


def test_a_steered_game_is_played_finished_saved_and_its_mistakes_become_practice(client):
    from chessme.analysis.runner import SimpleLine
    search = _fake_game_search()
    client.app.state.quick.searcher = lambda path: search
    foci = client.get("/api/coach/steer/foci").json()["foci"]
    assert {f["id"] for f in foci} == {"threats", "trades", "convert", "defend", "sharp"} and all(f["tip"] for f in foci)
    assert client.post("/api/coach/steer/start", json={"colour": "white", "foci": {}}).status_code == 422
    assert client.post("/api/coach/steer/start", json={"colour": "white", "foci": {"fly": 1}}).status_code == 422
    s = client.post("/api/coach/steer/start", json={"colour": "white", "foci": {"threats": 1, "trades": 1}}).json()
    for _ in range(4):
        legal = client.app.state.modes._app.steered[s["session"]].view()["legal"]
        r = client.post(f"/api/coach/steer/{s['session']}/move", json={"uci": legal[0]}).json()
        assert r["view"]["plies"] >= 2
    done = client.post(f"/api/coach/steer/{s['session']}/finish").json()
    assert done["gameId"].startswith("steer:") and set(done["focus"]) == {"threats", "trades"} and len(done["focus_lines"]) == 2
    g = client.get(f"/api/games/{done['gameId']}").json()
    assert g["source"] == "steer" and g["user"] == "white" and g["analysed"] and g["plies"] >= 8
    assert client.get("/api/coach/drills").json()["total"] == done["drillsAdded"]
    assert client.post(f"/api/coach/steer/{s['session']}/finish").status_code in (200, 422)               # finishing twice does not crash
    assert client.post("/api/coach/steer/nope/finish").status_code == 404 and client.post("/api/coach/steer/nope/move", json={"uci": "e2e4"}).status_code == 404
