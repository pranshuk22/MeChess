"""The computer takes its time like a person, and timed games have clocks."""
import random

import chess
import pytest

from chessme.app import pacing as P
from tests.unit.test_app_play import client, script  # noqa: F401  (the fixtures)


def board_after(*sans):
    b = chess.Board()
    for s in sans:
        b.push_san(s)
    return b


def test_forced_moves_and_openings_are_quick_and_a_busy_middlegame_takes_longer():
    forced = chess.Board("7k/8/8/8/8/8/6q1/K7 w - - 0 1")                       # one legal move
    assert P.median_seconds(forced) < 0.5
    opening = board_after("e4", "e5")
    middle = chess.Board("r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P1B2/2PBPN2/PP1N1PPP/R2QK2R w KQ - 0 9")
    middle.push_san("Nb3")
    for _ in range(4):
        middle.push(next(iter(middle.legal_moves)))
        if middle.is_game_over():
            break
    tense = chess.Board("r2q1rk1/ppp2ppp/2n1bn2/3pp3/1b1PP3/2N1BN2/PPP1BPPP/R2Q1RK1 w - - 0 8")
    assert P.median_seconds(opening) < 2.0 and P.median_seconds(tense) > P.median_seconds(opening)


def test_a_recapture_is_quicker_than_the_same_position_without_one():
    after = chess.Board("rnbq1rk1/pp2bppp/4pn2/2pp4/2PP4/2N1PN2/PP2BPPP/R1BQ1RK1 w - - 0 8")
    after.push_san("cxd5")                                                        # black can take back on d5
    quiet = chess.Board(after.fen())                                              # the same position, with no last move to recapture
    assert P.median_seconds(after) < P.median_seconds(quiet)


def test_stronger_opponents_think_longer_and_the_time_varies_from_move_to_move():
    b = chess.Board("r2q1rk1/ppp2ppp/2n1bn2/3pp3/1b1PP3/2N1BN2/PPP1BPPP/R2Q1RK1 w - - 0 8")
    assert P.strength_scale("stockfish", 1) < P.strength_scale("stockfish", 8) and P.strength_scale("mechess", 800) < P.strength_scale("mechess", 2600)
    rng = random.Random(1)
    times = [P.think_seconds(b, rng=rng) for _ in range(200)]
    assert min(times) >= P.MIN_S and max(times) <= P.MAX_UNTIMED_S and len({round(t, 1) for t in times}) > 20            # not a metronome
    weak = sum(P.think_seconds(b, strength=0.6, rng=random.Random(i)) for i in range(100))
    strong = sum(P.think_seconds(b, strength=1.5, rng=random.Random(i)) for i in range(100))
    assert strong > weak * 1.5


def test_the_clock_limits_the_thinking_time():
    b = chess.Board("r2q1rk1/ppp2ppp/2n1bn2/3pp3/1b1PP3/2N1BN2/PPP1BPPP/R2Q1RK1 w - - 0 8")
    for left in (600, 60, 10, 2):
        for i in range(50):
            t = P.think_seconds(b, strength=1.5, remaining=left, inc=0, rng=random.Random(i))
            assert t <= 0.2 * left + 1e-9 or t <= P.MIN_S + 1e-9
    assert P.think_seconds(b, remaining=0.4, rng=random.Random(0)) <= 0.2                                          # nearly out of time: a move at once


def test_an_untimed_game_still_makes_the_computer_wait_a_little_and_says_how_long(client):          # noqa: F811
    script(client, "e7e5")
    s = client.post("/api/play/start", json={"colour": "white", "opponent": "stockfish", "level": 4}).json()
    assert s["clock"] is None and s["timeControl"] is None
    r = client.post(f"/api/play/{s['id']}/move", json={"uci": "e2e4"}).json()
    assert 350 <= r["thinkMs"] <= 14_000
    instant = client.post("/api/play/start", json={"colour": "white", "opponent": "stockfish", "level": 4, "pace": False}).json()
    assert client.post(f"/api/play/{instant['id']}/move", json={"uci": "e2e4"}).json()["thinkMs"] == 0           # pacing can be turned off


def test_a_timed_game_charges_each_side_its_time_adds_the_increment_and_saves_the_clocks(client):          # noqa: F811
    script(client, "e7e5", "b8c6")
    s = client.post("/api/play/start", json={"colour": "white", "opponent": "stockfish", "level": 4, "base": 300, "inc": 2}).json()
    assert s["timeControl"] == {"base": 300, "inc": 2} and s["clock"] == {"white": 300.0, "black": 300.0} and s["running"] == "white"
    r = client.post(f"/api/play/{s['id']}/move", json={"uci": "e2e4"}).json()
    assert r["clock"]["white"] > 300 and r["clock"]["white"] <= 302.0                                         # you used a moment and got 2 seconds back
    assert r["clock"]["black"] < 302.0 and r["running"] == "white" and r["thinkMs"] > 0
    client.post(f"/api/play/{s['id']}/resign")
    gid = client.get(f"/api/play/{s['id']}").json()["gameId"]
    g = client.get(f"/api/games/{gid}").json()
    assert g["base"] == 300 and g["inc"] == 2 and len(g["clocks"]) == 2 and g["clocks"][0] > 300                # the clocks are in the saved game, so the review can chart them


def test_running_out_of_time_loses_the_game_and_the_page_can_report_it(client):          # noqa: F811
    script(client)
    s = client.post("/api/play/start", json={"colour": "white", "opponent": "stockfish", "level": 4, "base": 60}).json()
    client.app.state.play.get(s["id"]).turn_started -= 120                                                        # two minutes pass
    assert client.post(f"/api/play/{s['id']}/flag").json()["reason"] == "time"
    over = client.get(f"/api/play/{s['id']}").json()
    assert over["status"] == "over" and over["result"] == "0-1" and over["reason"] == "time" and over["clock"]["white"] == 0
    s2 = client.post("/api/play/start", json={"colour": "white", "opponent": "stockfish", "level": 4, "base": 60}).json()
    client.app.state.play.get(s2["id"]).turn_started -= 120
    late = client.post(f"/api/play/{s2['id']}/move", json={"uci": "e2e4"}).json()                                 # a move after the flag does not count
    assert late["status"] == "over" and late["reason"] == "time" and late["moves"] == []
    assert client.post("/api/play/start", json={"opponent": "stockfish", "base": 5}).status_code == 422
    assert client.post("/api/play/start", json={"opponent": "stockfish", "base": 300, "inc": 500}).status_code == 422


def test_as_black_the_computer_opens_and_its_think_time_comes_off_its_clock(client):          # noqa: F811
    script(client, "d2d4")
    s = client.post("/api/play/start", json={"colour": "black", "opponent": "stockfish", "level": 4, "base": 180, "inc": 0}).json()
    assert [m["san"] for m in s["moves"]] == ["d4"] and s["clock"]["white"] < 180 and s["clock"]["black"] == 180 and s["thinkMs"] > 0 and s["running"] == "black"
