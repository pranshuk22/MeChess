import io
import random

import numpy as np
import pytest

from chessme.style import axes as AX, model as M, population as P
from chessme.style.features import FEATURE_NAMES, INDEX
from tests.unit.test_style_model import make_positions

GAME = '''[Event "Rated Blitz game"]
[Site "https://lichess.org/{sid}"]
[White "alice"]
[Black "bob"]
[Result "1-0"]
[WhiteElo "{w}"]
[BlackElo "{b}"]
[TimeControl "{tc}"]
[Termination "Normal"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 8. c3 O-O 9. h3 Nb8 10. d4 Nbd7 1-0

'''


def sample(**kw):
    args = dict(sid="a1", w=1900, b=1900, tc="300+0")
    args.update(kw)
    return P.game_items(GAME.format(**args), lo=1800, hi=2000, time_classes=("blitz", "rapid"), per_game=4,
                        min_ply=8, rng=random.Random(0))


def test_a_suitable_game_yields_decisions_for_both_players():
    items = sample()
    assert len(items) == 4 and all(i.ply >= 8 for i in items)
    assert {i.player for i in P.game_items(GAME.format(sid="a", w=1900, b=1900, tc="300+0"), lo=1800, hi=2000,
                                           time_classes=("blitz",), per_game=50, min_ply=8, rng=random.Random(1))} == {"alice", "bob"}


def test_only_players_inside_the_rating_band_are_sampled():
    items = P.game_items(GAME.format(sid="a", w=1900, b=1500, tc="300+0"), lo=1800, hi=2000, time_classes=("blitz",),
                         per_game=50, min_ply=8, rng=random.Random(1))
    assert items and {i.player for i in items} == {"alice"} and all(i.mover_elo == 1900 for i in items)


@pytest.mark.parametrize("kw", [dict(w=1500, b=1500), dict(tc="60+0"), dict(tc="1800+0")])
def test_games_outside_band_or_time_control_are_skipped(kw):
    assert sample(**kw) == []


def test_variants_and_unrated_and_abandoned_are_skipped():
    for old, new in (('[Event "Rated Blitz game"]', '[Event "Casual Blitz game"]'),
                     ('[Termination "Normal"]', '[Termination "Abandoned"]')):
        assert P.game_items(GAME.format(sid="a", w=1900, b=1900, tc="300+0").replace(old, new), lo=1800, hi=2000,
                            time_classes=("blitz",), per_game=4, min_ply=8, rng=random.Random(0)) == []
    text = GAME.format(sid="a", w=1900, b=1900, tc="300+0").replace("[Result", '[Variant "Atomic"]\n[Result')
    assert P.game_items(text, lo=1800, hi=2000, time_classes=("blitz",), per_game=4, min_ply=8, rng=random.Random(0)) == []


def test_positions_are_the_position_before_the_played_move():
    import chess
    for it in sample():
        assert chess.Move.from_uci(it.played) in chess.Board(it.fen).legal_moves


def test_streaming_stops_at_the_requested_size_and_is_reproducible(tmp_path):
    src = tmp_path / "g.pgn"
    src.write_text("".join(GAME.format(sid=f"g{i}", w=1900, b=1900, tc="300+0") for i in range(20)))
    a = P.population_items(str(src), lo=1800, hi=2000, n_positions=30, seed=3)
    b = P.population_items(str(src), lo=1800, hi=2000, n_positions=30, seed=3)
    assert len(a) == 30 and a == b


