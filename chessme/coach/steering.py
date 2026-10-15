"""A steered game: you play a normal game, and the opponent, among the moves the engine thinks are good enough, prefers the ones that put you in the kind of situation
you chose to practise. It never plays a move that costs more than a fixed amount of expected score (the budget), so the game stays fair and the opponent never throws it away.

Situations ("foci") are rules on the position after the opponent's move, computed from the board alone:
* `threats`: the move creates a threat against you (a capture that wins material), so you must notice it;
* `trades`: the move trades pieces, steering toward the endgame;
* `convert`: the move hands you an edge (the opponent chooses the weakest of the acceptable moves, up to a larger budget), so you must convert it;
* `defend`: the opponent plays its strongest, most forcing moves (checks and captures first), so you must defend;
* `sharp`: the position afterwards is tactical (many captures and checks for both sides).
Several foci can be mixed. The opponent's choice is a weighted draw: weight = exp(-gap / temperature) * exp(beta * focus score), where gap is the expected points the move gives away compared with the engine's best, so a near-best move that serves the focus is much likelier than a clearly worse one.

The engine is a callable `search(board) -> [Line, ...]` (best line first, MultiPV), as everywhere in the coach, so it runs and is tested without Stockfish."""
import math
import random

import chess
import chess.pgn

from ..analysis import classify as C
from . import facts as F

