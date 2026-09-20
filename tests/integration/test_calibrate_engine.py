"""The measurement plumbing with real UCI processes. The opponent here is our own engine (so the tests need no Stockfish);
its 'Elo' options are replaced by plain ones, which is all the ladder machinery needs to be exercised."""
import math

import pytest

from chessme import calibrate as C
from chessme import openings
from chessme.match import EngineSpec, SearchLimit
from chessme.mechess.calibration import Calibration

pytestmark = pytest.mark.integration


def opts(elo):
    return {"Hash": 16}


def test_a_real_measurement_runs_end_to_end_with_no_engine_faults(engine_path):
    fens = openings.random_openings(6, seed=3)
    spec = EngineSpec.make("plain", str(engine_path))
    r = C.measure(spec, str(engine_path), fens, SearchLimit(movetime=20), start=1500, opponent_options=opts,
                  opp_range=(1000, 2000), pairs_per_round=1, min_games=4, max_games=6, log=lambda *_: None)
    assert r["games"] >= 4 and r["faults"] == 0 and math.isfinite(r["elo"]) and r["levels"]


@pytest.mark.slow
def test_mechess_is_measured_through_the_dial_calibration_path(engine_path, tmp_path):
    fens = openings.random_openings(4, seed=5)
    cal = C.calibrate_dial([1200], C.mechess_command(engine_path, "uniform"), str(engine_path), fens,
                           SearchLimit(movetime=20), tmp_path / "dial.json", log=lambda *_: None,
                           opponent_options=opts, opp_range=(1000, 2000), pairs_per_round=1, min_games=2, max_games=2)
    assert isinstance(cal, Calibration) and cal.points[0]["dial"] == 1200 and cal.points[0]["games"] == 2
    assert cal.points[0]["faults"] == 0 and (tmp_path / "dial.json").exists()
