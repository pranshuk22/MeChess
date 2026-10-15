"""Playing against the computer: sessions, legality, the engine's reply, takeback, resignation, the saved game, and real engines when they are installed."""
import shutil

import chess
import pytest
from fastapi.testclient import TestClient

from chessme.app.config import AppConfig
from chessme.app.main import create_app
from chessme.app.play import STOCKFISH_LEVELS, PlayError
from chessme.uci_client import GoResult

BASE = "http://127.0.0.1:8765"


class ScriptedEngine:
    """Answers with the next move of a script (then the first legal move)."""

    def __init__(self, script=()):
        self.script, self.options = list(script), []

    def _send(self, line):
        self.options.append(line)

    def go(self, fen, moves=(), *, nodes=None, depth=None, movetime=None, timeout=60):
        b = chess.Board(fen)
        for m in moves:
            b.push_uci(m)
        mv = None
        while self.script and mv is None:
            c = chess.Move.from_uci(self.script.pop(0))
            mv = c if c in b.legal_moves else None
        mv = mv or next(iter(b.legal_moves))
        return GoResult(bestmove=mv.uci())


@pytest.fixture()
def client(tmp_path):
    cfg = AppConfig(data_dir=tmp_path / "data", research_dir=tmp_path / "research", legacy_coach_dir=tmp_path / "coach", port=8765)
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        yield c


def script(client, *moves):
    eng = ScriptedEngine(moves)
    client.app.state.play._stockfish = lambda path: eng
    return eng


def test_the_options_list_the_levels_and_whether_each_opponent_is_available(client):
    o = client.get("/api/play/options").json()
    assert [l["id"] for l in o["stockfish"]["levels"]] == list(STOCKFISH_LEVELS) and o["mechess"]["min"] == 800 and o["mechess"]["max"] == 2600
    assert isinstance(o["stockfish"]["available"], bool) and isinstance(o["mechess"]["available"], bool)


def test_a_game_as_white_plays_the_engine_reply_to_every_move_and_rejects_bad_moves(client):
    script(client, "e7e5", "b8c6")
    s = client.post("/api/play/start", json={"colour": "white", "opponent": "stockfish", "level": 4}).json()
    assert s["colour"] == "white" and s["moves"] == [] and s["status"] == "playing" and s["opponent"] == "Stockfish, intermediate level"
    r = client.post(f"/api/play/{s['id']}/move", json={"uci": "e2e4"}).json()
    assert [m["san"] for m in r["moves"]] == ["e4", "e5"] and r["turn"] == "white"
    assert client.post(f"/api/play/{s['id']}/move", json={"uci": "e2e4"}).status_code == 422                 # not legal now
    assert client.post(f"/api/play/{s['id']}/move", json={"uci": "zz"}).status_code == 422
    r = client.post(f"/api/play/{s['id']}/move", json={"uci": "g1f3"}).json()
    assert [m["san"] for m in r["moves"]] == ["e4", "e5", "Nf3", "Nc6"]
    assert client.get(f"/api/play/{s['id']}").json()["fen"] == r["fen"]


def test_as_black_the_engine_opens(client):
    script(client, "d2d4")
    s = client.post("/api/play/start", json={"colour": "black", "opponent": "stockfish", "level": 1}).json()
    assert [m["san"] for m in s["moves"]] == ["d4"] and s["turn"] == "black"
    r = client.post(f"/api/play/{s['id']}/move", json={"uci": "d7d5"}).json()
    assert [m["san"] for m in r["moves"]][:2] == ["d4", "d5"]


def test_the_wrong_turn_a_finished_game_and_unknown_games_are_refused(client):
    script(client)
    s = client.post("/api/play/start", json={"colour": "white", "opponent": "stockfish", "level": 4}).json()
    client.post(f"/api/play/{s['id']}/resign")
    assert client.post(f"/api/play/{s['id']}/move", json={"uci": "e2e4"}).status_code == 409
    assert client.post(f"/api/play/{s['id']}/takeback").status_code == 409
    assert client.get("/api/play/nope").status_code == 404 and client.post("/api/play/nope/move", json={"uci": "e2e4"}).status_code == 404
    assert client.post("/api/play/start", json={"colour": "green"}).status_code == 422
    assert client.post("/api/play/start", json={"opponent": "stockfish", "level": 99}).status_code == 422
    assert client.post("/api/play/start", json={"opponent": "mechess", "level": 100}).status_code == 422
    assert client.post("/api/play/start", json={"opponent": "other"}).status_code == 422


def test_takeback_returns_to_your_own_turn(client):
    script(client)
    s = client.post("/api/play/start", json={"colour": "white", "opponent": "stockfish", "level": 4}).json()
    assert client.post(f"/api/play/{s['id']}/takeback").status_code == 409                                    # nothing played yet
    client.post(f"/api/play/{s['id']}/move", json={"uci": "e2e4"})
    r = client.post(f"/api/play/{s['id']}/takeback").json()
    assert r["moves"] == [] and r["turn"] == "white"
    client.post(f"/api/play/{s['id']}/move", json={"uci": "d2d4"})
    client.post(f"/api/play/{s['id']}/move", json={"uci": "c2c4"})
    assert len(client.post(f"/api/play/{s['id']}/takeback").json()["moves"]) == 2


