import pytest

from chessme.mechess import dial
from chessme.mechess.calibration import Calibration, isotonic


def cal(points, **kw):
    return Calibration([{"dial": d, "measured": m, "se": s} for d, m, s in points], **kw)


class TestIsotonic:
    def test_already_sorted_values_are_unchanged(self):
        assert isotonic([1, 2, 3], [1, 1, 1]) == [1, 2, 3]

    def test_violations_are_pooled_by_weight(self):
        assert isotonic([1, 3, 2, 4], [1, 1, 1, 1]) == [1, 2.5, 2.5, 4]
        assert isotonic([1, 3, 2], [1, 3, 1]) == [1, pytest.approx(2.75), pytest.approx(2.75)]   # (3*3 + 2*1) / 4

    def test_result_is_always_non_decreasing(self):
        out = isotonic([5, 1, 4, 2, 8, 3, 9], [1, 2, 1, 3, 1, 1, 2])
        assert all(a <= b for a, b in zip(out, out[1:]))


class TestCalibration:
    P = [(1200, 1400, 40), (1800, 1800, 40), (2400, 2300, 40)]

    def test_measured_interpolates_between_points_and_is_flat_outside(self):
        c = cal(self.P)
        assert c.measured(1500) == pytest.approx(1600) and c.measured(1000) == 1400 and c.measured(3000) == 2300

    def test_dial_for_is_the_inverse_of_measured(self):
        c = cal(self.P)
        for target in (1450, 1600, 1800, 2050):
            assert c.measured(c.dial_for(target)) == pytest.approx(target)
        assert c.dial_for(1600) == pytest.approx(1500)

    def test_targets_outside_the_measured_range_clamp_and_are_flagged(self):
        c = cal(self.P)
        assert c.dial_for(1000) == 1200 and c.dial_for(2800) == 2400
        assert c.in_range(1800) and not c.in_range(1000) and not c.in_range(2800)

    def test_noise_cannot_make_a_higher_dial_play_weaker(self):
        c = cal([(1200, 1500, 30), (1500, 1450, 30), (1800, 1900, 30)])   # 1500 measured below 1200: noise
        curve = c.curve()
        assert all(a[1] <= b[1] for a, b in zip(curve, curve[1:]))
        assert c.dial_for(1475) in (1200, 1500) or 1200 <= c.dial_for(1475) <= 1500

    def test_precise_points_outweigh_noisy_ones(self):
        c = cal([(1200, 1600, 10), (1500, 1400, 200)])                       # violation: pooled towards the precise point
        assert abs(c.curve()[0][1] - 1600) < 5 and abs(c.curve()[1][1] - 1600) < 5

    def test_a_flat_stretch_maps_to_the_middle_of_it(self):
        c = cal([(1200, 1500, 20), (1500, 1500, 20), (1800, 1900, 20)])
        assert c.dial_for(1500) == pytest.approx(1350)

    def test_offset_moves_the_scale(self):
        c = cal(self.P, offset=100)
        assert c.measured(1800) == pytest.approx(1900) and c.dial_for(1900) == pytest.approx(1800)

    def test_save_and_load_round_trip(self, tmp_path):
        c = cal(self.P, offset=25.0, meta={"opponent": "Stockfish X"})
        c.save(tmp_path / "sub" / "c.json")
        back = Calibration.load(tmp_path / "sub" / "c.json")
        assert back.points == c.points and back.offset == 25.0 and back.meta["opponent"] == "Stockfish X"
        assert back.dial_for(1700) == pytest.approx(c.dial_for(1700))

    def test_a_calibration_without_points_is_an_error(self):
        with pytest.raises(ValueError):
            Calibration([]).curve()


class TestDialUsesCalibration:
    def test_target_elo_is_mapped_to_the_calibrated_dial_setting(self):
        c = cal([(1200, 1400, 40), (1800, 1800, 40), (2400, 2300, 40)])
        assert dial.settings_for(1600, calibration=c) == dial.settings_for(c.dial_for(1600))
        assert dial.settings_for(1600, calibration=c).nodes != dial.settings_for(1600).nodes

    def test_without_calibration_nothing_changes(self):
        assert dial.settings_for(1700) == dial.settings_for(1700, None, None)

    def test_controller_applies_the_calibration(self):
        from tests.unit.test_mechess import LINES, START, StubEngine, prior_of
        from chessme.mechess.controller import MeChess
        c = cal([(1200, 1400, 40), (2600, 2300, 40)])
        eng = StubEngine(LINES)
        mc = MeChess(eng, prior_of({"e2e4": 1, "d2d4": 1}), None, None, 1, calibration=c)
        mc.choose(START, 1850)
        assert eng.calls[0][2] == dial.settings_for(1850, calibration=c).nodes != dial.settings_for(1850).nodes
