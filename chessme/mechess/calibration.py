"""Dial calibration: which dial setting really plays at which Elo.

`chessme calibrate` plays MeChess at several dial settings against Stockfish at known Elo and records the measured
strength of each. This module turns those points into a monotone curve (isotonic regression, weighted by precision, so
measurement noise cannot make a higher dial play "weaker") and inverts it: given a *target* Elo, `dial_for` returns the
dial setting that measured closest to it. The measured Elo is on the scale of the opponent used (Stockfish UCI_Elo at a
given time control); `offset` lets you shift it to another scale once you have validated against real opponents."""
import json
from dataclasses import dataclass, field
from pathlib import Path


def isotonic(ys, weights):
    """Weighted pool-adjacent-violators: the non-decreasing sequence closest to `ys` in weighted least squares."""
    blocks = []  # [value, weight, count]
    for y, w in zip(ys, weights):
        blocks.append([y, w, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            v2, w2, c2 = blocks.pop()
            v1, w1, c1 = blocks.pop()
            blocks.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, c1 + c2])
    out = []
    for v, _, c in blocks:
        out += [v] * c
    return out


def censored(point):
    """A point whose ladder stopped because the engine was beyond the opponent's range (e.g. weaker than Stockfish's lowest
    UCI_Elo). Its number is an extrapolation from a few games, not a measurement, so it is kept in the file but never used."""
    return str(point.get("stop", "")).startswith(("weaker than", "stronger than"))


@dataclass
class Calibration:
    points: list  # [{"dial": int, "measured": float, "se": float, ...}, ...]
    scale: str = "stockfish-UCI_Elo"
    offset: float = 0.0
    meta: dict = field(default_factory=dict)

    def curve(self):
        """[(dial, calibrated measured Elo)] sorted by dial, monotone non-decreasing."""
        pts = sorted((p for p in self.points if not censored(p)), key=lambda p: p["dial"])
        if not pts:
            raise ValueError("calibration has no usable points (all were beyond the opponent's measurable range)")
        fitted = isotonic([p["measured"] for p in pts], [1.0 / max(p.get("se", 100.0), 1.0) ** 2 for p in pts])
        return [(p["dial"], f + self.offset) for p, f in zip(pts, fitted)]

    def measured(self, dial):
        """Calibrated strength of a dial setting (linear between measured points; flat outside them)."""
        c = self.curve()
        if dial <= c[0][0]:
            return c[0][1]
        for (d0, m0), (d1, m1) in zip(c, c[1:]):
            if dial <= d1:
                return m0 + (m1 - m0) * (dial - d0) / (d1 - d0)
        return c[-1][1]

    def dial_for(self, target):
        """The dial setting whose measured strength is closest to `target` (clamped to the calibrated range)."""
        c = self.curve()
        if target < c[0][1]:
            return c[0][0]
        if target > c[-1][1]:
            return c[-1][0]
        flat = [d for d, m in c if abs(m - target) < 1e-9]
        if flat:  # the target sits exactly on measured points (possibly a flat stretch): the middle of them
            return sum(flat) / len(flat)
        for (d0, m0), (d1, m1) in zip(c, c[1:]):
            if m0 <= target <= m1:
                return d0 + (d1 - d0) * (target - m0) / (m1 - m0)
        return c[-1][0]

    def unmeasurable(self):
        """Dial settings that could not be measured because they fell outside the opponent's range."""
        return sorted(p["dial"] for p in self.points if censored(p))

    def in_range(self, target):
        c = self.curve()
        return c[0][1] <= target <= c[-1][1]

    def save(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"scale": self.scale, "offset": self.offset, "meta": self.meta,
                                          "points": self.points}, indent=1))

    @staticmethod
    def load(path):
        d = json.loads(Path(path).read_text())
        return Calibration(d["points"], d.get("scale", "stockfish-UCI_Elo"), d.get("offset", 0.0), d.get("meta", {}))
