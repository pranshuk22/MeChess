import gzip
import json
import threading
from types import SimpleNamespace

import pytest

from chessme import jobs as J
from chessme.style import cohort as CO
from chessme.style import games_fetch as GF
from chessme.style import gamefeatures as G
from tests.unit.test_style_gamefeatures import RUY, make_game

SALT = "s"


def lichess_pgn(user, n=6, **kw):
    text = make_game(white_thinks=[3] * 15, base=180, inc=2, **kw)
    text = (text.replace('[White "w"]', f'[White "{user}"]').replace('[Black "b"]', '[Black "opp"]')
            .replace('[Event "?"]', '[Event "rated blitz game"]').replace('[Black "opp"]', '[Black "opp"]\n[WhiteElo "1900"]\n[BlackElo "1880"]'))
    return "".join(text + "\n\n" for _ in range(n))


def make_cohort(tmp_path, users):
    d = tmp_path / "v1"
    d.mkdir()
    (d / "salt").write_text(SALT)
    (d / "candidates.json").write_text(json.dumps({u: 1900 for u in users}))
    (d / "players.json").write_text(json.dumps({CO.player_id(u, SALT): {"bin": 4, "rating": 1900, "games": 50, "decisions": 500} for u in users}))
    return d


def getter_for(games_by_user, calls=None, hook=None):
    def g(url, headers=None, params=None, **k):
        user = url.rsplit("/", 1)[1]
        if calls is not None:
            calls.append(user)
        if hook:
            hook(user)
        if games_by_user.get(user) is None:
            return SimpleNamespace(status_code=500, text="")
        return SimpleNamespace(status_code=200, text=games_by_user[user])
    return g


def run(tmp_path, users, games, **kw):
    v1 = make_cohort(tmp_path, users)
    kw.setdefault("log", lambda *_: None)
    return GF.run(v1, tmp_path / "v2", n_games=5, min_games=3, pause=0, control_dir=tmp_path / "ctl", **kw)


class TestFetch:
    def test_players_are_processed_stored_and_free_of_usernames(self, tmp_path):
        users = ["anna", "ben"]
        stats = run(tmp_path, users, None, getter=getter_for({u: lichess_pgn(u) for u in users}))
        assert stats["done"] == 2 and not stats["stopped"]
        files = sorted((tmp_path / "v2" / "games").glob("*.json.gz"))
        assert len(files) == 2 and not list((tmp_path / "v2" / "games").glob("*.partial"))
        assert b"anna" not in gzip.decompress(files[0].read_bytes()) + gzip.decompress(files[1].read_bytes())
        d = GF.read_player(files[0])
        assert d["short"] is False and d["n"] == 5 and d["rating"] == 1900 and d["names"] == list(G.FEATURE_NAMES)
        g = d["games"][0]
        assert g["moves"].split()[:2] == ["e2e4", "e7e5"] and len(g["moves"].split()) == 30 and len(g["clocks"]) == 30
        assert len(g["feat"]) == len(G.FEATURE_NAMES) and g["meta"]["eco"] == "C84" and g["clocks"][0] == pytest.approx(179.0)      # 180 s base - 3 s think + 2 s increment

    def test_nan_features_are_stored_as_null_and_load_back_as_nan(self, tmp_path):
        run(tmp_path, ["anna"], None, getter=getter_for({"anna": lichess_pgn("anna")}))
        players = GF.load_players(tmp_path / "v2", min_games=3)
        (rating, arr, metas), = players.values()
        names = list(G.FEATURE_NAMES)
        assert rating == 1900 and arr.shape == (5, len(names)) and len(metas) == 5
        assert arr[0, names.index("w_e4")] == 1.0 and arr[0, names.index("b_e4_e5")] != arr[0, names.index("b_e4_e5")]   # NaN for White

    def test_a_rerun_does_not_fetch_finished_players_again(self, tmp_path):
        calls = []
        g = getter_for({u: lichess_pgn(u) for u in ("anna", "ben")}, calls)
        run(tmp_path, ["anna", "ben"], None, getter=g)
        assert len(calls) == 2
        stats = GF.run(tmp_path / "v1", tmp_path / "v2", n_games=5, min_games=3, pause=0, control_dir=tmp_path / "ctl",
                       log=lambda *_: None, getter=g)
        assert len(calls) == 2 and stats["done"] == 0

    def test_players_with_too_few_games_are_marked_short_and_not_refetched(self, tmp_path):
        calls = []
        g = getter_for({"anna": lichess_pgn("anna", n=2)}, calls)
        stats = run(tmp_path, ["anna"], None, getter=g)
        assert stats["short"] == 1 and stats["done"] == 0
        assert GF.load_players(tmp_path / "v2", min_games=3) == {}
        GF.run(tmp_path / "v1", tmp_path / "v2", n_games=5, min_games=3, pause=0, control_dir=tmp_path / "ctl", log=lambda *_: None, getter=g)
        assert len(calls) == 1

    def test_players_without_a_username_on_record_are_skipped(self, tmp_path):
        v1 = make_cohort(tmp_path, ["anna"])
        ids = json.loads((v1 / "players.json").read_text())
        ids["deadbeef0000"] = {"bin": 1, "rating": 1500, "games": 50, "decisions": 500}
        (v1 / "players.json").write_text(json.dumps(ids))
        logs = []
        stats = GF.run(v1, tmp_path / "v2", n_games=5, min_games=3, pause=0, control_dir=tmp_path / "ctl", log=logs.append,
                       getter=getter_for({"anna": lichess_pgn("anna")}))
        assert stats["done"] == 1 and any("1 have no username" in l for l in logs)