class TestBaselineComparison:
    def test_a_player_with_a_different_taste_stands_out_and_a_twin_does_not(self):
        rng = np.random.default_rng(0)
        base = make_positions(2500, {"sacrifice": 0.0, "trade": 0.0}, rng)
        bold = make_positions(2500, {"sacrifice": 1.5}, rng)
        twin = make_positions(2500, {}, rng)
        r_bold = M.compare_to_baseline(bold, base, n_boot=12)
        r_twin = M.compare_to_baseline(twin, base, n_boot=12)
        assert r_bold["z"][INDEX["sacrifice"]] > 5
        assert np.max(np.abs(r_twin["z"])) < 4  # noise only; no feature stands out
        assert r_bold["names"] == FEATURE_NAMES

    def test_common_standardiser_makes_weights_comparable(self):
        rng = np.random.default_rng(1)
        base = make_positions(1500, {"trade": -1.0}, rng)
        std = M.standardiser(base)
        w1 = M.fit(base, standardise=std).w
        w2 = M.fit(make_positions(1500, {"trade": -1.0}, rng), standardise=std).w
        assert abs(w1[INDEX["trade"]] - w2[INDEX["trade"]]) < 0.2


class TestAxes:
    def test_axis_score_is_signed_mean_of_z(self):
        z = np.zeros(len(FEATURE_NAMES))
        for f in AX.AXES["aggression"]:
            z[INDEX[f]] = 2.0
        s = AX.axis_scores(FEATURE_NAMES, z)
        assert s["aggression"] == pytest.approx(2.0) and s["activity"] == 0.0

    def test_negative_signed_features_flip(self):
        z = np.zeros(len(FEATURE_NAMES))
        z[INDEX["own_doubled_delta"]] = 3.0
        assert AX.axis_scores(FEATURE_NAMES, z)["structural_care"] < 0

    def test_every_axis_uses_only_real_features(self):
        for feats in AX.AXES.values():
            assert set(feats) <= set(FEATURE_NAMES)

    def test_unknown_feature_is_an_error(self):
        with pytest.raises(KeyError):
            AX.axis_scores(("capture",), np.zeros(1))


class TestQuotasAndRatingModel:
    def _pgn(self, tmp_path, ratings):
        src = tmp_path / "g.pgn"
        src.write_text("".join(GAME.format(sid=f"g{i}", w=r, b=r, tc="300+0") for i, r in enumerate(ratings)))
        return str(src)

    def test_per_bin_quota_balances_the_sample(self, tmp_path):
        ratings = [1550] * 40 + [2450] * 6  # the crowded bin must not dominate
        items = P.population_items(self._pgn(tmp_path, ratings), lo=1500, hi=2500, per_bin=10, per_game=4, seed=1)
        n_low = sum(1 for i in items if i.mover_elo < 1600)
        n_high = sum(1 for i in items if i.mover_elo >= 2400)
        assert n_low == 10 and n_high == 10

    def test_stream_ends_once_every_bin_is_full(self, tmp_path):
        items = P.population_items(self._pgn(tmp_path, [1550] * 60), lo=1500, hi=1600, per_bin=8, per_game=4, seed=1)
        assert len(items) == 8  # exactly the quota, not everything in the 60 games

    def test_requires_a_size_target(self, tmp_path):
        with pytest.raises(ValueError):
            P.population_items(self._pgn(tmp_path, [1550]), lo=1500, hi=1600)

    def test_rating_dependent_fit_learns_that_taste_grows_with_rating(self):
        rng = np.random.default_rng(0)
        pos = []
        for r, taste in ((1600, 0.0), (1900, 0.8), (2300, 1.6)):
            for p in make_positions(1500, {"sacrifice": taste}, rng):
                p.rating = r
                pos.append(p)
        m = M.fit_by_rating(pos)
        F = len(FEATURE_NAMES)
        assert m.w[F + INDEX["sacrifice"]] > 0.15  # positive slope with rating
        assert M.expected_weights(m, 2300)[INDEX["sacrifice"]] > M.expected_weights(m, 1600)[INDEX["sacrifice"]]

    def test_gain_by_band_shows_where_style_is_stronger(self):
        rng = np.random.default_rng(1)
        pos = []
        for r, taste in ((1550, 0.0), (2350, 2.0)):
            for p in make_positions(1200, {"sacrifice": taste, "trade": -taste}, rng):
                p.rating = r
                pos.append(p)
        (lo1, _, n1, g1, _), (lo2, _, n2, g2, _) = M.style_gain_by_band(pos, [1500, 1600, 2300, 2400])[0], \
            M.style_gain_by_band(pos, [1500, 1600, 2300, 2400])[2]
        assert g2 > g1 + 0.05 and n1 >= 200 and n2 >= 200

    def test_bands_with_too_few_decisions_are_reported_as_nan(self):
        rng = np.random.default_rng(2)
        pos = make_positions(50, {}, rng)
        assert np.isnan(M.style_gain_by_band(pos, [1000, 2000])[0][3])

    def test_baseline_at_the_players_rating_flags_a_real_difference(self):
        rng = np.random.default_rng(3)
        base = []
        for r in (1600, 2000, 2400):
            for p in make_positions(1200, {"sacrifice": (r - 1600) / 800}, rng):
                p.rating = r
                base.append(p)
        bold = make_positions(2000, {"sacrifice": 2.5}, rng)   # far bolder than the ~0.5 expected at 2000
        for p in bold:
            p.rating = 2000
        r = M.compare_to_rating_baseline(bold, base, n_boot=10)
        assert r["z"][INDEX["sacrifice"]] > 4 and abs(r["rating"] - 2000) < 1
        typical = make_positions(2000, {"sacrifice": 0.5}, rng)
        for p in typical:
            p.rating = 2000
        assert abs(M.compare_to_rating_baseline(typical, base, n_boot=10)["z"][INDEX["sacrifice"]]) < 4


