"""Integration: self-play data -> C++ tuner -> tuned parameters loaded back into the engine and played."""
import subprocess

import chess
import pytest

from chessme import openings, selfplay
from chessme.match import Adjudication, EngineSpec, SearchLimit, run_match

pytestmark = pytest.mark.integration


def make_data(engine_path, out, games=12):
    spec = EngineSpec.make("selfplay", str(engine_path))
    fens = openings.random_openings(6, plies=6, seed=1)
    return selfplay.generate(spec, fens, games, out, SearchLimit(nodes=400), Adjudication(), concurrency=2,
                             seed=7, keep_prob=0.7)


def test_selfplay_writes_valid_labelled_positions(engine_path, tmp_path):
    out = tmp_path / "sp.txt"
    played, positions, errors = make_data(engine_path, out)
    assert played == 12 and errors == 0 and positions > 60
    lines = out.read_text().splitlines()
    assert len(lines) == positions
    for line in lines:
        fen, value = [x.strip() for x in line.split("|")]
        assert chess.Board(fen).is_valid()
        assert float(value) in (0.0, 0.5, 1.0)


def test_selfplay_is_reproducible(engine_path, tmp_path):
    make_data(engine_path, tmp_path / "a.txt", games=6)
    make_data(engine_path, tmp_path / "b.txt", games=6)
    assert sorted((tmp_path / "a.txt").read_text().splitlines()) == sorted((tmp_path / "b.txt").read_text().splitlines())


def test_full_loop_selfplay_tune_reload_and_play(engine_path, texel_path, tmp_path):
    data, tuned = tmp_path / "sp.txt", tmp_path / "tuned.txt"
    make_data(engine_path, data, games=16)
    r = subprocess.run([str(texel_path), "--data", str(data), "--out", str(tuned), "--epochs", "30", "--val", "0.2"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert "loaded" in r.stdout and "valid loss" in r.stdout and tuned.exists()

    # the tuner never touches the anchors
    lines = {l.split()[0]: l.split()[1:] for l in tuned.read_text().splitlines() if l and not l.startswith("#")}
    assert lines["mat_mg"][0] == "100" and lines["mat_mg"][5] == "0"
    assert len(lines["pst_mg"]) == 6 * 64 and len(lines["mob_eg"]) == 6

    # the engine accepts the tuned file and plays legal chess with it
    a = EngineSpec.make("tuned", str(engine_path), {"EvalFile": str(tuned)})
    b = EngineSpec.make("default", str(engine_path))
    res = run_match(a, b, openings.random_openings(2, plies=6, seed=12), SearchLimit(nodes=600), concurrency=2)
    assert res.pairs == 2 and not res.errors


def test_tuning_reduces_the_loss_on_its_own_data(engine_path, texel_path, tmp_path):
    data = tmp_path / "sp.txt"
    make_data(engine_path, data, games=24)
    r = subprocess.run([str(texel_path), "--data", str(data), "--out", str(tmp_path / "t.txt"), "--epochs", "60",
                        "--val", "0.2"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0
    train = [l for l in r.stdout.splitlines() if l.startswith("train loss")][0].split()
    before, after = float(train[2]), float(train[4])
    assert after < before


def test_tuner_rejects_bad_input(texel_path, tmp_path):
    out = tmp_path / "o.txt"
    missing = subprocess.run([str(texel_path), "--data", "/no/such/file", "--out", str(out)], capture_output=True, text=True)
    assert missing.returncode == 2 and not out.exists()
    empty = tmp_path / "empty.txt"
    empty.write_text("# nothing here\n")
    assert subprocess.run([str(texel_path), "--data", str(empty), "--out", str(out)], capture_output=True).returncode == 2
    data = tmp_path / "d.txt"
    data.write_text(f"{chess.STARTING_FEN} | 0.5\n")
    bad_group = subprocess.run([str(texel_path), "--data", str(data), "--out", str(out), "--freeze", "nonsense"],
                               capture_output=True, text=True)
    assert bad_group.returncode == 2 and "unknown group" in bad_group.stderr
    no_args = subprocess.run([str(texel_path)], capture_output=True, text=True)
    assert no_args.returncode == 2 and "usage" in no_args.stderr
