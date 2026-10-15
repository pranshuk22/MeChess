"""Exercises from a game: the moments where the player lost the most, each with the position BEFORE the move, the move played, the engine's better move,
the kind of mistake (rules on the board, `humanlike.blunders`), a ladder of hints and a plain-sentence explanation.

Input is a python-chess game and its analysis (`analysis.runner.analyse_game`: one record per move with the engine's best move and the expected-points loss).
Positions that were already lost before the move, or already won by a wide margin after it, are skipped: the exercise must be fair and worth the time."""
import chess

from ..humanlike import blunders as B
from . import facts as F
from .drills import drill_id

MIN_LOSS = 0.10          # expected points a move gave away to become an exercise
MIN_WIN_BEFORE = 0.15    # skip positions that were lost already
KIND_TEXT = {"mate in 1": "allowed a checkmate in one", "ignores a threat": "did not deal with a threat", "walks into a capture": "put a piece where it can be captured",
             "deeper": "gave away the advantage in a way that is not a one-move oversight"}


def _pct(x):
    return f"{100 * x:.0f}%"


def exercise(fen, played_uci, best_uci, loss, win_before, win_after, ply=None, phase=None, cls=None):
    """One exercise as a dictionary (JSON-friendly): everything the interface needs."""
    board = chess.Board(fen)
    played, best = chess.Move.from_uci(played_uci), chess.Move.from_uci(best_uci)
    kind, _ = B.classify(fen, played_uci)
    ex = {"id": drill_id(fen, best_uci), "fen": fen, "color": "white" if board.turn == chess.WHITE else "black", "ply": ply, "phase": phase, "class": cls,
          "played_uci": played_uci, "played_san": board.san(played), "best_uci": best_uci, "best_san": board.san(best), "loss": round(float(loss), 4),
          "win_before": round(float(win_before), 4), "win_after": round(float(win_after), 4), "kind": kind}
    ex["hints"] = hints(board, best)
    ex["explanation"] = explain(board, played, best, kind, win_before, win_after)
    return ex


def hints(board, best):
    """A ladder from vague to exact: the theme, the piece, the move."""
    mover = board.turn
    threats = F.threats_against(board, mover)
    wins = F.captures_for(board, mover)
    if board.is_check():
        first = "Your king is in check: look at every way to answer it."
    elif threats:
        first = f"Your {F.piece_name(board, threats[0][1])} on {chess.square_name(threats[0][1])} is under attack. Is there more than one way to deal with it?"
    elif wins:
        first = "You can win material here. Look at the captures."
    else:
        first = "Nothing is hanging at once, so think about the opponent's last move: what does it threaten, and what do you want your pieces to do?"
    piece = board.piece_at(best.from_square)
    second = f"Move your {F.NAMES[piece.piece_type]} (the one on {chess.square_name(best.from_square)})."
    return [first, second, f"The move is {board.san(best)}."]


def _san_line(board, first, pv, length):
    """SAN of `first` followed by the engine's line `pv` (UCI), at most `length` half-moves, stopping at the first illegal move."""
    b = board.copy(stack=False)
    out = []
    for uci in [first] + list(pv):
        if len(out) >= length:
            break
        try:
            m = chess.Move.from_uci(uci)
        except ValueError:
            break
        if m not in b.legal_moves:
            break
        out.append(b.san(m))
        b.push(m)
    return out


def enrich(ex, search, length=6):
    """Add the engine's own continuations: `refutation` (what the opponent does after the played move) and `main_line` (the better move and what follows),
    as short SAN strings, and rebuild the explanation with them. `search(board) -> [Line, ...]` as in `analysis.runner`."""
    board = chess.Board(ex["fen"])
    played, best = chess.Move.from_uci(ex["played_uci"]), chess.Move.from_uci(ex["best_uci"])
    lines = {}
    for key, move in (("refutation", played), ("main_line", best)):
        b = board.copy(stack=False)
        b.push(move)
        found = [] if b.is_game_over() else search(b)
        pv = list(found[0].pv) if found else []
        lines[key] = _san_line(b, pv[0], pv[1:], length - 1) if pv else []
    ex["refutation"] = " ".join(lines["refutation"])
    ex["main_line"] = " ".join(lines["main_line"])
    ex["explanation"] = explain(board, played, best, ex["kind"], ex["win_before"], ex["win_after"], ex["refutation"], ex["main_line"])
    return ex


def explain(board, played, best, kind, win_before, win_after, refutation="", main_line=""):
    """Plain sentences: what the played move allowed, then what the better move does. Only facts from the board and the engine's numbers."""
    san, best_san = board.san(played), board.san(best)
    mover = board.turn
    after = board.copy(stack=False)
    after.push(played)
    lines = [f"You played {san}. The engine gives your side about {_pct(win_before)} before it and {_pct(win_after)} after it."]
    if kind == "mate in 1":
        mate = next((m for m in after.legal_moves if _is_mate(after, m)), None)
        lines.append(f"After {san} the opponent can give checkmate with {after.san(mate)}." if mate else f"After {san} the opponent can give checkmate.")
    elif kind in ("walks into a capture", "ignores a threat"):
        gain, cap = B.best_capture(after)
        if cap is not None:
            victim = F.piece_name(after, cap.to_square)
            lines.append(f"After {san} the opponent wins material with {after.san(cap)}, taking your {victim} (worth about {gain} pawns after the exchange)."
                         + (" The same capture was already on before your move, and your move did not stop it." if kind == "ignores a threat" else ""))
    else:
        lines.append("Nothing is hanging at once, so this was not a one-move oversight: the move gave up the advantage over a longer sequence.")
    if refutation:
        lines.append(f"The engine expects the game to go on {refutation} after {san}.")
    what = F.describe_move(board, best)
    lines.append(f"A better move was {best_san}" + (": it " + ", and ".join(what) + "." if what else "."))
    if main_line:
        lines.append(f"The engine's line after {best_san} is {main_line}.")
    return " ".join(lines)


def _is_mate(board, move):
    board.push(move)
    mate = board.is_checkmate()
    board.pop()
    return mate


def from_analysis(game, analysis, color, max_n=5, min_gap=4):
    """The biggest mistakes of `color` ("white" or "black") in an analysed game, at most `max_n`, at least `min_gap` plies apart, in game order."""
    board = game.board()
    fens = {}
    for i, node in enumerate(game.mainline()):
        fens[i + 1] = board.fen()
        board.push(node.move)
    rows = [m for m in analysis["moves"] if m["color"] == color and m["loss"] >= MIN_LOSS and m["win_before"] >= MIN_WIN_BEFORE and m["uci"] != m["best_move"]]
    chosen = []
    for m in sorted(rows, key=lambda m: -m["loss"]):
        if all(abs(m["ply"] - c["ply"]) >= min_gap for c in chosen):
            chosen.append(m)
        if len(chosen) == max_n:
            break
    return [exercise(fens[m["ply"]], m["uci"], m["best_move"], m["loss"], m["win_before"], m["win_after"], m["ply"], m["phase"], m["class"])
            for m in sorted(chosen, key=lambda m: m["ply"])]
