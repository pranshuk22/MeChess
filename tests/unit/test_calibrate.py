import json
import random
import sys
from types import SimpleNamespace

import pytest

from chessme import calibrate as C
from chessme import strength as S
from chessme.match import EngineSpec, SearchLimit
from chessme.mechess.calibration import Calibration

FENS = [f"fen{i}" for i in range(4)]


def fake_match(true_elo_of, seed=0, faults=0):
    """Stand-in for run_match: results are drawn from a true rating, options and openings are recorded."""
    rng, calls = random.Random(seed), []

    def run(a, b, fens, limit, adj=None, *, concurrency=1, max_pairs=None):
        pairs = fens[:max_pairs] if max_pairs else fens
        opp = dict(b.options)["UCI_Elo"]
        p = S.expected(true_elo_of(a), opp)
        w = d = l = 0
        for _ in range(2 * len(pairs)):
            if rng.random() < p:
                w += 1
            else:
                l += 1
        calls.append({"a": a.name, "b_options": dict(b.options), "fens": list(pairs), "limit": limit})
        return SimpleNamespace(wins=w, draws=d, losses=l, errors=["boom"] * faults)
    run.calls = calls
    return run


@pytest.fixture
def sf_range(monkeypatch):
    monkeypatch.setattr(S, "engine_info", lambda cmd, timeout=15: {"name": "Stockfish X", "uci_elo": (1320, 1320, 3190)})


class TestMakePlay:
    def test_opponent_is_limited_to_the_requested_elo_and_openings_rotate_and_cycle(self, monkeypatch):
        run = fake_match(lambda a: 1800)
        monkeypatch.setattr(C, "run_match", run)
        play = C.make_play(EngineSpec.make("me", "x"), "sf", FENS, SearchLimit(movetime=50), log=lambda *_: None)
        play(1700, 3)
        play(1900, 3)
        assert run.calls[0]["fens"] == ["fen0", "fen1", "fen2"] and run.calls[1]["fens"] == ["fen3", "fen0", "fen1"]
        opts = run.calls[0]["b_options"]
        assert opts["UCI_LimitStrength"] == "true" and opts["UCI_Elo"] == 1700 and opts["Threads"] == 1
        assert run.calls[1]["b_options"]["UCI_Elo"] == 1900 and run.calls[0]["limit"].kwargs() == {"movetime": 50}

    def test_results_are_returned_from_the_measured_engines_side_and_faults_are_counted_and_logged(self, monkeypatch):
        monkeypatch.setattr(C, "run_match", fake_match(lambda a: 1800, faults=2))
        logs = []
        play = C.make_play(EngineSpec.make("me", "x"), "sf", FENS, SearchLimit(movetime=50), log=logs.append)
        w, d, l = play(1800, 2)
        assert w + d + l == 4 and play.state["faults"] == 2 and any("2 engine fault" in x for x in logs)

    def test_custom_opponent_options_are_used(self, monkeypatch):
        run = fake_match(lambda a: 1800)
        monkeypatch.setattr(C, "run_match", run)
        # fake_match reads UCI_Elo, so the custom options must still carry it
        play = C.make_play(EngineSpec.make("me", "x"), "sf", FENS, SearchLimit(movetime=5),
                           opponent_options=lambda e: {"UCI_Elo": e, "Hash": 4}, log=lambda *_: None)
        play(1500, 1)
        assert run.calls[0]["b_options"] == {"UCI_Elo": 1500, "Hash": 4}


