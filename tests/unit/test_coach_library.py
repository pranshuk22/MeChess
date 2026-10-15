"""The coach's opening library (named openings from the opening database) and the repertoire your own games show."""
import chess
import pytest
from fastapi.testclient import TestClient

from chessme.app.config import AppConfig
from chessme.app.main import create_app
from chessme.app.services import games as G
from chessme.coach import library as L
from chessme.coach import openings as OP
from chessme.prep import graph as GR
from tests.unit.test_app_coach_modes import with_explorer

BASE = "http://127.0.0.1:8765"


@pytest.fixture()
def client(tmp_path):
    cfg = AppConfig(data_dir=tmp_path / "data", research_dir=tmp_path / "research", legacy_coach_dir=tmp_path / "coach", port=8765)
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        yield c


def test_the_families_are_named_openings_with_the_side_that_plays_them_and_the_main_ones_first():
    fams = L.families()
    names = [f["name"] for f in fams]
    assert len(fams) > 100 and "Italian Game" in names and "Sicilian Defense" in names
    by = {f["name"]: f for f in fams}
    assert by["Italian Game"]["side"] == "white" and by["Sicilian Defense"]["side"] == "black" and by["Queen's Gambit Declined"]["side"] == "black" and by["London System"]["side"] == "white"
    assert by["Italian Game"]["featured"] and by["Italian Game"]["lines"] > 5 and fams[0]["featured"]


def test_a_library_repertoire_is_a_pgn_the_practice_understands_for_either_colour():
    pgn = L.library_pgn("Italian Game", "white")
    rep = OP.Repertoire.from_pgn(pgn, "white")
    assert rep.size > 10 and "e2e4" in rep.prepared(chess.Board()) and "Italian Game" in pgn
    black = OP.Repertoire.from_pgn(L.library_pgn("Sicilian Defense", "black"), "black")
    b = chess.Board()
    b.push_uci("e2e4")
    assert "c7c5" in black.prepared(b)
    assert L.library_pgn("No Such Opening", "white") is None


def test_the_explorer_decides_which_of_your_moves_are_kept():
    start = chess.Board().fen()
    replies = lambda fen: [("e2e4", 0.9), ("d2d4", 0.1)] if fen == start else []
    keep_one = OP.Repertoire.from_pgn(L.library_pgn("Italian Game", "white", replies, keep=1), "white")
    assert list(keep_one.prepared(chess.Board())) == ["e2e4"]


def games(moves_list, colour="white", result="1-0"):
    from chessme.prep import games as PG
    out = []
    for i, moves in enumerate(moves_list):
        board, ucis = chess.Board(), []
        for san in moves.split():
            mv = board.parse_san(san)
            ucis.append(mv.uci())
            board.push(mv)
        out.append(PG.OppGame(id=f"g{i}", colour=colour, moves=ucis, score={"1-0": 1.0, "0-1": 0.0}.get(result, 0.5) if colour == "white" else 1.0, speed="blitz", date="2026-01-01",
                              opening=None, family=None, opp_elo=None, their_elo=None, termination=None))
    return out


def test_your_own_repertoire_is_what_you_played_at_least_twice_with_its_results():
    gs = games(["e4 e5 Nf3 Nc6 Bc4", "e4 e5 Nf3 Nc6 Bb5", "e4 e5 Nf3 Nf6 Nxe5", "d4 d5"])
    pgn, st = L.repertoire_from_graph(GR.build(gs), "white")
    rep = OP.Repertoire.from_pgn(pgn, "white")
    assert "e2e4" in rep.prepared(chess.Board()) and "d2d4" not in rep.prepared(chess.Board())               # d4 was played once: not a repertoire move yet
    assert st["games"] == 4 and st["positions"] >= 2 and st["moves"] >= 2 and "3 games" in pgn
    empty, st0 = L.repertoire_from_graph(GR.build(gs[3:]), "white")
    assert st0["moves"] == 0


def seed(client, texts):
    s = client.app.state.sessions()
    for i, sans in enumerate(texts):
        board, ucis = chess.Board(), []
        for san in sans.split():
            mv = board.parse_san(san)
            ucis.append(mv.uci())
            board.push(mv)
        G.store(s, id=f"s{i}", source="test", headers={"White": "me", "Black": "x", "Result": "1-0", "TimeControl": "180+0", "Date": "2026.06.01"}, user_colour="white", uci_moves=ucis)
    s.commit()
    s.close()


def test_the_library_lists_filters_and_shows_how_you_do_with_each_opening(client):
    seed(client, ["e4 e5 Nf3 Nc6 Bc4 Bc5", "e4 e5 Nf3 Nc6 Bc4 Nf6"])
    allf = client.get("/api/coach/library").json()
    assert any(f["name"] == "Italian Game" for f in allf)
    only_black = client.get("/api/coach/library", params={"side": "black", "featured": True}).json()
    assert only_black and all(f["side"] == "black" and f["featured"] for f in only_black)
    assert [f["name"] for f in client.get("/api/coach/library", params={"q": "ruy"}).json()][0].startswith("Ruy")
    italian = next(f for f in allf if f["name"] == "Italian Game")
    assert italian["yours"]["games"] == 2 and italian["yours"]["score"] == 1.0
    assert next(f for f in allf if f["name"] == "Ruy Lopez")["yours"] is None


def test_a_library_opening_is_practised_or_saved_and_your_own_repertoire_is_made_from_your_games(client, monkeypatch, tmp_path):
    (tmp_path / "data" / "explorer.db").write_bytes(b"x")
    with_explorer(client, monkeypatch)
    s = client.post("/api/coach/library/start", json={"name": "Italian Game", "colour": "white", "rating": 1500})
    assert s.status_code == 200 and s.json()["view"]["color"] == "white" and s.json()["moves"] > 0
    assert client.post("/api/coach/library/start", json={"name": "Nonsense", "colour": "white"}).status_code == 404
    assert client.post("/api/coach/library/start", json={"name": "Italian Game", "colour": "green"}).status_code == 422
    saved = client.post("/api/coach/library/save", json={"name": "Ruy Lopez", "colour": "white"}).json()
    assert "Ruy Lopez" in saved["name"] and any(r["id"] == saved["id"] for r in client.get("/api/coach/repertoires").json())
    assert client.post("/api/coach/repertoires/mine", json={"colour": "white"}).status_code == 409                      # no games yet
    seed(client, ["e4 e5 Nf3 Nc6 Bc4 Bc5", "e4 e5 Nf3 Nc6 Bc4 Nf6", "e4 c5 Nf3 d6"])
    mine = client.post("/api/coach/repertoires/mine", json={"colour": "white"})
    assert mine.status_code == 201 and mine.json()["id"] == "mine-white" and mine.json()["moves"] >= 3 and mine.json()["games"] == 3
    again = client.post("/api/coach/repertoires/mine", json={"colour": "white"})
    assert again.json()["id"] == "mine-white" and len([r for r in client.get("/api/coach/repertoires").json() if r["id"] == "mine-white"]) == 1       # refreshed, not duplicated
    summary = client.get("/api/coach/mine").json()
    assert summary["white"]["games"] == 3 and summary["black"]["moves"] == 0
    started = client.post("/api/coach/repertoires/mine-white/start", params={"rating": 1500})
    assert started.status_code == 200 and started.json()["view"]["color"] == "white"
