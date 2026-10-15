"""Plain-language reasons for a move of an analysed game, from what is stored with it (the engine's lines before the move and before the next one) and the board.

`explain_move` returns one to three short sentences: what the move does, what the engine expected after it or what it allows, and what was better. Only facts from the board and the
engine's numbers are used (the same ones `coach.feedback` uses in practice), so every sentence can be checked on the board."""
import chess

from ..coach import facts as F
from ..humanlike import blunders as B
from . import classify as C
from . import runner as AR

BAD = ("inaccuracy", "mistake", "miss", "blunder")


def _pct(x):
    return f"{round(100 * x)}%"


def _what(board, move):
    facts = F.describe_move(board, move)
    return ", and ".join(facts)


def _san_line(board, ucis, length=5):
    b = board.copy(stack=False)
    out = []
    for u in ucis[:length]:
        try:
            mv = chess.Move.from_uci(u)
            out.append(b.san(mv))
            b.push(mv)
        except ValueError:
            break
    return out


def _win(cp_white, mover_white):
    return C.win_prob(cp_white if mover_white else -cp_white, cap=C.LICHESS_CP_CAP)


def explain_move(fen_before: str, m: dict, after_lines: list | None = None, prev_cls: str | None = None) -> list[str]:
    """`m`: a stored move row (san, uci, cls, loss, best, winBefore, winAfter, lines = engine lines before the move with cp for White). `after_lines`: the stored lines of the position
    after the move (the next move's `lines`). `prev_cls`: the class of the opponent's previous move."""
    board = chess.Board(fen_before)
    try:
        move = chess.Move.from_uci(m["uci"])
    except ValueError:
        return []
    if move not in board.legal_moves:
        return []
    san, cls = m["san"], m["cls"]
    lines = m.get("lines") or []
    mover_white = board.turn == chess.WHITE
    what = _what(board, move)
    if cls == "book":
        return [f"{san} is opening theory."]
    best_uci = lines[0]["uci"] if lines else m.get("best")
    best_move = None
    try:
        best_move = chess.Move.from_uci(best_uci) if best_uci else None
    except ValueError:
        pass
    best_san = board.san(best_move) if best_move and best_move in board.legal_moves else None
    out = []
    if cls in ("brilliant", "great", "best"):
        lead = {"brilliant": "A brilliant move", "great": "A great move", "best": "The engine's top choice"}[cls]
        out.append(f"{lead}: {san}" + (f" {what}." if what else "."))
        if len(lines) > 1:
            gap = _win(lines[0]["cp"], mover_white) - _win(lines[1]["cp"], mover_white)
            if gap >= 0.10:
                out.append(f"It is the only good move: the next best leaves you with {_pct(_win(lines[1]['cp'], mover_white))} instead of {_pct(_win(lines[0]['cp'], mover_white))}.")
        if cls == "brilliant" and AR.material_given(board, move, (after_lines[0]["pv"] if after_lines else [])) >= 1:
            out.append("It gives up material, and the engine's line shows it comes back.")
        return out
    if cls in ("excellent", "good"):
        out.append(f"{san} is a sound move" + (f": it {what}." if what else "."))
        if best_san and best_san != san and m["loss"] >= 0.01:
            bw = _what(board, best_move)
            out.append(f"The engine slightly prefers {best_san}" + (f" ({bw})" if bw else "") + f", worth about {round(100 * m['loss'])} points.")
        return out
    # a move that gave something away
    after = board.copy(stack=False)
    after.push(move)
    mate = next((mv for mv in after.legal_moves if _gives_mate(after, mv)), None)
    kind, _ = B.classify(fen_before, m["uci"])
    if mate is not None:
        out.append(f"After {san} the opponent can give checkmate with {after.san(mate)}.")
    elif kind in ("walks into a capture", "ignores a threat"):
        gain, cap = B.best_capture(after)
        if cap is not None:
            out.append(f"After {san} the opponent wins material with {after.san(cap)}, taking your {F.piece_name(after, cap.to_square)}.")
    if not out and after_lines:
        line = _san_line(after, after_lines[0]["pv"], 5)
        if line:
            out.append(f"The engine expects {' '.join(line)} after {san}.")
    elif out and after_lines and mate is None:
        line = _san_line(after, after_lines[0]["pv"], 4)
        if line:
            out.append(f"The engine's line: {' '.join(line)}.")
    out.append(f"Your chances fall from {_pct(m['winBefore'])} to {_pct(m['winAfter'])}.")
    if best_san and best_san != san:
        bw = _what(board, best_move)
        lead = "You missed" if cls == "miss" else "Better was"
        out.append(f"{lead} {best_san}" + (f", which {bw}." if bw else "."))
    return out


def _gives_mate(board, move):
    board.push(move)
    mate = board.is_checkmate()
    board.pop()
    return mate


def explain_all(moves: list[dict]) -> list[list[str]]:
    """Reasons for every move of a stored game (rows in the API's shape), walking the board once."""
    board = chess.Board()
    out = []
    for i, m in enumerate(moves):
        after_lines = moves[i + 1].get("lines") if i + 1 < len(moves) else None
        try:
            out.append(explain_move(board.fen(), m, after_lines, moves[i - 1]["cls"] if i else None))
            board.push_uci(m["uci"])
        except Exception:                                                              # (a sentence is never worth a failed page)
            out.append([])
            try:
                board.push_uci(m["uci"])
            except ValueError:
                pass
    return out
