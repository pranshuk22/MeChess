"""A guided replay: for each exercise the player is asked to find a better move than the one they played, with a ladder of hints; the move is judged by the
engine, explained in plain sentences, and the game goes on from the position after it against an opponent, so the consequence of the better move is
felt. The player can reset and try again. The engine and the opponent are passed in as plain callables (`search(board) -> [Line, ...]`, best line first,
scores from the side to move; see `analysis.runner`), so everything here runs and is tested without a real engine."""
import math
import random

import chess

from ..analysis import classify as C

FOUND, OK, NOT_YET = 0.03, 0.08, "not yet"      # loss (expected points) up to which a move counts as the engine's choice / still a good move
MAX_TRIES_BEFORE_OFFER = 3


def win(cp):
    return C.win_prob(cp, cap=C.LICHESS_CP_CAP)


class Judge:
    """Judges a move in a position by the engine: loss in expected points against the best move."""

    def __init__(self, search):
        self.search = search

    def loss(self, fen, uci):
        board = chess.Board(fen)
        lines = self.search(board)
        if not lines or uci == lines[0].move:
            return 0.0
        board.push_uci(uci)
        if board.is_checkmate():
            return 0.0
        if board.is_game_over():
            played = 0.0
        else:
            nxt = self.search(board)
            played = -nxt[0].cp if nxt else 0.0
        return max(0.0, win(lines[0].cp) - win(played))


class EngineOpponent:
    """Plays the engine's good moves with a little variety: among the lines within `window` expected points of the best, it picks with weights exp(-gap / temperature).
    A stand-in for a human-like opponent (a Maia model or the steering opponent can replace it: any object with `move(board) -> uci`)."""

    def __init__(self, search, window=0.08, temperature=0.04, seed=0):
        self.search, self.window, self.temperature = search, window, temperature
        self.rng = random.Random(seed)

    def move(self, board):
        lines = self.search(board)
        if not lines:
            return None
        top = win(lines[0].cp)
        pool = [(l, top - win(l.cp)) for l in lines if top - win(l.cp) <= self.window]
        weights = [math.exp(-gap / self.temperature) for _, gap in pool]
        return self.rng.choices([l.move for l, _ in pool], weights=weights)[0]


class Replay:
    """One player's guided replay of a list of exercises (`exercises.exercise` dictionaries)."""

    def __init__(self, exercises, judge, opponent):
        self.exercises, self.judge, self.opponent = list(exercises), judge, opponent
        self.index = -1
        self.log = []                                  # one record per attempt: for spaced repetition and the weakness profile
        self.next()

    # ---- state ------------------------------------------------------------------------------------------------------------------------
    @property
    def ex(self):
        return self.exercises[self.index] if 0 <= self.index < len(self.exercises) else None

    def next(self):
        self.index += 1
        self._start()
        return self.view()

    def _start(self):
        self.mode, self.hints_used, self.tries, self.board = "find", 0, 0, (chess.Board(self.ex["fen"]) if self.ex else None)

    def reset(self):
        """Back to the position before the mistake (the number of tries is kept for the log, the hints are reset)."""
        self.mode, self.hints_used, self.board = "find", 0, chess.Board(self.ex["fen"])
        return self.view()

    def view(self):
        if self.ex is None:
            return {"done": True, "mode": "done", "attempts": len(self.log)}
        return {"done": False, "mode": self.mode, "index": self.index, "of": len(self.exercises), "fen": self.board.fen(), "color": self.ex["color"], "ply": self.ex["ply"],
                "hints_used": self.hints_used, "tries": self.tries, "can_reveal": self.mode == "find" and self.tries >= MAX_TRIES_BEFORE_OFFER or self.hints_used >= 3,
                "last_moves_known": None}

    # ---- the find-a-better-move step ----------------------------------------------------------------------------------------------------
    def hint(self):
        if self.mode != "find":
            return {"error": "no hint now"}
        if self.hints_used >= len(self.ex["hints"]):
            return {"hint": self.ex["hints"][-1], "level": len(self.ex["hints"])}
        self.hints_used += 1
        return {"hint": self.ex["hints"][self.hints_used - 1], "level": self.hints_used}

    def attempt(self, uci):
        """Judge the player's move from the starting position of the exercise."""
        if self.mode != "find":
            return {"error": "not looking for a move now"}
        board = chess.Board(self.ex["fen"])
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return {"error": "that is not a move"}
        if move not in board.legal_moves:
            return {"error": "that move is not legal here"}
        self.tries += 1
        loss = 0.0 if uci == self.ex["best_uci"] else self.judge.loss(self.ex["fen"], uci)
        verdict = "found" if loss <= FOUND else "ok" if loss <= OK else NOT_YET
        self.log.append({"index": self.index, "ply": self.ex["ply"], "kind": self.ex["kind"], "phase": self.ex["phase"], "uci": uci, "loss": round(loss, 4),
                         "verdict": verdict, "hints_used": self.hints_used})
        if verdict == NOT_YET:
            if uci == self.ex["played_uci"]:
                msg = "That is the move from your game. Look for something else."
            else:
                msg = f"{board.san(move)} is not it: it still gives away about {100 * loss:.0f} points of expected score. Try again, or ask for a hint."
            return {"verdict": verdict, "loss": loss, "message": msg, "can_reveal": self.tries >= MAX_TRIES_BEFORE_OFFER}
        board.push(move)
        self.board, self.mode = board, "play"
        reply = self._reply()
        if verdict == "found":
            msg = "Yes. " + self.ex["explanation"]
        else:
            msg = (f"{self.ex['played_san']} was the mistake in your game; {chess.Board(self.ex['fen']).san(move)} is fine (it gives away only {100 * loss:.0f} points). "
                   f"The engine's first choice was {self.ex['best_san']}. " + self.ex["explanation"])
        return {"verdict": verdict, "loss": loss, "message": msg, **reply}

    def reveal(self):
        """Show the better move, explain it, and go on from the position after it."""
        if self.mode != "find":
            return {"error": "nothing to reveal now"}
        board = chess.Board(self.ex["fen"])
        board.push_uci(self.ex["best_uci"])
        self.board, self.mode = board, "play"
        reply = self._reply()
        self.log.append({"index": self.index, "ply": self.ex["ply"], "kind": self.ex["kind"], "phase": self.ex["phase"], "uci": None, "loss": None,
                         "verdict": "revealed", "hints_used": self.hints_used})
        return {"verdict": "revealed", "message": self.ex["explanation"], "best_uci": self.ex["best_uci"], **reply}

    # ---- playing on ------------------------------------------------------------------------------------------------------------------
    def _reply(self):
        """The opponent's move if the game is not over (it is the opponent's turn after the player's move); returns the extra fields for the answer."""
        out = {}
        if not self.board.is_game_over():
            reply = self.opponent.move(self.board)
            if reply:
                rm = chess.Move.from_uci(reply)
                out["reply_san"], out["reply_uci"] = self.board.san(rm), reply
                self.board.push(rm)
        out["fen"] = self.board.fen()
        out["game_over"] = self.board.is_game_over()
        out["result"] = self.board.result() if out["game_over"] else None
        return out

    def play(self, uci):
        """The player's move after the corrected position; the opponent answers. Returns the opponent's move and whether the game is over."""
        if self.mode != "play":
            return {"error": "play on only after the better move"}
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return {"error": "that is not a move"}
        if move not in self.board.legal_moves:
            return {"error": "that move is not legal here"}
        out = {"san": self.board.san(move)}
        self.board.push(move)
        out.update(self._reply())
        return out
