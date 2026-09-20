"""Designing the weak end of the dial.

Below the search floor, fewer nodes or a wider window stop weakening the play measurably (the two lowest original settings played
equally). This builds a smooth one-dimensional *path* of settings from a very weak row up to a measured anchor row, using every
knob together: the node budget rises geometrically, while the blunder rate, candidate window, temperature and cp scale ease
towards the anchor's values. The result is a table file for `mechess --table` / `calibrate --table`, plus a calibration skeleton
that `calibrate-link` fills in by playing adjacent settings against each other."""
import math

from .dial import DEFAULT_TABLE, _row

# nodes, multipv, window cp, temperature, cp scale, book plies, blunder rate, depth
WEAK_ROW = (60, 8, 350, 2.0, 250.0, 4, 0.40)
DEFAULT_LABELS = (400, 600, 800, 1000, 1200, 1400, 1600)


def path_row(label, weak_label, anchor_label, weak_row, anchor_row):
    """The row at `label` on the path from `weak_row` (at weak_label) to `anchor_row` (at anchor_label)."""
    if not weak_label <= label <= anchor_label:
        raise ValueError(f"label {label} is outside the path [{weak_label}, {anchor_label}]")
    t = (label - weak_label) / (anchor_label - weak_label)
    w, a = _row(weak_row), _row(anchor_row)
    nodes = math.exp(math.log(w[0]) + t * (math.log(a[0]) - math.log(w[0])))
    lin = [x + t * (y - x) for x, y in zip(w[1:], a[1:])]
    return (int(round(nodes)), int(round(lin[0])), int(round(lin[1])), round(lin[2], 3), round(lin[3], 2), int(round(lin[4])),
            round(max(lin[5], 0.0), 3), int(round(lin[6])))


def weak_end_table(labels=DEFAULT_LABELS, *, anchor_table=None, anchor_label=1800, weak_row=WEAK_ROW, weak_label=None):
    """{label: row}: the new path rows below `anchor_label`, and the anchor table's own rows from `anchor_label` upwards
    (unchanged, so their measurements stay valid)."""
    anchor_table = anchor_table or DEFAULT_TABLE
    if anchor_label not in anchor_table:
        raise ValueError(f"the anchor table has no row for {anchor_label}")
    weak_label = min(labels) if weak_label is None else weak_label   # the path always starts at weak_label, even if fewer labels are used
    table = {lab: path_row(lab, weak_label, anchor_label, weak_row, anchor_table[anchor_label]) for lab in sorted(labels)}
    table.update({k: _row(v) for k, v in anchor_table.items() if k >= anchor_label})   # all rows have 8 columns
    return table


def skeleton(table, measured_points, *, anchor_label=1800):
    """A calibration dict for `calibrate-link`: settings below the anchor are placeholders marked as beyond range (to be linked),
    settings from the anchor upward are copied from `measured_points` (absolute measurements against Stockfish)."""
    points = []
    for label in sorted(table):
        if label < anchor_label:
            points.append({"dial": label, "measured": 500.0, "se": 400.0, "games": 0, "pinned": "", "faults": 0,
                           "stop": "weaker than the weakest opponent available"})
        else:
            src = next((p for p in measured_points if p["dial"] == label), None)
            if src is None:
                raise ValueError(f"no measurement for setting {label}: it cannot anchor the links")
            points.append(dict(src))
    return points
