"""Facts about a position and a move, computed from the board alone (python-chess): what a move captures, whether it gives check, which piece of the
mover was under attack before it, whether the attack is gone after it, whether it creates a threat. The explanations and the hints are built only from
these facts and the engine's evaluations. "Wins material" always means a static-exchange value of at least two pawns (`humanlike.blunders.WIN`)."""
import chess

from ..humanlike import blunders as B

NAMES = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}
WIN = B.WIN


def piece_name(board, square):
    p = board.piece_at(square)
    return NAMES[p.piece_type] if p else "piece"


def _as_if_to_move(board, color):
    b = board.copy(stack=False)
    b.turn = color
    b.ep_square = None
    return b


def captures_for(board, color):
    """[(value, square of the captured piece, move)] of the captures `color` would have if it were its turn, best first, only those winning at least
    two pawns by static exchange; the king is never a victim."""
    b = _as_if_to_move(board, color)
    out = []
    for m in b.legal_moves:
        victim = b.piece_at(m.to_square)
        if b.is_capture(m) and (victim is None or victim.piece_type != chess.KING):
            v = B.see(b, m)
            if v >= WIN:
                out.append((v, m.to_square, m))
    return sorted(out, key=lambda t: -t[0])


def threats_against(board, color):
    """What the opponent of `color` could win by a capture if it were its turn (the threats `color` faces)."""
    return captures_for(board, not color)


def describe_move(board, move):
    """Short phrases saying what the move does: castles, promotes, captures, checkmates, gives check, saves an attacked piece, threatens to win material."""
    mover = board.turn
    piece = board.piece_at(move.from_square)
    out = []
    if board.is_castling(move):
        out.append("castles")
    if move.promotion:
        out.append(f"promotes to a {NAMES[move.promotion]}")
    if board.is_capture(move):
        out.append("captures a pawn en passant" if board.is_en_passant(move) else f"captures the {piece_name(board, move.to_square)} on {chess.square_name(move.to_square)}")
    attacked = {sq for _, sq, _ in threats_against(board, mover)}
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return out + ["gives checkmate"]
    if after.is_check():
        out.append("gives check")
    still = {sq for _, sq, _ in threats_against(after, mover)}
    if move.from_square in attacked and move.to_square not in still:
        out.append(f"moves the attacked {NAMES[piece.piece_type]} out of danger")
    else:
        saved = [sq for sq in attacked if sq != move.from_square and sq not in still]
        if saved:
            out.append(f"protects the {piece_name(board, saved[0])} on {chess.square_name(saved[0])}")
    if not after.is_check():
        nxt = captures_for(after, mover)
        if nxt:
            out.append(f"threatens to win material with {_as_if_to_move(after, mover).san(nxt[0][2])}")
    return out
