"""Style features of a single move, computed from the board before the move (python-chess only, no engine).

Every feature is a number (mostly 0/1) describing *what the move does*, in terms chess theory uses: forcing moves,
material dynamics (sacrifice, trade), king attack and safety, pawn structure, files, piece activity. Style is the
player's taste for these among moves of similar quality; that is measured elsewhere (choice-level model), not here.

Engine-dependent features (position sharpness, eval volatility, only-move creation) are deliberately absent: they need
search and are added at the candidate stage.
"""
import chess

VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
CENTER = chess.SquareSet([chess.D4, chess.E4, chess.D5, chess.E5])

FEATURE_NAMES = (
    # forcing
    "capture", "check", "promotion", "castle_short", "castle_long",
    # material dynamics
    "sacrifice", "exchange_sacrifice", "trade", "queen_trade",
    # king attack / safety
    "king_zone_delta", "pawn_storm", "weakens_own_king",
    # structure
    "pawn_break", "own_doubled_delta", "own_isolated_delta", "own_passed_delta",
    "opp_doubled_delta", "opp_isolated_delta", "takes_bishop_pair", "concedes_bishop_pair",
    # files
    "rook_open_file", "rook_semi_open_file", "rook_seventh",
    # activity
    "mobility_delta", "to_center", "pawn_push", "retreat", "king_move",
)
INDEX = {n: i for i, n in enumerate(FEATURE_NAMES)}


def _rel_rank(square, color):
    r = chess.square_rank(square)
    return r if color == chess.WHITE else 7 - r


def see(board, move):
    """Static exchange value of `move` for the mover in pawn units (>0 wins material, <0 loses it).

    Swap-list algorithm on the destination square, cheapest attacker first; x-rays revealed by the moving piece are
    counted, later ones are not. Promotions are not valued."""
    us, them = board.turn, not board.turn
    if board.is_en_passant(move):
        captured = 1
    else:
        p = board.piece_at(move.to_square)
        captured = VALUE[p.piece_type] if p else 0
    b = board.copy(stack=False)
    mover = b.piece_at(move.from_square)
    b.remove_piece_at(move.from_square)
    if board.is_en_passant(move):
        b.remove_piece_at(chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square)))
    b.remove_piece_at(move.to_square)  # the target piece is gone once captured
    atk = {c: sorted(VALUE[b.piece_type_at(s)] for s in b.attackers(c, move.to_square)) for c in (us, them)}
    gain = [captured]
    cur = VALUE[mover.piece_type]
    side = them
    while atk[side]:
        a = atk[side].pop(0)
        gain.append(cur - gain[-1])
        cur = a
        side = not side
    for i in range(len(gain) - 1, 0, -1):
        gain[i - 1] = -max(-gain[i - 1], gain[i])
    return gain[0]


def _pawn_structure(board, color):
    """(doubled, isolated, passed) pawn counts for `color`."""
    mine = board.pieces(chess.PAWN, color)
    theirs = board.pieces(chess.PAWN, not color)
    files = [0] * 8
    for s in mine:
        files[chess.square_file(s)] += 1
    doubled = sum(max(0, n - 1) for n in files)
    isolated = passed = 0
    for s in mine:
        f, r = chess.square_file(s), _rel_rank(s, color)
        if not any(files[g] for g in (f - 1, f + 1) if 0 <= g < 8):
            isolated += 1
        blocked = any(abs(chess.square_file(t) - f) <= 1 and _rel_rank(t, color) > r for t in theirs)
        if not blocked:
            passed += 1
    return doubled, isolated, passed


def _zone_attacks(board, color, king_sq):
    """How many attacks the non-king pieces of `color` put on the squares around (and including) `king_sq`."""
    zone = chess.SquareSet(board.attacks(king_sq)) | chess.SquareSet([king_sq])
    total = 0
    for sq, piece in board.piece_map().items():
        if piece.color == color and piece.piece_type != chess.KING:
            total += len(chess.SquareSet(board.attacks(sq)) & zone)
    return total


def _mobility(board, color):
    b = board.copy(stack=False)
    b.turn = color
    b.ep_square = None
    return b.pseudo_legal_moves.count()


