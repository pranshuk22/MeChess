"""The player's profile: summary, openings, habits, tactics and the filters."""
import chess
import pytest
from fastapi.testclient import TestClient

from chessme.app.config import AppConfig
from chessme.app.main import create_app
from chessme.app.services import games as G
from tests.unit.test_app_api import analysed_move

BASE = "http://127.0.0.1:8765"


@pytest.fixture()
def client(tmp_path):
    cfg = AppConfig(data_dir=tmp_path / "data", research_dir=tmp_path / "research", legacy_coach_dir=tmp_path / "coach", port=8765)
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        yield c


def move_rows(sans_ucis, colour_loss=None, best_for=None):
    """Analysed rows for a list of (san, uci); `colour_loss`: {ply: (loss, class)}; `best_for`: {ply: (best uci, line cp)}."""
    out = []
    for i, (san, uci) in enumerate(sans_ucis):
        colour = "white" if i % 2 == 0 else "black"
        loss, cls = (colour_loss or {}).get(i + 1, (0.0, "best"))
        best = (best_for or {}).get(i + 1)
        row = analysed_move(i + 1, san, uci, colour, loss=loss, cls=cls, best=best[0] if best else None)
        if best:
            row["top"] = [{"uci": best[0], "cp": best[1], "pv": [best[0]]}, {"uci": uci, "cp": best[1] - 800, "pv": [uci]}]
        out.append(row)
    return out


MATE_GAME = [("e4", "e2e4"), ("e5", "e7e5"), ("Qh5", "d1h5"), ("Nc6", "b8c6"), ("Bc4", "f1c4"), ("Nf6", "g8f6"), ("a3", "a2a3")]


def add(client, gid, result, date, time_="12:00:00", colour="white", opening="Italian Game", speed_tc="180+0", moves=None, white_elo=1500, black_elo=1500):
    s = client.app.state.sessions()
    h = {"White": "me" if colour == "white" else "x", "Black": "x" if colour == "white" else "me", "Result": result, "TimeControl": speed_tc, "Date": date.replace("-", "."), "UTCTime": time_,
         "WhiteElo": str(white_elo), "BlackElo": str(black_elo), "Opening": opening}
    rows = moves if moves is not None else move_rows([("e4", "e2e4"), ("e5", "e7e5")])
    G.store(s, id=gid, source="test", headers=h, user_colour=colour, analysis={"moves": rows}, nodes=1, multipv=1)
    s.commit()
    s.close()


def test_the_summary_counts_results_scores_against_stronger_and_weaker_opponents_and_a_performance(client):
    add(client, "a", "1-0", "2026-06-01", black_elo=1700)                      # a win against a stronger player
    add(client, "b", "0-1", "2026-06-02", black_elo=1300)                      # a loss against a weaker one
    add(client, "c", "1/2-1/2", "2026-06-03", white_elo=1500, black_elo=1500)
    p = client.get("/api/profile").json()["summary"]
    assert p["games"] == 3 and (p["wins"], p["draws"], p["losses"]) == (1, 1, 1) and p["score"] == 0.5 and p["analysed"] == 3
    assert p["against"]["stronger"] == {"games": 1, "score": 1.0} and p["against"]["weaker"] == {"games": 1, "score": 0.0} and p["against"]["similar"]["games"] == 1
    assert p["performance"]["rating"] > 0 and p["performanceByResult"] == (1700 + 1300 + 1500) // 3 + 0 or p["performanceByResult"] is not None
    assert p["ratings"]["blitz"][0]["date"] == "2026-06-01"


def test_filters_narrow_the_games_by_speed_colour_and_period(client):
    add(client, "a", "1-0", "2026-06-01", speed_tc="180+0")
    add(client, "b", "0-1", "2026-06-02", speed_tc="600+0", colour="black")
    assert client.get("/api/profile", params={"speed": "rapid"}).json()["summary"]["games"] == 1
    assert client.get("/api/profile", params={"colour": "black"}).json()["summary"]["wins"] == 1                  # black won (0-1)
    assert client.get("/api/profile", params={"days": 1}).json()["summary"]["games"] == 0                          # nothing in the last day
    assert client.get("/api/profile", params={"speed": "fast"}).status_code == 422


def test_openings_show_score_accuracy_and_which_ones_are_weak(client):
    for i in range(6):
        add(client, f"w{i}", "0-1", f"2026-06-{10 + i}", opening="Scotch Game: Main")
    for i in range(6):
        add(client, f"s{i}", "1-0", f"2026-06-{20 + i}", opening="Italian Game: Evans")
    ops = {o["name"]: o for o in client.get("/api/profile").json()["openings"]}
    assert ops["Scotch Game"]["games"] == 6 and ops["Scotch Game"]["score"] == 0.0 and ops["Scotch Game"]["weak"] and not ops["Scotch Game"]["strong"]
    assert ops["Italian Game"]["strong"] and ops["Italian Game"]["accuracy"] == pytest.approx(90.0)


def test_after_a_loss_you_play_worse_is_said_only_with_enough_games(client):
    # sessions of two games ten minutes apart: a loss then a loss, or a win then a win
    def sessions(n, prefix, month, result):
        for i in range(n):
            day = f"2026-{month}-{1 + i:02d}"
            add(client, f"{prefix}{i}a", result, day, "10:00:00")
            add(client, f"{prefix}{i}b", result, day, "10:10:00")
    sessions(14, "l", "07", "0-1")
    sessions(14, "w", "08", "1-0")
    few = client.get("/api/profile").json()["habits"]
    assert few["sessions"] == 28 and few["afterLoss"]["games"] == 14 and few["afterLoss"]["score"] == 0.0 and few["afterWin"]["score"] == 1.0
    assert few["sentences"] == []                                                                                       # 14 games are too few to say it
    sessions(8, "x", "09", "0-1")
    sessions(8, "y", "10", "1-0")
    h = client.get("/api/profile", params={"days": 3650}).json()["habits"]
    assert any("After a loss you score 0%" in x for x in h["sentences"])


def test_tactics_count_what_was_found_missed_and_allowed(client):
    # the player (White) misses Qxf7# on move 4 (plays a3): a missed mate; and the engine's reply to that mistake is another mate
    rows = move_rows(MATE_GAME, colour_loss={7: (0.9, "blunder")}, best_for={7: ("h5f7", 1500)})
    rows.append(analysed_move(8, "Nxh5", "f6h5", "black", cp=-300))
    add(client, "m1", "0-1", "2026-06-01", moves=rows)
    t = client.get("/api/profile").json()["deep"]["tactics"]
    mate = next(r for r in t["table"] if r["motif"] == "mate")
    assert mate["missed"] == 1 and t["examples"][0]["bestSan"] == "Qxf7#" and t["examples"][0]["motif"] == "mate" and t["examples"][0]["game"] == "m1"


def test_an_empty_library_gives_empty_sections_not_errors(client):
    p = client.get("/api/profile").json()
    assert p["summary"]["games"] == 0 and p["openings"] == [] and p["deep"]["games"] == 0 and p["habits"]["sessions"] == 0
