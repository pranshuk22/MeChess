"""A small deterministic 'engine' for the preparation tests: negamax over material to depth 2 with mate detection. Lines come best first with the score for the side to move."""
import chess

from chessme.analysis.runner import SimpleLine

VAL = {chess.PAWN: 100, chess.KNIGHT: 300, chess.BISHOP: 300, chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}


def material(board):
    s = sum(VAL[p.piece_type] * (1 if p.color == chess.WHITE else -1) for p in board.piece_map().values())
    return s if board.turn == chess.WHITE else -s


def negamax(board, depth):
    if board.is_checkmate():
        return -10000
    if board.is_game_over():
        return 0
    if depth == 0:
        return material(board)
    best = -10 ** 6
    for mv in board.legal_moves:
        board.push(mv)
        best = max(best, -negamax(board, depth - 1))
        board.pop()
    return best


def search(board, depth=2):
    lines = []
    for mv in sorted(board.legal_moves, key=lambda m: m.uci()):
        board.push(mv)
        lines.append(SimpleLine(mv.uci(), -negamax(board, depth - 1), [mv.uci()]))
        board.pop()
    lines.sort(key=lambda l: -l.cp)
    return lines
