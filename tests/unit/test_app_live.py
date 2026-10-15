"""Live analysis over a WebSocket (with a tiny fake UCI engine, and with Stockfish when it is installed) and the explorer endpoint."""
import os
import shutil
import stat
import sys
import time

import chess
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from chessme.app import live
from chessme.app.config import AppConfig
from chessme.app.main import create_app

BASE = "http://127.0.0.1:8765"
START = chess.STARTING_FEN
HOST = {"Host": "127.0.0.1:8765"}                                                                         # the test client does not set it for a WebSocket

FAKE = r'''#!{python}
import sys, time, threading
searching = threading.Event()
fen = [None]
def spin():
    d = 1
    while True:
        searching.wait()
        for mp in (1, 2):
            if not searching.is_set(): break
            mv = (["e7e5", "d7d5"] if " b " in fen[0] else ["e2e4", "d2d4"])[mp - 1]
            print(f"info depth {{d}} multipv {{mp}} score cp {{30 - 10 * mp + d}} nodes {{1000 * d}} nps 5000 pv {{mv}} e7e5", flush=True)
        d += 1
        time.sleep(0.02)
threading.Thread(target=spin, daemon=True).start()
for line in sys.stdin:
    line = line.strip()
    if line == "uci": print("id name Fake 1\nuciok", flush=True)
    elif line == "isready": print("readyok", flush=True)
    elif line.startswith("position fen "): fen[0] = line[len("position fen "):]
    elif line == "go infinite": searching.set()
    elif line == "stop": searching.clear(); print("bestmove e2e4", flush=True)
    elif line == "quit": break
'''


@pytest.fixture()
def fake_engine(tmp_path):
    p = tmp_path / "fake_uci"
    p.write_text(FAKE.format(python=sys.executable))
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def client_with(tmp_path, engine=None):
    cfg = AppConfig(data_dir=tmp_path / "d", research_dir=tmp_path / "r", legacy_coach_dir=tmp_path / "c", engine=engine, port=8765)
    return TestClient(create_app(cfg, static=False), base_url=BASE)


def test_info_lines_are_parsed_and_bounds_are_ignored():
    i = live.parse_info("info depth 12 seldepth 15 multipv 2 score cp -34 nodes 123456 nps 900000 hashfull 3 tbhits 0 time 137 pv e7e5 g1f3 b8c6")
    assert i == {"multipv": 2, "depth": 12, "kind": "cp", "score": -34, "nodes": 123456, "nps": 900000, "pv": ["e7e5", "g1f3", "b8c6"]}
    assert live.parse_info("info depth 3 score mate 2 pv h5f7")["kind"] == "mate"
    assert live.parse_info("info depth 3 score cp 10 lowerbound pv e2e4") is None and live.parse_info("info string NNUE evaluation using nn.nnue") is None
    assert live.parse_info("bestmove e2e4") is None and live.parse_info("info depth 1 currmove e2e4 currmovenumber 1") is None


def test_lines_are_shown_from_whites_point_of_view_in_san_and_cut_at_an_illegal_move():
    snap = {1: {"multipv": 1, "depth": 5, "kind": "cp", "score": 40, "nodes": 1, "nps": 1, "pv": ["e2e4", "e7e5", "g1f3", "zzzz", "a2a3"]}}
    out = live.to_lines(START, snap)
    assert out[0]["san"] == ["e4", "e5", "Nf3"] and out[0]["score"] == 40
    black = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    out = live.to_lines(black, {1: {"multipv": 1, "depth": 5, "kind": "cp", "score": 40, "nodes": 1, "nps": 1, "pv": ["e7e5"]}})
    assert out[0]["score"] == -40                                                                      # +40 for black is -40 for white
    assert live.to_lines(START, {1: {"multipv": 1, "depth": 1, "kind": "cp", "score": 0, "nodes": 0, "nps": 0, "pv": ["zzzz"]}}) == []


