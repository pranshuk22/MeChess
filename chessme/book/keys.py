"""Position keys shared with the C++ engine (engine/src/book/book.cpp: book_key)."""
import chess

FNV_OFFSET = 14695981039346656037
FNV_PRIME = 1099511628211
MASK = (1 << 64) - 1


def fnv1a64(text):
    h = FNV_OFFSET
    for b in text.encode():
        h = ((h ^ b) * FNV_PRIME) & MASK
    return h


def key_text(board):
    """Board, side to move and castling rights only: transpositions collapse, move counters and ep are ignored."""
    return " ".join(board.fen().split()[:3])


def book_key(board):
    if isinstance(board, str):
        board = chess.Board(board)
    return fnv1a64(key_text(board))
