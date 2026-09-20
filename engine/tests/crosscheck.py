"""Cross-check the C++ move generator against python-chess on random game positions.

    .venv/bin/python engine/tests/crosscheck.py [--positions 300] [--depth 3] [--seed 1]

Plays random legal moves with python-chess to reach varied positions (including promotions, castling,
en passant, checks), then compares perft counts from the engine's `perft` binary with python-chess's.
"""
import argparse
import random
import subprocess
import sys
from pathlib import Path

import chess

PERFT = Path(__file__).resolve().parent.parent / "build" / "perft"


def py_perft(board, depth):
    if depth == 0:
        return 1
    if depth == 1:
        return board.legal_moves.count()
    n = 0
    for m in list(board.legal_moves):
        board.push(m)
        n += py_perft(board, depth - 1)
        board.pop()
    return n


def engine_perft(fen, depth):
    out = subprocess.run([str(PERFT), "--fen", fen, str(depth)], capture_output=True, text=True, check=True).stdout
    return int(out.split("Nodes:")[1].split()[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--positions", type=int, default=300)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    bad = 0
    seen = set()
    while len(seen) < a.positions:
        board = chess.Board()
        for _ in range(rng.randint(4, 120)):
            moves = list(board.legal_moves)
            if not moves:
                break
            board.push(rng.choice(moves))
        if board.is_game_over():
            continue
        fen = board.fen()
        if fen in seen:
            continue
        seen.add(fen)
        # keep python-chess tractable: shallower on positions with many moves
        d = a.depth if board.legal_moves.count() < 35 else max(1, a.depth - 1)
        exp, got = py_perft(board, d), engine_perft(fen, d)
        if exp != got:
            bad += 1
            print(f"MISMATCH d{d}: {fen}  python-chess={exp} engine={got}")
    print(f"{len(seen)} positions, {bad} mismatches")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
