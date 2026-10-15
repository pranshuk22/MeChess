"""The opening evaluation cache: service, search wrapper, analysis and build jobs, API, and live analysis."""
import time

import chess
import pytest
from fastapi.testclient import TestClient

from chessme.analysis.runner import SimpleLine
from chessme.app.config import AppConfig
from chessme.app.main import create_app
from chessme.app.models import PositionEval
from chessme.app.services import cache as CA
from tests.unit.test_app_import import FakeEngine, pgn, wait
from tests.unit.test_app_live import FAKE, HOST, START  # noqa: F401

BASE = "http://127.0.0.1:8765"
AFTER_E4_E5 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
DEEP = "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P1B2/2PBPN2/PP1N1PPP/R2QK2R w KQ - 0 10"        # white to move on move 10 (ply 18)
LAST = "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P1B2/2PBPN2/PP1N1PPP/R2QK2R w KQ - 0 11"                      # white to move on move 11 (ply 20): the last position kept
TOO_DEEP = "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P1B2/2PBPN2/PP1N1PPP/R2QK2R w KQ - 0 12"                   # ply 22


@pytest.fixture()
def client(tmp_path):
    cfg = AppConfig(data_dir=tmp_path / "data", research_dir=tmp_path / "research", legacy_coach_dir=tmp_path / "coach", port=8765)
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        yield c


def test_positions_are_keyed_without_move_counters_and_only_the_first_ten_moves_count():
    assert CA.norm(START + " ") == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    assert CA.norm("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 5 9") == CA.norm(START)
    assert CA.ply_of(START) == 0 and CA.ply_of(AFTER_E4_E5) == 2 and CA.ply_of(DEEP) == 18 and CA.ply_of(LAST) == 20 and CA.ply_of(TOO_DEEP) == 22
    assert CA.eligible(DEEP) and CA.eligible(LAST) and not CA.eligible(TOO_DEEP) and not CA.eligible("8/8/8/8/8/8/8/K6k w - - 0 12")
    assert CA.ply_of("8/8/8/8/8/8/8/K6k b - - 0 11") == 21


def test_lines_round_trip_between_the_movers_and_whites_point_of_view():
    lines = [SimpleLine("e7e5", 25, ["e7e5", "g1f3"]), SimpleLine("c7c5", 10, ["c7c5"])]
    stored = CA.to_stored(False, lines)                                                              # black to move: +25 for black is -25 for white
    assert stored[0] == {"uci": "e7e5", "cp": -25, "pv": ["e7e5", "g1f3"]}
    back = CA.from_stored(False, stored)
    assert (back[0].move, back[0].cp, back[0].pv) == ("e7e5", 25, ["e7e5", "g1f3"])
    assert CA.from_stored(True, stored)[0].cp == -25


def test_get_put_improve_stats_and_clear(client):
    s = client.app.state.sessions()
    lines = [{"uci": "e2e4", "cp": 30, "pv": ["e2e4", "e7e5"]}]
    assert CA.put(s, START, lines, nodes=1000, multipv=1, depth=10, engine="Fake", source="analysis")
    assert not CA.put(s, START, lines, nodes=1000, multipv=1, depth=10, source="live")                 # not better: kept as it was
    assert CA.get(s, START, min_nodes=5000) is None and CA.get(s, START, min_multipv=2) is None        # a weaker search than asked for is not used
    row = CA.get(s, START, min_nodes=1000)
    assert row.hits == 1 and row.source == "analysis"
    assert CA.put(s, START, lines, nodes=50_000, multipv=3, depth=20, source="build") and CA.get(s, START).source == "build"
    assert not CA.put(s, TOO_DEEP, lines, nodes=1, multipv=1, source="live") and not CA.put(s, START, [], nodes=1, multipv=1, source="live")
    CA.put(s, AFTER_E4_E5, lines, nodes=1, multipv=1, source="live")
    s.commit()
    st = CA.stats(s)
    assert st["positions"] == 2 and st["hits"] >= 2 and st["bySource"] == {"build": 1, "live": 1} and st["maxMoves"] == 10
    assert {m["move"]: m["positions"] for m in st["byMove"]}[0] == 1 and sum(m["positions"] for m in st["byMove"]) == 2
    assert CA.clear(s, "live") == 1 and CA.stats(s)["positions"] == 1 and CA.clear(s) == 1 and CA.stats(s)["positions"] == 0
    s.close()