def test_checkmate_ends_the_game_and_saves_it_to_the_library_once(client):
    script(client, "f2f3", "g2g4")                                                                            # the engine plays the fool's mate as white
    s = client.post("/api/play/start", json={"colour": "black", "opponent": "stockfish", "level": 4}).json()
    client.post(f"/api/play/{s['id']}/move", json={"uci": "e7e5"})
    r = client.post(f"/api/play/{s['id']}/move", json={"uci": "d8h4"}).json()
    assert r["status"] == "over" and r["result"] == "0-1" and r["reason"] == "checkmate" and r["gameId"].startswith("play:")
    g = client.get(f"/api/games/{r['gameId']}").json()
    assert g["source"] == "play" and g["user"] == "black" and g["result"] == "0-1" and g["black"] == "You" and g["white"] == "Stockfish, intermediate level" and g["plies"] == 4
    again = client.get(f"/api/play/{s['id']}").json()
    assert again["gameId"] == r["gameId"] and client.get("/api/games").json()["total"] == 1


def test_resigning_loses_the_game_and_saves_it(client):
    script(client)
    s = client.post("/api/play/start", json={"colour": "white", "opponent": "stockfish", "level": 4}).json()
    client.post(f"/api/play/{s['id']}/move", json={"uci": "e2e4"})
    r = client.post(f"/api/play/{s['id']}/resign").json()
    assert r["result"] == "0-1" and r["reason"] == "resignation" and r["gameId"]
    assert client.get(f"/api/games/{r['gameId']}").json()["result"] == "0-1"
    empty = client.post("/api/play/start", json={"colour": "white", "opponent": "stockfish", "level": 4}).json()
    assert client.post(f"/api/play/{empty['id']}/resign").json()["gameId"] is None                           # a game without moves is not worth keeping


def test_an_illegal_engine_answer_cannot_corrupt_the_game(client):
    class Bad(ScriptedEngine):
        def go(self, *a, **k):
            return GoResult(bestmove="a1a8")
    client.app.state.play._stockfish = lambda path: Bad()
    s = client.post("/api/play/start", json={"colour": "white", "opponent": "stockfish", "level": 4}).json()
    r = client.post(f"/api/play/{s['id']}/move", json={"uci": "e2e4"}).json()
    assert len(r["moves"]) == 2 and chess.Board(r["fen"]).is_valid()


def test_the_lowest_levels_sometimes_play_a_random_move_without_asking_the_engine(client, monkeypatch):
    import random
    calls = []
    eng = script(client)
    real = eng.go
    eng.go = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
    monkeypatch.setattr(random.Random, "random", lambda self: 0.0)                                            # "the dice always say: blunder"
    s = client.post("/api/play/start", json={"colour": "white", "opponent": "stockfish", "level": 1}).json()
    assert client.post(f"/api/play/{s['id']}/move", json={"uci": "e2e4"}).status_code == 200 and calls == []
    s = client.post("/api/play/start", json={"colour": "white", "opponent": "stockfish", "level": 4}).json()    # level 4 never plays at random
    assert client.post(f"/api/play/{s['id']}/move", json={"uci": "e2e4"}).status_code == 200 and calls == [1]
    assert any(o == "setoption name Skill Level value 7" for o in eng.options)                              # the level's skill is set before the search


def test_old_games_make_room_when_too_many_are_open(client):
    script(client)
    ids = [client.post("/api/play/start", json={"colour": "white", "opponent": "stockfish", "level": 4}).json()["id"] for _ in range(22)]
    assert client.get(f"/api/play/{ids[0]}").status_code == 404 and client.get(f"/api/play/{ids[-1]}").status_code == 200


@pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish")
def test_real_stockfish_answers_at_every_level(client):
    for level in (1, 4, 8):
        s = client.post("/api/play/start", json={"colour": "white", "opponent": "stockfish", "level": level}).json()
        r = client.post(f"/api/play/{s['id']}/move", json={"uci": "e2e4"})
        assert r.status_code == 200 and len(r.json()["moves"]) == 2


def test_the_mechess_controller_plays_when_the_engine_is_built(client):
    from chessme.cli import ENGINE_BIN
    if not ENGINE_BIN.exists():
        pytest.skip("the C++ engine is not built")
    s = client.post("/api/play/start", json={"colour": "white", "opponent": "mechess", "level": 1500}).json()
    assert s["opponent"] == "MeChess, about 1500"
    r = client.post(f"/api/play/{s['id']}/move", json={"uci": "e2e4"})
    assert r.status_code == 200 and len(r.json()["moves"]) == 2
