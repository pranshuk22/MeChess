"""Integration tests: the real engine binary, driven over UCI, checked against python-chess."""
import random
import re
import subprocess

import chess
import pytest

from tests.integration.uci_helper import best_move, last_score, run_uci

pytestmark = pytest.mark.integration


def random_position(rng, min_plies=4, max_plies=100):
    board = chess.Board()
    for _ in range(rng.randint(min_plies, max_plies)):
        moves = list(board.legal_moves)
        if not moves:
            break
        board.push(rng.choice(moves))
    return board


def test_uci_handshake(engine_path):
    out = run_uci(engine_path, ["uci", "isready"])
    assert "uciok" in out and "readyok" in out and "id name chessme" in out


def test_engine_exits_cleanly_on_quit_and_on_eof(engine_path):
    for script in ("uci\nquit\n", "uci\n", ""):
        p = subprocess.run([str(engine_path)], input=script, capture_output=True, text=True, timeout=20)
        assert p.returncode == 0


def test_bestmove_is_legal_in_random_positions(engine_path):
    rng = random.Random(7)
    tested = 0
    while tested < 40:
        board = random_position(rng)
        if board.is_game_over():
            continue
        mv, _ = best_move(engine_path, board.fen(), depth=3)
        assert chess.Move.from_uci(mv) in board.legal_moves, (board.fen(), mv)
        tested += 1


def test_position_command_matches_python_chess(engine_path):
    rng = random.Random(11)
    for _ in range(15):
        board = random_position(rng, 10, 60)
        moves = [m.uci() for m in board.move_stack]
        out = run_uci(engine_path, ["position startpos moves " + " ".join(moves), "d"])
        fen = re.search(r"Fen: (.*)", out).group(1)
        # engine writes the ep square after every double push (original FEN convention);
        # python-chess's default omits it unless a capture is legal, so ask it for the same convention.
        assert fen == board.fen(en_passant="fen"), moves


def test_no_legal_moves_gives_bestmove_0000(engine_path):
    mated = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
    stale = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"
    for fen in (mated, stale):
        mv, _ = best_move(engine_path, fen, depth=3)
        assert mv == "0000"


# --- forced-mate verification with an independent brute-force solver ----------------------------------------

def mates_in_one(board):
    out = []
    for m in list(board.legal_moves):
        board.push(m)
        if board.is_checkmate():
            out.append(m)
        board.pop()
    return out


def forcing_mate_in_two_moves(board):
    """White moves that mate in 2 (every black reply allows a mate in 1). Empty if there is none."""
    good = []
    for m in list(board.legal_moves):
        board.push(m)
        if not board.is_game_over():
            replies = list(board.legal_moves)
            if replies and all(_after(board, r, lambda b: bool(mates_in_one(b))) for r in replies):
                good.append(m)
        board.pop()
    return good


def _after(board, move, pred):
    board.push(move)
    try:
        return pred(board)
    finally:
        board.pop()


def random_kqk(rng):
    while True:
        squares = rng.sample(range(64), 3)
        b = chess.Board(None)
        b.set_piece_at(squares[0], chess.Piece(chess.KING, chess.WHITE))
        b.set_piece_at(squares[1], chess.Piece(chess.QUEEN, chess.WHITE))
        b.set_piece_at(squares[2], chess.Piece(chess.KING, chess.BLACK))
        b.turn = chess.WHITE
        if b.is_valid() and not b.is_game_over():
            return b


def test_engine_finds_every_forced_mate_in_two_that_the_solver_finds(engine_path):
    rng = random.Random(3)
    checked = 0
    attempts = 0
    while checked < 12 and attempts < 4000:
        attempts += 1
        b = random_kqk(rng)
        if mates_in_one(b):
            continue
        solutions = forcing_mate_in_two_moves(b)
        if not solutions:
            continue
        mv, out = best_move(engine_path, b.fen(), depth=6)
        kind, val = last_score(out)
        assert (kind, val) == ("mate", 2), (b.fen(), out)
        assert chess.Move.from_uci(mv) in solutions, (b.fen(), mv, [s.uci() for s in solutions])
        checked += 1
    assert checked >= 12, "could not generate enough mate-in-2 positions"


def test_engine_finds_mate_in_one_wherever_it_exists(engine_path):
    rng = random.Random(5)
    checked = 0
    while checked < 15:
        b = random_kqk(rng)
        sols = mates_in_one(b)
        if not sols:
            continue
        mv, out = best_move(engine_path, b.fen(), depth=4)
        assert last_score(out) == ("mate", 1)
        assert chess.Move.from_uci(mv) in sols
        checked += 1


def test_engine_never_stalemates_a_won_endgame(engine_path):
    """Self-play KQ v K: the side with the queen must finish with checkmate, never stalemate or a draw."""
    rng = random.Random(21)
    for _ in range(3):
        board = random_kqk(rng)
        moves = []
        start_fen = board.fen()
        for _ply in range(60):
            if board.is_game_over(claim_draw=False):
                break
            mv, _ = best_move(engine_path, start_fen, depth=5, moves=moves)
            assert chess.Move.from_uci(mv) in board.legal_moves
            board.push_uci(mv)
            moves.append(mv)
        assert board.is_checkmate(), (start_fen, moves)


def test_self_play_game_stays_legal_to_the_end(engine_path):
    """Engine vs itself from the start position; every move must be legal, the game must end sanely."""
    board = chess.Board()
    moves = []
    for _ in range(160):
        if board.is_game_over(claim_draw=True):
            break
        mv, _ = best_move(engine_path, chess.STARTING_FEN, depth=3, moves=moves)
        assert chess.Move.from_uci(mv) in board.legal_moves, (moves, mv)
        board.push_uci(mv)
        moves.append(mv)
    assert len(moves) > 20


def test_movetime_is_respected(engine_path):
    import time

    t0 = time.time()
    out = run_uci(engine_path, ["position startpos", "go movetime 300"])
    elapsed = time.time() - t0
    assert re.search(r"^bestmove ", out, re.M)
    assert elapsed < 1.5


def test_perft_command_agrees_with_python_chess(engine_path):
    rng = random.Random(2)
    for _ in range(8):
        b = random_position(rng, 6, 60)
        if b.is_game_over():
            continue
        out = run_uci(engine_path, [f"position fen {b.fen()}", "perft 2"])
        expected = sum(_count(b, m) for m in list(b.legal_moves))
        assert f"nodes {expected}" in out, b.fen()


def _count(board, move):
    board.push(move)
    n = board.legal_moves.count()
    board.pop()
    return n