class TestMeasure:
    def test_the_estimate_lands_near_the_true_rating_and_the_result_is_complete(self, monkeypatch, sf_range):
        monkeypatch.setattr(C, "run_match", fake_match(lambda a: 2000, seed=5))
        r = C.measure(EngineSpec.make("me", "x"), "sf", FENS, SearchLimit(movetime=50), start=1600, target_se=40,
                      log=lambda *_: None)
        assert abs(r["elo"] - 2000) < 3 * r["se"] + 25 and r["stop"] == "target precision reached"
        assert r["opponent"] == "Stockfish X" and r["limit"] == {"movetime": 50} and r["faults"] == 0
        assert sum(l["games"] for l in r["levels"]) == r["games"] and json.dumps(r)   # JSON-serialisable

    def test_an_opponent_without_uci_elo_is_refused_with_a_clear_message(self, monkeypatch):
        monkeypatch.setattr(S, "engine_info", lambda cmd, timeout=15: {"name": "Old", "uci_elo": None})
        with pytest.raises(SystemExit, match="UCI_Elo"):
            C.measure(EngineSpec.make("me", "x"), "old", FENS, SearchLimit(movetime=5), log=lambda *_: None)

    def test_progress_is_logged(self, monkeypatch, sf_range):
        monkeypatch.setattr(C, "run_match", fake_match(lambda a: 1900, seed=2))
        logs = []
        C.measure(EngineSpec.make("me", "x"), "sf", FENS, SearchLimit(movetime=5), max_games=40, min_games=20, log=logs.append)
        text = "\n".join(logs)
        assert "measuring me against Stockfish X" in text and "estimate" in text and "=>" in text


class TestCalibrateDial:
    def run_cal(self, tmp_path, monkeypatch, dials, **kw):
        # MeChess at dial d really plays at d - 150
        run = fake_match(lambda a: dict(a.options)["Elo"] - 150, seed=9)
        monkeypatch.setattr(C, "run_match", run)
        cal = C.calibrate_dial(dials, ("mechess",), "sf", FENS, SearchLimit(movetime=5), tmp_path / "dial.json",
                               log=lambda *_: None, target_se=45, max_games=300, **kw)
        return cal, run

    def test_a_calibration_file_is_written_and_recovers_the_offset_between_dial_and_strength(self, tmp_path, monkeypatch, sf_range):
        cal, run = self.run_cal(tmp_path, monkeypatch, [1500, 1800, 2100])
        assert isinstance(cal, Calibration) and [p["dial"] for p in cal.points] == [1500, 1800, 2100]
        for p in cal.points:
            assert abs(p["measured"] - (p["dial"] - 150)) < 3 * p["se"] + 30
        assert abs(cal.dial_for(1650) - 1800) < 90          # the dial that plays 1650 is the one that was labelled 1800
        data = json.loads((tmp_path / "dial.json").read_text())
        assert data["scale"] == "stockfish-UCI_Elo" and data["meta"]["opponent"] == "Stockfish X"

    def test_a_rerun_skips_finished_dial_points_and_redo_measures_again(self, tmp_path, monkeypatch, sf_range):
        _, run = self.run_cal(tmp_path, monkeypatch, [1500, 1800])
        first = len(run.calls)
        _, run2 = self.run_cal(tmp_path, monkeypatch, [1500, 1800, 2100])
        assert {c["a"] for c in run2.calls} == {"mechess-2100"} and first > 0
        _, run3 = self.run_cal(tmp_path, monkeypatch, [1500], redo=True)
        assert run3.calls and {c["a"] for c in run3.calls} == {"mechess-1500"}
        assert [p["dial"] for p in json.loads((tmp_path / "dial.json").read_text())["points"]] == [1500]

    def test_the_dial_setting_is_sent_to_mechess_as_the_elo_option(self, tmp_path, monkeypatch, sf_range):
        seen = []
        real = fake_match(lambda a: dict(a.options)["Elo"] - 150, seed=1)

        def spy(a, b, *args, **kw):
            seen.append(dict(a.options))
            return real(a, b, *args, **kw)
        monkeypatch.setattr(C, "run_match", spy)
        C.calibrate_dial([1600], ("mechess",), "sf", FENS, SearchLimit(movetime=5), tmp_path / "d.json",
                         log=lambda *_: None, max_games=20, min_games=10)
        assert seen and all(o == {"Elo": 1600} for o in seen)


