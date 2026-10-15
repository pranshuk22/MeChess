"""What KIND of blunder is it? A rule-based classification of moves that give away a lot, from the position and the move alone (no engine).

A blunder (loss > 0.20, `judge.py`) is sorted by what a one-move look at the position shows:

* `mate in 1`: after the move the opponent can give checkmate;
* `ignores a threat`: the opponent could win material by a capture BEFORE the move (as if the mover passed) and still can after it, by at least as much;
* `walks into a capture`: after the move the opponent wins material by a capture and that threat was not there before (the move moved to or exposed a piece);
  the value of what the move itself captured is subtracted, so an even trade (rook takes rook, rook is retaken) is not counted;
* `deeper`: none of the above, so the loss is not visible at one move (quiet or longer tactics, bad plans, wrong trades).

"Wins material" = the static exchange (swap) value of the best capture is at least two pawns. The classes depend on nothing but the board, so they apply in the
same way to the moves humans played and to the moves a model would sample. The point is a comparison of the MIX of blunder types between humans and models
(and between a model and its adapted version), because an equal blunder rate can hide a different kind of blunder."""
import chess
import numpy as np

from . import errors as E
from . import metrics as M

VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
WIN = 2                                                    # a capture wins material when its exchange value is at least this (in pawns)
TYPES = ["mate in 1", "ignores a threat", "walks into a capture", "deeper"]


def see(board, move):
    """Static exchange value of the capture `move` for the side moving, in pawns (swap algorithm; pieces are removed one by one so x-rays count)."""
    b = board.copy(stack=False)
    sq = move.to_square
    mover = b.piece_at(move.from_square)
    if mover is None:
        return 0
    if b.is_en_passant(move):
        captured = 1
    else:
        victim = b.piece_at(sq)
        if victim is None:
            return 0
        captured = VALUE[victim.piece_type]
    gain = [captured]
    cur = VALUE[mover.piece_type]
    b.remove_piece_at(move.from_square)
    if b.is_en_passant(move):
        b.remove_piece_at(chess.square(chess.square_file(sq), chess.square_rank(move.from_square)))
    b.set_piece_at(sq, mover)
    side = not mover.color
    while True:
        attackers = b.attackers(side, sq)
        if not attackers:
            break
        a_sq = min(attackers, key=lambda s: VALUE[b.piece_at(s).piece_type])
        gain.append(cur - gain[-1])
        cur = VALUE[b.piece_at(a_sq).piece_type]
        b.remove_piece_at(a_sq)
        side = not side
    for d in range(len(gain) - 1, 0, -1):
        gain[d - 1] = -max(-gain[d - 1], gain[d])
    return gain[0]


def best_capture(board):
    """(exchange value, move) of the best legal capture of the side to move, by static exchange; (0, None) if there is none."""
    best, move = 0, None
    for m in board.legal_moves:
        if board.is_capture(m):
            v = see(board, m)
            if move is None or v > best:
                best, move = v, m
    return best, move


def best_capture_gain(board):
    """The largest exchange value among the legal captures of the side to move (0 if none)."""
    return max(0, best_capture(board)[0])


def _pass_threat(board):
    """What the opponent could win if the side to move passed (0 when the side to move is in check: passing is not possible)."""
    if board.is_check():
        return 0
    b = board.copy(stack=False)
    b.push(chess.Move.null())
    return best_capture_gain(b)


def has_mate_in_one(board):
    for m in board.legal_moves:
        board.push(m)
        mate = board.is_checkmate()
        board.pop()
        if mate:
            return True
    return False


def classify(fen, uci):
    """(type, descriptors) of the move `uci` in the position `fen`; the type is one of `TYPES`. Meaningful for blunders only."""
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    piece = board.piece_at(move.from_square)
    desc = {"piece": chess.piece_name(piece.piece_type) if piece else "?", "capture": board.is_capture(move), "check": board.gives_check(move)}
    before = _pass_threat(board)
    taken = 1 if board.is_en_passant(move) else (VALUE[board.piece_at(move.to_square).piece_type] if board.is_capture(move) else 0)
    board.push(move)
    if board.is_game_over():
        return "deeper", desc
    if has_mate_in_one(board):
        return "mate in 1", desc
    after = best_capture_gain(board)
    if after - taken >= WIN:                              # what the opponent wins back, net of what the move itself captured (an even trade is no blunder of this kind)
        return ("ignores a threat" if before >= WIN and after >= before else "walks into a capture"), desc
    return "deeper", desc


