import json
import sqlite3

import pytest

from chessme.analysis import accuracy as A


def test_a_game_of_perfect_moves_is_100_and_one_blunder_costs_far_more_than_its_share_of_a_plain_average():
    cps = [20] * 40
    assert A.game_accuracy(cps, [100.0] * 40)["white"] == pytest.approx(100.0)
    cps[20] = cps[21] = -300
    accs = [100.0] * 40
    accs[20], accs[21] = 30.0, 30.0
    got = A.game_accuracy(cps, accs)
    plain = sum(accs[0::2]) / 20
    assert plain == pytest.approx(96.5) and got["white"] < plain - 5               # the plain average hid the blunder; the harmonic and volatility-weighted means do not
    assert 0 <= got["black"] <= 100


def test_moves_in_quiet_positions_count_less_than_moves_in_sharp_ones():
    quiet, sharp = [10] * 30, [10] * 12 + [400, -400, 400, -400, 400, -400] + [10] * 12
    w_quiet, w_sharp = A.weights(quiet), A.weights(sharp)
    assert max(w_quiet) <= 0.5 + 1e-9 and max(w_sharp) > 5 and len(w_sharp) == 30


def test_phases_are_combined_per_colour_and_missing_phases_are_none():
    cps, accs = [20] * 20, [100.0] * 20
    phases = ["opening"] * 10 + ["middlegame"] * 10
    out = A.game_accuracy(cps, accs, phases)
    assert out["by_phase"]["white"]["opening"] == pytest.approx(100.0) and out["by_phase"]["white"]["endgame"] is None
    assert A.game_accuracy([], [])["white"] is None


def test_the_migration_recomputes_stored_accuracy(tmp_path):
    """Regression: stored games kept the generous plain average; the migration moves them to the new figure."""
    import importlib
    from types import SimpleNamespace
    from sqlalchemy import create_engine
    mig = importlib.import_module("chessme.app.migrations.versions.0007_accuracy_recomputed")
    moves = [{"cp": 20 if i not in (20, 21) else -300, "acc": 100.0 if i not in (20, 21) else 30.0, "phase": "middlegame"} for i in range(40)]
    eng = create_engine(f"sqlite:///{tmp_path / 'x.db'}")
    with eng.begin() as conn:
        conn.exec_driver_sql("create table analyses (game_id text, moves text, accuracy_white float, accuracy_black float)")
        conn.exec_driver_sql("insert into analyses values ('g', ?, 96.5, 96.5)", (json.dumps(moves),))
        mig.op = SimpleNamespace(get_bind=lambda: conn)                   # only this module's `op` is replaced, nothing global
        mig.upgrade()
    acc = sqlite3.connect(tmp_path / "x.db").execute("select accuracy_white from analyses").fetchone()[0]
    assert acc < 91