def test_mechess_command_starts_the_controller_module():
    cmd = C.mechess_command("engine/build/chessme-engine", "uniform")
    assert cmd[:3] == (sys.executable, "-m", "chessme") and "mechess" in cmd and "--book" not in cmd
    assert "--book" in C.mechess_command("e", "uniform", book="b.bin") and C.mechess_command("e", "ours=x.pt")[-1] == "ours=x.pt"


def test_stockfish_options():
    assert C.stockfish_options(1800) == {"UCI_LimitStrength": "true", "UCI_Elo": 1800, "Threads": 1, "Hash": 16}


class TestLinkCalibration:
    TRUE = {1200: 1050, 1500: 1250, 1800: 1550, 2100: 1850}     # what each dial setting really plays at

    def cal_file(self, tmp_path, censored_dials=(1200, 1500)):
        pts = []
        for d, t in self.TRUE.items():
            if d in censored_dials:
                pts.append({"dial": d, "measured": t - 300.0, "se": 170.0, "games": 20, "stop": "weaker than the weakest opponent available",
                            "pinned": "", "faults": 0})
            else:
                pts.append({"dial": d, "measured": float(t), "se": 35.0, "games": 200, "stop": "target precision reached", "pinned": "", "faults": 0})
        path = tmp_path / "dial.json"
        path.write_text(json.dumps({"scale": "stockfish-UCI_Elo", "offset": 0.0, "meta": {}, "points": pts}))
        return path

    def fake_link_match(self, seed=0):
        rng, calls = random.Random(seed), []

        def run(a, b, fens, limit, adj=None, *, concurrency=1, max_pairs=None):
            ta, tb = self.TRUE[dict(a.options)["Elo"]], self.TRUE[dict(b.options)["Elo"]]
            p = S.expected(ta, tb)
            w = d = l = 0
            for _ in range(2 * len(fens[:max_pairs])):
                if rng.random() < p:
                    w += 1
                else:
                    l += 1
            calls.append((a.name, b.name))
            return SimpleNamespace(wins=w, draws=d, losses=l, errors=[])
        run.calls = calls
        return run

    def test_unmeasurable_dial_settings_are_linked_to_measured_ones_and_recover_their_strength(self, tmp_path, monkeypatch):
        path = self.cal_file(tmp_path)
        run = self.fake_link_match(1)
        monkeypatch.setattr(C, "run_match", run)
        n = C.link_calibration(path, ("mechess",), FENS, SearchLimit(movetime=5), pairs_per_link=150, log=lambda *_: None)
        assert n == 2 and sorted(run.calls) == [("mechess-1200", "mechess-1500"), ("mechess-1500", "mechess-1800")]
        pts = {p["dial"]: p for p in json.loads(path.read_text())["points"]}
        assert abs(pts[1500]["measured"] - 1250) < 3 * pts[1500]["se"] + 15 and abs(pts[1200]["measured"] - 1050) < 3 * pts[1200]["se"] + 15
        assert pts[1500]["linked_to"] == 1800 and pts[1200]["linked_to"] == 1500 and pts[1200]["raw_measured"] == 750.0
        cal = Calibration.load(path)
        assert cal.unmeasurable() == [] and [d for d, _ in cal.curve()] == [1200, 1500, 1800, 2100]   # all usable now

    def test_a_rerun_replays_no_games_and_redo_replays_them(self, tmp_path, monkeypatch):
        path = self.cal_file(tmp_path)
        monkeypatch.setattr(C, "run_match", self.fake_link_match(2))
        C.link_calibration(path, ("mechess",), FENS, SearchLimit(movetime=5), pairs_per_link=20, log=lambda *_: None)
        run2 = self.fake_link_match(3)
        monkeypatch.setattr(C, "run_match", run2)
        assert C.link_calibration(path, ("mechess",), FENS, SearchLimit(movetime=5), pairs_per_link=20, log=lambda *_: None) == 0 and not run2.calls
        assert C.link_calibration(path, ("mechess",), FENS, SearchLimit(movetime=5), pairs_per_link=20, redo=True, log=lambda *_: None) == 2

    def test_nothing_to_link_is_a_no_op_and_nothing_measured_is_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(C, "run_match", self.fake_link_match())
        assert C.link_calibration(self.cal_file(tmp_path, censored_dials=()), ("m",), FENS, SearchLimit(movetime=5), log=lambda *_: None) == 0
        with pytest.raises(SystemExit, match="nothing to anchor"):
            C.link_calibration(self.cal_file(tmp_path, censored_dials=tuple(self.TRUE)), ("m",), FENS, SearchLimit(movetime=5), log=lambda *_: None)

    def test_a_lopsided_link_is_flagged_in_the_log(self, tmp_path, monkeypatch):
        path = self.cal_file(tmp_path, censored_dials=(1200,))
        run = SimpleNamespace(calls=[])
        monkeypatch.setattr(C, "run_match", lambda a, b, fens, limit, adj=None, **k: SimpleNamespace(wins=0, draws=0, losses=2 * len(fens[:k.get("max_pairs")]), errors=[]))
        logs = []
        C.link_calibration(path, ("m",), FENS, SearchLimit(movetime=5), pairs_per_link=4, log=logs.append)
        assert any("lopsided" in l for l in logs)


