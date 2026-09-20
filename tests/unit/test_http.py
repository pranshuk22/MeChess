import pytest

from chessme.ingest import http


class Resp:
    def __init__(self, status):
        self.status_code = status


def test_get_sends_generic_user_agent_and_merges_headers(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, params=None, stream=False, timeout=None):
        seen.update(headers=headers, params=params, stream=stream, timeout=timeout)
        return Resp(200)

    monkeypatch.setattr(http.requests, "get", fake_get)
    r = http.get("https://example.test", headers={"Accept": "x"}, params={"a": 1}, stream=True)
    assert r.status_code == 200
    assert seen["headers"]["Accept"] == "x"
    assert seen["headers"]["User-Agent"] == http.USER_AGENT
    assert "@" not in http.USER_AGENT  # never leak contact details / email to third parties
    assert seen["timeout"]


def test_get_backs_off_on_429_then_succeeds(monkeypatch):
    responses = [Resp(429), Resp(429), Resp(200)]
    sleeps = []
    monkeypatch.setattr(http.requests, "get", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(http.time, "sleep", lambda s: sleeps.append(s))
    assert http.get("https://example.test").status_code == 200
    assert sleeps == [65, 65]


def test_get_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(http.requests, "get", lambda *a, **k: Resp(429))
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    with pytest.raises(SystemExit):
        http.get("https://example.test", retries=3)


def test_get_retries_network_errors(monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise http.requests.ConnectionError("boom")
        return Resp(200)

    monkeypatch.setattr(http.requests, "get", flaky)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    assert http.get("https://example.test").status_code == 200
    assert calls["n"] == 3


def test_non_429_errors_are_returned_not_retried(monkeypatch):
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return Resp(404)

    monkeypatch.setattr(http.requests, "get", fake)
    assert http.get("https://example.test").status_code == 404
    assert calls["n"] == 1
