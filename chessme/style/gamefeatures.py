"""Game-level style features from one PGN game with clocks (plan 8m): F1 opening, F2 clock use, F3 game shape.

Everything is computed for ONE side (the player) from the game text alone: no engine. NaN means "not applicable" (for example the
reply to 1.e4 in a game where the player was White, or clock features when the PGN has no clock comments). Aggregation over a
player's games ignores NaN, so a player is compared on the games where a feature exists."""
import io
import math
import re
import warnings

import chess
import chess.pgn
import numpy as np

NAN = float("nan")
CENTRE = chess.SquareSet([chess.D4, chess.E4, chess.D5, chess.E5])
MINOR_HOME = {chess.WHITE: (chess.B1, chess.G1, chess.C1, chess.F1), chess.BLACK: (chess.B8, chess.G8, chess.C8, chess.F8)}

OPENING = (
    "w_e4", "w_d4", "w_c4", "w_nf3", "w_other",
    "b_e4_e5", "b_e4_c5", "b_e4_e6", "b_e4_c6", "b_e4_other", "b_d4_d5", "b_d4_nf6", "b_d4_other",
    "early_pawn", "early_knight", "early_bishop", "early_rook", "early_queen", "early_king",
    "queen_early", "castle_move", "castled_short", "castled_by_10", "minors_out_by_8", "centre_control_10", "centre_pawns_10",
)
SHAPE = (
    "plies", "first_capture_ply", "queen_trade_ply", "pieces_at_40", "pieces_at_60", "pawns_at_40", "endgame_reached",
    "result", "end_mate", "end_resign", "end_time", "end_draw", "lost_on_time", "won_on_time",
)
CLOCK = (
    "think_median_rel", "think_mean_rel", "think_cv", "think_p90_rel", "think_open_rel", "think_mid_rel", "think_end_rel",
    "premove_frac", "instant_frac", "long_think_frac", "time_trouble_frac", "clock_left_frac", "first_think_rel", "opening_time_share",
)
FEATURE_NAMES = OPENING + SHAPE + CLOCK
FAMILY = {**{n: "opening" for n in OPENING}, **{n: "shape" for n in SHAPE}, **{n: "clock" for n in CLOCK}}
REPERTOIRE = ("eco_entropy_w", "eco_entropy_b", "distinct_eco_per_100", "top_eco_share_w", "top_eco_share_b")
_TC = re.compile(r"^(\d+)(?:\+(\d+))?$")


def parse_time_control(tc):
    """(base seconds, increment seconds) from '300+3' / '600'; (None, None) if unusable."""
    m = _TC.match(str(tc or "").strip())
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (None, None)


def _nan_dict(names):
    return {n: NAN for n in names}


def _entropy(counts):
    n = sum(counts)
    return -sum(c / n * math.log2(c / n) for c in counts if c) if n else NAN


# ---- F1 opening ------------------------------------------------------------------------------------------------------