class TestSamplingLog:
    def _pgn(self, tmp_path, ratings):
        src = tmp_path / "g.pgn"
        src.write_text("".join(GAME.format(sid=f"g{i}", w=r, b=r, tc="300+0") for i, r in enumerate(ratings)))
        return str(src)

    def test_stats_report_counts_and_why_it_stopped(self, tmp_path):
        st = {}
        items = P.population_items(self._pgn(tmp_path, [1550] * 60), lo=1500, hi=1600, per_bin=8, per_game=4, seed=1, stats=st)
        assert st["stop_reason"] == "quota" and st["decisions"] == len(items) == 8
        assert st["per_bin"] == {1500: 8} and 0 < st["games_used"] <= st["games_seen"] < 60 and st["bytes_read"] > 0

    def test_running_out_of_data_is_reported_with_the_short_bin(self, tmp_path):
        st = {}
        P.population_items(self._pgn(tmp_path, [1550] * 3), lo=1500, hi=1700, per_bin=50, per_game=4, seed=1, stats=st)
        assert st["stop_reason"] == "end_of_data" and st["per_bin"][1600] == 0 and st["per_bin"][1500] < 50

    def test_byte_budget_stops_the_stream_and_says_so(self, tmp_path):
        st = {}
        P.population_items(self._pgn(tmp_path, [1550] * 400), lo=1500, hi=1600, per_bin=100000, per_game=4, seed=1,
                           budget_bytes=2000, stats=st)
        assert st["stop_reason"] == "budget" and st["games_seen"] < 400

    def test_progress_callback_gets_live_stats(self, tmp_path):
        calls = []
        P.population_items(self._pgn(tmp_path, [1550] * 30), lo=1500, hi=1600, per_bin=100000, per_game=2, seed=1,
                           progress=lambda s: calls.append((s["games_seen"], s["decisions"])), progress_every=10)
        assert [c[0] for c in calls] == [10, 20, 30] and calls[0][1] > 0


def test_full_bins_are_not_parsed_at_all():
    text = GAME.format(sid="a", w=1900, b=1900, tc="300+0")
    kw = dict(lo=1800, hi=2000, time_classes=("blitz",), per_game=4, min_ply=8, rng=random.Random(0))
    assert P.game_items(text, accept=lambda e: False, **kw) == []
    assert len(P.game_items(text, accept=lambda e: True, **kw)) == 4
