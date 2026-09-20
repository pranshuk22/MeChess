"""Move classification from engine evaluations (plan 8n): Best / Excellent / Good / Inaccuracy / Mistake / Blunder, plus Book, Great,
Brilliant and Miss. Pure functions of numbers, so every rule can be tested without an engine.

Everything is measured in *expected points* for the player who moved (0 = lost, 0.5 = even, 1 = won): the loss of a move is the
expected points of the best move minus those of the move played. The thresholds follow the published Chess.com scale; the
special classes are our own reading of their published descriptions (their exact rules are not public) and are configurable."""
import math
from dataclasses import dataclass

MATE_CP = 10000
LICHESS_K = 0.00368208          # Lichess: win% = 50 + 50 * (2 / (1 + exp(-K * cp)) - 1)


@dataclass(frozen=True)
class Thresholds:
    best: float = 0.005            # loss at most this counts as the best move (engine ties and noise)
    excellent: float = 0.02
    good: float = 0.05
    inaccuracy: float = 0.10
    mistake: float = 0.20          # above this: blunder
    great_only: float = 0.15       # the runner-up is worse than the best by at least this: the best move is the only good one
    brilliant_after_min: float = 0.45    # a brilliant move must leave the player at least this well off
    brilliant_before_max: float = 0.85   # ... and must not be a move in an already won position
    brilliant_loss_max: float = 0.02     # ... and must be (almost) the best move
    sacrifice_pawns: float = 2.0         # material given up (in pawns) that makes a move a sacrifice
    miss_opp_loss: float = 0.10          # the opponent's previous move lost at least this expected points (so there was a gain to take)
    bad: float = 0.35              # "losing" / "winning" bounds for the evaluation-class change used by Great
    good_pos: float = 0.65


DEFAULT = Thresholds()


def win_prob(cp, k=LICHESS_K):
    """Expected points for the side the evaluation favours when positive, from a centipawn score (mate scores are clamped)."""
    cp = max(-MATE_CP, min(MATE_CP, cp))
    return 1.0 / (1.0 + math.exp(-k * cp))


def move_accuracy(win_before, win_after):
    """Lichess accuracy of one move (0-100) from the mover's win probability before and after (0-1)."""
    drop = max(0.0, (win_before - win_after) * 100.0)
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354415 * drop) - 3.1669 + 1.0))


@dataclass(frozen=True)
class MoveEval:
    """What the classifier needs about one move; all scores in centipawns from the mover's point of view."""
    best_cp: float                 # engine score of the best move (before the move)
    played_cp: float               # engine score after the move actually played
    second_cp: float | None = None  # score of the second-best move (None: only one legal move or not searched)
    book: bool = False             # the move is in the opening book
    material_given: float = 0.0    # net material lost by the sacrifice along the engine line (pawns); 0 when none
    opp_loss: float = 0.0          # expected points the opponent's previous move lost (0 when unknown)
    only_legal: bool = False       # a forced move (one legal move)


def tier(p, t=DEFAULT):
    """0 = losing, 1 = balanced, 2 = winning, from expected points."""
    return 0 if p < t.bad else 2 if p > t.good_pos else 1


def classify(m, t=DEFAULT):
    """The class of a move, as a lowercase string: book, brilliant, great, best, excellent, good, miss, inaccuracy, mistake, blunder.

    - book: the move is opening theory.
    - brilliant: (almost) the best move, a real material sacrifice, not leaving the player in a bad position, and not a move in an
      already won position.
    - great: the best move when it is critical: the second-best move is much worse (`great_only`) or falls to a lower tier
      (winning -> balanced, balanced -> losing). A forced move (one legal move) is never great.
    - best / excellent / good / inaccuracy / mistake / blunder: by the loss in expected points against the best move.
    - miss: an inaccuracy or mistake right after the opponent's error, when the player did not take the gain."""
    if m.book:
        return "book"
    best, played = win_prob(m.best_cp), win_prob(m.played_cp)
    loss = max(0.0, best - played)
    if loss <= t.brilliant_loss_max and m.material_given >= t.sacrifice_pawns and played >= t.brilliant_after_min \
            and best < t.brilliant_before_max:
        return "brilliant"
    if loss <= t.best:
        if m.second_cp is not None and not m.only_legal:
            second = win_prob(m.second_cp)
            if best - second >= t.great_only or tier(best, t) > tier(second, t):
                return "great"
        return "best"
    if loss <= t.excellent:
        return "excellent"
    if loss <= t.good:
        return "good"
    if loss <= t.mistake and m.opp_loss >= t.miss_opp_loss:
        return "miss"
    if loss <= t.inaccuracy:
        return "inaccuracy"
    if loss <= t.mistake:
        return "mistake"
    return "blunder"
