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

# elo: (search nodes, MultiPV lines, candidate window in cp, sampling temperature, cp scale, book plies[, blunder rate[, depth]])
# The optional 7th value is the probability of playing a random legal move instead of the chosen one: a strength knob that keeps
# working below the search floor, where fewer nodes or a wider window no longer weaken the play measurably.
# The optional 8th value is a search depth limit (0 = none), sent as `go depth D nodes N`: it stops the search from spending its
# nodes on a few lines, so the weak levels see shallow tactics at every MultiPV line instead of stopping at depth 2.
DEFAULT_TABLE = {
    # Weak end: a smooth path (chessme.mechess.design.weak_end_table) from a very weak row towards the 1800 row; the node budget rises
    # geometrically while the blunder rate, window, temperature and cp scale ease towards it. Measured against Stockfish (linked
    # chain, 200 games per link): 1000 -> ~370, 1200 -> ~430, 1300 -> ~520, 1400 -> ~600, 1500 -> ~720, 1600 -> ~990, 1700 -> ~1090.
    1000: (363, 7, 251, 1.61, 177.1, 12, 0.23),
    1200: (661, 7, 219, 1.49, 152.9, 14, 0.17),
    1300: (893, 7, 202, 1.42, 140.7, 16, 0.14),
    1400: (1205, 7, 186, 1.36, 128.6, 17, 0.11),
    1500: (1626, 6, 169, 1.29, 116.4, 18, 0.09),
    1600: (2195, 6, 153, 1.23, 104.3, 19, 0.06),
    1700: (2963, 6, 136, 1.16, 92.1, 21, 0.03),
    # Upper part (unchanged): measured 1800 -> ~1240, 2100 -> ~1530, 2400 -> ~2050, 2600 -> ~2340 on the same scale.
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
    depth: int = 0  # search depth limit (0 = only the node budget)


def _row(r):
    """A table row as 8 numbers (blunder rate and depth default to 0)."""
    return tuple(r) + (0.0,) * (8 - len(r))


def widen(table, window_scale=1.0, extra_lines=0):
    """A copy of `table` whose candidate window is multiplied by `window_scale` and whose MultiPV is raised by `extra_lines`: more of the moves the
    player might really play become candidates (the weights still prefer the better ones; measure the strength again with `calibrate`)."""
    out = {}
    for elo, row in table.items():
        r = list(_row(row))
        r[1] = int(r[1]) + int(extra_lines)
        r[2] = r[2] * window_scale
        out[elo] = tuple(r)
    return out


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
    nodes, k, window, temp, scale, book, blunder, depth = row
    return DialSettings(int(elo), max(1, int(round(nodes))), max(1, int(round(k))), int(round(window)), float(temp),
                        float(scale), int(round(book)), min(max(float(blunder), 0.0), 1.0), max(0, int(round(depth))))
