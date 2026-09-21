"""Clock habits: how long the player thinks. The bot searches in a fraction of a second, so without this it answers every move at once, which no
human does; with it, the bot waits the way the player would have: a fraction of the time left that depends on the time control, how far the game
is, and whether the move is simple (a recapture, or at most two legal moves).

The model is an empirical one: for each (time class, stage of the game, simple or not) it keeps the fractions of the remaining time the player
actually used on their moves (fraction = seconds thought / seconds left before the move). At play time a fraction is drawn from the matching cell,
so the delays have the player's spread, not just an average. Sparse cells fall back to coarser ones. The delay never uses more than `cap` of what is
left (after a safety margin), so the bot cannot lose on time by imitating a slow player."""
import json
from pathlib import Path

import numpy as np

import chess

from ..style.gamefeatures import parse_time_control

MIN_CELL = 30
MAX_SAMPLES = 500
STAGES = ((10, 0), (20, 1), (40, 2))               # my move index (half-moves played so far) below the bound -> stage


def time_class(base, inc):
    """Lichess time classes from the estimated duration base + 40 * increment (seconds)."""
    t = base + 40 * inc
    return "ultrabullet" if t <= 29 else "bullet" if t < 180 else "blitz" if t < 480 else "rapid" if t < 1500 else "classical"


def stage(ply):
    return next((s for bound, s in STAGES if ply < bound), 3)


def _recapture(board):
    """True when the opponent's last move captured and a legal capture on that square exists."""
    if not board.move_stack:
        return False
    last = board.peek()
    board.pop()
    captured = board.is_capture(last)
    board.push(last)
    return captured and any(m.to_square == last.to_square and board.is_capture(m) for m in board.legal_moves)


def simple(board):
    return board.legal_moves.count() <= 2 or _recapture(board)


class ClockModel:
    def __init__(self, cells, meta=None):
        self.cells, self.meta = cells, meta or {}

    def _cell(self, tc, st, sim):
        for key in (f"{tc}|{st}|{int(sim)}", f"{tc}|{st}|*", f"{tc}|*|*", "*|*|*"):
            c = self.cells.get(key)
            if c and len(c) >= MIN_CELL:
                return c
        return next(iter(self.cells.values()), [0.0])

    def fraction(self, tc, ply, sim, rng):
        c = self._cell(tc, stage(ply), sim)
        return float(c[int(rng.integers(len(c)))])

    def delay(self, board, remaining, base, inc, rng, *, strength=1.0, cap=0.25, margin=1.0):
        """Seconds to wait before playing, for a bot with `remaining` seconds left in a game of `base`+`inc`."""
        tc = time_class(base, inc)
        f = self.fraction(tc, len(board.move_stack), simple(board), rng)
        return max(0.0, min(f * remaining * strength, cap * max(remaining - margin, 0.0)))

    def save(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"cells": self.cells, "meta": self.meta}, separators=(",", ":")))

    @classmethod
    def load(cls, path):
        d = json.loads(Path(path).read_text())
        return cls(d["cells"], d.get("meta"))


def think_times(row):
    """[(ply, seconds left before the move, seconds thought, base, inc)] for the player's moves of a normalised game with clocks, else []."""
    base, inc = parse_time_control(row.get("time_control"))
    clocks = row.get("clocks")
    if base is None or not clocks or not isinstance(clocks, list):
        return []
    white = row["color"] == "white"
    out = []
    for i in range(len(clocks)):
        if (i % 2 == 0) != white or clocks[i] is None:
            continue
        prev = clocks[i - 2] if i >= 2 else base
        if prev is None or prev <= 0:
            continue
        out.append((i, float(prev), max(0.0, prev + inc - clocks[i]), base, inc))
    return out


def fit(rows, *, max_samples=MAX_SAMPLES, seed=0):
    """A `ClockModel` from normalised Lichess games (with clocks). Fractions of the time left, per (time class, stage, simple)."""
    rng = np.random.default_rng(seed)
    cells, n_moves = {}, 0
    for row in rows:
        if row.get("platform") != "lichess" or not row.get("usable") or not row.get("moves"):
            continue
        tt = think_times(row)
        if not tt:
            continue
        sans = row["moves"].split()
        board = chess.Board()
        by_ply = {}
        try:
            for i, san in enumerate(sans):
                by_ply[i] = simple(board)
                board.push_san(san)
        except ValueError:
            pass
        for ply, prev, think, base, inc in tt:
            if ply not in by_ply:
                continue
            tc = time_class(base, inc)
            f = min(think / prev, 1.0)
            for key in (f"{tc}|{stage(ply)}|{int(by_ply[ply])}", f"{tc}|{stage(ply)}|*", f"{tc}|*|*", "*|*|*"):
                cells.setdefault(key, []).append(round(f, 4))
            n_moves += 1
    for k, v in cells.items():
        if len(v) > max_samples:
            cells[k] = [v[i] for i in sorted(rng.choice(len(v), max_samples, replace=False))]
    return ClockModel(cells, {"moves": n_moves, "cells": len(cells)})
