"""What the app knows about the player: ratings by speed with the change over 30 days, the main speed, the explorer band, openings by colour, best and weakest opening."""
import pytest
from fastapi.testclient import TestClient

from chessme.app.config import AppConfig
from chessme.app.main import create_app
from chessme.app.services import games as G
from chessme.app.services import stats as ST

BASE = "http://127.0.0.1:8765"


@pytest.fixture()
def client(tmp_path):
    cfg = AppConfig(data_dir=tmp_path / "data", research_dir=tmp_path / "research", legacy_coach_dir=tmp_path / "coach", port=8765)
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        yield c


def add(client, i, date, speed, elo, result, opening, colour="white"):
    s = client.app.state.sessions()
    tc = {"blitz": "180+0", "rapid": "600+0"}[speed]
    headers = {"White": "me" if colour == "white" else "x", "Black": "x" if colour == "white" else "me", "Result": result, "TimeControl": tc, "Date": date.replace("-", "."), "Opening": opening,
               "WhiteElo" if colour == "white" else "BlackElo": str(elo), "BlackElo" if colour == "white" else "WhiteElo": "1500"}
    G.store(s, id=f"m{i}", source="test", headers=headers, user_colour=colour, uci_moves=["e2e4", "e7e5"])
    s.commit()
    s.close()


def test_without_games_nothing_is_guessed(client):
    me = client.get("/api/me").json()
    assert me["games"] == 0 and me["ratings"] == [] and me["rating"] is None and me["band"] is None and me["stockfishLevel"] == 4 and me["name"] is None


def test_ratings_by_speed_the_main_speed_the_band_and_the_openings(client):
    client.put("/api/accounts", json={"lichess": "mypal", "chesscom": None})
    n = 0
    for k in range(12):                                                                               # 12 blitz games from mid August to the end of September, rating from 1580 to 1646
        add(client, n, f"2026-08-{10 + k:02d}" if k < 6 else f"2026-09-{2 * k:02d}", "blitz", 1580 + 6 * k, "1-0" if k % 3 else "0-1", "Italian Game: Giuoco Piano" if k < 8 else "Sicilian Defense: Najdorf", "white")
        n += 1
    for k in range(3):
        add(client, n, f"2026-09-{20 + k:02d}", "rapid", 1700, "1-0", "Caro-Kann Defense", "black")
        n += 1
    me = client.get("/api/me").json()
    assert me["name"] == "mypal" and me["handles"] == {"lichess": "mypal"} and me["games"] == 15 and me["since"] == "2026-08-10"
    blitz = next(r for r in me["ratings"] if r["speed"] == "blitz")
    assert me["mainSpeed"] == "blitz" and me["rating"] == blitz["rating"] == 1646 and me["band"] == 1600 and me["stockfishLevel"] == 5
    assert blitz["games"] == 12 and blitz["change"] == 1646 - 1610                                    # against the last game at least 30 days before the latest one
    white = me["openings"]["white"]
    assert white["top"][0]["name"] == "Italian Game" and white["top"][0]["games"] == 8
    assert white["best"]["name"] == "Italian Game" and white["weakest"] is None or white["weakest"]["name"] != white["best"]["name"]
    assert me["openings"]["black"]["top"][0]["name"] == "Caro-Kann Defense" and me["openings"]["black"]["best"] is None          # three games are too few to call it the best


def test_the_suggested_stockfish_level_follows_the_rating():
    assert [ST.stockfish_level_for(r) for r in (None, 700, 1000, 1200, 1500, 1800, 2000, 2200, 2500)] == [4, 1, 2, 3, 4, 5, 6, 7, 8]
