"""Sample weights for training, driven entirely by the profile's `filters` block.

game_weight(row)      -> 0.0 if the game is excluded, else the recency weight
move_weight(row, ply) -> game weight x time-class weight at that ply
"""
from datetime import datetime


def _ts(row):
    return datetime.fromisoformat(row["played_at"])


class Weighter:
    def __init__(self, cfg, rows):
        f = cfg.get("filters", {})
        self.min_rating = f.get("min_rating", {})
        rec = f.get("recency", {})
        self.half_life = rec.get("half_life_days")
        self.min_weight = rec.get("min_weight", 0.0)
        self.tcw = f.get("time_class_weights", {})
        dated = [r for r in rows if r.get("played_at")]
        self.ref = max(_ts(r) for r in dated) if dated else None

    def game_weight(self, row):
        if not row["usable"] or not row.get("played_at"):
            return 0.0
        floor = self.min_rating.get(row["platform"])
        if floor is not None and (row["my_rating"] or 0) < floor:
            return 0.0
        if self.tcw.get(row["time_class"], 1.0) == 0:
            return 0.0
        if not self.half_life:
            return 1.0
        age = (self.ref - _ts(row)).total_seconds() / 86400
        return max(self.min_weight, 0.5 ** (age / self.half_life))

    def time_class_weight(self, row, ply):
        spec = self.tcw.get(row["time_class"], 1.0)
        if isinstance(spec, dict):
            return 1.0 if ply < spec["full_until_ply"] else spec["late_weight"]
        return float(spec)

    def move_weight(self, row, ply):
        gw = self.game_weight(row)
        return gw * self.time_class_weight(row, ply) if gw else 0.0

    def my_plies(self, row):
        """Plies (0-based) at which I was to move."""
        return range(0 if row["color"] == "white" else 1, row["plies"], 2)
