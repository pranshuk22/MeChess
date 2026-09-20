import sys
from pathlib import Path

import pytest

from chessme.uci_client import STARTPOS_FEN, EngineError, UciEngine

FAKE = str(Path(__file__).resolve().parents[1] / "fake_engine.py")


def fake(mode="normal", log=None, **kw):
    cmd = [sys.executable, FAKE, mode] + ([str(log)] if log else [])
    return UciEngine(cmd, name="fake", **kw)


def test_start_go_and_parse_info(tmp_path):
    with fake(log=tmp_path / "log.txt") as e:
        r = e.go(depth=3)
    assert r.bestmove == "e2e4"
    assert (r.score_kind, r.score, r.depth, r.nodes) == ("cp", 25, 3, 100)  # the *last* info line wins
    assert r.pv == ["e2e4", "e7e5"]


def test_mate_score_is_parsed():
    with fake("mate") as e:
        r = e.go(nodes=100)
    assert (r.score_kind, r.score) == ("mate", 3)


def test_no_info_lines_gives_none_score():
    with fake("noscore") as e:
        r = e.go(movetime=10)
    assert r.bestmove == "e2e4" and r.score_kind is None and r.score is None


def test_commands_sent_to_the_engine(tmp_path):
    log = tmp_path / "log.txt"
    with fake(log=log, options={"Hash": 32, "EvalFile": "/x/y.txt"}) as e:
        e.new_game()
        e.go(STARTPOS_FEN, ["e2e4", "e7e5"], nodes=500)
        e.go("4k3/8/8/8/8/8/8/4K3 w - - 0 1", [], depth=4)
        e.go(movetime=250)
    lines = log.read_text().splitlines()
    assert lines[0] == "uci"
    assert "setoption name Hash value 32" in lines and "setoption name EvalFile value /x/y.txt" in lines
    assert "ucinewgame" in lines
    assert "position startpos moves e2e4 e7e5" in lines and "go nodes 500" in lines
    assert "position fen 4k3/8/8/8/8/8/8/4K3 w - - 0 1" in lines and "go depth 4" in lines
    assert "go movetime 250" in lines and lines[-1] == "quit"


def test_go_needs_a_limit():
    with fake() as e, pytest.raises(ValueError):
        e.go()


def test_timeout_raises_and_kills_the_process():
    e = fake("hang").start()
    with pytest.raises(EngineError, match="timed out"):
        e.go(depth=2, timeout=0.6)
    assert e.proc.poll() is not None  # no orphaned process left running
    e.close()


def test_crash_is_reported():
    e = fake("crash").start()
    with pytest.raises(EngineError):
        e.go(depth=2, timeout=5)
    e.close()


def test_malformed_bestmove_is_an_error():
    with fake("garbage") as e, pytest.raises(EngineError, match="malformed"):
        e.go(depth=2)


def test_missing_binary_is_an_engine_error():
    with pytest.raises(EngineError, match="cannot start"):
        UciEngine(["/no/such/engine"]).start()


def test_engine_that_never_says_uciok_times_out():
    e = UciEngine([sys.executable, "-c", "import time; time.sleep(30)"], startup_timeout=0.5)
    with pytest.raises(EngineError):
        e.start()
    e.close()


def test_close_is_idempotent_and_cleans_up():
    e = fake().start()
    proc = e.proc
    e.close()
    e.close()
    assert proc.poll() is not None


def test_multipv_lines_of_the_deepest_depth_are_returned_in_order():
    with fake("multipv") as e:
        r = e.go(depth=3)
    assert [(l.move, l.score_kind, l.score, l.depth) for l in r.lines] == [
        ("e2e4", "cp", 35, 3), ("d2d4", "cp", -20, 3), ("g1f3", "mate", 4, 3)]
    assert r.lines[0].pv == ["e2e4", "e7e5", "g1f3"] and r.bestmove == "e2e4"
    assert r.lines[2].cp > 90000 and r.lines[1].cp == -20 and r.lines[0].cp == 35


def test_single_line_engines_still_give_one_line():
    with fake() as e:
        r = e.go(depth=3)
    assert len(r.lines) == 1 and r.lines[0].move == "e2e4" and r.lines[0].score == 25


def test_no_info_means_no_lines():
    with fake("noscore") as e:
        assert e.go(movetime=10).lines == []


def test_partial_final_iteration_and_bounds_do_not_corrupt_multipv_lines():
    """Regression (real Stockfish output at a node limit): the last iteration is cut short and printed again without
    line 1, and aspiration bounds appear; the lines must be the last COMPLETE iteration, all distinct moves."""
    with fake("multipv_cut") as e:
        r = e.go(nodes=10)
    assert [l.move for l in r.lines] == ["e2e4", "d2d4", "g1f3"]
    assert [l.score for l in r.lines] == [24, 16, 15] and all(l.depth == 7 for l in r.lines)


def test_nodes_and_depth_can_be_combined_in_one_go_command():
    sent = []

    class Recorder(UciEngine):
        def _send(self, line):
            sent.append(line)

        def _readline(self, deadline):
            return "bestmove e2e4"

    e = Recorder("x")
    e.go(nodes=5000, depth=4)
    e.go(nodes=5000)
    e.go(depth=4)
    e.go(movetime=50)
    assert [l for l in sent if l.startswith("go")] == ["go depth 4 nodes 5000", "go nodes 5000", "go depth 4", "go movetime 50"]
    with pytest.raises(ValueError):
        e.go()
