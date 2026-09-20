"""Integration: Python-built book files consumed by the real C++ engine."""
import random
import re
from collections import Counter

import chess
import pytest

from chessme.book import build
from chessme.book import format as bf
from chessme.book.keys import book_key
from chessme.match import Adjudication, SearchLimit, play_game
from chessme.uci_client import STARTPOS_FEN, UciEngine
from tests.integration.uci_helper import run_uci
from tests.samples import make_row

pytestmark = pytest.mark.integration

CFG = {"filters": {"min_rating": {"lichess": 1400}, "recency": {"half_life_days": 3650, "min_weight": 0.1},
                   "time_class_weights": {"blitz": 1.0}},
       "book": {"max_ply": 20, "min_games": 1, "min_position_games": 1, "min_share": 0.0}}


def synthetic_rows():
    """White: 1.d4 in 30 games then 2.c4 (20) or 2.Nf3 (10). Black: 1.e4 c5 (all)."""
    rows = []
    for i in range(20):
        rows.append(make_row(game_id=f"a{i}", color="white", my_result="win", moves="d4 d5 c4 e6 Nc3 Nf6"))
    for i in range(10):
        rows.append(make_row(game_id=f"b{i}", color="white", my_result="win", moves="d4 d5 Nf3 Nf6 c4 e6"))
    for i in range(10):
        rows.append(make_row(game_id=f"c{i}", color="black", my_result="win", moves="e4 c5 Nf3 d6"))
    return rows


@pytest.fixture()
def book_path(tmp_path):
    res = build.build_book(CFG, synthetic_rows())
    path = tmp_path / "book.bin"
    bf.write_book(path, res.entries)
    return path


def random_positions(n, seed):
    rng, out = random.Random(seed), []
    while len(out) < n:
        b = chess.Board()
        for _ in range(rng.randint(0, 90)):
            moves = list(b.legal_moves)
            if not moves:
                break
            b.push(rng.choice(moves))
        out.append(b)
    return out


def test_python_and_cpp_compute_identical_position_keys(engine_path):
    boards = random_positions(400, seed=3)
    script = []
    for b in boards:
        script += [f"position fen {b.fen()}", "bookkey"]
    out = run_uci(engine_path, script)
    keys = re.findall(r"^bookkey ([0-9a-f]+)$", out, re.M)
    assert len(keys) == len(boards)
    for b, k in zip(boards, keys):
        assert int(k, 16) == book_key(b), b.fen()


def test_positions_with_castling_ep_and_promotions_have_matching_keys(engine_path):
    fens = ["r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "r3k2r/8/8/8/8/8/8/R3K2R w Kq - 0 1",
            "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3", "8/P7/8/8/8/8/8/k6K w - - 0 1",
            "4k3/8/8/8/8/8/8/4K3 b - - 55 90"]
    out = run_uci(engine_path, [x for f in fens for x in (f"position fen {f}", "bookkey")])
    for f, k in zip(fens, re.findall(r"^bookkey ([0-9a-f]+)$", out, re.M)):
        assert int(k, 16) == book_key(f)


def test_engine_reads_the_book_and_reports_its_moves(engine_path, book_path):
    out = run_uci(engine_path, [f"setoption name BookFile value {book_path}", "position startpos", "bookmoves"])
    assert "loaded book" in out
    (line,) = re.findall(r"^bookmoves (.*)$", out, re.M)
    assert line.split(":")[0] == "d2d4" and float(line.split(":")[1]) == pytest.approx(30, rel=0.01)


def test_engine_plays_the_book_move_and_leaves_the_book_when_it_ends(engine_path, book_path):
    base = [f"setoption name BookFile value {book_path}", "setoption name OwnBook value true",
            "setoption name BookTemperature value 0"]
    out = run_uci(engine_path, base + ["position startpos", "go depth 3"])
    assert "info string book move d2d4" in out and "bestmove d2d4" in out
    out = run_uci(engine_path, base + ["position startpos moves d2d4 d7d5", "go depth 3"])
    assert "book move c2c4" in out  # the more frequent of my two second moves
    # the book stops after 1.d4 d5 2.c4 e6 3.Nc3 Nf6 (game length) -> the engine searches instead
    out = run_uci(engine_path, base + ["position startpos moves d2d4 d7d5 c2c4 e7e6 b1c3 g8f6", "go depth 3"])
    assert "book move" not in out and "info depth 1" in out


