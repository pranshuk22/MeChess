import pytest

from chessme.mechess import design as D
from chessme.mechess.calibration import censored
from chessme.mechess.dial import DEFAULT_TABLE, _row, settings_for


def test_the_path_starts_at_the_weak_row_and_ends_at_the_anchor_row():
    anchor = DEFAULT_TABLE[1800]
    assert D.path_row(400, 400, 1800, D.WEAK_ROW, anchor) == (60, 8, 350, 2.0, 250.0, 4, 0.4)
    assert D.path_row(1800, 400, 1800, D.WEAK_ROW, anchor) == (4000, 6, 120, 1.1, 80.0, 22, 0.0)


def test_knobs_move_monotonically_towards_the_anchor_and_nodes_grow_geometrically():
    t = D.weak_end_table()
    labels = [k for k in sorted(t) if k <= 1800]
    rows = [t[k] for k in labels]
    nodes = [r[0] for r in rows]
    assert all(a < b for a, b in zip(nodes, nodes[1:]))
    ratios = [b / a for a, b in zip(nodes, nodes[1:])]
    assert max(ratios) / min(ratios) < 1.35                                   # even steps on a log scale
    for col, direction in ((2, -1), (3, -1), (4, -1), (5, +1), (6, -1)):      # window, T, scale shrink; book grows; blunder shrinks
        vals = [r[col] for r in rows]
        assert all(direction * (b - a) >= 0 for a, b in zip(vals, vals[1:])), col


def test_rows_from_the_anchor_upwards_are_the_original_ones_so_their_measurements_stay_valid():
    t = D.weak_end_table()
    for k in (1800, 2100, 2400, 2600):
        assert t[k] == _row(DEFAULT_TABLE[k])       # same numbers (padded with a zero blunder rate)
    assert 1200 not in t or t[1200] != DEFAULT_TABLE[1200]                      # the old low rows are replaced


def test_the_table_works_with_settings_for_and_gives_a_blunder_rate_at_the_bottom():
    t = D.weak_end_table()
    assert settings_for(400, t).blunder_rate == pytest.approx(0.4) and settings_for(1800, t).blunder_rate == 0.0
    assert 0.0 < settings_for(1500, t).blunder_rate < settings_for(700, t).blunder_rate


def test_labels_outside_the_path_and_a_missing_anchor_row_are_errors():
    with pytest.raises(ValueError):
        D.path_row(300, 400, 1800, D.WEAK_ROW, DEFAULT_TABLE[1800])
    with pytest.raises(ValueError):
        D.weak_end_table(anchor_table={2100: DEFAULT_TABLE[2100]})


def test_the_skeleton_marks_weak_settings_for_linking_and_copies_the_measured_anchors():
    t = D.weak_end_table((400, 800, 1200))
    measured = [{"dial": 1800, "measured": 1236.0, "se": 35.0, "games": 120, "stop": "target precision reached", "faults": 0},
                {"dial": 2100, "measured": 1531.0, "se": 35.0, "games": 120, "stop": "target precision reached", "faults": 0}]
    pts = D.skeleton({k: v for k, v in t.items() if k <= 2100}, measured)
    by = {p["dial"]: p for p in pts}
    assert [censored(by[k]) for k in (400, 800, 1200)] == [True, True, True]
    assert not censored(by[1800]) and by[1800]["measured"] == 1236.0 and by[2100]["measured"] == 1531.0
    with pytest.raises(ValueError, match="cannot anchor"):
        D.skeleton(t, measured)                                                # 2400 / 2600 rows have no measurement here
