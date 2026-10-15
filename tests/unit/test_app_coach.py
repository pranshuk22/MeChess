"""The coach's drills (Leitner boxes in the database), judging, hints, and the weakness profile with its comparison against players of your rating."""
import time

import chess
import pytest
from fastapi.testclient import TestClient

from chessme.analysis.runner import SimpleLine
from chessme.app.config import AppConfig
from chessme.app.main import create_app
from chessme.app.models import Drill
from chessme.app.services import games as G
from chessme.coach.drills import DAY, INTERVALS
from tests.unit.test_app_api import analysed_move, game_moves
from tests.unit.test_coach_reference import make_ref

BASE = "http://127.0.0.1:8765"
AFTER_E4_E5 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"


@pytest.fixture()
def client(tmp_path):
    cfg = AppConfig(data_dir=tmp_path / "data", research_dir=tmp_path / "research", legacy_coach_dir=tmp_path / "coach", port=8765)
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        yield c


def seed(client, gid="g1", colour="white", elo=1450):
    s = client.app.state.sessions()
    G.store(s, id=gid, source="test", headers={"White": "me", "Black": "x", "Result": "0-1", "WhiteElo": str(elo), "BlackElo": "1500", "TimeControl": "180+0", "Date": "2026.06.01"},
            user_colour=colour, analysis={"moves": game_moves()}, nodes=1, multipv=1)
    s.commit()
    s.close()


def fake_search(client, table=None, default=0):
    """search(board) answering by position: `table` maps a FEN (without counters) to (best move, cp for the side to move)."""
    table = table or {}

    def search(board):
        key = " ".join(board.fen().split()[:4])
        mv, cp = table.get(key, (next(iter(board.legal_moves)).uci() if any(board.legal_moves) else None, default))
        return [SimpleLine(mv, cp, [mv])] if mv else []
    client.app.state.quick.searcher = lambda path: search
    return search


def after(fen, uci):
    b = chess.Board(fen)
    b.push_uci(uci)
    return " ".join(b.fen().split()[:4])


def test_drills_come_from_the_players_biggest_mistakes_once(client):
    seed(client)
    assert client.get("/api/coach/drills").json() == {"total": 0, "due": 0, "boxes": [0] * 6}
    r = client.post("/api/coach/drills/refresh").json()
    assert r["added"] == 1 and r["total"] == 1 and r["due"] == 1 and r["boxes"][0] == 1
    assert client.post("/api/coach/drills/refresh").json()["added"] == 0                                        # the same game gives no second drill
    seed(client, "g2", colour="black")                                                                          # black made no mistake in game_moves()
    assert client.post("/api/coach/drills/refresh").json()["added"] == 0
    nxt = client.get("/api/coach/drills/next").json()
    d = nxt["items"][0]
    assert d["fen"] == AFTER_E4_E5 and d["playedSan"] == "Qh5" and d["colour"] == "white" and d["move"] == 2 and d["gameId"] == "g1" and "bestSan" not in d and "bestUci" not in d


def test_hints_go_from_vague_to_exact_and_do_not_record_anything(client):
    seed(client)
    client.post("/api/coach/drills/refresh")
    did = client.get("/api/coach/drills/next").json()["items"][0]["id"]
    texts = [client.get(f"/api/coach/drills/{did}/hint", params={"level": k}).json()["text"] for k in (1, 2, 3)]
    assert texts[2] == "The move is Nf3." and "knight" in texts[1].lower() and texts[0] != texts[1]
    assert client.get(f"/api/coach/drills/{did}/hint", params={"level": 4}).status_code == 422
    assert client.get("/api/coach/drills/zzz/hint").status_code == 404
    assert client.get("/api/coach/drills").json()["boxes"][0] == 1


