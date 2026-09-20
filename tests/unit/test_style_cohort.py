import json
import random

import chess
import numpy as np
import pytest

from chessme.style import cohort as CO
from chessme.style import reliability as RL
from chessme.style.features import INDEX
from tests.unit.test_style_model import make_positions

MOVES = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 8. c3 O-O 9. h3 Nb8 10. d4 Nbd7 1-0"


def pgn(white="alice", black="bob", welo=1900, belo=1900, tc="300+0", event="Rated Blitz game", extra="", site="x"):
    return (f'[Event "{event}"]\n[Site "https://lichess.org/{site}"]\n[White "{white}"]\n[Black "{black}"]\n'
            f'[Result "1-0"]\n[WhiteElo "{welo}"]\n[BlackElo "{belo}"]\n[TimeControl "{tc}"]\n'
            f'[Termination "Normal"]\n{extra}\n{MOVES}\n\n')


class Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


class TestCandidates:
    def _src(self, tmp_path, games):
        f = tmp_path / "d.pgn"
        f.write_text("".join(games))
        return str(f)

    def test_players_are_collected_per_rating_bin_with_a_shared_top_bin(self, tmp_path):
        games = [pgn(f"lo{i}", f"lo2{i}", 1550, 1550, site=f"a{i}") for i in range(5)] + \
                [pgn(f"hi{i}", f"hj{i}", 2450 + 10 * i, 2450, site=f"b{i}") for i in range(5)]
        st = {}
        cand = CO.collect_candidates(self._src(tmp_path, games), lo=1500, hi=2600, per_bin=3, stats=st)
        low = [n for n, e in cand.items() if e < 1600]
        high = [n for n, e in cand.items() if e >= 2400]
        assert len(low) == 3 and len(high) == 3  # quota per bin, top bin merges 2400+

    def test_bots_variants_unrated_and_bullet_are_skipped(self, tmp_path):
        games = [pgn("botty", "human", extra='[WhiteTitle "BOT"]', site="a"),
                 pgn("casual", "x1", event="Casual Blitz game", site="b"),
                 pgn("bul", "x2", tc="60+0", site="c"),
                 pgn("fine", "fine2", site="d")]
        cand = CO.collect_candidates(self._src(tmp_path, games), lo=1500, hi=2600, per_bin=10)
        assert set(cand) == {"fine", "fine2"}

    def test_out_of_range_players_and_duplicates_are_ignored(self, tmp_path):
        games = [pgn("a", "b", 1900, 1200, site="1"), pgn("a", "c", 1900, 1900, site="2")]
        cand = CO.collect_candidates(self._src(tmp_path, games), lo=1500, hi=2600, per_bin=10)
        assert cand == {"a": 1900, "c": 1900}


class TestGames:
    def test_select_keeps_the_users_games_near_their_usual_rating(self):
        texts = [pgn("me", "o", 1900, 1900, site="1"), pgn("o", "me", 1950, 1910, site="2"),
                 pgn("me", "o", 1200, 1900, site="3"),           # far below their usual rating
                 pgn("x", "y", 1900, 1900, site="4"),             # not their game
                 pgn("me", "o", 1900, 1900, tc="60+0", site="5")]  # bullet
        sel = CO.select_games(texts, "Me", n_games=10)
        assert [(c, e) for _, c, e in sel] == [(chess.WHITE, 1900), (chess.BLACK, 1910)]

    def test_select_caps_at_n_games_newest_first(self):
        texts = [pgn("me", "o", 1900, 1900, site=str(i)) for i in range(20)]
        sel = CO.select_games(texts, "me", n_games=5)
        assert len(sel) == 5 and sel[0][0] == texts[0]

    def test_decisions_are_only_the_users_own_moves(self):
        d = CO.game_decisions(pgn(), chess.BLACK, 1900, "bob", 7, per_game=50, min_ply=8, rng=random.Random(0))
        assert d and all(chess.Board(x.fen).turn == chess.BLACK and x.game == 7 and x.ply >= 8 for x in d)
        assert all(chess.Move.from_uci(x.played) in chess.Board(x.fen).legal_moves for x in d)