# ---- the mix of blunder types, humans against a model ------------------------------------------------------------------------------------------

BLUNDER = E.THRESHOLDS["blunder (loss > 0.20)"]


def type_arrays(fens, played, cand_moves, cand_loss, human_loss, *, rank=None):
    """Type index (into TYPES) of every blunder, -1 where the move is no blunder (or empty). Returns (human_type (n,), cand_type (n, K), descriptors of the human
    blunders as a list of dicts, None for the others). Identical (position, move) pairs are classified once."""
    cache = {}

    def kind(fen, uci):
        key = (fen, uci)
        if key not in cache:
            cache[key] = classify(fen, uci)
        return cache[key]
    n, k = cand_loss.shape
    human = np.full(n, -1, dtype=np.int8)
    cand = np.full((n, k), -1, dtype=np.int8)
    desc = [None] * n
    for i in range(n):
        if human_loss[i] > BLUNDER:
            t, d = kind(fens[i], played[i])
            human[i], desc[i] = TYPES.index(t), d
        for j in range(k):
            if cand_loss[i, j] > BLUNDER and cand_moves[i][j]:
                cand[i, j] = TYPES.index(kind(fens[i], cand_moves[i][j])[0])
    return human, cand, desc


def tail_type_rates(human_type, rank, regime, k, min_n=20):
    """{regime: array over TYPES}: how often the humans' moves outside the judged candidates (rank > k) are blunders of each type, per clock regime."""
    out = {}
    for r in sorted(set(regime)):
        sel = (regime == r) & (rank > k)
        if sel.sum() >= min_n:
            out[r] = np.array([(human_type[sel] == t).mean() for t in range(len(TYPES))])
    return out


def type_rates(prep, cand_type, human_type, regime, tail=None):
    """Per position and type: (model's expected rate, human indicator), each (n, len(TYPES)). The model's probabilities are those of `prep` (frozen or adapted);
    the mass outside the judged candidates is added back at the humans' tail rate of that type in the same regime (if `tail` is given; a regime without
    enough tail positions gets no correction)."""
    n = len(human_type)
    model = np.zeros((n, len(TYPES)))
    human = np.zeros((n, len(TYPES)))
    for t in range(len(TYPES)):
        model[:, t] = (prep["p"] * (cand_type == t)).sum(axis=1)
        human[:, t] = human_type == t
    if tail is not None:
        mass = np.clip(prep["tail"], 0.0, 1.0)
        fill = np.array([tail.get(r, np.zeros(len(TYPES))) for r in regime])
        model = (1.0 - mass)[:, None] * model + mass[:, None] * fill
    return model, human


def compare_types(model, human, arr, mask, n_boot=500, seed=0):
    """{type: {"human", "model", "diff"} with (value, lo, hi)} on the masked positions; plus the shares of each type among the blunders."""
    out = {}
    for t, name in enumerate(TYPES):
        out[name] = {"human": M.cluster_bootstrap_mean(human[:, t], arr["gid"], n_boot=n_boot, seed=seed, mask=mask)[:3],
                     "model": M.cluster_bootstrap_mean(model[:, t], arr["gid"], n_boot=n_boot, seed=seed, mask=mask)[:3],
                     "diff": M.paired_cluster_bootstrap(model[:, t], human[:, t], arr["gid"], n_boot=n_boot, seed=seed, mask=mask)[:3]}
    sel = np.asarray(mask, dtype=bool)
    th, tm = human[sel].sum(), np.nansum(model[sel])
    out["share"] = {name: (float(human[sel][:, t].sum() / th) if th else float("nan"), float(np.nansum(model[sel][:, t]) / tm) if tm else float("nan")) for t, name in enumerate(TYPES)}
    out["n"] = int(sel.sum())
    return out


def render_types(rows, title=""):
    """Markdown: {label: compare_types() result}; rates in points (x100 per position), shares of the blunders in %."""
    lines = [title] if title else []
    lines += ["| subset | positions | blunder type | humans | model | model - humans | share of humans' blunders % | share of model's % |", "|---|---|---|---|---|---|---|---|"]
    for label, r in rows.items():
        for name in TYPES:
            f = lambda t: f"{100 * t[0]:.2f} [{100 * t[1]:.2f}, {100 * t[2]:.2f}]"
            sh, sm = r["share"][name]
            lines.append(f"| {label} | {r['n']:,} | {name} | {f(r[name]['human'])} | {f(r[name]['model'])} | {f(r[name]['diff'])} | {100 * sh:.0f} | {100 * sm:.0f} |")
    return "\n".join(lines)
