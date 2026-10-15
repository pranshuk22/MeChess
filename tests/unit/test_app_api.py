"""The web app backend: database, games API, workspace scan, legacy import, jobs, and the local-only guard."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from chessme.app.config import AppConfig
from chessme.app.main import create_app
from chessme.app.services import games as G

BASE = "http://127.0.0.1:8765"


def analysed_move(ply, san, uci, color, loss=0.0, cls="best", best=None, cp=20):
    sign = 1 if color == "white" else -1
    return {"top": [{"uci": best or uci, "cp": 33, "pv": [best or uci, "e7e5"]}, {"uci": "a2a3", "cp": -10, "pv": ["a2a3"]}],"ply": ply, "move": san, "uci": uci, "color": color, "class": cls, "loss": loss, "best_move": best or uci, "best_cp": cp, "played_cp": cp,
            "win_before": 0.5, "win_after": 0.5 - loss, "accuracy": 90.0, "phase": "opening"}


def game_moves():
    return [analysed_move(1, "e4", "e2e4", "white"), analysed_move(2, "e5", "e7e5", "black"),
            analysed_move(3, "Qh5", "d1h5", "white", loss=0.2, cls="mistake", best="g1f3", cp=-80), analysed_move(4, "Nc6", "b8c6", "black", cp=-60)]


@pytest.fixture()
def cfg(tmp_path):
    return AppConfig(data_dir=tmp_path / "data", research_dir=tmp_path / "research", legacy_coach_dir=tmp_path / "coach", port=8765)


@pytest.fixture()
def client(cfg):
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        yield c


def seed(client, n=3):
    s = client.app.state.sessions()
    for i in range(n):
        G.store(s, id=f"t:{i}", source="test", headers={"White": "Me", "Black": f"Opp{i}", "Result": ["1-0", "0-1", "1/2-1/2"][i % 3], "WhiteElo": "1500", "BlackElo": "1600",
                                                       "TimeControl": "180+0", "Date": f"2026.0{i + 1}.10", "Opening": "Italian Game"},
                user_colour="white", analysis={"moves": game_moves()}, nodes=1000, multipv=2)
    s.commit()
    s.close()


def test_the_database_is_created_and_migrated_on_start(client, cfg):
    assert cfg.db_path.exists()
    assert client.get("/api/health").json() == {"ok": True, "auth": True}
    assert client.get("/api/games").json() == {"total": 0, "items": []}


def test_games_list_detail_filters_and_delete(client):
    seed(client)
    page = client.get("/api/games").json()
    assert page["total"] == 3 and [g["id"] for g in page["items"]] == ["t:2", "t:1", "t:0"]            # newest date first
    g = page["items"][-1]
    assert g["analysed"] and g["user"] == "white" and g["mistakes"] == 1 and g["speed"] == "blitz" and g["date"] == "2026-01-10" and g["spark"]
    assert client.get("/api/games", params={"result": "win"}).json()["total"] == 1
    assert client.get("/api/games", params={"result": "loss"}).json()["total"] == 1
    assert client.get("/api/games", params={"result": "draw"}).json()["total"] == 1
    assert client.get("/api/games", params={"q": "opp1"}).json()["total"] == 1
    assert client.get("/api/games", params={"q": "italian"}).json()["total"] == 3
    assert client.get("/api/games", params={"colour": "black"}).json()["total"] == 0
    assert client.get("/api/games", params={"analysed": "false"}).json()["total"] == 0
    assert len(client.get("/api/games", params={"limit": 2, "offset": 2}).json()["items"]) == 1
    d = client.get("/api/games/t:0").json()
    assert len(d["moves"]) == 4 and d["moves"][2]["cls"] == "mistake" and d["moves"][2]["best"] == "g1f3" and d["moves"][2]["cp"] == -80 and d["pgn"].count("e4") >= 1
    assert d["moves"][0]["acc"] == 90.0 and d["moves"][0]["phase"] == "opening"
    assert d["moves"][0]["lines"][0] == {"uci": "e2e4", "cp": 33, "pv": ["e2e4", "e7e5"]} and d["moves"][1]["lines"][0]["cp"] == -33        # lines are shown from white's point of view
    assert d["moves"][3]["cp"] == 60                                                                    # black's -60 is +60 for white
    assert client.delete("/api/games/t:0").status_code == 204 and client.get("/api/games/t:0").status_code == 404
    assert client.delete("/api/games/t:0").status_code == 404


def test_a_game_without_analysis_is_listed_as_not_analysed(client):
    s = client.app.state.sessions()
    G.store(s, id="p:1", source="pgn", headers={"White": "A", "Black": "B", "Result": "1-0"}, user_colour=None, uci_moves=["e2e4", "e7e5"])
    s.commit()
    s.close()
    g = client.get("/api/games/p:1").json()
    assert not g["analysed"] and g["moves"] == [] and g["accuracy"] is None and g["mistakes"] is None and g["plies"] == 2
    assert client.get("/api/games", params={"analysed": "false"}).json()["total"] == 1


def test_storing_the_same_game_twice_keeps_one(client):
    seed(client, 1)
    seed(client, 1)
    assert client.get("/api/games").json()["total"] == 1


def test_settings_defaults_patch_and_validation(client, tmp_path):
    assert client.get("/api/settings").json()["nodes"] == 100_000
    assert client.patch("/api/settings", json={"nodes": 50_000, "multipv": 3}).json()["nodes"] == 50_000
    assert client.get("/api/settings").json()["multipv"] == 3
    assert client.patch("/api/settings", json={"nodes": 5}).status_code == 422                           # below the allowed range
    assert client.patch("/api/settings", json={"engine_path": str(tmp_path / "nope")}).status_code == 422
    fake = tmp_path / "engine"
    fake.write_text("#!/bin/sh\necho 'id name Fake Engine 1'\necho uciok\n")
    fake.chmod(0o755)
    assert client.patch("/api/settings", json={"engine_path": str(fake)}).json()["engine_path"] == str(fake)
    notengine = tmp_path / "notengine"
    notengine.write_text("#!/bin/sh\necho hello\n")
    notengine.chmod(0o755)
    assert client.patch("/api/settings", json={"engine_path": str(notengine)}).status_code == 422                 # an executable that is not a UCI engine is refused when it is set
    assert next(c for c in client.get("/api/workspace").json()["checks"] if c["id"] == "engine")["detail"] == "Fake Engine 1"
    assert client.get("/api/settings").json()["nodes"] == 50_000                                         # earlier values survive


def check(ws, cid):
    return next(c for c in ws["checks"] if c["id"] == cid)


def test_the_workspace_scan_says_what_is_there_and_what_is_next(client, cfg):
    ws = client.get("/api/workspace").json()
    assert check(ws, "games")["state"] == "todo" and check(ws, "explorer")["state"] == "optional" and ws["data_dir"] == str(cfg.data_dir)
    assert ws["next_step"] in ("set-engine", "import")
    seed(client, 2)
    client.app.state.sessions().close()
    ws = client.get("/api/workspace").json()
    assert check(ws, "games")["state"] == "ok" and "2 games" in check(ws, "games")["detail"] and check(ws, "analysed")["state"] == "ok"
    (cfg.research_dir / "explorer").mkdir(parents=True)
    (cfg.research_dir / "explorer" / "explorer.db").write_bytes(b"x")
    assert check(client.get("/api/workspace").json(), "explorer")["state"] == "ok"


def wait_job(client, job_id, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = next(j for j in client.get("/api/jobs").json() if j["id"] == job_id)
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError("the job did not finish")


def write_legacy(cfg):
    coach = cfg.legacy_coach_dir / "games"
    coach.mkdir(parents=True)
    (coach / "abc.json").write_text(json.dumps({"color": "white", "moves": game_moves(), "rating": 1450, "speed": "blitz"}))
    (coach / "bad.json").write_text("{not json")
    an = cfg.research_dir / "analysis" / "personal" / "games"
    an.mkdir(parents=True)
    (an / "g1.json").write_text(json.dumps({"moves": game_moves(), "player_color": "black", "summary": None, "headers": {"White": "X", "Black": "Y", "Result": "0-1", "Site": "https://lichess.org/Zz9Yy8Xx", "TimeControl": "300+0", "UTCDate": "2026.05.01", "Opening": "Scotch"}}))


def test_earlier_work_is_found_and_imported_once(client, cfg):
    write_legacy(cfg)
    ws = client.get("/api/workspace").json()
    assert check(ws, "legacy")["action"] == "import-legacy" and "3 analysed games" in check(ws, "legacy")["detail"] and ws["next_step"] in ("set-engine", "import-legacy")
    job = client.post("/api/workspace/import-legacy").json()
    done = wait_job(client, job["id"])
    assert done["status"] == "done" and "2 games added" in done["message"] and "1 files could not be read" in done["message"]
    page = client.get("/api/games").json()
    assert page["total"] == 2
    lich = client.get("/api/games/lichess:Zz9Yy8Xx").json()
    assert lich["source"] == "lichess" and lich["user"] == "black" and lich["white"] == "X" and lich["date"] == "2026-05-01" and lich["speed"] == "blitz" and lich["accuracy"]
    coach = client.get("/api/games/coach:abc").json()
    assert coach["user"] == "white" and coach["whiteElo"] == 1450 and coach["white"] == "You" and coach["speed"] == "blitz"
    assert "legacy" not in [c["id"] for c in client.get("/api/workspace").json()["checks"] if c["state"] == "todo"]            # not offered again
    again = wait_job(client, client.post("/api/workspace/import-legacy").json()["id"])
    assert "0 games added" in again["message"] and client.get("/api/games").json()["total"] == 2


def test_a_failing_job_is_reported_and_a_running_one_can_be_cancelled(client):
    jobs = client.app.state.jobs
    bad = jobs.submit("test", "boom", lambda ctx: 1 / 0)
    j = wait_job(client, bad)
    assert j["status"] == "failed" and "ZeroDivisionError" in j["message"]

    def slow(ctx):
        for i in range(400):
            time.sleep(0.01)
            ctx.progress(i / 400, f"step {i}")
    slow_id = jobs.submit("test", "slow", slow)
    time.sleep(0.15)
    assert client.post(f"/api/jobs/{slow_id}/cancel").status_code == 202
    assert wait_job(client, slow_id)["status"] == "cancelled"
    assert client.post("/api/jobs/nope/cancel").status_code == 404
    ok = jobs.submit("test", "fine", lambda ctx: "all good")
    j = wait_job(client, ok)
    assert j["status"] == "done" and j["message"] == "all good" and j["progress"] == 1.0


def test_jobs_left_running_by_a_stopped_app_are_marked_failed(cfg):
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        from chessme.app.models import Job
        s = c.app.state.sessions()
        s.add(Job(id="old", kind="x", title="old", status="running"))
        s.commit()
        s.close()
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        j = next(j for j in c.get("/api/jobs").json() if j["id"] == "old")
        assert j["status"] == "failed" and "interrupted" in j["message"]


def test_other_hosts_and_other_origins_are_refused(cfg):
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        assert c.get("/api/health", headers={"Host": "evil.example:8765"}).status_code == 403            # DNS rebinding
        assert c.get("/api/health", headers={"Host": "localhost:8765"}).status_code == 200
        assert c.post("/api/workspace/import-legacy", headers={"Origin": "https://evil.example"}).status_code == 403
        assert c.patch("/api/settings", json={"nodes": 2000}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert c.patch("/api/settings", json={"nodes": 2000}, headers={"Origin": BASE}).status_code == 200
        assert c.get("/api/health", headers={"Origin": "https://evil.example"}).status_code == 200      # reading is not a change; the Host check is the guard there


def test_the_built_frontend_is_served_with_a_fallback_and_never_outside_its_folder(cfg, tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>app</html>")
    (root / "assets" / "a.js").write_text("1")
    (tmp_path / "secret.txt").write_text("secret")
    with TestClient(create_app(cfg, static=root), base_url=BASE) as c:
        assert c.get("/").text == "<html>app</html>" and c.get("/review/abc").text == "<html>app</html>"        # client-side routes
        r = c.get("/assets/a.js")
        assert r.text == "1" and "immutable" in r.headers["cache-control"]
        assert c.get("/../secret.txt").text == "<html>app</html>" and c.get("/%2e%2e/secret.txt").text == "<html>app</html>"
        assert c.get("/api/nope").status_code == 404 and c.get("/api/health").json()["ok"]


def test_the_openapi_schema_describes_the_contract(client):
    spec = client.get("/api/openapi.json").json()
    assert {"/api/games", "/api/games/{game_id}", "/api/workspace", "/api/jobs", "/api/settings", "/api/events"} <= set(spec["paths"])
    assert {"GameSummary", "GameDetail", "Workspace", "JobOut", "Settings"} <= set(spec["components"]["schemas"])


def test_stats_summarise_the_players_own_games(client):
    s = client.app.state.sessions()
    for i, (res, colour, opening) in enumerate([("1-0", "white", "Italian Game: Giuoco Piano"), ("0-1", "white", "Italian Game"), ("1/2-1/2", "black", "Sicilian Defense"), ("0-1", "black", "Sicilian Defense: Najdorf")]):
        G.store(s, id=f"s:{i}", source="test", headers={"White": "a", "Black": "b", "Result": res, "Date": f"2026.0{i + 1}.01", "Opening": opening}, user_colour=colour, analysis={"moves": game_moves()}, nodes=1, multipv=1)
    G.store(s, id="s:x", source="test", headers={"White": "a", "Black": "b", "Result": "1-0"}, user_colour=None, uci_moves=["e2e4"])
    s.commit()
    s.close()
    st = client.get("/api/stats").json()
    assert st["games"] == 5 and st["analysed"] == 4 and st["results"] == {"win": 2, "draw": 1, "loss": 1}
    assert st["accuracy"]["recent"] == 90.0 and st["accuracy"]["previous"] is None and len(st["accuracy"]["series"]) == 4
    assert st["mistakesPerGame"]["recent"] == 0.5                                                      # one mistake by white in two games with white... black has none
    assert {o["name"]: o["games"] for o in st["openings"]} == {"Italian Game": 2, "Sicilian Defense": 2}
    assert [o for o in st["openings"] if o["name"] == "Italian Game"][0]["score"] == 0.5


def test_the_generated_typescript_types_are_up_to_date():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import gen_ts_types
    assert (Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "schema.ts").read_text() == gen_ts_types.build(), "run: PYTHONPATH=. python tools/gen_ts_types.py frontend/src/api/schema.ts"


def test_insights_cover_calendar_phases_kinds_rating_colours_and_speeds(client):
    from datetime import date, timedelta
    s = client.app.state.sessions()
    today = date.today()
    for i in range(6):
        d = (today - timedelta(days=i % 3)).strftime("%Y.%m.%d")
        G.store(s, id=f"i:{i}", source="test", headers={"White": "a", "Black": "b", "Result": ["1-0", "0-1"][i % 2], "Date": d, "WhiteElo": str(1500 + 10 * i), "BlackElo": "1600", "TimeControl": ["180+0", "600+0"][i % 2]},
                user_colour="white" if i < 4 else "black", analysis={"moves": game_moves()}, nodes=1, multipv=1)
    s.commit()
    s.close()
    st = client.get("/api/stats").json()
    assert sum(d["games"] for d in st["perDay"]) == 6 and len(st["perDay"]) == 3 and st["perDay"][0]["date"] < st["perDay"][-1]["date"]
    assert st["phaseAccuracy"]["opening"] == 90.0 and st["phaseAccuracy"]["endgame"] is None
    assert st["classCounts"]["mistake"] == 4 and st["classCounts"]["best"] >= 4                                      # the four games the player was white in: one mistake each
    assert [r["rating"] for r in st["ratingSeries"]][-1] in (1500, 1510, 1520, 1530, 1540, 1550) and len(st["ratingSeries"]) == 6
    assert {c["name"] for c in st["colours"]} == {"white", "black"} and {c["name"] for c in st["speeds"]} == {"blitz", "rapid"}
    assert all(0 <= c["score"] <= 1 for c in st["colours"] + st["speeds"])
