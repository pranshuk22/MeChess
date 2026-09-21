import io
import json

import chess
import numpy as np
import pytest

from chessme.mechess import agreement as AG
from chessme.mechess import clock as CK
from chessme.mechess.controller import MeChess
from chessme.mechess.priors import UniformPrior
from chessme.mechess.uci import MechessUci
from tests.unit.test_mechess import L, StubEngine, table


def test_time_classes_and_stages():
    assert [CK.time_class(*x) for x in ((15, 0), (60, 0), (180, 0), (180, 2), (300, 0), (600, 0), (900, 10), (1800, 0))] == \
        ["ultrabullet", "bullet", "blitz", "blitz", "blitz", "rapid", "rapid", "classical"]
    assert [CK.stage(p) for p in (0, 9, 10, 19, 20, 39, 40, 200)] == [0, 0, 1, 1, 2, 2, 3, 3]


def test_simple_moves_are_recaptures_or_almost_forced():
    b = chess.Board()
    for m in "e2e4 d7d5 e4d5".split():
        b.push_uci(m)
    assert CK.simple(b)                                                     # black can recapture on d5 (queen or knight)
    assert not CK.simple(chess.Board())
    assert CK.simple(chess.Board("7k/8/8/8/8/8/5q2/K7 w - - 0 1"))            # the king has two legal squares at most
    b = chess.Board()
    b.push_uci("e2e4")
    assert not CK.simple(b)                                                 # no capture: nothing forced


def row(clocks, color="white", tc="60+0", moves="e4 e5 Nf3 Nc6 Bb5 a6", platform="lichess"):
    return {"platform": platform, "usable": True, "color": color, "time_control": tc, "clocks": clocks, "moves": moves}


def test_think_times_are_read_from_the_clocks_with_increment():
    tt = CK.think_times(row([60, 60, 58, 59, 55, 56], tc="60+2"))
    assert [(p, prev, round(t, 1)) for p, prev, t, _, _ in tt] == [(0, 60.0, 2.0), (2, 60.0, 4.0), (4, 58.0, 5.0)]
    assert CK.think_times(row([60, 60, 58, 59, 55, 56], color="black"))[0][:3] == (1, 60.0, 0.0)
    assert CK.think_times(row([None] * 6)) == [] and CK.think_times(row([60] * 6, tc="-")) == [] and CK.think_times({"color": "white"}) == []


def synthetic_rows(n=150, frac=0.1, base=300, seed=0):
    """Games where the player always uses `frac` of the time left (plus the increment, none here)."""
    rows = []
    for _ in range(n):
        clocks, mine, theirs = [], float(base), float(base)
        for i in range(24):
            if i % 2 == 0:
                mine -= mine * frac
                clocks.append(round(mine, 1))
            else:
                theirs -= theirs * 0.05
                clocks.append(round(theirs, 1))
        rows.append(row(clocks, tc=f"{base}+0", moves="e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5"))
    return rows


def test_fit_learns_the_fraction_of_the_time_left_the_player_uses():
    model = CK.fit(synthetic_rows())
    rng = np.random.default_rng(0)
    draws = [model.fraction("blitz", 4, False, rng) for _ in range(200)]
    assert abs(np.mean(draws) - 0.1) < 0.02 and model.meta["moves"] == 900


def test_a_sparse_cell_falls_back_to_a_coarser_one():
    m = CK.ClockModel({"blitz|0|1": [0.9] * 5, "blitz|*|*": [0.2] * 100, "*|*|*": [0.5] * 100})
    rng = np.random.default_rng(0)
    assert m.fraction("blitz", 0, True, rng) == 0.2 and m.fraction("rapid", 0, True, rng) == 0.5


def test_delay_scales_with_the_time_left_and_is_capped_and_switchable():
    m = CK.ClockModel({"*|*|*": [0.5] * 100})
    rng = np.random.default_rng(0)
    b = chess.Board()
    assert m.delay(b, 100.0, 300, 0, rng, cap=1.0) == pytest.approx(50.0)
    assert m.delay(b, 100.0, 300, 0, rng) == pytest.approx(0.25 * 99.0)         # never more than a quarter of what is left (after 1s margin)
    assert m.delay(b, 100.0, 300, 0, rng, strength=0.0) == 0.0
    assert m.delay(b, 0.5, 300, 0, rng) == 0.0                                  # nothing to spend


def test_save_and_load_roundtrip(tmp_path):
    m = CK.fit(synthetic_rows(60))
    m.save(tmp_path / "c.json")
    back = CK.ClockModel.load(tmp_path / "c.json")
    assert back.cells == m.cells and json.loads((tmp_path / "c.json").read_text())["meta"]["moves"] == m.meta["moves"]


def bot(clock, sleeps, strength=1.0, script="", seed=1):
    engine = StubEngine([L("e2e4", 0), L("d2d4", 0)])
    mc = MeChess(engine, UniformPrior(), None, table=table(), seed=seed)
    out = io.StringIO()
    MechessUci(mc, io.StringIO(script), out, elo=1500, clock=clock, clock_strength=strength, sleep=sleeps.append, clock_seed=3).run()
    return out.getvalue()


def test_the_bot_waits_when_the_gui_sends_clocks_and_reports_it():
    sleeps = []
    out = bot(CK.ClockModel({"*|*|*": [0.1] * 100}), sleeps, script="position startpos\ngo wtime 60000 btime 60000 winc 0 binc 0\nquit\n")
    assert len(sleeps) == 1 and 4.5 < sleeps[0] <= 6.0                           # 10% of 60 s, less the little the search took
    assert "info string clock: thought 6.0s of 60s" in out and "bestmove" in out


def test_no_wait_without_a_model_without_clocks_or_with_strength_zero():
    for clock, strength, go in ((None, 1.0, "go wtime 60000 btime 60000"), (CK.ClockModel({"*|*|*": [0.1] * 100}), 1.0, "go"),
                                (CK.ClockModel({"*|*|*": [0.1] * 100}), 0.0, "go wtime 60000 btime 60000")):
        sleeps = []
        out = bot(clock, sleeps, strength, script=f"position startpos\n{go}\nquit\n")
        assert sleeps == [] and "bestmove" in out


def test_black_uses_its_own_clock_and_increment():
    sleeps = []
    bot(CK.ClockModel({"*|*|*": [0.1] * 100}), sleeps, script="position startpos moves e2e4\ngo wtime 10000 btime 40000 winc 0 binc 2000\nquit\n")
    assert 3.5 < sleeps[0] <= 4.0                                                # 10% of Black's 40 s


def test_clock_agreement_beats_answering_at_once_on_matching_behaviour():
    model = CK.fit(synthetic_rows(150, frac=0.1))
    res = AG.clock_agreement(model, synthetic_rows(60, frac=0.1, seed=1), instant=1.0)
    s = res["blitz"]
    assert s["ks_model"] < s["ks_instant"] and s["ks_model"] < 0.3 and abs(s["real_mean"] - s["model_mean"]) < 0.25 * s["real_mean"]
    assert "blitz" in AG.render_clock(res)
