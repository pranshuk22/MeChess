"""Tactical motifs of a move, from the board alone: what the move does that makes it a tactic. Used to name the tactic a player missed (the engine's better move) or allowed (the opponent's
reply), so that mistakes can be counted by kind: "you miss forks and hanging pieces more than anything".

The motifs, in the order they are tried (the first that fits names the move):
  mate        gives checkmate, or the engine's line mates within a few moves
  back-rank   a rook or queen check that mates a king boxed in by its own pawns on the first rank
  promotion   promotes a pawn
  fork        the moved piece attacks two or more enemy pieces that are worth more than it or are not defended
  pin         the moved piece pins an enemy piece to its king or to a more valuable piece
  discovery   moving the piece uncovers an attack of a bishop, rook or queen behind it (a discovered check counts)
  hanging     takes a piece that cannot be recaptured, or that is worth more than the capturing piece
  trade       a capture that is otherwise even
  sacrifice   gives up material that the engine's line wins back
Nothing else is guessed: a move that fits none is "quiet"."""
import chess

from ..coach import facts as F

VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
TACTICS = ("mate", "back-rank", "promotion", "fork", "pin", "discovery", "hanging", "sacrifice")
NAMES = {"mate": "a forced mate", "back-rank": "a back-rank mate", "promotion": "a promotion", "fork": "a fork", "pin": "a pin", "discovery": "a discovered attack", "hanging": "a piece left hanging",
         "trade": "a trade", "sacrifice": "a sacrifice", "quiet": "a quiet move"}


def _attacked_by(board, square, colour):
    return board.attackers(colour, square)


def _targets(board, square):
    """Enemy pieces attacked by the piece on `square` that are worth more than it or are not defended (kings are not targets here)."""
    piece = board.piece_at(square)
    if piece is None:
        return []
    out = []
    for target in board.attacks(square):
        t = board.piece_at(target)
        if t is None or t.color == piece.color or t.piece_type == chess.KING:
            continue
        if VALUE[t.piece_type] > VALUE[piece.piece_type] or not board.attackers(t.color, target):
            if t.piece_type != chess.PAWN or not board.attackers(t.color, target):
                out.append(target)
    return out


def _mates_within(board, pv, plies):
    b = board.copy(stack=False)
    for i, u in enumerate(pv[:plies]):
        try:
            b.push_uci(u)
        except ValueError:
            return False
        if b.is_checkmate():
            return True
    return False


def motif_of(fen: str, uci: str, pv: list[str] | None = None) -> str:
    """The motif of the move `uci` in the position `fen` (one of `NAMES`' keys). `pv`: the engine's line that starts with the move (to see mates and returns of material)."""
    board = chess.Board(fen)
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return "quiet"
    if move not in board.legal_moves:
        return "quiet"
    mover = board.turn
    piece = board.piece_at(move.from_square)
    victim = board.piece_at(move.to_square)
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        king = after.king(not mover)
        rank = chess.square_rank(king)
        if rank in (0, 7) and piece.piece_type in (chess.ROOK, chess.QUEEN) and chess.square_rank(move.to_square) == rank:
            return "back-rank"
        return "mate"
    if pv and _mates_within(board, pv, 7):
        return "mate"
    if move.promotion:
        return "promotion"
    targets = _targets(after, move.to_square)
    if after.is_check() and move.to_square in after.checkers():
        targets = targets + [after.king(not mover)]                              # a check is one of the two attacks of a fork
    if len(targets) >= 2:
        return "fork"
    # pin: an enemy piece now stands between the moved slider and its king or a more valuable piece
    if piece.piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        for sq in chess.SquareSet(after.occupied_co[not mover]):
            p = after.piece_at(sq)
            if p.piece_type == chess.KING or not after.is_pinned(not mover, sq):
                continue
            pin_mask = after.pin(not mover, sq)
            if move.to_square in pin_mask and move.to_square != sq:
                return "pin"
    # discovered attack: a slider of ours behind the moved piece now attacks something new
    before_attacks = {sq for sq in chess.SquareSet(board.occupied_co[mover]) if sq != move.from_square and board.piece_at(sq).piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN)}
    for sq in before_attacks:
        gained = set(after.attacks(sq)) - set(board.attacks(sq))
        if any((t := after.piece_at(x)) is not None and t.color != mover and (t.piece_type == chess.KING or VALUE[t.piece_type] >= 3) for x in gained):
            return "discovery"
    if victim is not None or board.is_en_passant(move):
        gain = VALUE[victim.piece_type] if victim else 1
        recapture = bool(after.attackers(not mover, move.to_square))
        if not recapture or gain > VALUE[piece.piece_type]:
            return "hanging"
        return "trade"
    if pv:
        from . import runner as AR
        if AR.material_given(board, move, pv[1:]) >= 2:
            return "sacrifice"
    return "quiet"


def tactic_of_line(fen: str, line: list[str]) -> str:
    """The motif of the first move of an engine line, using the line itself for mates and material."""
    return motif_of(fen, line[0], line) if line else "quiet"