class TestFetch:
    def test_failed_requests_give_none(self):
        assert CO.fetch_player_games("u", getter=lambda *a, **k: Resp("", 404)) is None
        def boom(*a, **k):
            raise SystemExit("gave up")
        assert CO.fetch_player_games("u", getter=boom) is None

    def test_token_is_read_from_the_environment_only(self, monkeypatch):
        seen = {}
        def g(url, headers=None, params=None, **k):
            seen.update(headers=headers, params=params)
            return Resp(pgn())
        monkeypatch.delenv("LICHESS_TOKEN", raising=False)
        CO.fetch_player_games("u", getter=g)
        assert "Authorization" not in seen["headers"] and seen["params"]["perfType"] == "blitz,rapid"
        monkeypatch.setenv("LICHESS_TOKEN", "sekret")
        CO.fetch_player_games("u", getter=g)
        assert seen["headers"]["Authorization"] == "Bearer sekret"

    def _getter(self, games_by_user):
        calls = []
        def g(url, headers=None, params=None, **k):
            user = url.rsplit("/", 1)[1]
            calls.append(user)
            n = games_by_user.get(user, 0)
            return Resp("".join(pgn(user, "opp", 1900, 1900, site=f"{user}{i}") for i in range(n)))
        return g, calls

    def test_cohort_accepts_players_with_enough_games_and_hides_usernames(self, tmp_path):
        g, calls = self._getter({"anna": 40, "ben": 5})
        res = CO.fetch_cohort({"anna": 1900, "ben": 2150}, tmp_path, "salt", players=10, lo=1500, hi=2600, n_games=30,
                              per_game=5, min_games=30, pause=0, getter=g, log=lambda *_: None)
        idx = json.loads((tmp_path / "players.json").read_text())
        assert res["players"] == 1 and len(idx) == 1 and res["rejected"] == 1
        pid = CO.player_id("anna", "salt")
        assert idx[pid]["games"] == 30 and idx[pid]["decisions"] == 150
        raw = (tmp_path / "items" / f"{pid}.jsonl").read_text()
        assert "anna" not in raw and pid in raw
        assert "anna" not in (tmp_path / "players.json").read_text()

    def test_rerun_does_not_ask_the_api_again(self, tmp_path):
        g, calls = self._getter({"anna": 40, "ben": 5})
        kw = dict(players=10, lo=1500, hi=2600, n_games=30, per_game=3, min_games=30, pause=0, getter=g, log=lambda *_: None)
        CO.fetch_cohort({"anna": 1900, "ben": 2150}, tmp_path, "salt", **kw)
        n = len(calls)
        assert n == 2
        CO.fetch_cohort({"anna": 1900, "ben": 2150}, tmp_path, "salt", **kw)
        assert len(calls) == n

    def test_quota_is_per_rating_bin(self, tmp_path):
        g, calls = self._getter({f"u{i}": 40 for i in range(20)})
        cand = {f"u{i}": 1550 for i in range(10)} | {f"u{i}": 2450 for i in range(10, 20)}
        # 20 players over the 10 bins of 1500-2600 = 2 per bin; only bins 0 and 9 have candidates
        CO.fetch_cohort(cand, tmp_path, "s", players=20, lo=1500, hi=2600, n_games=30, per_game=2, min_games=30,
                        pause=0, getter=g, log=lambda *_: None)
        bins = sorted(v["bin"] for v in json.loads((tmp_path / "players.json").read_text()).values())
        assert bins == [0, 0, 9, 9] and len(calls) == 4

    def test_player_ids_are_stable_salted_and_case_insensitive(self):
        assert CO.player_id("Anna", "s1") == CO.player_id("anna", "s1") != CO.player_id("anna", "s2")


