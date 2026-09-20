import numpy as np
import pytest

from chessme.style import reliability as RL
from chessme.style import summary as SU
from chessme.style.features import FEATURE_NAMES, INDEX
from tests.unit.test_style_cohort import cohort
from tests.unit.test_style_model import make_positions

F = len(FEATURE_NAMES)


@pytest.fixture(scope="module")
def sh():
    rng = np.random.default_rng(0)
    return RL.split_half(cohort(50, 1.2, rng, n=300), min_usable=40)


def user_with(taste, seed, n=800, games=20):
    ps = make_positions(n, taste, np.random.default_rng(seed))
    for j, p in enumerate(ps):
        p.game = j % games
    return ps


def test_split_half_now_returns_the_per_player_vectors(sh):
    assert sh["WA"].shape == sh["WB"].shape == (50, F + 1) and len(sh["ids"]) == 50


class TestMeVsCohort:
    def test_an_extreme_player_stands_out_on_a_reliable_preference_only(self, sh):
        rows, w = SU.me_vs_cohort(user_with({"sacrifice": 4.0}, 1), sh, n_boot=6)
        by = {r["name"]: r for r in rows}
        assert by["sacrifice"]["reliability"] > 0.5 and by["sacrifice"]["z_shrunk"] > 1.5 and by["sacrifice"]["z_raw"] > 2
        assert abs(by["capture"]["z_shrunk"]) < abs(by["sacrifice"]["z_shrunk"]) / 2
        assert len(rows) == F + 1 and w.shape == (F + 1,)

    def test_an_average_player_is_near_zero_everywhere(self, sh):
        rows, _ = SU.me_vs_cohort(user_with({}, 2), sh, n_boot=6)
        assert max(abs(r["z_shrunk"]) for r in rows if r["reliability"] > 0.3) < 2.5

    def test_features_nobody_varies_on_are_never_reported_as_personal(self, sh):
        rows, _ = SU.me_vs_cohort(user_with({"sacrifice": 4.0}, 3), sh, n_boot=4)
        for r in rows:
            if r["sd_between"] <= 1e-6:
                assert r["z_shrunk"] == 0.0


class TestAxes:
    def test_reliability_is_high_for_an_axis_with_a_real_personal_trait_and_low_without(self, sh):
        ax = SU.axis_table(sh, np.zeros(F + 1))
        assert ax["aggression"]["reliability"] > 0.4            # contains "sacrifice", the trait built into the cohort
        assert ax["activity"]["reliability"] < ax["aggression"]["reliability"]

    def test_the_players_axis_score_is_shrunk_by_reliability(self, sh):
        _, w = SU.me_vs_cohort(user_with({"sacrifice": 4.0}, 4), sh, n_boot=4)
        d = SU.axis_table(sh, w)["aggression"]
        assert d["z_observed"] > 1 and 0 < d["z_shrunk"] < d["z_observed"]


def anchors_and_poles(rng, per_pole=3, n=500, games=16):
    tastes = {"attack": {"sacrifice": 2.0, "trade": -2.0}, "solid": {"sacrifice": -2.0, "trade": 2.0}}
    anchors, pole_of = {}, {}
    for pole, t in tastes.items():
        for k in range(per_pole):
            ps = make_positions(n, t, rng)
            for j, p in enumerate(ps):
                p.game = j % games
            key = f"anchor_{pole}{k}"
            anchors[key], pole_of[key] = ps, pole
    return anchors, pole_of


class TestPoles:
    def test_poles_with_different_tastes_are_told_apart(self):
        anchors, pole_of = anchors_and_poles(np.random.default_rng(5))
        r = SU.pole_confusion(anchors, pole_of)
        assert r["poles"] == ["attack", "solid"] and r["chunks"] >= 20 and r["accuracy"] > 0.8 and r["chance"] == 0.5

    def test_poles_with_the_same_taste_are_at_chance(self):
        rng = np.random.default_rng(6)
        anchors, pole_of = anchors_and_poles(rng)
        for key in anchors:  # replace every anchor's data by the same taste
            ps = make_positions(500, {"sacrifice": 1.0}, rng)
            for j, p in enumerate(ps):
                p.game = j % 16
            anchors[key] = ps
        assert SU.pole_confusion(anchors, pole_of)["accuracy"] < 0.7

    def test_the_players_choices_are_closest_to_the_pole_with_the_same_taste(self):
        anchors, pole_of = anchors_and_poles(np.random.default_rng(7))
        train, test = user_with({"sacrifice": 2.0, "trade": -2.0}, 8), user_with({"sacrifice": 2.0, "trade": -2.0}, 9, n=500)
        r = SU.user_vs_poles(anchors, pole_of, train, test)
        assert r["poles"][0][0] == "attack" and r["poles"][-1][0] == "solid" and r["own"] < r["uniform"]

    def test_anchors_without_a_pole_or_with_too_little_data_are_ignored_and_one_pole_is_refused(self):
        anchors, pole_of = anchors_and_poles(np.random.default_rng(10))
        anchors["anchor_stray"] = anchors["anchor_attack0"]
        assert "anchor_stray" not in SU.pole_models(anchors, pole_of)[1]
        with pytest.raises(ValueError):
            SU.pole_confusion({k: v for k, v in anchors.items() if k.startswith("anchor_attack")}, pole_of)


def test_the_report_has_every_section_and_says_what_it_does_not_claim(sh):
    rows, w = SU.me_vs_cohort(user_with({"sacrifice": 3.0}, 11), sh, n_boot=4)
    anchors, pole_of = anchors_and_poles(np.random.default_rng(12))
    text = SU.render(label="Test", n_user=800, n_cohort=50, me_rows=rows, axes=SU.axis_table(sh, w),
                     poles=SU.pole_confusion(anchors, pole_of),
                     user_poles=SU.user_vs_poles(anchors, pole_of, user_with({}, 13), user_with({}, 14, n=400)),
                     population=[("trade", 2.3), ("castle_short", 2.8)],
                     shrunk={"gain": (0.002, 0.0004), "n_players": 500})
    for needle in ("# Style summary: Test", "## 1. Against the cohort", "## 2. The five hypothesis axes", "## 3. Against the rating-matched",
                   "## 4. Anchors at the level of style poles", "## 5. Is there personal signal", "have reliability below",
                   "a real but small signal", "| sacrifice |", "chance 50%"):
        assert needle in text, needle
    assert "no detectable signal" in SU.render(label="T", n_user=1, n_cohort=1, me_rows=rows, axes={}, shrunk={"gain": (0.0, 0.01), "n_players": 3})