def test_finding_the_move_first_time_moves_a_drill_up_and_it_is_not_due_again_soon(client):
    seed(client)
    client.post("/api/coach/drills/refresh")
    fake_search(client)
    did = client.get("/api/coach/drills/next").json()["items"][0]["id"]
    t0 = time.time()
    r = client.post(f"/api/coach/drills/{did}/attempt", json={"uci": "g1f3", "tries": 0, "hints": 0}).json()
    assert r["verdict"] == "found" and r["recorded"] == "up" and r["bestSan"] == "Nf3" and "Qh5" in r["explanation"] or r["explanation"]
    with client.app.state.sessions() as s:
        d = s.get(Drill, did)
        assert d.box == 1 and abs(d.due - (t0 + INTERVALS[1])) < 5 and d.history[-1][1] is True
    assert client.get("/api/coach/drills/next").json()["items"] == [] and client.get("/api/coach/drills").json()["due"] == 0


def test_a_move_that_is_nearly_as_good_counts_a_bad_one_does_not_and_hints_or_tries_send_it_back(client):
    seed(client)
    client.post("/api/coach/drills/refresh")
    ok_fen, bad_fen = after(AFTER_E4_E5, "d2d3"), after(AFTER_E4_E5, "a2a3")
    key = " ".join(AFTER_E4_E5.split()[:4])
    fake_search(client, {key: ("g1f3", 30), ok_fen: ("e7e6", -25), bad_fen: ("e7e6", 400)})                      # after d3 black is a bit better for black by -25 (nearly as good as +30); after a3 black is +400
    did = client.get("/api/coach/drills/next").json()["items"][0]["id"]
    wrong = client.post(f"/api/coach/drills/{did}/attempt", json={"uci": "a2a3"}).json()
    assert wrong["verdict"] == "wrong" and wrong["loss"] > 0.3 and "bestSan" not in wrong                       # a wrong try does not give the answer away
    with client.app.state.sessions() as s:
        assert s.get(Drill, did).box == 0 and s.get(Drill, did).history == []                                    # and is not recorded
    ok = client.post(f"/api/coach/drills/{did}/attempt", json={"uci": "d2d3", "tries": 1, "hints": 0}).json()
    assert ok["verdict"] == "ok" and ok["loss"] <= 0.03 and ok["recorded"] == "again" and ok["bestSan"] == "Nf3"
    with client.app.state.sessions() as s:
        assert s.get(Drill, did).box == 0                                                                        # needed a second try: back to box 0
    with_hint = client.post(f"/api/coach/drills/{did}/attempt", json={"uci": "g1f3", "tries": 0, "hints": 2}).json()
    assert with_hint["verdict"] == "found" and with_hint["recorded"] == "again"
    assert client.post(f"/api/coach/drills/{did}/attempt", json={"uci": "e1e5"}).status_code == 422


def test_revealing_counts_as_missed_and_a_succession_of_successes_climbs_the_boxes(client):
    seed(client)
    client.post("/api/coach/drills/refresh")
    fake_search(client)
    did = client.get("/api/coach/drills/next").json()["items"][0]["id"]
    r = client.post(f"/api/coach/drills/{did}/reveal").json()
    assert r["verdict"] == "revealed" and r["bestSan"] == "Nf3"
    with client.app.state.sessions() as s:
        d = s.get(Drill, did)
        assert d.box == 0 and d.history[-1][1] is False
        for expected in (1, 2, 3, 4, 5, 5):
            d.due = 0
            from chessme.app.services import coach as CO
            CO.record(s, d, True)
            assert d.box == expected
        assert d.due - time.time() > 30 * DAY                                                                    # box 5: about five weeks


def test_no_engine_gives_a_clear_message(client, monkeypatch):
    from chessme.app import workspace
    monkeypatch.setattr(workspace.shutil, "which", lambda name: None)
    seed(client)
    client.post("/api/coach/drills/refresh")
    did = client.get("/api/coach/drills/next").json()["items"][0]["id"]
    assert client.post(f"/api/coach/drills/{did}/attempt", json={"uci": "a2a3"}).status_code == 409
    assert client.post(f"/api/coach/drills/{did}/attempt", json={"uci": "g1f3"}).json()["verdict"] == "found"    # the engine's own move needs no engine to be recognised