def move_features(board, move):
    """dict feature name -> float for `move` played by the side to move on `board` (move must be legal)."""
    us, them = board.turn, not board.turn
    piece = board.piece_at(move.from_square)
    pt = piece.piece_type
    ep = board.is_en_passant(move)
    victim = board.piece_at(move.to_square)
    is_capture = board.is_capture(move)
    captured = 1 if ep else (VALUE[victim.piece_type] if victim else 0)
    victim_type = chess.PAWN if ep else (victim.piece_type if victim else None)
    f = dict.fromkeys(FEATURE_NAMES, 0.0)

    after = board.copy(stack=False)
    after.push(move)

    f["capture"] = float(is_capture)
    f["check"] = float(board.gives_check(move))
    f["promotion"] = float(move.promotion is not None)
    if board.is_castling(move):
        f["castle_short" if chess.square_file(move.to_square) > chess.square_file(move.from_square) else "castle_long"] = 1.0

    # material dynamics
    if pt != chess.KING or is_capture:
        s = see(board, move)
        f["sacrifice"] = float(s <= -2)
        f["exchange_sacrifice"] = float(pt == chess.ROOK and -3 <= s <= -2)
        recapture = bool(after.attackers(them, move.to_square)) if is_capture else False
        f["trade"] = float(is_capture and captured >= 3 and s >= -1 and recapture)
        f["queen_trade"] = float(pt == chess.QUEEN and victim_type == chess.QUEEN and recapture)

    # king attack and safety
    ek, ok = board.king(them), board.king(us)
    if ek is not None:
        f["king_zone_delta"] = float(_zone_attacks(after, us, ek) - _zone_attacks(board, us, ek))
        ek_file = chess.square_file(ek)
        if pt == chess.PAWN and (ek_file <= 2 or ek_file >= 5):
            f["pawn_storm"] = float(abs(chess.square_file(move.to_square) - ek_file) <= 2
                                    and _rel_rank(move.to_square, us) >= 3)
    if ok is not None and pt == chess.PAWN:
        ok_file = chess.square_file(ok)
        if (ok_file <= 2 or ok_file >= 5) and _rel_rank(ok, us) <= 1:
            f["weakens_own_king"] = float(abs(chess.square_file(move.from_square) - ok_file) <= 1
                                          and _rel_rank(move.from_square, us) <= 2
                                          and _rel_rank(move.to_square, us) >= 3)

    # structure
    if pt == chess.PAWN:
        contact = bool(after.attackers(them, move.to_square) & board.pieces_mask(chess.PAWN, them))
        f["pawn_break"] = float(contact or victim_type == chess.PAWN)
    for name, color, idx in (("own_doubled_delta", us, 0), ("own_isolated_delta", us, 1), ("own_passed_delta", us, 2),
                             ("opp_doubled_delta", them, 0), ("opp_isolated_delta", them, 1)):
        f[name] = float(_pawn_structure(after, color)[idx] - _pawn_structure(board, color)[idx])
    if victim_type == chess.BISHOP and len(board.pieces(chess.BISHOP, them)) == 2:
        f["takes_bishop_pair"] = 1.0
    if (pt == chess.BISHOP and victim_type in (chess.KNIGHT, chess.BISHOP) and len(board.pieces(chess.BISHOP, us)) == 2
            and after.attackers(them, move.to_square)):
        f["concedes_bishop_pair"] = 1.0

    # files
    if pt == chess.ROOK and chess.square_file(move.to_square) != chess.square_file(move.from_square):
        file_mask = chess.BB_FILES[chess.square_file(move.to_square)]
        own = board.pieces_mask(chess.PAWN, us) & file_mask
        opp = board.pieces_mask(chess.PAWN, them) & file_mask
        f["rook_open_file"] = float(not own and not opp)
        f["rook_semi_open_file"] = float(not own and bool(opp))
    f["rook_seventh"] = float(pt == chess.ROOK and _rel_rank(move.to_square, us) == 6
                              and _rel_rank(move.from_square, us) != 6)

    # activity
    f["mobility_delta"] = float(_mobility(after, us) - _mobility(board, us))
    f["to_center"] = float(move.to_square in CENTER and pt != chess.KING)
    f["pawn_push"] = float(pt == chess.PAWN and not is_capture)
    f["retreat"] = float(pt not in (chess.PAWN, chess.KING)
                         and _rel_rank(move.to_square, us) < _rel_rank(move.from_square, us))
    f["king_move"] = float(pt == chess.KING and not board.is_castling(move))
    return f


def feature_vector(board, move):
    d = move_features(board, move)
    return [d[n] for n in FEATURE_NAMES]
