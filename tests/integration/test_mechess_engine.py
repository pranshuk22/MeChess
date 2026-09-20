"""Integration: MeChess (controller) driving the real C++ engine."""
import subprocess
import sys

import chess
import pytest

from chessme.book import format as bf
from chessme.book.keys import book_key
from chessme.mechess.controller import BookReader, MeChess
from chessme.mechess.priors import UniformPrior
from chessme.uci_client import UciEngine

pytestmark = pytest.mark.integration

# fast table for tests: a weak (wide window, tiny search) and a strong (narrow window) end
TABLE = {1200: (150, 8, 350, 1.6, 200, 6), 2400: (4000, 4, 40, 0.9, 40, 30)}


def play(engine_path, white_elo, black_elo, seed, book=None, max_plies=160):
    with UciEngine([str(engine_path)]) as ew, UciEngine([str(engine_path)]) as eb:
        players = {chess.WHITE: (MeChess(ew, UniformPrior(), book, TABLE, seed), white_elo),
                   chess.BLACK: (MeChess(eb, UniformPrior(), book, TABLE, seed + 1), black_elo)}
        board = chess.Board()
        while not board.is_game_over(claim_draw=True) and len(board.move_stack) < max_plies:
            mover, elo = players[board.turn]
            choice = mover.choose(board, elo)
            assert choice.move in board.legal_moves
            board.push(choice.move)
        return board


def score_for(board, color):
    out = board.outcome(claim_draw=True)
    if out is None or out.winner is None:
        return 0.5
    return 1.0 if out.winner == color else 0.0


def test_a_game_is_played_legally_from_start_to_finish(engine_path):
    board = play(engine_path, 1500, 1500, seed=3, max_plies=60)
    assert len(board.move_stack) >= 20


def test_the_rating_dial_changes_strength(engine_path):
    """Same prior, same engine: only the dial differs. The high setting must beat the low one clearly."""
    total, games = 0.0, 8
    for g in range(games):
        strong_white = g % 2 == 0
        board = play(engine_path, 2400 if strong_white else 1200, 1200 if strong_white else 2400, seed=10 + g)
        total += score_for(board, chess.WHITE if strong_white else chess.BLACK)
    assert total >= 6.0, f"strong setting scored only {total}/{games}"


def test_the_opening_book_is_followed_and_then_search_takes_over(engine_path, tmp_path):
    b = chess.Board()
    entries = [bf.Entry(book_key(b), chess.E2, chess.E4, 0, 5.0, 3, 500)]
    b.push_uci("e2e4")
    entries.append(bf.Entry(book_key(b), chess.E7, chess.E5, 0, 5.0, 3, 500))
    b.push_uci("e7e5")
    entries.append(bf.Entry(book_key(b), chess.G1, chess.F3, 0, 5.0, 3, 500))
    bf.write_book(tmp_path / "b.bin", entries)
    board = play(engine_path, 2400, 2400, seed=1, book=BookReader(tmp_path / "b.bin"), max_plies=8)
    assert [m.uci() for m in board.move_stack[:1]] == ["e2e4"] and board.move_stack[2].uci() == "g1f3"
    assert len(board.move_stack) == 8  # after the book ran out the engine kept playing legal moves


def run_uci_process(engine_path, script, *extra):
    p = subprocess.run([sys.executable, "-m", "chessme", "mechess", "--engine", str(engine_path), "--prior", "uniform",
                        "--seed", "5", *extra], input=script, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    return p.stdout


def test_mechess_runs_as_a_uci_engine_process(engine_path):
    out = run_uci_process(engine_path, "uci\nisready\nsetoption name Elo value 1500\n"
                                       "position startpos moves e2e4 e7e5 g1f3\ngo\nquit\n", "--elo", "1800")
    assert "id name MeChess" in out and "uciok" in out and "readyok" in out
    bm = [l for l in out.splitlines() if l.startswith("bestmove")][0].split()[1]
    b = chess.Board()
    for u in ("e2e4", "e7e5", "g1f3"):
        b.push_uci(u)
    assert chess.Move.from_uci(bm) in b.legal_moves


def test_mechess_finds_a_forced_mate_at_any_rating(engine_path):
    for elo in (1200, 2400):
        out = run_uci_process(engine_path, f"setoption name Elo value {elo}\n"
                                           "position fen 6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1\ngo\nquit\n")
        assert "bestmove d1d8" in out, out
