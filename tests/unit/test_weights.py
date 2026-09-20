import pytest

from chessme.dataset.weights import Weighter
from tests.samples import make_row

CFG = {"filters": {
    "min_rating": {"lichess": 1400, "chesscom": 1200},
    "recency": {"half_life_days": 100, "min_weight": 0.1},
    "time_class_weights": {
        "bullet": {"full_until_ply": 20, "late_weight": 0.1},
        "blitz": 1.0, "rapid": 1.0, "correspondence": 0.0,
    },
}}
NEWEST = "2024-12-31T00:00:00+00:00"


def weighter(rows, cfg=CFG):
    return Weighter(cfg, rows)


def rows_with_newest(*rows):
    return [make_row(played_at=NEWEST, game_id="newest"), *rows]


def test_newest_game_has_full_weight():
    r = make_row(played_at=NEWEST)
    assert weighter([r]).game_weight(r) == pytest.approx(1.0)


def test_recency_halves_every_half_life():
    old = make_row(played_at="2024-09-22T00:00:00+00:00", game_id="old")  # exactly 100 days before NEWEST
    w = weighter(rows_with_newest(old))
    assert w.game_weight(old) == pytest.approx(0.5, rel=1e-3)


def test_recency_has_a_floor():
    ancient = make_row(played_at="2020-01-01T00:00:00+00:00", game_id="a")
    assert weighter(rows_with_newest(ancient)).game_weight(ancient) == pytest.approx(0.1)


def test_rating_floor_is_per_platform_scale():
    li_low = make_row(platform="lichess", my_rating=1399, game_id="1")
    li_ok = make_row(platform="lichess", my_rating=1400, game_id="2")
    cc_ok = make_row(platform="chesscom", my_rating=1200, game_id="3")
    cc_low = make_row(platform="chesscom", my_rating=1199, game_id="4")
    rows = [li_low, li_ok, cc_ok, cc_low]
    w = weighter(rows)
    assert w.game_weight(li_low) == 0 and w.game_weight(cc_low) == 0
    assert w.game_weight(li_ok) > 0 and w.game_weight(cc_ok) > 0
    # the same 1300 rating passes on chess.com but not on Lichess
    assert w.game_weight(make_row(platform="chesscom", my_rating=1300)) > 0
    assert w.game_weight(make_row(platform="lichess", my_rating=1300)) == 0


def test_unusable_and_excluded_time_classes_get_zero():
    w = weighter([make_row()])
    assert w.game_weight(make_row(usable=False, unusable_reason="too_short")) == 0
    assert w.game_weight(make_row(time_class="correspondence")) == 0


def test_bullet_is_trusted_early_and_down_weighted_late():
    r = make_row(time_class="bullet", played_at=NEWEST)
    w = weighter([r])
    assert w.move_weight(r, 0) == pytest.approx(1.0)
    assert w.move_weight(r, 19) == pytest.approx(1.0)
    assert w.move_weight(r, 20) == pytest.approx(0.1)
    assert w.move_weight(r, 60) == pytest.approx(0.1)


def test_slower_time_controls_are_flat():
    r = make_row(time_class="rapid", played_at=NEWEST)
    w = weighter([r])
    assert w.move_weight(r, 0) == w.move_weight(r, 80) == pytest.approx(1.0)


def test_move_weight_multiplies_recency_and_time_class():
    old_bullet = make_row(time_class="bullet", played_at="2024-09-22T00:00:00+00:00", game_id="b")
    w = weighter(rows_with_newest(old_bullet))
    assert w.move_weight(old_bullet, 30) == pytest.approx(0.5 * 0.1, rel=1e-3)


def test_excluded_games_have_zero_move_weight():
    r = make_row(my_rating=900)
    assert weighter([r]).move_weight(r, 0) == 0


def test_my_plies_depend_on_colour():
    w = weighter([make_row()])
    assert list(w.my_plies(make_row(color="white", plies=6))) == [0, 2, 4]
    assert list(w.my_plies(make_row(color="black", plies=6))) == [1, 3, 5]
    assert list(w.my_plies(make_row(color="white", plies=5))) == [0, 2, 4]


def test_no_recency_config_means_no_decay():
    cfg = {"filters": {"time_class_weights": {}}}
    r = make_row(played_at="2020-01-01T00:00:00+00:00")
    assert Weighter(cfg, [r, make_row(played_at=NEWEST, game_id="n")]).game_weight(r) == 1.0
