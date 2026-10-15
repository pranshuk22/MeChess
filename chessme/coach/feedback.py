"""Feedback on a move a player tries in practice: not "right / wrong" but what the move does and how it compares with the engine's choice.

Grades, by the expected points the move gives away against the engine's best move (`loss`):
  best        the engine's first choice
  great       as good as the best (within 3 points): another way to the same result
  good        a sound move, not the best (up to 6 points): worth keeping, and the player may try for the best
  inaccuracy  6 to 10 points: gives something away
  mistake     10 to 20 points
  blunder     20 points or more: loses material, the advantage or the game
Every grade comes with reasons built from the board and the engine's lines only: what the move does, what the engine expects after it, what it costs, and for the best move
why it is better than the alternatives. `search(board) -> [Line, ...]` is the engine as everywhere else (best first, scores for the side to move)."""
import chess

from ..analysis import classify as C
from ..analysis import runner as AR
from ..humanlike import blunders as B
from . import exercises as X
from . import facts as F

GREAT, GOOD, MISTAKE, BLUNDER = 0.03, 0.06, 0.10, 0.20
SOLVED = ("best", "great", "good")                    # grades that count as finding a good move


def win(cp):
    return C.win_prob(cp, cap=C.LICHESS_CP_CAP)


def pct(x):
    return f"{round(100 * x)}%"


def grade_of(loss: float, is_best: bool) -> str:
    if is_best:
        return "best"
    if loss <= GREAT:
        return "great"
    if loss <= GOOD:
        return "good"
    if loss < MISTAKE:
        return "inaccuracy"
    return "mistake" if loss < BLUNDER else "blunder"


def _what(board, move):
    facts = F.describe_move(board, move)
    return (", and ".join(facts)) if facts else ""


def _line(board, pv, length=6):
    """SAN of an engine line (UCI moves, the first one played from `board`)."""
    return " ".join(X._san_line(board, pv[0], pv[1:], length)) if pv else ""


def feedback(fen: str, uci: str, search) -> dict:
    board = chess.Board(fen)
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return {"grade": "illegal"}
    if move not in board.legal_moves:
        return {"grade": "illegal"}
    lines = search(board)
    san = board.san(move)
    after = board.copy(stack=False)
    after.push(move)
    if not lines:                                                              # nothing to compare with (no engine line): say what the move does and nothing more
        return {"grade": "good", "solved": True, "loss": 0.0, "title": "Played", "reasons": [f"{san} " + (_what(board, move) or "is a legal move") + "."], "san": san, "uci": uci}
    best = lines[0]
    best_move = chess.Move.from_uci(best.move)
    best_san = board.san(best_move)
    best_wp = win(best.cp)
    is_best = uci == best.move
    reply = []
    if after.is_checkmate():
        played_wp, is_best_like = 1.0, True
    elif after.is_game_over():
        played_wp = 0.5
    else:
        reply = search(after)
        played_wp = win(-reply[0].cp) if reply else best_wp
    if is_best:
        played_wp = best_wp
    loss = 0.0 if is_best or after.is_checkmate() else max(0.0, best_wp - played_wp)
    grade = grade_of(loss, is_best)
    refutation = _line(after, list(reply[0].pv), 6) if reply else ""
    main_line = _line(board, list(best.pv), 6)
    others = [board.san(chess.Move.from_uci(l.move)) for l in lines[1:] if best_wp - win(l.cp) <= GREAT and l.move != uci]
    what = _what(board, move)
    out = {"grade": grade, "solved": grade in SOLVED, "loss": round(loss, 4), "winBefore": round(best_wp, 4), "winAfter": round(played_wp, 4), "san": san, "uci": uci,
           "bestSan": best_san, "bestUci": best.move, "alternatives": others, "line": refutation if grade not in ("best",) else main_line}
    reasons = []
    if grade == "best":
        out["title"] = "Best move"
        reasons.append(f"{san} is the engine's first choice" + (f": it {what}." if what else "."))
        if len(lines) > 1 and best_wp - win(lines[1].cp) >= MISTAKE:
            second = board.san(chess.Move.from_uci(lines[1].move))
            reasons.append(f"It is the only good move here: the next best, {second}, leaves you with {pct(win(lines[1].cp))} instead of {pct(best_wp)}.")
        elif others:
            reasons.append(f"{', '.join(others)} would also have been fine.")
        if main_line:
            reasons.append(f"The engine expects {main_line}, which keeps you at about {pct(best_wp)}.")
    elif grade == "great":
        out["title"] = "Excellent: as good as the best"
        reasons.append(f"{san} keeps you at about {pct(played_wp)}, the same as the engine's choice {best_san} ({pct(best_wp)})" + (f"; it {what}." if what else "."))
        if refutation:
            reasons.append(f"The engine expects {refutation}.")
    elif grade == "good":
        out["title"] = "Good move, not the best"
        reasons.append(f"{san} is sound" + (f" (it {what})" if what else "") + f", but {best_san} is about {round(100 * loss)} points stronger: {pct(best_wp)} against {pct(played_wp)}.")
        best_what = _what(board, best_move)
        if best_what:
            reasons.append(f"{best_san} {best_what}.")
        reasons.append("Keep this move, or try again for the best one.")
    else:
        kind, _ = B.classify(fen, uci)
        mate = next((m for m in after.legal_moves if X._is_mate(after, m)), None)
        given = AR.material_given(board, move, [l for l in (reply[0].pv if reply else [])])
        if mate is not None:
            reasons.append(f"After {san} the opponent can give checkmate with {after.san(mate)}.")
        elif kind in ("walks into a capture", "ignores a threat"):
            gain, cap = B.best_capture(after)
            if cap is not None:
                reasons.append(f"After {san} the opponent wins material with {after.san(cap)}, taking your {F.piece_name(after, cap.to_square)}.")
        elif given >= 2:
            reasons.append(f"You lose about {given:.0f} pawns' worth of material along the engine's line.")
        if refutation and mate is None:
            reasons.append(f"The engine expects {refutation}.")
        if played_wp <= 0.2 or (loss >= BLUNDER and played_wp < 0.35):
            out["title"] = "That loses"
            reasons.append(f"After {san} your chances fall from {pct(best_wp)} to {pct(played_wp)}: the position is lost.")
        else:
            out["title"] = "Inaccurate" if grade == "inaccuracy" else "That is a mistake"
            reasons.append(f"It gives away about {round(100 * loss)} points: your chances fall from {pct(best_wp)} to {pct(played_wp)}." if not mate else f"Your chances fall from {pct(best_wp)} to {pct(played_wp)}.")
        out["kind"] = kind
    out["reasons"] = reasons
    out["bestWhy"] = ([f"{best_san} " + (_what(board, best_move) or "is the engine's choice") + "."] + ([f"The engine's line: {main_line}."] if main_line else []))
    return out


def sentence(fb: dict) -> str:
    """The feedback as one paragraph (for places that show text only)."""
    return " ".join(fb.get("reasons", []))
