"""Opening names from moves: the packaged dataset, the precedence of names, storing, and the background naming of games that came without one."""
import time

import chess
import pytest
from fastapi.testclient import TestClient

from chessme import openings_db as OD
from chessme.app.config import AppConfig
from chessme.app.main import create_app
from chessme.app.services import games as G
from chessme.prep import games as PG

BASE = "http://127.0.0.1:8765"


def test_the_longest_named_line_wins_and_unknown_starts_get_the_first_move_name_or_none():
    assert len(OD.table()) > 3000
    assert OD.name_for("e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6".split())[1].startswith("Ruy Lopez")
    assert OD.name_for("e2e4 e7e5 g1f3 b8c6 f1c4".split())[1].startswith("Italian Game")
    assert OD.name_for([]) is None
    assert OD.name_for(["a2a3"])[1] == "Anderssen's Opening"
    long = "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7".split()
    assert OD.name_for(long) == OD.name_for(long + ["h2h3", "d7d6"] * 30)               # only the first moves count


def test_the_name_from_the_site_comes_first_then_chesscoms_url_then_the_moves():
    moves = ["e2e4", "c7c5", "g1f3"]
    assert G.opening_name({"Opening": "Sicilian Defense: Smith-Morra"}, moves) == "Sicilian Defense: Smith-Morra"
    assert G.opening_name({"Opening": "?", "ECOUrl": "https://www.chess.com/openings/Sicilian-Defense-Open-Najdorf-Variation-6.Be3"}, moves) == "Sicilian Defense Open Najdorf Variation"
    assert G.opening_name({}, moves).startswith("Sicilian Defense")
    assert G.opening_name({}, []) is None


def test_a_stored_game_without_a_name_gets_one_from_its_moves_and_prep_games_too(tmp_path):
    cfg = AppConfig(data_dir=tmp_path / "d", research_dir=tmp_path / "r", legacy_coach_dir=tmp_path / "c", port=8765)
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        s = c.app.state.sessions()
        G.store(s, id="x1", source="test", headers={"White": "a", "Black": "b", "Result": "1-0"}, user_colour="white", uci_moves=["d2d4", "d7d5", "c2c4"])
        s.commit()
        assert s.get(G.Game, "x1").opening.startswith("Queen's Gambit")
        s.close()
    text = '[Event "x"]\n[Site "https://www.chess.com/game/live/9"]\n[White "Me"]\n[Black "o"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 1-0\n'
    assert PG.parse(text, ["me"]).family == "Ruy Lopez"


def test_games_that_came_without_a_name_are_named_in_the_background_when_the_app_starts(tmp_path):
    cfg = AppConfig(data_dir=tmp_path / "d", research_dir=tmp_path / "r", legacy_coach_dir=tmp_path / "c", port=8765)
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        s = c.app.state.sessions()
        G.store(s, id="y1", source="test", headers={"White": "a", "Black": "b", "Result": "1-0"}, user_colour="white", uci_moves=["e2e4", "e7e6"], title=None)
        g = s.get(G.Game, "y1")
        g.opening = None                                                                    # as an older version of the app stored it
        s.commit()
        s.close()
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        end = time.time() + 10
        name = None
        while time.time() < end and not name:
            time.sleep(0.1)
            name = c.get("/api/games/y1").json()["opening"]
        assert name and name.startswith("French Defense")
