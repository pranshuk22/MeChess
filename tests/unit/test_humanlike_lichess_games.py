import json
import urllib.error

import pytest

from chessme.humanlike import lichess_games as L


def make_post(calls, fail=()):
    def post(ids):
        calls.append(list(ids))
        if len(calls) in fail:
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        return "\n".join(json.dumps({"id": i}) for i in ids if i != "missing") + "\n"
    return post


def test_fetch_games_batches_the_ids_and_pauses_between_requests():
    calls, sleeps = [], []
    got = list(L.fetch_games([f"g{i}" for i in range(7)], post=make_post(calls), batch=3, pause=2.0, sleep=sleeps.append, log=lambda *a: None))
    assert [g["id"] for g in got] == [f"g{i}" for i in range(7)]
    assert [len(c) for c in calls] == [3, 3, 1] and sleeps == [2.0, 2.0]


def test_missing_ids_are_simply_absent():
    got = list(L.fetch_games(["a", "missing", "b"], post=make_post([]), sleep=lambda s: None, log=lambda *a: None))
    assert [g["id"] for g in got] == ["a", "b"]


def test_a_rate_limit_answer_waits_and_retries_the_same_ids():
    calls, sleeps = [], []
    got = list(L.fetch_games(["a", "b"], post=make_post(calls, fail=(1,)), rate_limit_wait=65.0, sleep=sleeps.append, log=lambda *a: None))
    assert calls == [["a", "b"], ["a", "b"]] and sleeps == [65.0] and len(got) == 2


def test_gives_up_after_the_retries():
    calls = []
    with pytest.raises(RuntimeError):
        list(L.fetch_games(["a"], post=make_post(calls, fail=range(1, 20)), retries=3, sleep=lambda s: None, log=lambda *a: None))
    assert len(calls) == 3