class Counting:
    def __init__(self):
        self.calls = []

    def __call__(self, board):
        self.calls.append(board.fen())
        if not any(board.legal_moves):
            return []
        mv = next(iter(board.legal_moves)).uci()
        return [SimpleLine(mv, 40, [mv])]


def test_the_search_wrapper_looks_up_opening_positions_and_stores_new_ones(client):
    inner = Counting()
    wrapped = CA.CachedSearch(inner, client.app.state.sessions, nodes=1000, multipv=1, engine="Fake")
    b = chess.Board()
    first = wrapped(b)
    second = wrapped(b)
    assert len(inner.calls) == 1 and wrapped.hits == 1 and wrapped.misses == 1 and (first[0].move, first[0].cp) == (second[0].move, second[0].cp)
    black = chess.Board(AFTER_E4_E5.replace(" w ", " b "))
    assert wrapped(black)[0].cp == 40 and wrapped(black)[0].cp == 40 and len(inner.calls) == 2         # the mover's point of view survives the round trip
    deep = chess.Board(TOO_DEEP)
    wrapped(deep), wrapped(deep)
    assert len(inner.calls) == 4                                                                      # beyond ten moves nothing is kept
    stronger = CA.CachedSearch(inner, client.app.state.sessions, nodes=9000, multipv=1)
    stronger(b)
    assert len(inner.calls) == 5                                                                      # the stored search was weaker than asked
    over = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert wrapped(over) == []                                                                       # a finished game is passed through, not cached


def two_games():
    return pgn(site="https://lichess.org/AAAAAAAA", moves="1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0") + "\n" + pgn(site="https://lichess.org/BBBBBBBB", moves="1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 1-0")


def test_analysing_games_takes_opening_positions_from_the_cache(client):
    wait(client, client.post("/api/import/pgn", json={"text": two_games(), "player": "me"}).json())
    engines = []

    def factory(settings):
        def make():
            e = FakeEngine()
            e.calls = 0
            real = e.go

            def counted(*a, **k):
                e.calls += 1
                return real(*a, **k)
            e.go = counted
            engines.append(e)
            return e
        return make
    client.app.state.engine_factory = factory
    client.patch("/api/settings", json={"nodes": 1000, "multipv": 1})
    first = wait(client, client.post("/api/analyse", json={"ids": ["lichess:AAAAAAAA"]}).json())
    assert first["status"] == "done" and "from the cache" not in first["message"]
    n_first = engines[0].calls
    second = wait(client, client.post("/api/analyse", json={"ids": ["lichess:BBBBBBBB"]}).json())
    assert "opening positions came from the cache" in second["message"] and engines[1].calls < n_first       # shared opening moves were not searched again
    assert client.get("/api/cache").json()["positions"] > 5
    # with the cache switched off nothing is looked up or stored
    client.delete("/api/cache")
    client.patch("/api/settings", json={"use_cache": False})
    wait(client, client.post("/api/analyse", json={"ids": ["lichess:AAAAAAAA"]}).json())
    assert client.get("/api/cache").json()["positions"] == 0


def test_the_cache_is_built_from_the_players_openings_and_can_be_deleted(client):
    wait(client, client.post("/api/import/pgn", json={"text": two_games() + "\n" + two_games().replace("AAAAAAAA", "CCCCCCCC").replace("BBBBBBBB", "DDDDDDDD"), "player": "me"}).json())
    client.app.state.engine_factory = lambda settings: (lambda: FakeEngine())
    client.patch("/api/settings", json={"nodes": 1000, "multipv": 1})
    job = wait(client, client.post("/api/cache/build", json={"min_count": 2, "limit": 50}).json())
    assert job["status"] == "done" and "opening positions added" in job["message"]
    st = client.get("/api/cache").json()
    assert st["positions"] >= 6 and st["bySource"] == {"build": st["positions"]}                          # positions shared by two or more games (and the moves up to move 3 are shared)
    again = wait(client, client.post("/api/cache/build", json={"min_count": 2}).json())
    assert "nothing to add" in again["message"]
    assert client.delete("/api/cache", params={"source": "live"}).json() == {"deleted": 0}
    assert client.delete("/api/cache").json()["deleted"] == st["positions"] and client.get("/api/cache").json()["positions"] == 0
    capped = wait(client, client.post("/api/cache/build", json={"min_count": 1, "limit": 3}).json())
    assert "3 opening positions" in capped["message"]


