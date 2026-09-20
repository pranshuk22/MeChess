import random
import sys

import pytest

from chessme import strength as S


def test_expected_score_follows_the_elo_formula():
    assert S.expected(1500, 1500) == 0.5
    assert abs(S.expected(1700, 1500) - 0.7597) < 1e-3 and abs(S.expected(1500, 1700) - 0.2403) < 1e-3


class TestEstimate:
    def test_even_score_against_one_opponent_gives_that_opponents_rating(self):
        e = S.estimate([S.Level(1500, 50.0, 100)])
        assert abs(e.elo - 1500) < 1 and e.games == 100 and e.pinned == ""

    def test_seventy_six_percent_is_about_two_hundred_points_above(self):
        e = S.estimate([S.Level(1500, 152.0, 200)])
        assert abs(e.elo - 1699) < 4

    def test_scores_that_match_a_true_rating_at_several_levels_recover_it(self):
        true = 1800
        levels = [S.Level(o, 100 * S.expected(true, o), 100) for o in (1600, 1800, 2000)]
        assert abs(S.estimate(levels).elo - true) < 1

    def test_all_wins_or_all_losses_stay_finite_and_are_flagged_as_out_of_range(self):
        hi = S.estimate([S.Level(1500, 30.0, 30)])
        lo = S.estimate([S.Level(1500, 0.0, 30)])
        assert hi.pinned == "high" and hi.elo > 2000 and lo.pinned == "low" and lo.elo < 1000
        assert all(x == x and abs(x) < 1e6 for x in (hi.elo, lo.elo, hi.se))

    def test_more_games_mean_a_smaller_error_and_the_ci_is_1_96_se(self):
        a, b = S.estimate([S.Level(1500, 50.0, 100)]), S.estimate([S.Level(1500, 200.0, 400)])
        assert b.se < a.se and abs(a.se - 34.7) < 1.5 and abs(a.ci95 - 1.96 * a.se) < 1e-9

    def test_levels_without_games_are_ignored_and_nothing_at_all_is_an_error(self):
        assert abs(S.estimate([S.Level(1500, 5.0, 10), S.Level(2500, 0.0, 0)]).elo - S.estimate([S.Level(1500, 5.0, 10)]).elo) < 1e-6
        with pytest.raises(ValueError):
            S.estimate([S.Level(1500, 0.0, 0)])


def test_next_opponent_rounds_and_clamps():
    assert S.next_opponent(1512.4, 1320, 3190) == 1500 and S.next_opponent(1513, 1320, 3190) == 1525
    assert S.next_opponent(900, 1320, 3190) == 1320 and S.next_opponent(4000, 1320, 3190) == 3190


def simulated(true, seed, draw=0.0):
    """A `play` function whose results come from a true rating: what a real match would do, without engines."""
    rng = random.Random(seed)

    def play(opp, pairs):
        w = d = l = 0
        for _ in range(2 * pairs):
            p = S.expected(true, opp)
            if rng.random() < draw:
                d += 1
            elif rng.random() < p:
                w += 1
            else:
                l += 1
        return w, d, l
    return play


class TestLadder:
    def test_converges_from_a_bad_start_to_the_true_rating_within_its_own_error(self):
        lad = S.run_ladder(simulated(1850, seed=3), start=2600, opp_min=1320, opp_max=3190, pairs_per_round=5, target_se=40)
        assert lad.stop_reason == "target precision reached"
        assert abs(lad.estimate.elo - 1850) < 3 * lad.estimate.se + 20 and lad.estimate.games <= 400
        assert all(r["opp"] % 25 == 0 for r in lad.rounds) and lad.levels == sorted(lad.levels, key=lambda x: x.opp)

    def test_it_never_stops_before_the_minimum_number_of_games(self):
        lad = S.run_ladder(simulated(1850, seed=1), start=1850, opp_min=1320, opp_max=3190, pairs_per_round=2,
                           target_se=10_000, min_games=40)
        assert lad.estimate.games >= 40

    def test_max_games_is_a_hard_limit_with_its_own_stop_reason(self):
        lad = S.run_ladder(simulated(1850, seed=2), start=1850, opp_min=1320, opp_max=3190, pairs_per_round=5,
                           target_se=0.001, max_games=60)
        assert lad.stop_reason == "max games reached" and 60 <= lad.estimate.games <= 70

    def test_an_engine_stronger_than_every_opponent_is_reported_not_measured(self):
        lad = S.run_ladder(simulated(3800, seed=4), start=3000, opp_min=1320, opp_max=3190, pairs_per_round=5)
        assert "stronger than the strongest" in lad.stop_reason and lad.estimate.pinned == "high"

    def test_an_engine_weaker_than_every_opponent_is_reported_too(self):
        lad = S.run_ladder(simulated(600, seed=5), start=1400, opp_min=1320, opp_max=3190, pairs_per_round=5)
        assert "weaker than the weakest" in lad.stop_reason

    def test_draws_are_counted_as_half_points(self):
        lad = S.run_ladder(simulated(1850, seed=6, draw=0.5), start=1850, opp_min=1320, opp_max=3190, pairs_per_round=5, target_se=40)
        assert abs(lad.estimate.elo - 1850) < 3 * lad.estimate.se + 20

    def test_a_round_with_no_games_is_an_error_not_an_infinite_loop(self):
        with pytest.raises(RuntimeError):
            S.run_ladder(lambda opp, pairs: (0, 0, 0), start=1800, opp_min=1320, opp_max=3190)

    def test_progress_is_logged_every_round(self):
        lines = []
        S.run_ladder(simulated(1850, seed=7), start=1850, opp_min=1320, opp_max=3190, pairs_per_round=5, max_games=30,
                     min_games=20, log=lines.append)
        assert lines and all("estimate" in l and "games" in l for l in lines)


class TestEngineInfo:
    LINE = "option name UCI_Elo type spin default 1320 min 1320 max 3190"

    def test_uci_elo_range_is_parsed(self):
        assert S.parse_uci_elo_range("id name X\n" + self.LINE + "\nuciok") == (1320, 1320, 3190)
        assert S.parse_uci_elo_range("option name Hash type spin default 16 min 1 max 33554432") is None

    def test_engine_info_talks_to_a_real_process(self):
        script = ("import sys\nfor l in sys.stdin:\n if l.strip()=='uci':\n  print('id name Fake 1.0');"
                  f"print('{self.LINE}');print('uciok',flush=True)\n if l.strip()=='quit': break\n")
        info = S.engine_info([sys.executable, "-c", script])
        assert info == {"name": "Fake 1.0", "uci_elo": (1320, 1320, 3190)}