def collect(ws, n, timeout=10):
    got, t0 = [], time.time()
    while len(got) < n and time.time() - t0 < timeout:
        got.append(ws.receive_json())
    return got


def test_the_socket_streams_lines_and_a_new_position_replaces_the_old_one(tmp_path, fake_engine):
    after_e4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    with client_with(tmp_path, fake_engine) as c, c.websocket_connect("/api/ws/analysis", headers=HOST) as ws:
        ws.send_json({"fen": START, "multipv": 2})
        msgs = collect(ws, 4)
        assert all(m["type"] == "lines" and m["fen"] == START for m in msgs)
        assert {l["multipv"] for m in msgs for l in m["lines"]} == {1, 2} and msgs[-1]["lines"][0]["san"][:2] == ["e4", "e5"]
        depths = [m["lines"][0]["depth"] for m in msgs]
        assert depths == sorted(depths)
        ws.send_json({"fen": after_e4, "multipv": 1})
        for _ in range(60):                                                                               # messages of the old position may still be on their way; the new one must follow
            m = ws.receive_json()
            if m["fen"] == after_e4:
                break
        assert m["fen"] == after_e4 and m["lines"][0]["score"] < 100
        ws.send_json({"stop": True})


def test_bad_input_and_a_missing_engine_are_reported_not_raised(tmp_path, monkeypatch):
    from chessme.app import workspace
    monkeypatch.setattr(workspace.shutil, "which", lambda name: None)
    with client_with(tmp_path) as c, c.websocket_connect("/api/ws/analysis", headers=HOST) as ws:
        ws.send_json({"fen": "not a fen"})
        assert ws.receive_json()["message"] == "that is not a position"
        ws.send_json({"fen": START})
        assert "Stockfish was not found" in ws.receive_json()["message"]


def test_a_websocket_from_another_origin_or_host_is_refused(tmp_path, fake_engine):
    with client_with(tmp_path, fake_engine) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/api/ws/analysis", headers={**HOST, "Origin": "https://evil.example"}) as ws:
                ws.send_json({"fen": START})
                ws.receive_json()
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/api/ws/analysis", headers={"Host": "evil.example:8765"}) as ws:
                ws.receive_json()


@pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish")
def test_the_real_engine_streams_sane_lines(tmp_path):
    with client_with(tmp_path) as c, c.websocket_connect("/api/ws/analysis", headers=HOST) as ws:
        ws.send_json({"fen": START, "multipv": 3})
        msgs = collect(ws, 12, timeout=30)
        last = msgs[-1]["lines"]
        assert len(last) >= 1 and all(l["san"] and abs(l["score"]) < 200 and l["depth"] >= 1 for l in last)
        ws.send_json({"fen": "6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1", "multipv": 1})
        for _ in range(100):
            m = ws.receive_json()
            if m["fen"].startswith("6k1") and m["lines"] and m["lines"][0]["kind"] == "mate":
                break
        assert m["lines"][0]["kind"] == "mate" and m["lines"][0]["san"][0] == "Ra8#"


def test_the_explorer_endpoint_needs_the_database_and_validates_input(tmp_path, monkeypatch):
    with client_with(tmp_path) as c:
        assert c.get("/api/explorer", params={"fen": START}).status_code == 404
        db = tmp_path / "d" / "explorer.db"
        db.write_bytes(b"x")
        assert c.get("/api/explorer", params={"fen": "nonsense"}).status_code == 422
        from chessme.book import explorer as E
        monkeypatch.setattr(E, "query_position", lambda path, fen, rating=None, band=None: {"total": 5, "other": 0, "moves": [{"san": "e4", "uci": "e2e4", "games": 5, "share": 1.0, "white": 0.5, "draw": 0.2, "black": 0.3, "avg_rating": 1500, "eval": 0.2, "eval_n": 3, "top_game": None, "top_url": None, "top_rating": 0}]})
        r = c.get("/api/explorer", params={"fen": START, "rating": 1600}).json()
        assert r["total"] == 5 and r["moves"][0]["san"] == "e4"
