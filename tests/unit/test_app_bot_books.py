"""The Lichess bot launcher (a fake launcher script) and the searchable index of the book comments."""
import gzip
import json
import os
import stat
import time

import pytest
from fastapi.testclient import TestClient

from chessme.app.config import AppConfig
from chessme.app.main import create_app
from tests.unit.test_app_import import wait

BASE = "http://127.0.0.1:8765"


def make_client(tmp_path, **kw):
    cfg = AppConfig(data_dir=tmp_path / "data", research_dir=tmp_path / "research", legacy_coach_dir=tmp_path / "coach", bot_dir=tmp_path / "bot", port=8765, **kw)
    return TestClient(create_app(cfg, static=False), base_url=BASE)


@pytest.fixture()
def client(tmp_path):
    with make_client(tmp_path) as c:
        yield c


# ---- the bot ------------------------------------------------------------------------------------------------------------------------------------------

def install_bot(tmp_path):
    d = tmp_path / "bot"
    (d / "logs").mkdir(parents=True)
    run = d / "run-bot.sh"
    run.write_text(f"#!/bin/bash\necho started >> {d}/logs/bot.log\necho \"token seen: ${{LICHESS_BOT_TOKEN:+yes}}\" >> {d}/logs/bot.log\nexec sleep 60\n")
    run.chmod(run.stat().st_mode | stat.S_IEXEC)
    return d


def test_the_bot_page_says_when_nothing_is_installed(client):
    st = client.get("/api/bot").json()
    assert st["installed"] is False and st["running"] is False and st["log"] == []
    assert client.post("/api/bot/start").status_code == 409 and "not installed" in client.post("/api/bot/start").json()["detail"]
    assert client.post("/api/bot/stop").status_code == 409


def test_without_a_token_the_bot_is_not_started_and_the_message_says_where_it_goes(tmp_path, monkeypatch):
    monkeypatch.delenv("LICHESS_BOT_TOKEN", raising=False)
    monkeypatch.setattr("chessme.app.bot_service.sys.platform", "linux")
    install_bot(tmp_path)
    with make_client(tmp_path) as c:
        st = c.get("/api/bot").json()
        assert st["installed"] and st["token"] is False
        r = c.post("/api/bot/start")
        assert r.status_code == 409 and "LICHESS_BOT_TOKEN" in r.json()["detail"]


def test_the_bot_starts_runs_shows_its_log_and_stops_and_the_app_never_sees_the_token(tmp_path, monkeypatch):
    monkeypatch.setenv("LICHESS_BOT_TOKEN", "SECRET-TOKEN-VALUE")
    install_bot(tmp_path)
    with make_client(tmp_path) as c:
        assert c.post("/api/bot/start").status_code == 202
        deadline = time.time() + 10
        while time.time() < deadline and "token seen: yes" not in "\n".join(c.get("/api/bot").json()["log"]):
            time.sleep(0.1)
        st = c.get("/api/bot").json()
        assert st["running"] and "started" in st["log"] and "token seen: yes" in st["log"] and st["token"] is True
        assert "SECRET-TOKEN-VALUE" not in json.dumps(st)                                                # status never contains the token
        assert c.post("/api/bot/start").status_code == 409 and "already running" in c.post("/api/bot/start").json()["detail"]
        assert c.post("/api/bot/stop").status_code == 200 and c.get("/api/bot").json()["running"] is False


def test_closing_the_app_stops_the_bot_it_started(tmp_path, monkeypatch):
    monkeypatch.setenv("LICHESS_BOT_TOKEN", "x")
    install_bot(tmp_path)
    with make_client(tmp_path) as c:
        c.post("/api/bot/start")
        proc = c.app.state.bot.proc
        assert proc.poll() is None
    assert proc.poll() is not None


# ---- the books ----------------------------------------------------------------------------------------------------------------------------------------

RECORDS = [
    {"ply": 11, "color": "white", "fen": "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P1B2/2PBPN2/PP1N1PPP/R2QK2R w KQ - 0 10", "uci": "e3e4", "san": "e4", "glyph": "!", "comment": "Now White breaks in the centre and the outpost on e5 becomes strong.", "concepts": {"outpost": 1, "centre": 1}, "source": "gameknot"},
    {"ply": 20, "color": "black", "fen": "4k3/8/8/8/8/8/4P3/4K3 b - - 0 1", "uci": "e8e7", "san": "Ke7", "glyph": None, "comment": "A classic case of zugzwang: whoever must move loses.", "concepts": {"zugzwang": 2}, "source": "pgn-library"},
    {"ply": 3, "color": "white", "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "uci": "g1f3", "san": "Nf3", "comment": "Develops a piece. O'Brien said \"always develop\" (a quote) AND more -- with symbols *()^", "concepts": {}, "source": "gutenberg"},
    {"ply": 5, "color": "white", "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "uci": "e2e4", "san": "e4", "comment": "", "concepts": {}},
]


def write_books(tmp_path):
    d = tmp_path / "research" / "books_learn" / "run" / "annotated"
    d.mkdir(parents=True)
    with gzip.open(d / "annotated_moves.jsonl.gz", "wt") as f:
        for r in RECORDS:
            f.write(json.dumps(r) + "\n")
        f.write("not json\n")


def test_books_report_when_the_reader_output_is_missing(client):
    assert client.get("/api/books").json() == {"indexed": 0, "available": False, "concepts": []}
    assert client.get("/api/books/search", params={"q": "zugzwang"}).json() == {"total": 0, "items": []}
    j = wait(client, client.post("/api/books/index").json())
    assert j["status"] == "failed" and "books-learn" in j["message"]


def test_the_comments_are_indexed_and_found_by_words_and_concepts(tmp_path):
    write_books(tmp_path)
    with make_client(tmp_path) as c:
        assert c.get("/api/books").json()["available"] is True
        j = wait(c, c.post("/api/books/index").json())
        assert j["status"] == "done" and "3 comments indexed" in j["message"]                              # the empty comment and the broken line are left out
        st = c.get("/api/books").json()
        assert st["indexed"] == 3 and {x["name"]: x["count"] for x in st["concepts"]} == {"outpost": 1, "centre": 1, "zugzwang": 1}
        r = c.get("/api/books/search", params={"q": "zugzwang"}).json()
        assert r["total"] == 1 and r["items"][0]["san"] == "Ke7" and r["items"][0]["concepts"] == ["zugzwang"]
        assert c.get("/api/books/search", params={"q": "outp"}).json()["total"] == 1                         # a word prefix
        assert c.get("/api/books/search", params={"q": "centre outpost"}).json()["total"] == 1                # all words
        assert c.get("/api/books/search", params={"concept": "outpost"}).json()["items"][0]["glyph"] == "!"
        assert c.get("/api/books/search", params={"q": "classic", "concept": "outpost"}).json()["total"] == 0
        assert c.get("/api/books/search").json()["total"] == 3 and len(c.get("/api/books/search", params={"limit": 2}).json()["items"]) == 2
        for nasty in ['"', "AND OR NOT", "*()^", "a\" OR \"b", "NEAR(", "-", "O'Brien", ""]:
            assert c.get("/api/books/search", params={"q": nasty}).status_code == 200, nasty                 # whatever is typed cannot break the query
        assert c.get("/api/books/search", params={"concept": "x'; DROP TABLE book_notes;--"}).json()["total"] == 3     # an odd concept name is ignored, not executed
        again = wait(c, c.post("/api/books/index").json())
        assert "3 comments indexed" in again["message"] and c.get("/api/books").json()["indexed"] == 3        # indexing again replaces, not doubles