class TestPauseStopResume:
    def test_a_stop_request_ends_the_run_cleanly_and_the_same_command_resumes(self, tmp_path):
        users = ["anna", "ben", "cara", "dan"]
        games = {u: lichess_pgn(u) for u in users}
        calls = []
        hook = lambda user: J.set_flag("STOP", control_dir=tmp_path / "ctl") if len(calls) == 2 else None    # stop after the 2nd request
        stats = run(tmp_path, users, None, getter=getter_for(games, calls, hook))
        assert stats["stopped"] and stats["done"] == 2
        J.clear_flag("STOP", control_dir=tmp_path / "ctl")
        stats2 = GF.run(tmp_path / "v1", tmp_path / "v2", n_games=5, min_games=3, pause=0, control_dir=tmp_path / "ctl",
                        log=lambda *_: None, getter=getter_for(games, calls))
        assert stats2["done"] == 2 and not stats2["stopped"] and len(list((tmp_path / "v2" / "games").glob("*.json.gz"))) == 4

    def test_a_pause_holds_the_run_until_it_is_resumed(self, tmp_path):
        v1 = make_cohort(tmp_path, ["anna", "ben"])
        J.set_flag("PAUSE", control_dir=tmp_path / "ctl")
        calls = []
        threading.Timer(0.5, lambda: J.clear_flag("PAUSE", control_dir=tmp_path / "ctl")).start()
        import time
        t0 = time.time()
        stats = GF.run(v1, tmp_path / "v2", n_games=5, min_games=3, pause=0, control_dir=tmp_path / "ctl", log=lambda *_: None,
                       getter=getter_for({u: lichess_pgn(u) for u in ("anna", "ben")}, calls))
        assert stats["done"] == 2 and time.time() - t0 >= 0.45

    def test_the_job_is_paused_by_its_own_name_too(self, tmp_path):
        v1 = make_cohort(tmp_path, ["anna"])
        J.set_flag("PAUSE", "fetch2", control_dir=tmp_path / "ctl")
        threading.Timer(0.4, lambda: J.clear_flag("PAUSE", "fetch2", control_dir=tmp_path / "ctl")).start()
        stats = GF.run(v1, tmp_path / "v2", n_games=5, min_games=3, pause=0, control_dir=tmp_path / "ctl", log=lambda *_: None,
                       getter=getter_for({"anna": lichess_pgn("anna")}))
        assert stats["done"] == 1


class TestFailures:
    def test_failed_requests_never_create_a_file_and_stop_the_run_after_several_in_a_row(self, tmp_path):
        users = [f"u{i}" for i in range(8)]
        stats = run(tmp_path, users, None, getter=getter_for({u: None for u in users}), max_failures=3)
        assert stats["network"] and stats["done"] == 0 and stats["failed"] == 3
        assert not list((tmp_path / "v2" / "games").glob("*.json.gz"))

    def test_a_failure_followed_by_success_is_not_fatal(self, tmp_path):
        users = ["anna", "ben"]
        state = {"n": 0}
        good = {u: lichess_pgn(u) for u in users}

        def g(url, **k):
            state["n"] += 1
            u = url.rsplit("/", 1)[1]
            return SimpleNamespace(status_code=500, text="") if state["n"] == 1 else SimpleNamespace(status_code=200, text=good[u])
        stats = run(tmp_path, users, None, getter=g)
        assert stats["failed"] == 1 and stats["done"] == 1        # the failed player is retried on the next run
        stats2 = GF.run(tmp_path / "v1", tmp_path / "v2", n_games=5, min_games=3, pause=0, control_dir=tmp_path / "ctl", log=lambda *_: None, getter=g)
        assert stats2["done"] == 1

    def test_the_request_asks_for_clocks_and_openings_and_sends_no_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LICHESS_BOT_TOKEN", "must-never-be-sent")
        monkeypatch.setenv("LICHESS_TOKEN", "must-never-be-sent")
        seen = {}

        def g(url, headers=None, params=None, **k):
            seen.update(headers=headers, params=params)
            return SimpleNamespace(status_code=200, text=lichess_pgn("anna"))
        GF.fetch_games("anna", getter=g)
        assert seen["params"]["clocks"] == "true" and seen["params"]["opening"] == "true"
        assert "Authorization" not in seen["headers"] and "must-never-be-sent" not in json.dumps(seen)
