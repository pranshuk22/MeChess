import json
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(not shutil.which("stockfish"), reason="stockfish not installed")

PGN = '[White "Alice"]\n[Black "Bob"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 f6 3. Nxe5 fxe5 4. Qh5+ Ke7 5. Qxe5+ Kf7 1-0\n'


def run(tmp_path, *extra):
    pgn = tmp_path / "g.pgn"
    pgn.write_text(PGN)
    return subprocess.run([sys.executable, "-m", "chessme", "analyse", str(pgn), "--out", str(tmp_path / "out"), "--player", "Bob",
                           "--nodes", "5000", "--log", str(tmp_path / "log"), "--control-dir", str(tmp_path / "ctl"), *extra],
                          capture_output=True, text=True, timeout=120)


def test_analyse_writes_games_and_report_and_resumes(tmp_path):
    r = run(tmp_path, "--openings-dir", str(tmp_path / "no_names"))         # no opening names: every move is classed by its loss
    assert r.returncode == 0, r.stderr
    files = list((tmp_path / "out" / "games").glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["player_color"] == "black" and len(data["moves"]) == 10
    assert any(m["class"] in ("mistake", "blunder") and m["move"] in ("f6", "fxe5") for m in data["moves"])
    assert "Game analysis: Bob" in (tmp_path / "out" / "report.md").read_text()
    before = files[0].stat().st_mtime_ns
    assert run(tmp_path, "--openings-dir", str(tmp_path / "no_names")).returncode == 0
    assert files[0].stat().st_mtime_ns == before          # the finished game is not analysed again


def test_analyse_marks_theory_moves_as_book_when_opening_names_are_given(tmp_path):
    names = tmp_path / "names"
    names.mkdir()
    (names / "a.tsv").write_text("eco\tname\tpgn\nC44\tKing's Pawn Game\t1. e4 e5 2. Nf3\n")
    r = run(tmp_path, "--openings-dir", str(names))
    assert r.returncode == 0, r.stderr
    data = json.loads(next((tmp_path / "out" / "games").glob("*.json")).read_text())
    assert [m["class"] for m in data["moves"][:3]] == ["book", "book", "book"] and data["moves"][3]["class"] != "book"      # 2...f6 is not theory
