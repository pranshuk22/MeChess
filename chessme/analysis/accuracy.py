"""Game accuracy the way Lichess computes it: the per-move accuracies of a player are combined as the mean of (a) a mean weighted by how volatile the position was
around each move (a move in a quiet position counts little, one in a sharp position counts much) and (b) the harmonic mean (one bad move pulls the figure down, ten
easy ones do not lift it back). A plain average of the per-move numbers was too generous: forced and book moves score 100 and hid the mistakes.

Input: per move, the evaluation after it from White's point of view (centipawns) and the move's own accuracy; the moves alternate White, Black, ..."""
import math

from . import classify as C

START_CP = 15                       # Lichess starts the chain from the usual opening evaluation


def _win(cp):
    return 100.0 * C.win_prob(cp, cap=C.LICHESS_CP_CAP)


def weights(cps_white):
    """Volatility weight of each move: the standard deviation of the win percentages (White's view) in a sliding window around it, clamped to 0.5 .. 12."""
    wins = [_win(START_CP)] + [_win(c) for c in cps_white]
    n = len(cps_white)
    size = max(2, min(8, n // 10))
    windows = [wins[:size]] * min(size - 2, len(wins)) + [wins[i:i + size] for i in range(max(0, len(wins) - size + 1))]
    out = []
    for w in windows[:n]:
        mean = sum(w) / len(w)
        sd = math.sqrt(sum((x - mean) ** 2 for x in w) / len(w))
        out.append(max(0.5, min(12.0, sd)))
    return out + [0.5] * (n - len(out))


def combine(accs, wts):
    """(weighted mean + harmonic mean) / 2 of move accuracies; None when there are no moves."""
    if not accs:
        return None
    weighted = sum(a * w for a, w in zip(accs, wts)) / sum(wts)
    harmonic = len(accs) / sum(1.0 / max(a, 1e-6) for a in accs)
    return max(0.0, min(100.0, (weighted + harmonic) / 2))


def game_accuracy(cps_white, accs, phases=None, colours=None):
    """{'white': x, 'black': y, 'by_phase': {'white': {phase: x}, 'black': {...}}} for a game given per move (White's cp after the move, the move's accuracy, optionally its phase)."""
    wts = weights(cps_white)
    colours = colours or ["white" if i % 2 == 0 else "black" for i in range(len(accs))]
    out = {"white": None, "black": None, "by_phase": {"white": {}, "black": {}}}
    for colour in ("white", "black"):
        idx = [i for i in range(len(accs)) if colours[i] == colour]
        out[colour] = combine([accs[i] for i in idx], [wts[i] for i in idx])
        if phases:
            for ph in ("opening", "middlegame", "endgame"):
                sub = [i for i in idx if phases[i] == ph]
                out["by_phase"][colour][ph] = combine([accs[i] for i in sub], [wts[i] for i in sub])
    return out


def from_api_moves(moves):
    """`game_accuracy` for the moves in the API's shape (stored analysis rows: `cp` after the move from White's view, `acc`, `phase`)."""
    return game_accuracy([m["cp"] for m in moves], [m["acc"] if m.get("acc") is not None else 100.0 for m in moves], [m.get("phase") for m in moves])