class TestMechessCommand:
    def test_options_are_passed_through(self):
        cmd = C.mechess_command("eng", "uniform", "b.bin", table="t.json")
        assert cmd[:3] == (sys.executable, "-m", "chessme") and cmd[cmd.index("--table") + 1] == "t.json"
        assert cmd[cmd.index("--book") + 1] == "b.bin" and cmd[0] != "env"                # uniform prior: no thread limits needed

    def test_neural_priors_are_started_with_limited_threads_and_get_their_paths(self):
        cmd = C.mechess_command("eng", "maia3=w.pt", None, maia3_repo="/m3", maia3_size="5m", extra_path="/libs", threads=2)
        assert cmd[:3] == ("env", "OMP_NUM_THREADS=2", "MKL_NUM_THREADS=2")
        assert cmd[cmd.index("--maia3-repo") + 1] == "/m3" and cmd[cmd.index("--maia3-size") + 1] == "5m"
        assert cmd[cmd.index("--extra-path") + 1] == "/libs" and cmd[cmd.index("--prior") + 1] == "maia3=w.pt"

    def test_absent_options_are_absent(self):
        cmd = C.mechess_command("eng", "ours=m.pt")
        assert "--table" not in cmd and "--book" not in cmd and "--maia3-repo" not in cmd


class TestCalibrationCarriesItsTable:
    def test_the_table_used_for_the_measurements_is_stored_and_read_back(self, tmp_path, monkeypatch, sf_range):
        monkeypatch.setattr(C, "run_match", fake_match(lambda a: dict(a.options)["Elo"] - 150, seed=9))
        table = {1500: (100, 4, 100, 1.0, 50.0, 0, 0.1), 1800: (400, 4, 100, 1.0, 50.0, 0, 0.0)}
        C.calibrate_dial([1800], ("m",), "sf", FENS, SearchLimit(movetime=5), tmp_path / "d.json", log=lambda *_: None,
                         table=table, target_se=60, max_games=120, min_games=20)
        cal = Calibration.load(tmp_path / "d.json")
        assert cal.table() == {1500: (100, 4, 100, 1.0, 50.0, 0, 0.1), 1800: (400, 4, 100, 1.0, 50.0, 0, 0.0)}

    def test_files_without_a_recorded_table_return_none(self):
        assert Calibration([{"dial": 1800, "measured": 1200.0, "se": 50.0}]).table() is None