def test_the_weakness_profile_is_built_from_analysed_games_and_compared_with_players_of_your_rating(client):
    for i in range(3):
        seed(client, f"p{i}", elo=1450)
    prof = client.get("/api/coach/profile").json()
    assert prof["games"] == 3 and prof["moves"] == 6 and prof["mistake_rate"] == pytest.approx(0.5) and "reference" not in prof
    assert isinstance(prof["sentences"], list) and isinstance(prof["foci"], list)
    client.app.state.reference = make_ref(mistakes=1000, moves=10000, nodes=100000)
    prof = client.get("/api/coach/profile").json()
    assert prof["reference"]["band"] == 1400 and prof["reference"]["speed"] == "blitz" and prof["reference"]["overall"]["you"] == pytest.approx(0.5)
    assert client.get("/api/stats").status_code == 200


def test_a_try_gets_graded_feedback_with_reasons_and_the_answer_is_kept_back_until_it_is_found(client):
    seed(client)
    client.post("/api/coach/drills/refresh")
    ok_fen, bad_fen, mid_fen = after(AFTER_E4_E5, "d2d3"), after(AFTER_E4_E5, "a2a3"), after(AFTER_E4_E5, "b1c3")
    key = " ".join(AFTER_E4_E5.split()[:4])
    fake_search(client, {key: ("g1f3", 30), ok_fen: ("e7e6", -25), bad_fen: ("e7e6", 400), mid_fen: ("e7e6", 20)})            # after Nc3 black is at +20: a sound move, about 4 points under the best
    did = client.get("/api/coach/drills/next").json()["items"][0]["id"]
    wrong = client.post(f"/api/coach/drills/{did}/attempt", json={"uci": "a2a3"}).json()
    assert wrong["verdict"] == "wrong" and wrong["grade"] in ("mistake", "blunder") and wrong["title"] and any("fall from" in r for r in wrong["reasons"])
    assert not {"bestSan", "bestUci", "bestWhy", "alternatives"} & set(wrong)                                                   # what it allows is explained, the answer is not given away
    good = client.post(f"/api/coach/drills/{did}/attempt", json={"uci": "b1c3", "tries": 1}).json()
    assert good["verdict"] == "ok" and good["grade"] in ("great", "good") and good["bestSan"] == "Nf3" and good["reasons"]
    if good["grade"] == "good":
        assert "try again for the best" in " ".join(good["reasons"])
    best = client.post(f"/api/coach/drills/{did}/attempt", json={"uci": "g1f3"}).json()
    assert best["verdict"] == "found" and best["grade"] == "best" and best["title"] == "Best move" and best["bestWhy"] and best["reasons"]


def test_the_feedback_endpoint_works_for_any_position_and_hides_the_best_move_of_a_bad_try(client):
    fake_search(client, {" ".join(chess.STARTING_FEN.split()[:4]): ("e2e4", 40), after(chess.STARTING_FEN, "f2f3"): ("e7e5", 600)})
    fb = client.post("/api/coach/feedback", json={"fen": chess.STARTING_FEN, "uci": "f2f3"}).json()
    assert fb["grade"] in ("mistake", "blunder") and "bestSan" not in fb and fb["reasons"]
    shown = client.post("/api/coach/feedback", json={"fen": chess.STARTING_FEN, "uci": "f2f3", "hide_best": False}).json()
    assert shown["bestSan"] == "e4"
    assert client.post("/api/coach/feedback", json={"fen": chess.STARTING_FEN, "uci": "e2e5"}).status_code == 422
    assert client.post("/api/coach/feedback", json={"fen": "not a fen", "uci": "e2e4"}).status_code == 422
    best = client.post("/api/coach/feedback", json={"fen": chess.STARTING_FEN, "uci": "e2e4"}).json()
    assert best["grade"] == "best" and best["bestSan"] == "e4"