FOCI = {
    "threats": {"title": "Notice threats", "budget": 0.06, "tip": "The opponent will keep creating threats. Before every move ask what it attacks."},
    "trades": {"title": "Play the endgame", "budget": 0.06, "tip": "The opponent will trade pieces. Aim for the endgame with a plan."},
    "convert": {"title": "Convert an advantage", "budget": 0.15, "tip": "The opponent will give you an edge. Convert it without letting it go."},
    "defend": {"title": "Defend under pressure", "budget": 0.04, "tip": "The opponent will play its strongest, most forcing moves. Hold the position together."},
    "sharp": {"title": "Calculate in sharp positions", "budget": 0.08, "tip": "Expect tactical positions with many captures and checks. Calculate before you move."},
}
BETA = 3.0
TEMPERATURE = 0.03
NONPAWN = {chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


def win(cp):
    return C.win_prob(cp, cap=C.LICHESS_CP_CAP)


def _material(board):
    return sum(NONPAWN.get(p.piece_type, 0) for p in board.piece_map().values())


def score(focus, before, move, after, player):
    """How well the position `after` the opponent's `move` (played from `before`) serves the focus, 0..1."""
    if focus == "threats":
        return 1.0 if F.threats_against(after, player) else 0.0
    if focus == "trades":
        return 1.0 if before.is_capture(move) and _material(after) < _material(before) else 0.0
    if focus == "defend":
        return 1.0 if before.gives_check(move) else 0.6 if before.is_capture(move) else 0.0
    if focus == "sharp":
        n = sum(1 for m in after.legal_moves if after.is_capture(m) or after.gives_check(m))
        return min(1.0, n / 6.0)
    return 0.0                                                                # "convert" is handled through the gap, not a board feature


class SteeredOpponent:
    """`move(board) -> uci`, the interface of `session.EngineOpponent`. `foci` maps a focus name to a weight (the foci mixed in that proportion)."""

    def __init__(self, search, foci, player, beta=BETA, seed=0):
        unknown = [f for f in foci if f not in FOCI]
        if unknown:
            raise ValueError(f"unknown focus: {unknown}")
        self.search, self.foci, self.player, self.beta = search, dict(foci), player, beta
        self.rng = random.Random(seed)
        self.budget = max((FOCI[f]["budget"] for f in foci), default=0.05)
        self.hits = []                                                        # (ply index of the opponent's move, focus scores) for the review

    def candidates(self, board):
        """[(move, gap, focus score, per-focus scores)] of the moves allowed by the budget."""
        lines = self.search(board)
        if not lines:
            return []
        top = win(lines[0].cp)
        out = []
        for l in lines:
            gap = top - win(l.cp)
            if gap > self.budget:
                continue
            move = chess.Move.from_uci(l.move)
            after = board.copy(stack=False)
            after.push(move)
            per = {f: score(f, board, move, after, self.player) for f in self.foci}
            total_w = sum(self.foci.values()) or 1.0
            s = sum(self.foci[f] * v for f, v in per.items()) / total_w
            if "convert" in self.foci:                                        # prefer the weaker acceptable moves: the more it gives away, the better for this focus
                s += self.foci["convert"] / total_w * min(1.0, gap / max(self.budget, 1e-9)) - 0.0
            out.append((move, gap, s, per))
        return out

    def move(self, board):
        cands = self.candidates(board)
        if not cands:
            return None
        weights = [math.exp(-gap / TEMPERATURE) * math.exp(self.beta * s) for _, gap, s, _ in cands]
        i = self.rng.choices(range(len(cands)), weights=weights)[0]
        move, gap, s, per = cands[i]
        self.hits.append({"ply": len(board.move_stack) + 1, "scores": per, "gap": round(gap, 4)})
        return move.uci()


class SteeredGame:
    """A whole game against a `SteeredOpponent`. The player moves with `move(uci)`; the opponent answers at once. `pgn()` gives the finished game for the review."""

    def __init__(self, search, player_color, foci, seed=0, max_plies=240):
        self.player = chess.WHITE if player_color == "white" else chess.BLACK
        self.opponent = SteeredOpponent(search, foci, self.player, seed=seed)
        self.board = chess.Board()
        self.max_plies = max_plies
        self.finished = False
        self.foci = dict(foci)
        self._opponent_moves()

    def _opponent_moves(self):
        out = None
        if not self.is_over() and self.board.turn != self.player:
            uci = self.opponent.move(self.board)
            if uci:
                m = chess.Move.from_uci(uci)
                out = self.board.san(m)
                self.board.push(m)
        return out

    def is_over(self):
        return self.finished or self.board.is_game_over(claim_draw=True) or len(self.board.move_stack) >= self.max_plies

    def result(self):
        if self.board.is_game_over(claim_draw=True):
            return self.board.result(claim_draw=True)
        return "*"

    def view(self):
        over = self.is_over()
        return {"fen": self.board.fen(), "color": "white" if self.player == chess.WHITE else "black", "over": over, "result": self.result() if over else None,
                "legal": [] if over else [m.uci() for m in self.board.legal_moves], "plies": len(self.board.move_stack), "foci": self.foci}

    def move(self, uci):
        if self.is_over():
            return {"error": "the game is over", "view": self.view()}
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return {"error": "that is not a move", "view": self.view()}
        if move not in self.board.legal_moves:
            return {"error": "that move is not legal here", "view": self.view()}
        san = self.board.san(move)
        self.board.push(move)
        reply = self._opponent_moves()
        return {"san": san, "reply_san": reply, "view": self.view()}

    def finish(self):
        self.finished = True

    def pgn(self):
        game = chess.pgn.Game()
        game.headers["White"] = "You" if self.player == chess.WHITE else "Coach"
        game.headers["Black"] = "You" if self.player == chess.BLACK else "Coach"
        game.headers["Result"] = self.result()
        node = game
        for m in self.board.move_stack:
            node = node.add_variation(m)
        return str(game)


def focus_report(game, analysis, color, hits, foci, threshold=0.5):
    """How the player did in the situations the opponent steered toward: for each focus, how often it arose (a hit with score at least `threshold`), and the expected points the
    player gave away on the next move in those situations compared with the rest of the game. Returns (per-focus dict, plain sentences)."""
    by_ply = {m["ply"]: m for m in analysis["moves"]}
    mine = [m for m in analysis["moves"] if m["color"] == color]
    overall = sum(m["loss"] for m in mine) / len(mine) if mine else 0.0
    out, lines = {}, []
    for f in foci:
        times = [h["ply"] for h in hits if h["scores"].get(f, 0.0) >= threshold]
        replies = [by_ply[p + 1] for p in times if (p + 1) in by_ply and by_ply[p + 1]["color"] == color]
        if f == "convert":                                                      # "arose" = the opponent gave something away: the player's move is the conversion
            replies = [by_ply[h["ply"] + 1] for h in hits if h["gap"] > 0.02 and (h["ply"] + 1) in by_ply and by_ply[h["ply"] + 1]["color"] == color]
        n = len(replies)
        bad = [m for m in replies if m["loss"] >= 0.10]
        mean = sum(m["loss"] for m in replies) / n if n else None
        out[f] = {"situations": n, "mistakes": len(bad), "mean_loss": mean, "overall_mean_loss": overall}
        if n:
            lines.append(f"{FOCI[f]['title']}: the situation came up {n} time(s); you gave away points on {len(bad)} of them (on average {100 * mean:.0f} points per move, against {100 * overall:.0f} over the whole game).")
        else:
            lines.append(f"{FOCI[f]['title']}: the situation did not come up in this game.")
    return out, lines
