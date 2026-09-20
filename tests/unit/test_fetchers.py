import json
from datetime import datetime, timezone

from chessme.ingest import chesscom, lichess
from tests.samples import LICHESS_GAME, chesscom_game, fill

TOKEN = "lip_supersecret_test_token"


class FakeResp:
    def __init__(self, status=200, body=b"", json_body=None):
        self.status_code = status
        self._body = body
        self._json = json_body
        self.text = json.dumps(json_body) if json_body is not None else body.decode()

    def iter_content(self, chunk_size=1):
        yield self._body

    def json(self):
        return self._json


# ---- Lichess ---------------------------------------------------------------------------------------------

def test_lichess_fetch_writes_pgn_and_records_incremental_state(tmp_path, monkeypatch):
    calls = []
    body = fill(LICHESS_GAME, "Me", "Opp").encode()

    def fake_get(url, headers=None, params=None, stream=False):
        calls.append((url, dict(params or {}), dict(headers or {})))
        return FakeResp(200, body)

    monkeypatch.setattr(lichess, "get", fake_get)
    monkeypatch.delenv("LICHESS_TOKEN", raising=False)
    n = lichess.fetch("Me", tmp_path)
    assert n == 1
    files = list((tmp_path / "lichess" / "Me").glob("games_*.pgn"))
    assert len(files) == 1 and files[0].read_bytes() == body
    state = json.loads((tmp_path / "lichess" / "Me" / "state.json").read_text())
    expected_ms = int(datetime(2024, 3, 30, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert state["since_ms"] == expected_ms
    url, params, headers = calls[0]
    assert url.endswith("/api/games/user/Me")
    assert params["clocks"] == "true" and params["opening"] == "true" and "since" not in params
    assert "Authorization" not in headers


def test_lichess_second_fetch_is_incremental_and_creates_no_empty_file(tmp_path, monkeypatch):
    monkeypatch.setattr(lichess, "get", lambda *a, **k: FakeResp(200, fill(LICHESS_GAME, "Me", "Opp").encode()))
    lichess.fetch("Me", tmp_path)
    seen = {}

    def second(url, headers=None, params=None, stream=False):
        seen.update(params)
        return FakeResp(200, b"")

    monkeypatch.setattr(lichess, "get", second)
    assert lichess.fetch("Me", tmp_path) == 0
    expected_ms = int(datetime(2024, 3, 30, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert seen["since"] == expected_ms + 1  # strictly after the newest game we already have
    assert len(list((tmp_path / "lichess" / "Me").glob("games_*.pgn"))) == 1  # no empty file left behind


def test_lichess_token_is_sent_but_never_written_to_disk(tmp_path, monkeypatch):
    seen = {}

    def fake_get(url, headers=None, params=None, stream=False):
        seen.update(headers)
        return FakeResp(200, fill(LICHESS_GAME, "Me", "Opp").encode())

    monkeypatch.setattr(lichess, "get", fake_get)
    monkeypatch.setenv("LICHESS_TOKEN", TOKEN)
    lichess.fetch("Me", tmp_path)
    assert seen["Authorization"] == f"Bearer {TOKEN}"
    for f in tmp_path.rglob("*"):
        if f.is_file():
            assert TOKEN not in f.read_text(errors="ignore")


def test_lichess_unknown_user_and_server_errors_return_zero(tmp_path, monkeypatch):
    for status in (404, 500):
        monkeypatch.setattr(lichess, "get", lambda *a, _s=status, **k: FakeResp(_s))
        assert lichess.fetch("Nobody", tmp_path) == 0


# ---- chess.com -------------------------------------------------------------------------------------------

def month_url(user, y, m):
    return f"https://api.chess.com/pub/player/{user.lower()}/games/{y}/{m:02d}"


def test_chesscom_fetch_downloads_each_month_and_caches_old_ones(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    urls = [month_url("me", 2020, 1), month_url("me", 2020, 2), month_url("me", now.year, now.month)]
    fetched = []

    def fake_get(url, **k):
        if url.endswith("/games/archives"):
            return FakeResp(200, json_body={"archives": urls})
        fetched.append(url)
        return FakeResp(200, json_body={"games": [chesscom_game(uuid=url[-7:])]})

    monkeypatch.setattr(chesscom, "get", fake_get)
    monkeypatch.setattr(chesscom.time, "sleep", lambda s: None)
    assert chesscom.fetch("Me", tmp_path) == 3
    assert sorted(p.name for p in (tmp_path / "chesscom" / "Me").glob("*.json")) == sorted(
        ["2020-01.json", "2020-02.json", f"{now.year}-{now.month:02d}.json"])

    fetched.clear()
    assert chesscom.fetch("Me", tmp_path) == 3
    # old months are served from cache; only the current month is refreshed
    assert fetched == [urls[2]]


def test_chesscom_unknown_user_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(chesscom, "get", lambda *a, **k: FakeResp(404))
    assert chesscom.fetch("Nobody", tmp_path) == 0


def test_chesscom_failed_month_is_skipped_not_fatal(tmp_path, monkeypatch):
    urls = [month_url("me", 2020, 1), month_url("me", 2020, 2)]

    def fake_get(url, **k):
        if url.endswith("/games/archives"):
            return FakeResp(200, json_body={"archives": urls})
        if url.endswith("/01"):
            return FakeResp(500)
        return FakeResp(200, json_body={"games": [chesscom_game()]})

    monkeypatch.setattr(chesscom, "get", fake_get)
    monkeypatch.setattr(chesscom.time, "sleep", lambda s: None)
    assert chesscom.fetch("Me", tmp_path) == 1
    assert not (tmp_path / "chesscom" / "Me" / "2020-01.json").exists()  # so it will be retried next run


def test_lichess_back_to_back_fetches_never_overwrite_each_other(tmp_path, monkeypatch):
    """Regression: two runs in the same second used to share a filename and the second could destroy the first."""
    monkeypatch.setattr(lichess, "get", lambda *a, **k: FakeResp(200, fill(LICHESS_GAME, "Me", "Opp").encode()))
    lichess.fetch("Me", tmp_path)
    lichess.fetch("Me", tmp_path)
    files = list((tmp_path / "lichess" / "Me").glob("games_*.pgn"))
    assert len(files) == 2
    assert all(f.stat().st_size > 0 for f in files)
    assert not (tmp_path / "lichess" / "Me" / "download.part").exists()
