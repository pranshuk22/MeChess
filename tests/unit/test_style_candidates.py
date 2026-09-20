import chess
import numpy as np

from chessme.style import candidates as C
from chessme.style.features import FEATURE_NAMES
from chessme.uci_client import GoResult, Line


class Item:
    def __init__(self, fen, move, rating=1800, ply=12, platform=0):
        self.fen, self.played, self.mover_elo, self.ply, self.platform = fen, move, rating, ply, platform


class ScriptedEngine:
    def __init__(self, lines):
        self.lines = lines

    def new_game(self):
        pass

    def go(self, fen, **kw):
        return GoResult(bestmove=self.lines[0].move if self.lines else None, lines=self.lines)


def line(move, cp, k=1):
    return Line(move, "cp", cp, 8, [move])


START = chess.STARTING_FEN


def run(lines, played, window=50):
    return C.candidates_for(ScriptedEngine(lines), Item(START, played), nodes=100, multipv=len(lines), window=window)


def test_window_filters_candidates_and_records_choice_and_loss():
    p = run([line("e2e4", 30), line("d2d4", 20), line("g1f3", 0), line("a2a3", -80)], "d2d4")
    assert p.cands == ["e2e4", "d2d4", "g1f3"] and p.chosen == 1
    assert list(p.loss) == [0, 10, 30] and p.played_loss == 10
    assert p.feats.shape == (3, len(FEATURE_NAMES))


def test_played_move_outside_the_window_is_not_a_choice_but_keeps_its_loss():
    p = run([line("e2e4", 30), line("d2d4", 25), line("a2a3", -80)], "a2a3")
    assert p.chosen == -1 and p.played_loss == 110


def test_played_move_the_engine_did_not_score_has_nan_loss():
    p = run([line("e2e4", 30), line("d2d4", 25)], "h2h4")
    assert p.chosen == -1 and np.isnan(p.played_loss)


def test_a_single_good_move_carries_no_style_information():
    assert run([line("e2e4", 300), line("d2d4", 0)], "e2e4") is None


def test_no_engine_lines_gives_none():
    assert C.candidates_for(ScriptedEngine([Line("e2e4", "cp", 0, 1, [])]), Item(START, "e2e4"), nodes=1, multipv=1, window=50) is None


def test_save_load_round_trip(tmp_path):
    ps = [run([line("e2e4", 30), line("d2d4", 20)], "e2e4"), run([line("e2e4", 30), line("g1f3", 25), line("b1c3", 10)], "b1c3")]
    C.save(ps, tmp_path / "c.npz")
    back = C.load(tmp_path / "c.npz")
    assert [b.cands for b in back] == [p.cands for p in ps]
    assert [b.chosen for b in back] == [0, 2]
    assert np.array_equal(back[1].feats, ps[1].feats) and np.array_equal(back[1].loss, ps[1].loss)


def test_platform_is_recorded_and_survives_save_load(tmp_path):
    p = C.candidates_for(ScriptedEngine([line("e2e4", 30), line("d2d4", 20)]), Item(START, "e2e4", platform=1),
                         nodes=1, multipv=2, window=50)
    C.save([p], tmp_path / "c.npz")
    assert p.platform == 1 and C.load(tmp_path / "c.npz")[0].platform == 1


def test_load_reads_each_array_once_not_once_per_position(tmp_path, monkeypatch):
    """Regression: indexing an NpzFile decompresses the whole array every time; loading N positions must not do that N times."""
    ps = [run([line("e2e4", 30), line("d2d4", 20)], "e2e4") for _ in range(50)]
    C.save(ps, tmp_path / "c.npz")
    real = np.load
    reads = []

    class Counting:
        def __init__(self, z):
            self.z = z
            self.files = z.files

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.z.close()

        def __getitem__(self, k):
            reads.append(k)
            return self.z[k]

    monkeypatch.setattr(C.np, "load", lambda *a, **k: Counting(real(*a, **k)))
    assert len(C.load(tmp_path / "c.npz")) == 50
    assert len(reads) == len(set(reads)) <= 14  # one read per stored array


def test_judge_label_engine_options_and_stored_label(tmp_path):
    assert C.judge_label("/opt/homebrew/bin/stockfish", 20000) == "stockfish@20000n"
    assert C.engine_options("/x/stockfish", 8) == {"MultiPV": 8, "Threads": 1, "Hash": 64}
    assert C.engine_options("/x/chessme-engine", 8) == {"MultiPV": 8}  # our engine gets no options it may not know
    ps = [run([line("e2e4", 30), line("d2d4", 20)], "e2e4")]
    C.save(ps, tmp_path / "a.npz", judge="stockfish@20000n")
    C.save(ps, tmp_path / "b.npz")
    assert C.judge_of(tmp_path / "a.npz") == "stockfish@20000n" and C.judge_of(tmp_path / "b.npz") == ""


def test_candidates_are_sorted_best_first_whatever_order_the_engine_gave():
    p = run([line("d2d4", 10), line("e2e4", 30), line("g1f3", 20)], "e2e4")
    assert p.cands == ["e2e4", "g1f3", "d2d4"] and list(p.loss) == [0, 10, 20]
