"""Performance rating of a game: from how the moves compare with each rating's rates, and from the result."""
import json
from pathlib import Path

import pytest

from chessme.analysis import performance as P
from chessme.coach import reference as R

REF = json.loads((Path(R.__file__).with_name("reference_rates.json")).read_text())


def test_cleaner_play_rates_higher_and_more_moves_make_a_narrower_interval():
    clean = P.estimate([0.0] * 30, "blitz", REF)
    two = P.estimate([0.0] * 28 + [0.12, 0.15], "blitz", REF)
    messy = P.estimate([0.0] * 20 + [0.12] * 4 + [0.3] * 3 + [0.02] * 3, "blitz", REF)
    assert clean["rating"] > two["rating"] > messy["rating"]
    assert clean["low"] < clean["rating"] < clean["high"] and clean["moves"] == 30
    long = P.estimate(([0.0] * 28 + [0.12, 0.15]) * 10, "blitz", REF)
    assert long["high"] - long["low"] < (two["high"] - two["low"]) * 0.6                         # ten games say more than one
    assert long["rating"] > two["rating"] > 1500                                                # 6.7% of moves being mistakes is better than the reference rates of 1600 (10%); one game is pulled to the middle by the prior, ten are not


def test_a_blunder_costs_more_than_a_mistake_and_the_speed_picks_the_reference_cell():
    blunder = P.estimate([0.0] * 29 + [0.3], "blitz", REF)["rating"]
    mistake = P.estimate([0.0] * 29 + [0.12], "blitz", REF)["rating"]
    assert blunder < mistake
    assert P.estimate([0.0] * 30, "bullet", REF) == P.estimate([0.0] * 30, "blitz", REF)           # bullet is read against blitz
    assert P.estimate([0.0] * 30, "classical", REF) == P.estimate([0.0] * 30, "rapid", REF)


def test_nothing_is_guessed_without_moves_a_speed_or_a_reference():
    assert P.estimate([], "blitz", REF) is None and P.estimate([0.0] * 10, None, REF) is None and P.estimate([0.0] * 10, "blitz", None) is None
    assert P.estimate([0.0] * 10, "daily", REF) is None and P.estimate([0.0] * 10, "blitz", {"cells": {}}) is None


def test_the_result_performance_follows_the_400_rule():
    assert P.by_result(1500, 1, 0) == 1900 and P.by_result(1500, 0, 1) == 1100 and P.by_result(1500, 0, 0, 1) == 1500
    assert P.by_result(1600, 6, 2, 2) == 1600 + 160 and P.by_result(None, 1, 0) is None and P.by_result(1500, 0, 0) is None
    assert P.counts([0.0, 0.1, 0.19, 0.2, 0.5]) == (1, 2, 2)


def test_the_api_gives_each_game_a_performance_and_the_overview_one_for_the_last_games(tmp_path):
    from fastapi.testclient import TestClient
    from chessme.app.config import AppConfig
    from chessme.app.main import create_app
    from chessme.app.services import games as G
    from tests.unit.test_app_api import game_moves
    cfg = AppConfig(data_dir=tmp_path / "d", research_dir=tmp_path / "r", legacy_coach_dir=tmp_path / "c", port=8765)
    with TestClient(create_app(cfg, static=False), base_url="http://127.0.0.1:8765") as c:
        s = c.app.state.sessions()
        G.store(s, id="p1", source="t", headers={"White": "me", "Black": "x", "Result": "0-1", "WhiteElo": "1500", "BlackElo": "1600", "TimeControl": "180+0", "Date": "2026.06.01"}, user_colour="white",
                analysis={"moves": game_moves()}, nodes=1, multipv=1)
        G.store(s, id="p2", source="t", headers={"White": "me", "Black": "x", "Result": "1-0"}, user_colour="white", uci_moves=["e2e4", "e7e5"])
        s.commit()
        s.close()
        g = c.get("/api/games/p1").json()
        assert g["perf"]["white"]["rating"] > 0 and g["perf"]["white"]["low"] < g["perf"]["white"]["rating"] < g["perf"]["white"]["high"] and g["perf"]["black"]["moves"] == len(game_moves()) // 2
        assert g["resultPerf"] == {"white": 1200, "black": 1900}                                      # lost to a 1600: 1600 - 400; the opponent beat a 1500: 1500 + 400
        un = c.get("/api/games/p2").json()
        assert un["perf"] == {"white": None, "black": None} and un["resultPerf"] == {"white": None, "black": None}      # not analysed, no opponent rating
        st = c.get("/api/stats").json()["performance"]
        assert st["games"] == 1 and st["rating"] and st["byResult"] == 1200