def test_black_repertoire_is_played_too(engine_path, book_path):
    out = run_uci(engine_path, [f"setoption name BookFile value {book_path}", "setoption name OwnBook value true",
                                "setoption name BookTemperature value 0", "position startpos moves e2e4", "go depth 3"])
    assert "bestmove c7c5" in out


def test_book_sampling_matches_my_frequencies(engine_path, book_path):
    """After 1.d4 d5 I played 2.c4 in 20 games and 2.Nf3 in 10: about 2/3 vs 1/3 over many samples."""
    script = [f"setoption name BookFile value {book_path}", "setoption name OwnBook value true",
              "setoption name BookSeed value 12345"]
    for _ in range(600):
        script += ["position startpos moves d2d4 d7d5", "go depth 1"]
    out = run_uci(engine_path, script, timeout=120)
    picks = Counter(re.findall(r"^bestmove (\S+)", out, re.M))
    assert set(picks) == {"c2c4", "g1f3"}
    assert 0.60 < picks["c2c4"] / 600 < 0.73


def test_a_seed_makes_book_choices_reproducible(engine_path, book_path):
    def choices(seed):
        script = [f"setoption name BookFile value {book_path}", "setoption name OwnBook value true",
                  f"setoption name BookSeed value {seed}"]
        for _ in range(60):
            script += ["position startpos moves d2d4 d7d5", "go depth 1"]
        return re.findall(r"^bestmove (\S+)", run_uci(engine_path, script), re.M)

    assert choices(7) == choices(7)
    assert choices(7) != choices(8)


def test_engine_with_a_book_plays_legal_games_that_follow_the_book(engine_path, book_path):
    opts = {"BookFile": str(book_path), "OwnBook": "true", "BookMaxPly": 4, "BookSeed": 5, "BookTemperature": 0}
    with UciEngine([str(engine_path)], options=opts, name="booked") as white, \
            UciEngine([str(engine_path)], options=opts, name="booked2") as black:
        g = play_game(white, black, STARTPOS_FEN, SearchLimit(nodes=500), Adjudication(resign_cp=0, draw_cp=0, max_plies=30))
    assert g.error is None and len(g.moves) >= 6
    # BookMaxPly=4. White's book move is 1.d4; Black's book only covers 1.e4, so Black searches from ply 1.
    assert g.moves[0] == "d2d4"
    board = chess.Board()
    for m in g.moves:
        assert chess.Move.from_uci(m) in board.legal_moves
        board.push_uci(m)


def test_book_is_off_by_default_and_never_affects_plain_search(engine_path, book_path):
    with_file = run_uci(engine_path, [f"setoption name BookFile value {book_path}", "position startpos", "go depth 4"])
    without = run_uci(engine_path, ["position startpos", "go depth 4"])
    strip = lambda s: [l for l in s.splitlines() if l.startswith("bestmove")]
    assert strip(with_file) == strip(without) and "book move" not in with_file


def test_realistic_book_built_from_the_pipeline_is_loadable(engine_path, tmp_path):
    """A larger book, including transposing lines, must load and answer at the start position."""
    rows = synthetic_rows() + [make_row(game_id=f"t{i}", color="white", my_result="win",
                                        moves="Nf3 Nf6 c4 e6 d4 d5") for i in range(6)]
    res = build.build_book(CFG, rows)
    path = tmp_path / "b.bin"
    bf.write_book(path, res.entries)
    out = run_uci(engine_path, [f"setoption name BookFile value {path}", "position startpos", "bookmoves"])
    assert f"({len(res.entries)} entries)" in out
    assert "d2d4" in out and "g1f3" in out
