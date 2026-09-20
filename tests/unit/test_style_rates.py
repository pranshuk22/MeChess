import json

import chess
import numpy as np
import pytest

from chessme.style import rates as R
from chessme.style.cohort import PopItem
from chessme.style.features import FEATURE_NAMES, INDEX

F = len(FEATURE_NAMES)


def synthetic(n_players, latent_sd, seed, decisions=200, games=10, rating_effect=0.0):
    """rates dict: every player has a stable personal rate per feature (+ optional rating trend) and binomial noise."""
    rng = np.random.default_rng(seed)
    rates, ratings = {}, {}
    for i in range(n_players):
        rating = float(rng.uniform(1500, 2500))
        p = np.clip(0.3 + rng.normal(0, latent_sd, F) + rating_effect * (rating - 2000) / 1000, 0.01, 0.99)
        feats = (rng.random((decisions, F)) < p).astype(np.float32)
        rates[f"p{i}"] = (feats, np.arange(decisions) % games)
        ratings[f"p{i}"] = rating
    return rates, ratings


class TestHalves:
    def test_alternating_games_go_to_each_half(self):
        feats = np.arange(8, dtype=np.float32).reshape(8, 1) * np.ones((1, F), dtype=np.float32)
        a, b = R.half_means(feats, np.array([0, 0, 1, 1, 2, 2, 3, 3]))
        assert a[0] == pytest.approx(np.mean([0, 1, 4, 5])) and b[0] == pytest.approx(np.mean([2, 3, 6, 7]))

    def test_one_game_cannot_be_split(self):
        with pytest.raises(ValueError):
            R.half_means(np.zeros((5, F), dtype=np.float32), np.zeros(5, dtype=int))


class TestReliability:
    def test_stable_personal_rates_are_reliable_and_pure_noise_is_not(self):
        rows, n = R.reliability(synthetic(80, 0.12, 1)[0])
        assert n == 80 and np.mean([r["r_half"] for r in rows]) > 0.6
        noise, _ = R.reliability(synthetic(80, 0.0, 2)[0])
        assert abs(np.mean([r["r_half"] for r in noise])) < 0.15

    def test_spearman_brown_raises_the_full_data_reliability(self):
        rows, _ = R.reliability(synthetic(80, 0.05, 3)[0])
        assert all(r["r_full"] >= r["r_half"] - 1e-9 for r in rows if r["r_half"] > 0)

    def test_a_rate_driven_only_by_rating_is_reliable_raw_but_not_net_of_rating(self):
        rates, ratings = synthetic(120, 0.0, 4, decisions=400, rating_effect=0.35)
        rows, _ = R.reliability(rates, ratings)
        mean_raw = np.mean([r["r_half"] for r in rows])
        mean_net = np.mean([r["r_half_net_of_rating"] for r in rows])
        assert mean_raw > 0.4 and abs(mean_net) < 0.2 and np.mean([abs(r["corr_with_rating"]) for r in rows]) > 0.6

    def test_players_with_too_little_data_are_dropped(self):
        rates, _ = synthetic(20, 0.1, 5)
        rates["thin"] = (np.zeros((30, F), dtype=np.float32), np.arange(30) % 4)
        assert R.reliability(rates, min_decisions=100)[1] == 20

    def test_the_report_lists_every_feature(self):
        rows, n = R.reliability(*synthetic(40, 0.1, 6))
        text = R.render(rows, n)
        assert all(f in text for f in FEATURE_NAMES) and "net of rating" in text and "40 players" in text


MOVES = "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7 f1e1 b7b5 a4b3 d7d6 c2c3 e8g8 h2h3 c6b8"


def items_of_game(game):
    b, out = chess.Board(), []
    for ply, u in enumerate(MOVES.split()):
        if ply >= 8:
            out.append(PopItem(b.fen(), u, 1900, ply, 0, "p", game))
        b.push_uci(u)
    return out


