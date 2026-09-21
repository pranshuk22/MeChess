"""Analyse a game move by move (plan 8n): one engine search per position, then classification, accuracy, phase and the
per-game summary (accuracy, class counts, critical moments, opportunism / luck, conversion / resourcefulness).

The engine is passed in as a `search(board) -> [Line, ...]` callable (best line first, scores from the side to move's point of view,
each Line with `.move` (UCI), `.cp` and `.pv`), so the logic runs and is tested without a real engine."""
import chess
import chess.pgn

from . import classify as C

PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
OPENING_MOVES = 10            # up to this full move: opening (unless the position is already an endgame)
ENDGAME_MATERIAL = 26         # both sides' pieces (knight, bishop 3, rook 5, queen 9; no pawns) at or below this: endgame
SACRIFICE_PLIES = 5           # follow the opponent's best line this far (own move, reply, own move, ...) before counting the material given
CLASSES = ("brilliant", "great", "best", "excellent", "good", "book", "inaccuracy", "mistake", "miss", "blunder")


def material(board, color):
    return sum(PIECE_VALUE[p.piece_type] for p in board.piece_map().values() if p.color == color and p.piece_type in PIECE_VALUE)


def phase(board):
    pieces = sum(PIECE_VALUE[p.piece_type] for p in board.piece_map().values() if p.piece_type not in (chess.PAWN, chess.KING))
    if pieces <= ENDGAME_MATERIAL:
        return "endgame"
    return "opening" if board.fullmove_number <= OPENING_MOVES else "middlegame"


def material_given(board, move, pv):
    """Pawns of material the mover is down after `move` and the opponent's best line `pv` (UCI list, opponent's move first),
    measured at the end of the (truncated) line, so that trades and recaptures inside it do not count as sacrifices."""
    mover = board.turn
    before = material(board, mover) - material(board, not mover)
    b = board.copy()
    b.push(move)
    for uci in pv[: SACRIFICE_PLIES - 1]:
        try:
            b.push_uci(uci)
        except ValueError:
            break
    end = b
    after = material(end, mover) - material(end, not mover)
    return max(0.0, before - after)


def analyse_game(game, search, *, book=None, thresholds=C.DEFAULT):
    """Analyse a python-chess game. Returns {"moves": [...], "summary": {...}}. `book(board, move) -> bool` marks theory moves."""
    board = game.board()
    nodes = list(game.mainline())
    positions, lines = [board.copy()], [search(board)]
    for node in nodes:
        board.push(node.move)
        positions.append(board.copy())
        lines.append(search(board) if not board.is_game_over() else [])
    out, prev_loss = [], {chess.WHITE: 0.0, chess.BLACK: 0.0}
    for i, node in enumerate(nodes):
        b, mv = positions[i], node.move
        mover = b.turn
        top = lines[i]
        if not top:
            continue
        best_cp = top[0].cp
        after = lines[i + 1]
        if after:
            played_cp = -after[0].cp
        elif positions[i + 1].is_checkmate():
            played_cp = C.MATE_CP
        else:
            played_cp = 0.0                                       # stalemate / other game end
        if mv.uci() == top[0].move:
            played_cp = best_cp                                   # the engine's own move: no loss, whatever the next search says
        opp_pv = after[0].pv if after else []
        me = C.MoveEval(
            best_cp=best_cp, played_cp=played_cp,
            second_cp=top[1].cp if len(top) > 1 else None, book=bool(book and book(b, mv)),
            material_given=material_given(b, mv, opp_pv), opp_loss=prev_loss[not mover], only_legal=b.legal_moves.count() == 1)
        cls = C.classify(me, thresholds)
        wb, wa = C.win_prob(best_cp), C.win_prob(played_cp)
        loss = max(0.0, wb - wa)
        prev_loss[mover] = loss
        out.append({"ply": i + 1, "move": b.san(mv), "uci": mv.uci(), "color": "white" if mover == chess.WHITE else "black",
                    "class": cls, "loss": round(loss, 4), "best_move": top[0].move, "best_cp": best_cp, "played_cp": played_cp,
                    "win_before": round(C.win_prob(best_cp), 4), "win_after": round(wa, 4),
                    "accuracy": round(C.move_accuracy(wb, wa), 2), "phase": phase(b)})
    return {"moves": out, "summary": summarise(out, game.headers)}


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def summarise(moves, headers=None, critical=5):
    """Per colour: accuracy overall and by phase, class counts, opportunism / luck, conversion / resourcefulness moments;
    plus the `critical` biggest losses of the whole game."""
    out = {"critical": [{k: m[k] for k in ("ply", "color", "move", "class", "loss", "best_move")}
                        for m in sorted(moves, key=lambda m: -m["loss"])[:critical] if m["loss"] >= 0.1]}
    for color in ("white", "black"):
        mine = [m for m in moves if m["color"] == color]
        theirs = [m for m in moves if m["color"] != color]
        by_phase = {ph: _mean([m["accuracy"] for m in mine if m["phase"] == ph]) for ph in ("opening", "middlegame", "endgame")}
        counts = {c: sum(m["class"] == c for m in mine) for c in CLASSES}
        # opportunism: after an opponent's mistake or worse (loss >= 0.10), did we take the gain (loss <= inaccuracy threshold)?
        opp_slips = [m for m in theirs if m["loss"] >= 0.10]
        taken = sum(1 for s in opp_slips for r in mine if r["ply"] == s["ply"] + 1 and r["loss"] <= 0.05)
        replied = sum(1 for s in opp_slips for r in mine if r["ply"] == s["ply"] + 1)
        my_slips = [m for m in mine if m["loss"] >= 0.10]
        unpunished = sum(1 for s in my_slips for r in theirs if r["ply"] == s["ply"] + 1 and r["loss"] > 0.05)
        replied_me = sum(1 for s in my_slips for r in theirs if r["ply"] == s["ply"] + 1)
        result = (headers or {}).get("Result", "*")
        score = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}.get(result)
        if score is not None and color == "black":
            score = 1.0 - score
        peak = max((v for m in mine for v in (m["win_before"], m["win_after"])), default=None)
        low = min((v for m in mine for v in (m["win_before"], m["win_after"])), default=None)
        out[color] = {
            "moves": len(mine), "accuracy": _mean([m["accuracy"] for m in mine]), "accuracy_by_phase": by_phase, "classes": counts,
            "opportunism": taken / replied if replied else None, "luck": unpunished / replied_me if replied_me else None,
            "peak_win": peak, "low_win": low, "score": score,
            # Lichess Tutor definitions: conversion = won after reaching >= 66.6% win chance; resourcefulness = not lost after falling <= 33.3%
            "had_winning_chance": None if peak is None else peak >= 0.666, "converted": None if score is None or peak is None or peak < 0.666 else score == 1.0,
            "was_losing": None if low is None else low <= 0.333, "saved": None if score is None or low is None or low > 0.333 else score > 0.0,
        }
    return out