def test_the_build_needs_an_engine_and_reports_that_clearly(client, monkeypatch):
    from chessme.app import workspace
    monkeypatch.setattr(workspace.shutil, "which", lambda name: None)
    wait(client, client.post("/api/import/pgn", json={"text": two_games()}).json())
    j = wait(client, client.post("/api/cache/build", json={"min_count": 1}).json())
    assert j["status"] == "failed" and "Stockfish was not found" in j["message"]


def test_live_analysis_stores_deep_opening_lines_and_shows_them_at_once_next_time(tmp_path):
    import stat
    import sys
    fake = tmp_path / "fake_uci"
    fake.write_text(FAKE.format(python=sys.executable))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    cfg = AppConfig(data_dir=tmp_path / "d", research_dir=tmp_path / "r", legacy_coach_dir=tmp_path / "c", engine=str(fake), port=8765)
    after_e4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        with c.websocket_connect("/api/ws/analysis", headers=HOST) as ws:
            ws.send_json({"fen": START, "multipv": 2})
            t0 = time.time()
            while time.time() - t0 < 15:
                m = ws.receive_json()
                if m["lines"] and min(l["depth"] for l in m["lines"]) >= 14:
                    break
            assert min(l["depth"] for l in m["lines"]) >= 14 and not m["cached"]
            ws.send_json({"fen": after_e4, "multipv": 1})                                              # leaving the position stores it
            for _ in range(60):
                if ws.receive_json()["fen"] == after_e4:
                    break
        with c.app.state.sessions() as s:
            row = s.get(PositionEval, CA.norm(START))
            assert row is not None and row.source == "live" and row.depth >= 14 and row.lines[0]["uci"] == "e2e4" and row.lines[0]["cp"] > 0
        with c.websocket_connect("/api/ws/analysis", headers=HOST) as ws:
            ws.send_json({"fen": START, "multipv": 2})
            first = ws.receive_json()
            assert first["cached"] is True and first["lines"][0]["san"][0] == "e4" and first["lines"][0]["depth"] >= 14
            for _ in range(10):                                                                       # engine lines that follow are at least as deep as the stored ones
                m = ws.receive_json()
                if not m["cached"]:
                    assert min(l["depth"] for l in m["lines"]) >= first["lines"][0]["depth"]
                    break
        c.patch("/api/settings", json={"use_cache": False})
        c.delete("/api/cache")
        with c.websocket_connect("/api/ws/analysis", headers=HOST) as ws:
            ws.send_json({"fen": START, "multipv": 1})
            assert ws.receive_json()["cached"] is False                                               # with the cache off nothing stored is shown


def test_a_deeper_build_replaces_shallower_entries_and_the_stats_show_the_deepest_search(client):
    wait(client, client.post("/api/import/pgn", json={"text": two_games() + "\n" + two_games().replace("AAAAAAAA", "CCCCCCCC").replace("BBBBBBBB", "DDDDDDDD"), "player": "me"}).json())
    client.app.state.engine_factory = lambda settings: (lambda: FakeEngine())
    client.patch("/api/settings", json={"nodes": 1000, "multipv": 1})
    wait(client, client.post("/api/cache/build", json={"min_count": 2, "limit": 50}).json())
    shallow = client.get("/api/cache").json()
    assert shallow["deepest"] == 1000 and shallow["deep"] == 0
    deeper = wait(client, client.post("/api/cache/build", json={"min_count": 2, "limit": 50, "nodes": 2_000_000}).json())
    assert deeper["status"] == "done" and "opening positions added" in deeper["message"]               # every stored position is searched again, deeper
    deep = client.get("/api/cache").json()
    assert deep["positions"] == shallow["positions"] and deep["deepest"] == 2_000_000 and deep["deep"] == deep["positions"]
    assert "nothing to add" in wait(client, client.post("/api/cache/build", json={"min_count": 2, "nodes": 2_000_000}).json())["message"]       # and not searched a third time