def opening_features(game, color):
    f = _nan_dict(OPENING)
    moves = list(game.mainline_moves())
    board = game.board()
    san = []
    for m in moves:
        san.append(board.san(m))
        board.push(m)
    if color == chess.WHITE and san:
        first = san[0]
        for name, mv in (("w_e4", "e4"), ("w_d4", "d4"), ("w_c4", "c4"), ("w_nf3", "Nf3")):
            f[name] = float(first == mv)
        f["w_other"] = float(first not in ("e4", "d4", "c4", "Nf3"))
    if color == chess.BLACK and len(san) >= 2:
        first, reply = san[0], san[1]
        if first == "e4":
            for name, mv in (("b_e4_e5", "e5"), ("b_e4_c5", "c5"), ("b_e4_e6", "e6"), ("b_e4_c6", "c6")):
                f[name] = float(reply == mv)
            f["b_e4_other"] = float(reply not in ("e5", "c5", "e6", "c6"))
        elif first == "d4":
            for name, mv in (("b_d4_d5", "d5"), ("b_d4_nf6", "Nf6")):
                f[name] = float(reply == mv)
            f["b_d4_other"] = float(reply not in ("d5", "Nf6"))
    # own moves, replayed
    board = game.board()
    own_no, counts = 0, dict.fromkeys(("pawn", "knight", "bishop", "rook", "queen", "king"), 0)
    names = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}
    castle_no, castle_short, queen_by_8, at10, at8 = None, None, False, None, None
    for m in moves:
        if board.turn == color:
            own_no += 1
            piece = board.piece_type_at(m.from_square)
            if own_no <= 10:
                counts[names[piece]] += 1
            if own_no <= 8 and piece == chess.QUEEN:
                queen_by_8 = True
            if board.is_castling(m) and castle_no is None:
                castle_no, castle_short = own_no, chess.square_file(m.to_square) > chess.square_file(m.from_square)
        board.push(m)
        if board.turn != color and own_no in (8, 10) and (board.turn != color):     # just after the player's own move number 8 / 10
            snap = board.copy(stack=False)
            if own_no == 8 and at8 is None:
                at8 = snap
            if own_no == 10 and at10 is None:
                at10 = snap
    n_own = min(own_no, 10)
    if n_own >= 6:
        for k, v in counts.items():
            f[f"early_{k}"] = v / n_own
        f["queen_early"] = float(queen_by_8)
    if own_no >= 1:
        f["castle_move"] = float(castle_no) if castle_no is not None else NAN
        f["castled_short"] = float(castle_short) if castle_no is not None else NAN
        f["castled_by_10"] = float(castle_no is not None and castle_no <= 10) if own_no >= 10 else NAN
    if at8 is not None:
        f["minors_out_by_8"] = float(sum(1 for sq in MINOR_HOME[color] if (p := at8.piece_at(sq)) is None or p.color != color
                                          or p.piece_type not in (chess.KNIGHT, chess.BISHOP)))
    if at10 is not None:
        f["centre_control_10"] = float(sum(1 for sq in CENTRE if at10.is_attacked_by(color, sq)
                                           or ((p := at10.piece_at(sq)) is not None and p.color == color)))
        f["centre_pawns_10"] = float(sum(1 for sq in CENTRE if (p := at10.piece_at(sq)) is not None and p.color == color
                                         and p.piece_type == chess.PAWN))
    return f


# ---- F3 game shape ---------------------------------------------------------------------------------------------------

def shape_features(game, color):
    f = _nan_dict(SHAPE)
    moves = list(game.mainline_moves())
    board = game.board()
    first_capture = queen_trade = None
    at40 = at60 = None
    min_pieces = 32
    for ply, m in enumerate(moves, 1):
        if first_capture is None and board.is_capture(m):
            first_capture = ply
        board.push(m)
        if queen_trade is None and not board.pieces(chess.QUEEN, chess.WHITE) and not board.pieces(chess.QUEEN, chess.BLACK):
            queen_trade = ply
        n = chess.popcount(board.occupied)
        min_pieces = min(min_pieces, n)
        if ply == 40:
            at40 = (n, len(board.pieces(chess.PAWN, chess.WHITE)) + len(board.pieces(chess.PAWN, chess.BLACK)))
        if ply == 60:
            at60 = n
    f["plies"] = float(len(moves))
    f["first_capture_ply"] = float(first_capture) if first_capture else NAN
    f["queen_trade_ply"] = float(queen_trade) if queen_trade else NAN
    if at40:
        f["pieces_at_40"], f["pawns_at_40"] = float(at40[0]), float(at40[1])
    if at60 is not None:
        f["pieces_at_60"] = float(at60)
    f["endgame_reached"] = float(min_pieces <= 14)
    res = game.headers.get("Result", "*")
    score = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}.get(res)
    if score is not None:
        mine = score if color == chess.WHITE else 1.0 - score
        f["result"] = mine
        time_forfeit = "time" in game.headers.get("Termination", "").lower()
        f["end_mate"] = float(board.is_checkmate())
        f["end_time"] = float(time_forfeit)
        f["end_draw"] = float(score == 0.5)
        f["end_resign"] = float(score != 0.5 and not board.is_checkmate() and not time_forfeit)
        f["lost_on_time"] = float(time_forfeit and mine == 0.0)
        f["won_on_time"] = float(time_forfeit and mine == 1.0)
    return f


# ---- F2 clock use ----------------------------------------------------------------------------------------------------

def think_times(game, color, base, inc):
    """Seconds spent on each of the player's moves, from the %clk comments (None if the game has no clocks)."""
    node, prev, out = game, float(base), []
    board = game.board()
    while node.variations:
        node = node.variations[0]
        mover = board.turn
        board.push(node.move)
        clk = node.clock()
        if mover == color:
            if clk is None:
                return None
            out.append(max(prev - clk + inc, 0.0))
            prev = clk
    return out