def cohort(n_players, taste_sd, rng, n=420, games=14):
    """Synthetic players whose taste for sacrificing / trading is a stable personal trait."""
    out = {}
    for i in range(n_players):
        taste = {"sacrifice": rng.normal(0, taste_sd), "trade": rng.normal(0, taste_sd)}
        ps = make_positions(n, taste, rng)
        for j, p in enumerate(ps):
            p.game = j % games
        out[f"p{i}"] = ps
    return out


class TestReliability:
    def test_stable_personal_taste_is_reliable_and_predicts_the_other_half(self):
        rng = np.random.default_rng(0)
        c = cohort(40, 1.2, rng)
        sh = RL.split_half(c)
        i = sh["names"].index("sacrifice")
        # taste spread 1.2 in raw units; weights are per standardised feature and a 0/1 feature has sd ~0.5 -> ~0.6
        assert sh["reliability"][i] > 0.8 and 0.45 < sh["sd_true"][i] < 0.75
        assert sh["reliability"][sh["names"].index("capture")] < 0.5
        res, n = RL.personal_vs_population(c)
        assert n == 40 and res[1.0][0] > 3 * res[1.0][1] and res[1.0][0] > 0.02

    def test_no_personal_taste_means_no_reliability_and_no_gain(self):
        rng = np.random.default_rng(1)
        c = cohort(40, 0.0, rng)
        sh = RL.split_half(c)
        assert abs(sh["reliability"][sh["names"].index("sacrifice")]) < 0.4 and sh["sd_true"][sh["names"].index("sacrifice")] < 0.3
        res, _ = RL.personal_vs_population(c)
        assert res[1.0][0] < 0.005  # own noisy half-fit is not better than the pooled style (usually worse)

    def test_split_puts_alternate_games_in_each_half(self):
        rng = np.random.default_rng(2)
        ps = make_positions(60, {}, rng)
        for j, p in enumerate(ps):
            p.game = j % 6
        a, b = RL.split_games(ps)
        assert {p.game for p in a} == {0, 2, 4} and {p.game for p in b} == {1, 3, 5} and len(a) + len(b) == 60

    def test_players_with_too_little_data_are_dropped_and_tiny_cohorts_refused(self):
        rng = np.random.default_rng(3)
        c = cohort(12, 1.0, rng)
        c["thin"] = make_positions(30, {}, rng)
        assert "thin" not in RL.usable_players(c)
        with pytest.raises(ValueError):
            RL.split_half({"a": c["p0"]})

    def test_render_is_readable(self):
        rng = np.random.default_rng(4)
        c = cohort(20, 1.0, rng)
        text = RL.render(RL.split_half(c), RL.personal_vs_population(c))
        assert "sacrifice" in text and "alpha 1.0" in text and "players analysed: 20" in text


def test_api_style_lowercase_event_is_accepted_and_casual_is_not():
    """Regression: the games API writes "rated blitz game" (lowercase); the dump writes "Rated Blitz game"."""
    api = [pgn("me", "o", 1900, 1900, event="rated blitz game", site="1"),
           pgn("me", "o", 1900, 1900, event="casual blitz game", site="2"),
           pgn("me", "o", 1900, 1900, event="Rated Rapid game", site="3")]
    assert len(CO.select_games(api, "me", n_games=10)) == 2


