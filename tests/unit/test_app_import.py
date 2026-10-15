"""Importing games (Lichess, Chess.com, PGN), analysing them as jobs, and the custom theme folders."""
import shutil
import time

import pytest
from fastapi.testclient import TestClient

from chessme.app import importers
from chessme.app.config import AppConfig
from chessme.app.main import create_app

BASE = "http://127.0.0.1:8765"


def pgn(site="https://lichess.org/AbCd1234", white="me", black="you", result="1-0", tc="180+0", moves="1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 1-0", extra=""):
    return (f'[Event "Rated Blitz game"]\n[Site "{site}"]\n[Date "2026.06.01"]\n[White "{white}"]\n[Black "{black}"]\n[Result "{result}"]\n[WhiteElo "1500"]\n[BlackElo "1550"]\n'
            f'[TimeControl "{tc}"]\n{extra}\n{moves}\n')


@pytest.fixture()
def client(tmp_path):
    cfg = AppConfig(data_dir=tmp_path / "data", research_dir=tmp_path / "research", legacy_coach_dir=tmp_path / "coach", port=8765)
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        yield c


def wait(client, job, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = next(j for j in client.get("/api/jobs").json() if j["id"] == job["id"])
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_a_pgn_stream_is_split_into_games():
    text = pgn(site="https://lichess.org/AAAAAAAA") + "\n" + pgn(site="https://lichess.org/BBBBBBBB") + "\n\n" + pgn(site="https://lichess.org/CCCCCCCC")
    games = list(importers.split_pgn(text.splitlines()))
    assert len(games) == 3 and all(g.startswith("[Event") for g in games) and "BBBBBBBB" in games[1]
    assert list(importers.split_pgn([])) == []


def test_keys_sources_and_the_players_side():
    assert importers.game_key({"Site": "https://lichess.org/AbCd1234"}, "x") == ("lichess:AbCd1234", "lichess")
    assert importers.game_key({"Link": "https://www.chess.com/game/live/987654"}, "x") == ("chesscom:987654", "chesscom")
    assert importers.game_key({}, "text")[1] == "pgn" and importers.game_key({}, "text") == importers.game_key({}, "text")
    assert importers.colour_for({"White": "Me", "Black": "x"}, ["me"]) == "white" and importers.colour_for({"White": "x", "Black": "ME"}, ["me"]) == "black"
    assert importers.colour_for({"White": "x", "Black": "y"}, ["me"]) is None


def test_importing_a_pgn_adds_games_once_and_knows_your_side(client):
    text = pgn(site="https://lichess.org/AAAAAAAA") + "\n" + pgn(site="https://lichess.org/BBBBBBBB", white="other", black="me", result="0-1", moves="1. d4 d5 2. c4 e6 0-1") + "\n" + pgn(extra="", moves="*", site="https://lichess.org/EMPTY000")
    job = wait(client, client.post("/api/import/pgn", json={"text": text, "player": "me"}).json())
    assert job["status"] == "done" and "2 new games" in job["message"] and "1 skipped" in job["message"]
    page = client.get("/api/games").json()
    assert page["total"] == 2
    a = client.get("/api/games/lichess:AAAAAAAA").json()
    assert a["user"] == "white" and a["speed"] == "blitz" and a["plies"] == 10 and not a["analysed"] and a["opening"] is None and "Bb5" in a["pgn"]
    assert client.get("/api/games/lichess:BBBBBBBB").json()["user"] == "black"
    again = wait(client, client.post("/api/import/pgn", json={"text": text, "player": "me"}).json())
    assert "0 new games" in again["message"] and "2 already" in again["message"] and client.get("/api/games").json()["total"] == 2


def test_importing_from_lichess_and_chesscom_uses_the_fetchers_and_remembers_the_names(client):
    calls = []

    def fake(platform):
        def f(user, n):
            calls.append((platform, user, n))
            yield pgn(site=f"https://lichess.org/{platform[:1].upper() * 8}", white=user, black="opp")
        return f
    client.app.state.fetchers = {"lichess": fake("lichess"), "chesscom": fake("chesscom")}
    j = wait(client, client.post("/api/import/lichess", json={"username": "Magnus_C", "max": 50}).json())
    assert j["status"] == "done" and calls == [("lichess", "Magnus_C", 50)] and "1 new games" in j["message"]
    assert client.get("/api/accounts").json() == {"lichess": "Magnus_C", "chesscom": None}
    assert client.get("/api/games/lichess:LLLLLLLL").json()["user"] == "white"
    assert client.post("/api/import/chesscom", json={"username": "bad name!", "max": 5}).status_code == 422
    assert client.post("/api/import/lichess", json={"username": "ok_name", "max": 0}).status_code == 422
    assert client.put("/api/accounts", json={"lichess": "a", "chesscom": None}).status_code == 422
    assert client.put("/api/accounts", json={"lichess": "someone", "chesscom": "other"}).json()["chesscom"] == "other"


def test_a_sync_stops_after_a_run_of_known_games(client):
    def stream(user, n):
        for i in range(100):
            yield pgn(site=f"https://lichess.org/{i:08d}", white=user)
    client.app.state.fetchers = {"lichess": stream, "chesscom": stream}
    first = wait(client, client.post("/api/import/lichess", json={"username": "someone", "max": 100, "only_new": False}).json())
    assert "100 new games" in first["message"]
    seen = []

    def longer(user, n):
        for i in range(300):
            seen.append(i)
            yield pgn(site=f"https://lichess.org/{i:08d}", white=user)
    client.app.state.fetchers["lichess"] = longer
    second = wait(client, client.post("/api/import/lichess", json={"username": "someone", "max": 300}).json())
    assert "0 new games" in second["message"] and len(seen) <= 40                                     # stopped after 30 known games in a row


def test_a_failing_fetch_is_a_failed_job_with_the_reason(client):
    def broken(user, n):
        raise ValueError("Lichess has no user nobody")
        yield
    client.app.state.fetchers["lichess"] = broken
    j = wait(client, client.post("/api/import/lichess", json={"username": "nobody", "max": 5}).json())
    assert j["status"] == "failed" and "no user nobody" in j["message"]


class FakeEngine:
    name = "Fake 1"

    def __init__(self):
        self.closed = False

    def new_game(self):
        pass

    def close(self):
        self.closed = True

    def go(self, fen, moves=(), *, nodes=None, depth=None, movetime=None, timeout=60):
        from chessme.uci_client import GoResult, Line
        import chess
        b = chess.Board(fen)
        for m in moves:
            b.push_uci(m)
        mv = next(iter(b.legal_moves)).uci()
        return GoResult(bestmove=mv, score_kind="cp", score=20, depth=1, nodes=1, pv=[mv], lines=[Line(move=mv, score_kind="cp", score=20, depth=1, pv=[mv])])

    def _send(self, line):
        pass

    def ready(self, timeout=None):
        pass


def test_analysing_games_is_a_job_that_stores_the_analysis(client):
    wait(client, client.post("/api/import/pgn", json={"text": pgn(site="https://lichess.org/AAAAAAAA") + "\n" + pgn(site="https://lichess.org/BBBBBBBB"), "player": "me"}).json())
    engine = FakeEngine()
    client.app.state.engine_factory = lambda settings: (lambda: engine)
    job = wait(client, client.post("/api/analyse", json={"limit": 1}).json())
    assert job["status"] == "done" and "1 games analysed" in job["message"] and engine.closed
    games = client.get("/api/games").json()["items"]
    assert sum(g["analysed"] for g in games) == 1
    client.app.state.engine_factory = lambda settings: (lambda: FakeEngine())
    wait(client, client.post("/api/analyse", json={}).json())
    assert all(g["analysed"] for g in client.get("/api/games").json()["items"])
    d = client.get("/api/games/lichess:AAAAAAAA").json()
    assert len(d["moves"]) == 10 and d["moves"][0]["san"] == "e4" and d["accuracy"]["white"] is not None
    assert client.post("/api/analyse", json={}).status_code == 409                                  # nothing left to do


@pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish")
def test_analysing_with_the_real_engine(client):
    wait(client, client.post("/api/import/pgn", json={"text": pgn(site="https://lichess.org/AAAAAAAA", moves="1. f3 e5 2. g4 Qh4# 0-1", result="0-1")}).json())
    client.patch("/api/settings", json={"nodes": 2000, "multipv": 2})
    job = wait(client, client.post("/api/analyse", json={}).json(), timeout=60)
    assert job["status"] == "done", job
    d = client.get("/api/games/lichess:AAAAAAAA").json()
    assert [m["san"] for m in d["moves"]] == ["f3", "e5", "g4", "Qh4#"] and d["moves"][2]["cls"] in ("mistake", "blunder", "miss", "inaccuracy") and d["moves"][3]["cp"] < -500


def test_without_an_engine_the_job_fails_with_a_clear_message(client, monkeypatch):
    from chessme.app import workspace
    monkeypatch.setattr(workspace.shutil, "which", lambda name: None)
    wait(client, client.post("/api/import/pgn", json={"text": pgn()}).json())
    j = wait(client, client.post("/api/analyse", json={}).json())
    assert j["status"] == "failed" and "Stockfish was not found" in j["message"]


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="45" height="45"><circle cx="22" cy="22" r="10"/></svg>'


def test_custom_piece_sets_and_boards_are_listed_served_and_validated(client):
    assert client.get("/api/themes").json()["pieces"] == []
    for name in [c + p for c in "wb" for p in "KQRBNP"]:
        assert client.put(f"/api/themes/pieces/My Set/{name}.svg", content=SVG).status_code == 204
    t = client.get("/api/themes").json()
    assert [p["id"] for p in t["pieces"]] == ["My Set"] and t["pieces"][0]["files"]["wK"] == "/api/themes/pieces/My Set/wK.svg"
    r = client.get(t["pieces"][0]["files"]["wK"])
    assert r.content == SVG and r.headers["content-type"] == "image/svg+xml" and "default-src 'none'" in r.headers["content-security-policy"]
    client.put("/api/themes/pieces/Half/wK.svg", content=SVG)
    assert [p["id"] for p in client.get("/api/themes").json()["pieces"]] == ["My Set"]                    # an incomplete set is not offered
    assert client.put("/api/themes/pieces/My Set/wK.svg", content=b"<svg onload=alert(1)></svg>").status_code == 422
    assert client.put("/api/themes/pieces/My Set/wK.svg", content=b"<svg><script>x</script></svg>").status_code == 422
    assert client.put("/api/themes/pieces/My Set/wK.svg", content=b'<svg><image href="https://evil.example/x.png"/></svg>').status_code == 422
    assert client.put("/api/themes/pieces/My Set/zz.svg", content=SVG).status_code == 422
    assert client.put("/api/themes/pieces/..%2Fx/wK.svg", content=SVG).status_code in (404, 422)
    assert client.put("/api/themes/pieces/My Set/wK.png", content=b"not a png").status_code == 422
    assert client.put("/api/themes/pieces/My Set/wK.png", content=b"\x89PNG\r\n\x1a\n" + b"0" * 20).status_code == 204
    assert client.get("/api/themes/pieces/My Set/wK.svg").status_code == 404                              # the png replaced the svg
    assert client.put("/api/themes/boards/wood.svg", content=SVG).status_code == 204
    assert client.put("/api/themes/boards/big.png", content=b"\x89PNG\r\n\x1a\n" + b"0" * 3_100_000).status_code == 413
    assert [b["id"] for b in client.get("/api/themes").json()["boards"]] == ["wood"]
    assert client.get("/api/themes/boards/wood.svg").content == SVG
    assert client.delete("/api/themes/boards/wood.svg").status_code == 204 and client.get("/api/themes/boards/wood.svg").status_code == 404
    assert client.delete("/api/themes/pieces/Half").status_code == 204 and client.delete("/api/themes/pieces/Nope").status_code == 404