def clock_features(game, color):
    f = _nan_dict(CLOCK)
    base, inc = parse_time_control(game.headers.get("TimeControl"))
    if base is None or base <= 0:
        return f
    times = think_times(game, color, base, inc)
    if not times or len(times) < 8:
        return f
    t = np.array(times)
    budget = base / 40.0 + inc                      # a nominal per-move budget: makes bullet and rapid comparable
    med = float(np.median(t))
    f["think_median_rel"], f["think_mean_rel"] = med / budget, float(t.mean()) / budget
    f["think_cv"] = float(t.std() / t.mean()) if t.mean() > 0 else NAN
    f["think_p90_rel"] = float(np.percentile(t, 90)) / budget
    for name, sl in (("think_open_rel", t[:12]), ("think_mid_rel", t[12:30]), ("think_end_rel", t[30:])):
        f[name] = float(sl.mean()) / budget if len(sl) >= 3 else NAN
    f["premove_frac"] = float((t <= 0.2 + 1e-9).mean())
    f["instant_frac"] = float((t <= 1.0).mean())
    f["long_think_frac"] = float((t > 3 * max(med, 0.5)).mean()) if med >= 0 else NAN
    f["first_think_rel"] = float(t[0]) / budget
    f["opening_time_share"] = float(t[:12].sum() / t.sum()) if t.sum() > 0 else NAN
    # clocks after each own move: remaining time
    clocks, node, board = [], game, game.board()
    while node.variations:
        node = node.variations[0]
        mover = board.turn
        board.push(node.move)
        if mover == color and node.clock() is not None:
            clocks.append(node.clock())
    if clocks:
        f["clock_left_frac"] = clocks[-1] / base
        f["time_trouble_frac"] = float(np.mean([c < max(10.0, 0.1 * base) for c in clocks]))
    return f


# ---- one game --------------------------------------------------------------------------------------------------------

def game_features(pgn_text, color):
    """(feature dict over FEATURE_NAMES, meta dict) for the player of `color`, or None if the PGN cannot be parsed."""
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return None
    f = {**opening_features(game, color), **shape_features(game, color), **clock_features(game, color)}
    h = game.headers
    meta = {"eco": h.get("ECO", "?"), "opening": h.get("Opening", "?"), "color": "white" if color == chess.WHITE else "black",
            "time_control": h.get("TimeControl", "?"), "result": f["result"]}
    return f, meta


def vector(feat):
    return np.array([feat[n] for n in FEATURE_NAMES], dtype=np.float32)


# ---- many games -> one player ----------------------------------------------------------------------------------------

def aggregate(rows, metas):
    """Mean of every feature over the games where it exists (NaN when it never does), plus repertoire statistics from the ECO
    codes: entropy per colour, distinct openings per 100 games, share of the most played opening per colour.
    Returns a vector over FEATURE_NAMES + REPERTOIRE."""
    arr = np.array(rows, dtype=float) if len(rows) else np.zeros((0, len(FEATURE_NAMES)))
    if len(arr):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)          # "mean of empty slice": a feature that never exists is NaN
            mean = np.nanmean(np.where(np.isfinite(arr), arr, np.nan), axis=0)
    else:
        mean = np.full(len(FEATURE_NAMES), np.nan)
    rep = []
    for colour in ("white", "black"):
        ecos = [m["eco"] for m in metas if m["color"] == colour and m["eco"] not in ("?", "")]
        counts = list(_counter(ecos).values())
        rep.append(_entropy(counts))
    n = max(len(metas), 1)
    rep.append(len({m["eco"] for m in metas if m["eco"] not in ("?", "")}) * 100.0 / n)
    for colour in ("white", "black"):
        ecos = [m["eco"] for m in metas if m["color"] == colour and m["eco"] not in ("?", "")]
        c = _counter(ecos)
        rep.append(max(c.values()) / sum(c.values()) if c else NAN)
    return np.concatenate([mean, np.array(rep, dtype=float)])


def _counter(items):
    out = {}
    for x in items:
        out[x] = out.get(x, 0) + 1
    return out


ALL_NAMES = FEATURE_NAMES + REPERTOIRE