class TestNetworkFailures:
    """Regression: a failed request used to reject the candidate for good; only a real lack of games may do that."""

    def _flaky(self, fail_first):
        state = {"n": 0}

        def g(url, headers=None, params=None, **k):
            state["n"] += 1
            if state["n"] <= fail_first:
                raise SystemExit("network down")
            user = url.rsplit("/", 1)[1]
            return Resp("".join(pgn(user, "opp", 1900, 1900, site=f"{user}{i}") for i in range(40)))
        g.state = state
        return g

    def test_a_failed_request_is_retried_and_not_rejected(self, tmp_path):
        g = self._flaky(2)
        res = CO.fetch_cohort({"anna": 1900}, tmp_path, "s", players=10, lo=1500, hi=2600, n_games=30, per_game=2,
                              min_games=30, pause=0, getter=g, log=lambda *_: None)
        assert res["players"] == 1 and res["rejected"] == 0 and g.state["n"] == 3

    def test_many_failures_in_a_row_stop_the_run_without_rejecting_anyone(self, tmp_path):
        g = self._flaky(10 ** 6)
        logs = []
        res = CO.fetch_cohort({f"u{i}": 1900 for i in range(10)}, tmp_path, "s", players=10, lo=1500, hi=2600,
                              n_games=30, per_game=2, min_games=30, pause=0, getter=g, log=logs.append, max_failures=4)
        assert res["stopped"] == "network" and res["rejected"] == 0 and res["players"] == 0
        assert any("stopping" in l for l in logs) and not json.loads((tmp_path / "rejected.json").read_text())

    def test_too_few_games_is_still_a_rejection(self, tmp_path):
        def g(url, **k):
            return Resp(pgn("bob", "opp", 1900, 1900))  # one game only
        res = CO.fetch_cohort({"bob": 1900}, tmp_path, "s", players=10, lo=1500, hi=2600, n_games=30, per_game=2,
                              min_games=30, pause=0, getter=g, log=lambda *_: None)
        assert res["rejected"] == 1


class TestCleanTermination:
    """Regression: `pkill` (SIGTERM) used to kill the analysis parent instantly, leaving pool workers with a broken
    pipe (BrokenPipeError tracebacks in the log, leaked semaphores)."""

    def test_sigterm_becomes_keyboard_interrupt_and_the_old_handler_is_restored(self):
        import os
        import signal
        before = signal.getsignal(signal.SIGTERM)
        with pytest.raises(KeyboardInterrupt):
            with CO.terminate_cleanly():
                os.kill(os.getpid(), signal.SIGTERM)
        assert signal.getsignal(signal.SIGTERM) == before

    def test_handler_is_restored_after_a_normal_exit(self):
        import signal
        before = signal.getsignal(signal.SIGTERM)
        with CO.terminate_cleanly():
            assert signal.getsignal(signal.SIGTERM) != before
        assert signal.getsignal(signal.SIGTERM) == before


class TestShrunkTraitTest:
    def test_real_personal_taste_gives_a_positive_gain_where_full_trust_would_lose_or_barely_win(self):
        rng = np.random.default_rng(10)
        c = cohort(60, 1.2, rng, n=300)
        res = RL.shrunk_trait_test(c, min_usable=40)
        m, se = res["gain"]
        assert res["n_players"] == 30 and m > 3 * se and m > 0
        assert res["r"][res["names"].index("sacrifice")] > res["r"][res["names"].index("capture")]

    def test_no_personal_taste_gives_no_gain_and_shrinkage_does_far_less_harm_than_full_trust(self):
        rng = np.random.default_rng(11)
        c = cohort(60, 0.0, rng, n=300)
        shrunk = RL.shrunk_trait_test(c, min_usable=40)
        full, _ = RL.personal_vs_population(c, min_usable=40)
        assert shrunk["gain"][0] < 0.005
        assert shrunk["gain"][0] > full[1.0][0]          # shrinking is never worse than trusting a noisy personal fit

    def test_reliabilities_come_from_a_different_group_of_players_than_the_one_scored(self):
        rng = np.random.default_rng(12)
        c = cohort(40, 1.0, rng, n=300)
        a, b = RL.shrunk_trait_test(c, min_usable=40, seed=1), RL.shrunk_trait_test(c, min_usable=40, seed=2)
        assert a["n_players"] == b["n_players"] == 20 and not np.allclose(a["r"], b["r"])
