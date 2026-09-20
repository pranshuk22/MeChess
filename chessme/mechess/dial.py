"""The rating dial: maps a target Elo to the knobs that make the engine play at that level.

The table below is a starting point. `chessme calibrate` measures what each setting really plays at (against Stockfish at
known Elo) and writes a calibration file (see calibration.py); with it, a *target* Elo is first mapped to the dial setting
that measured closest to it. Knobs interpolate linearly in Elo (node budget geometrically).
"""
import bisect
import json
import math
from dataclasses import dataclass
from pathlib import Path

# elo: (search nodes, MultiPV lines, candidate window in cp, sampling temperature, cp scale, book plies[, blunder rate])
# The optional 7th value is the probability of playing a random legal move instead of the chosen one: a strength knob that keeps
# working below the search floor, where fewer nodes or a wider window no longer weaken the play measurably.
DEFAULT_TABLE = {
    1200: (300, 8, 250, 1.6, 150, 8),
    1500: (1000, 8, 180, 1.3, 110, 14),
    1800: (4000, 6, 120, 1.1, 80, 22),
    2100: (15000, 5, 80, 1.0, 55, 30),
    2400: (60000, 4, 50, 0.9, 40, 30),
    2600: (150000, 3, 35, 0.8, 30, 30),
}


@dataclass(frozen=True)
class DialSettings:
    elo: int
    nodes: int  # search budget for the candidate search
    multipv: int  # how many candidate lines to ask the engine for
    window_cp: int  # keep candidates within this many centipawns of the best move
    temperature: float  # >1 flattens the prior, <1 sharpens it, 0 = always the most likely candidate
    cp_scale: float  # each cp of loss multiplies a candidate's weight by exp(-1/cp_scale): small = strict
    book_plies: int  # the opening book is used only within this many plies of the start
    blunder_rate: float = 0.0  # probability of replacing the chosen search move by a random legal move


def _row(r):
    """A table row as 7 numbers (the blunder rate defaults to 0)."""
    return tuple(r) + (0.0,) * (7 - len(r))


def load_table(path):
    """{elo: row} from a JSON file such as {"800": [100, 8, 300, 2.0, 200, 6, 0.3], ...}."""
    return {int(k): tuple(v) for k, v in json.loads(Path(path).read_text()).items()}


def save_table(table, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({str(k): list(v) for k, v in sorted(table.items())}, indent=1))


def settings_for(elo, table=None, calibration=None):
    """Knobs for a target Elo. With a `Calibration`, the target is first mapped to the dial setting that measured closest to it."""
    if calibration is not None:
        elo = calibration.dial_for(elo)
    table = table or DEFAULT_TABLE
    table = {k: _row(v) for k, v in table.items()}
    elos = sorted(table)
    e = min(max(elo, elos[0]), elos[-1])
    i = bisect.bisect_right(elos, e)
    if i == len(elos):
        row = table[elos[-1]]
    else:
        lo, hi = elos[i - 1], elos[i]
        t = (e - lo) / (hi - lo)
        a, b = table[lo], table[hi]
        row = (math.exp(math.log(a[0]) + t * (math.log(b[0]) - math.log(a[0]))),) + tuple(x + t * (y - x) for x, y in zip(a[1:], b[1:]))
    nodes, k, window, temp, scale, book, blunder = row
    return DialSettings(int(elo), max(1, int(round(nodes))), max(1, int(round(k))), int(round(window)), float(temp),
                        float(scale), int(round(book)), min(max(float(blunder), 0.0), 1.0))
