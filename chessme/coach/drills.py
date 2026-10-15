"""Drills from your own mistakes, repeated on a schedule until you find the move without help (a Leitner box system).

A position enters the store the first time you try it in a review. Finding the better move at the first try without a hint moves it up a box (the next review
comes later); anything else (a wrong try, a hint, looking at the answer) puts it back in box 0, due again in ten minutes. Boxes 0 to 5 are due after 0, 1, 3, 7, 16 and 35
days. The store is one small JSON file on this machine (written atomically); `now` is a parameter everywhere so the schedule is testable."""
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

DAY = 86400.0
INTERVALS = [10 * 60.0, 1 * DAY, 3 * DAY, 7 * DAY, 16 * DAY, 35 * DAY]       # seconds until due after being in box 0..5 (box 0 = failed or new)
MAX_BOX = len(INTERVALS) - 1


def drill_id(fen, best_uci):
    return hashlib.sha1(f"{fen}|{best_uci}".encode()).hexdigest()[:12]


class DrillStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.items = {}
        if self.path and self.path.exists():
            self.items = json.loads(self.path.read_text(encoding="utf-8")).get("items", {})

    def _save(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"items": self.items}, f)
        os.replace(tmp, self.path)

    def record(self, exercise, success, now=None):
        """Note an attempt at `exercise` (an `exercises.exercise` dict): adds it if new, moves it up a box on success, back to box 0 otherwise."""
        now = time.time() if now is None else now
        key = exercise.get("id") or drill_id(exercise["fen"], exercise["best_uci"])
        item = self.items.get(key) or {"exercise": exercise, "box": 0, "history": []}
        item["box"] = min(item["box"] + 1, MAX_BOX) if success else 0
        item["due"] = now + INTERVALS[item["box"]]
        item["history"] = (item["history"] + [[now, bool(success)]])[-20:]
        self.items[key] = item
        self._save()
        return item

    def due(self, now=None, limit=10):
        """Exercises whose time has come, most overdue first."""
        now = time.time() if now is None else now
        rows = sorted((v for v in self.items.values() if v["due"] <= now), key=lambda v: v["due"])
        return [v["exercise"] for v in rows[:limit]]

    def stats(self, now=None):
        now = time.time() if now is None else now
        boxes = [0] * (MAX_BOX + 1)
        for v in self.items.values():
            boxes[v["box"]] += 1
        return {"total": len(self.items), "due": sum(v["due"] <= now for v in self.items.values()), "boxes": boxes}