class TestFeaturesAndCache:
    def test_item_features_describe_the_played_move(self):
        feats, games = R.item_features(items_of_game(0) + items_of_game(1))
        assert feats.shape == (2 * len(items_of_game(0)), F) and set(games.tolist()) == {0, 1}
        first = feats[0]                                  # ply 8: white castles short (e1g1)
        assert first[INDEX["castle_short"]] == 1

    def test_cohort_rates_reads_items_caches_them_and_survives_a_rerun(self, tmp_path):
        (tmp_path / "items").mkdir()
        for pid in ("a", "b"):
            (tmp_path / "items" / f"{pid}.jsonl").write_text("\n".join(json.dumps(vars(i)) for g in range(4) for i in items_of_game(g)))
        logs = []
        first = R.cohort_rates(tmp_path, log=logs.append, every=1)
        assert set(first) == {"a", "b"} and len(list((tmp_path / "rates").glob("*.npz"))) == 2 and not list((tmp_path / "rates").glob("*partial*"))
        (tmp_path / "items" / "a.jsonl").write_text("garbage that would fail to parse")   # a cached player is not re-read
        again = R.cohort_rates(tmp_path, log=lambda *_: None)
        assert np.array_equal(first["a"][0], again["a"][0]) and np.array_equal(first["b"][1], again["b"][1])


def rows_for(rates, ratings=None):
    return R.reliability(rates, ratings)[0]


class TestAnchorsAndPlayerByRates:
    def anchors(self, spread, seed, per_pole=3, decisions=1000, games=100):
        rng = np.random.default_rng(seed)
        pole_of, out = {}, {}
        centres = {"attack": np.linspace(0.15, 0.45, F), "solid": np.linspace(0.45, 0.15, F)}
        for pole, c in centres.items():
            for k in range(per_pole):
                p = np.clip(c + rng.normal(0, spread, F), 0.02, 0.98)
                feats = (rng.random((decisions, F)) < p).astype(np.float32)
                out[f"a_{pole}{k}"] = (feats, np.arange(decisions) % games)
                pole_of[f"a_{pole}{k}"] = pole
        return out, pole_of

    def test_distinct_habits_are_classified_far_above_chance_and_identical_ones_are_not(self):
        rows = rows_for(synthetic(80, 0.1, 21)[0])
        anchors, pole_of = self.anchors(0.08, 1)
        r = R.anchor_classification(anchors, pole_of, rows)
        assert r["anchor_accuracy"] > 3 * r["anchor_chance"] and r["pole_accuracy"] > 0.9 and r["n_anchors"] == 6
        rng = np.random.default_rng(3)
        same = {k: ((rng.random((1000, F)) < np.linspace(0.15, 0.45, F)).astype(np.float32), np.arange(1000) % 100) for k in anchors}
        assert R.anchor_classification(same, pole_of, rows)["pole_accuracy"] < 0.75   # identical habits: poles are a coin flip

    def test_only_cohort_reliable_features_are_used(self):
        rows = rows_for(synthetic(80, 0.1, 22)[0])
        rows[0]["r_half"] = 0.0
        assert rows[0]["name"] not in R.reliable_features(rows) and len(R.reliable_features(rows)) == F - 1

    def test_too_few_anchors_is_an_error(self):
        rows = rows_for(synthetic(40, 0.1, 23)[0])
        anchors, pole_of = self.anchors(0.05, 4, per_pole=1)
        with pytest.raises(ValueError):
            R.anchor_classification({k: v for k, v in anchors.items() if "attack" in k}, pole_of, rows)

    def test_a_players_profile_lists_reliable_features_most_extreme_first(self):
        rates, _ = synthetic(100, 0.12, 24)
        rows = rows_for(rates)
        mean, sd = R.cohort_scale(rows)
        player = np.tile(mean, (50, 1)).astype(np.float32)
        player[:, 3] = mean[3] + 3 * sd[3]                    # three cohort SDs above average on feature 3
        prof = R.player_profile(player, rows)
        assert prof[0][0] == FEATURE_NAMES[3] and prof[0][3] == pytest.approx(3.0, abs=0.01)
        assert all(abs(prof[i][3]) >= abs(prof[i + 1][3]) for i in range(len(prof) - 1))

    def test_the_report_text_has_both_parts(self):
        rows = rows_for(synthetic(60, 0.1, 25)[0])
        anchors, pole_of = self.anchors(0.08, 5)
        cls = R.anchor_classification(anchors, pole_of, rows)
        text = R.render_who(cls, R.player_profile(np.full((20, F), 0.3, dtype=np.float32), rows))
        assert "anchor level" in text and "pole level" in text and "habit rates against the cohort" in text