# ---- engine adapter, files, report ------------------------------------------------------------------------------------------------

def engine_search(engine, *, nodes=200000, multipv=2):
    """A `search(board)` for a `UciEngine` (Stockfish): MultiPV lines at a fixed node budget, so results do not depend on the machine."""
    engine._send(f"setoption name MultiPV value {multipv}")
    engine.ready()

    def search(board):
        root = board.root()
        res = engine.go(root.fen(), [m.uci() for m in board.move_stack], nodes=nodes)
        return res.lines or ([SimpleLine(res.bestmove, res.score if res.score_kind == "cp" else 0, res.pv)] if res.bestmove else [])
    return search


class SimpleLine:
    def __init__(self, move, cp, pv):
        self.move, self.cp, self.pv = move, cp, list(pv)


def game_key(game, index):
    """A stable id for a game: the site id when the headers have one, else the position in the file."""
    site = game.headers.get("Site", "")
    gid = site.rsplit("/", 1)[-1] if "lichess.org" in site else ""
    return f"{index:05d}-{gid}" if gid else f"{index:05d}"


def side_of(game, player):
    """'white' / 'black' for the named player in a game, else None. A `MeChessSide` header (set when the games were chosen for a personal report) wins."""
    marked = game.headers.get("MeChessSide", "").lower()
    if marked in ("white", "black"):
        return marked
    p = (player or "").lower()
    for color, tag in (("white", "White"), ("black", "Black")):
        if p and game.headers.get(tag, "").lower() == p:
            return color
    return None


def render_report(results, player=None):
    """Markdown report over analysed games: accuracy by phase, class shares, critical moments, opportunism / luck, conversion."""
    rows, crit = [], []
    for key, res in results:
        color = res.get("player_color")
        if color:
            rows.append((key, res["summary"][color], res))
            crit += [(key, c) for c in res["summary"]["critical"] if c["color"] == color]
    if not rows:
        return "No games with the player found.\n"
    n = len(rows)

    def avg(f):
        vals = [f(s) for _, s, _ in rows if f(s) is not None]
        return sum(vals) / len(vals) if vals else None

    def fmt(v, pct=False):
        return "n/a" if v is None else (f"{100 * v:.0f}%" if pct else f"{v:.1f}")
    L = [f"# Game analysis{f': {player}' if player else ''}", "", f"{n} games analysed (engine analysis at a fixed node budget; scores are expected points, Lichess sigmoid).", "",
         f"- Accuracy: **{fmt(avg(lambda s: s['accuracy']))}**  (opening {fmt(avg(lambda s: s['accuracy_by_phase']['opening']))}, "
         f"middlegame {fmt(avg(lambda s: s['accuracy_by_phase']['middlegame']))}, endgame {fmt(avg(lambda s: s['accuracy_by_phase']['endgame']))})",
         f"- Opportunism (you punish their mistakes): {fmt(avg(lambda s: s['opportunism']), True)};  luck (they miss yours): {fmt(avg(lambda s: s['luck']), True)}"]
    conv = [s["converted"] for _, s, _ in rows if s["converted"] is not None]
    save = [s["saved"] for _, s, _ in rows if s["saved"] is not None]
    if conv:
        L.append(f"- Conversion (won after reaching >= 66.6% win chance): {sum(conv)}/{len(conv)}")
    if save:
        L.append(f"- Resourcefulness (not lost after falling to <= 33.3%): {sum(save)}/{len(save)}")
    total = {c: sum(s["classes"][c] for _, s, _ in rows) for c in CLASSES}
    moves = sum(s["moves"] for _, s, _ in rows) or 1
    L += ["", "## Move classes", "", "| class | moves | share |", "|---|---|---|"]
    L += [f"| {c} | {total[c]} | {100 * total[c] / moves:.1f}% |" for c in CLASSES if total[c]]
    L += ["", "## Biggest mistakes", "", "| game | ply | move | class | expected points lost | engine move |", "|---|---|---|---|---|---|"]
    L += [f"| {k} | {c['ply']} | {c['move']} | {c['class']} | {c['loss']:.2f} | {c['best_move']} |"
          for k, c in sorted(crit, key=lambda kc: -kc[1]["loss"])[:10]]
    return "\n".join(L) + "\n"
