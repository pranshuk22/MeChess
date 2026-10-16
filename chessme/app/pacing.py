"""How long a person would think about a position: the computer answers at once, the app makes it wait like a player would, so a game against it feels like a game.

The time depends on the position (a forced move, a recapture and the first moves of an opening are quick; many captures and checks to weigh, an endgame or being in check take longer), on the
opponent's strength (stronger players think more) and, in a timed game, on the clock (about a thirtieth of what is left plus most of the increment, never more than a fifth of it). It varies
from move to move (a log-normal spread) so that the rhythm is not mechanical. The server does not sleep: it says how long the reply took, charges that to the opponent's clock, and the page
shows the reply after that time."""
import math
import random

import chess

MIN_S, MAX_UNTIMED_S = 0.35, 14.0
SIGMA = 0.45


def median_seconds(board: chess.Board) -> float:
    """The typical thinking time for the side to move, in seconds, before the opponent's strength and the clock."""
    legal = list(board.legal_moves)
    n = len(legal)
    if n <= 1:
        return 0.35
    ply = (board.fullmove_number - 1) * 2 + (0 if board.turn == chess.WHITE else 1)          # (from the move number: a position set up from a FEN has no history)
    if ply < 10:
        return 0.7 + 0.12 * ply                                                  # the first moves of an opening are known
    caps = sum(1 for m in legal if board.is_capture(m))
    checks = sum(1 for m in legal if board.gives_check(m))
    tension = (caps + 0.7 * checks) / n
    t = 1.0 + 0.07 * n + 3.0 * tension + (1.2 if board.is_check() else 0.0)
    if board.move_stack and board.is_capture(board.peek()) and any(board.is_capture(m) and m.to_square == board.peek().to_square for m in legal):
        t *= 0.45                                                                # a recapture is quick
    if len(board.piece_map()) <= 8:
        t *= 1.15
    return t


def think_seconds(board: chess.Board, *, strength=1.0, remaining: float | None = None, inc: float = 0.0, rng: random.Random | None = None) -> float:
    """A thinking time in seconds for the side to move. `strength` scales the typical time (about 0.6 for a beginner, 1.5 for the strongest); `remaining` and `inc` are the clock (None: untimed)."""
    rng = rng or random
    t = median_seconds(board) * strength * math.exp(rng.gauss(0.0, SIGMA))
    if remaining is None:
        return max(MIN_S, min(MAX_UNTIMED_S, t))
    cap = 0.2 * remaining + 0.6 * inc
    target = remaining / 30 + 0.8 * inc
    return max(min(MIN_S, remaining * 0.5), min(t, target * 1.8, cap))


def strength_scale(kind: str, level: int) -> float:
    """How much longer or shorter than the typical time the opponent thinks: Stockfish levels 1..8 from 0.6 to 1.5, MeChess by rating (800 to 2600)."""
    if kind == "stockfish":
        return 0.6 + 0.9 * (max(1, min(8, level)) - 1) / 7
    return 0.6 + 0.9 * (max(800, min(2600, level)) - 800) / 1800
