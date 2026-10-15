"""How do players of your rating usually do? Reference rates for the weakness profile.

A weakness is only a weakness against something: giving away points in 12% of your endgame moves is normal at one rating and a problem at another. The
reference is built from public Lichess games of players in a rating band, analysed by the SAME analysis (same engine, same node budget, same loss) as
your own reviews, and reduced to counts per band and speed: moves, mistakes (loss at least 0.10), blunders (at least 0.20), by phase, by situation and the
kinds of mistake. Only these counts are kept (no games, no names).

`select_games` picks the games (a quota per speed and band, both players within `max_gap` of each other), `tally` turns analysed games into counts,
`compare` sets a player's rows (`profile.player_rows`) against the counts of the player's band. A difference is reported only when it is clear after allowing
for the many categories compared (`Z_CUT`), and the reference states the node budget it was made with: rates from another budget are not comparable."""
import json
import math
from pathlib import Path

from ..humanlike import testset as T
from . import profile as PR

BAND = 200
LOWEST, HIGHEST = 1000, 2400                    # first band 1000-1199 (lower ratings fall into it), last band 2400 and above
SPEEDS = ("blitz", "rapid")
Z_CUT = 2.5                                     # two-sided, about 1% per comparison: ten or so categories are looked at
MIN_N = PR.MIN_N
DEFAULT = Path(__file__).with_name("reference_rates.json")


def band_of(rating):
    """Lower edge of the band that holds `rating` (clamped to the bands that exist)."""
    return int(min(max(int(rating) // BAND * BAND, LOWEST), HIGHEST))


def speed_of(headers):
    """'blitz' / 'rapid' / ... from a PGN TimeControl tag, or None when it cannot be told."""
    tc = T.parse_tc(headers.get("TimeControl"))
    return T.time_class_of(*tc) if tc else None


class Picker:
    """Quotas of `per_band` games per (speed, band): standard rated, finished normally, no bots, both ratings within `max_gap`, at least `min_plies`
    half-moves. The band is that of the two players' mean rating. `wants` decides from the headers alone (so a dump can be scanned without parsing the
    moves of the games that are not needed), `take` decides on the whole game and counts it."""

    def __init__(self, per_band, speeds=SPEEDS, min_plies=20, max_gap=200):
        self.left = {(s, b): per_band for s in speeds for b in range(LOWEST, HIGHEST + 1, BAND)}
        self.speeds, self.min_plies, self.max_gap = speeds, min_plies, max_gap

    def key(self, h):
        if T.game_ok(h, time_class=None) is None:
            return None
        speed = speed_of(h)
        w, b = int(h["WhiteElo"]), int(h["BlackElo"])
        if speed not in self.speeds or abs(w - b) > self.max_gap:
            return None
        key = (speed, band_of((w + b) / 2))
        return key if key in self.left else None

    def wants(self, headers):
        return self.key(headers) is not None

    def take(self, game):
        key = self.key(game.headers)
        if key is None or game.end().ply() < self.min_plies:
            return False
        self.left[key] -= 1
        if self.left[key] == 0:
            del self.left[key]
        return True

    @property
    def done(self):
        return not self.left


def select_games(games, per_band, **kw):
    """Yield the games a `Picker` takes, and stop as soon as every quota is full."""
    picker = Picker(per_band, **kw)
    for g in games:
        if picker.take(g):
            yield g
            if picker.done:
                return


def reader(stream, wants):
    """Games of a PGN text stream; with `wants`, the moves of a game are skipped (not parsed) unless `wants(headers)`: such games come back without moves."""
    import chess.pgn
    if wants is None:
        return iter(lambda: chess.pgn.read_game(stream), None)

    class Visitor(chess.pgn.GameBuilder):
        def end_headers(self):
            if not wants(self.game.headers):
                return chess.pgn.SKIP
    return iter(lambda: chess.pgn.read_game(stream, Visitor=Visitor), None)


def iter_window_games(source, parts, windows, wants=None):
    """Games from byte windows of a Lichess `.pgn.zst` dump (URL or file), the first and the last game of a window dropped (cut in the middle). With `wants`
    (header test) only the wanted games are parsed; the others are not yielded."""
    from ..book import rangescan as RS
    fetcher = RS.make_fetcher(source)
    total = fetcher.total_size()
    spans = RS.partition_bytes(total, parts)
    for w in windows:
        start, end = spans[w]
        _, _, data = RS.read_window(fetcher.fetch, total, start, end)
        if not data:
            continue
        previous = None
        for i, g in enumerate(reader(RS.decode_window_text(data), wants)):
            if previous is not None and previous.next() is not None:
                yield previous                                           # one game behind, so that the last (cut) game is never yielded
            previous = None if i == 0 else g                             # the first game of a window starts in the middle


# ---- counts ---------------------------------------------------------------------------------------------------------------------------------

def _empty():
    return {"games": 0, "moves": 0, "mistakes": 0, "blunders": 0, "by_phase": {}, "by_situation": {}, "kinds": {}}


def add_rows(cell, rows):
    """Add the rows of one player in one game (`profile.player_rows`) to a counts cell."""
    cell["games"] += 1
    for r in rows:
        mistake = r["loss"] >= PR.MISTAKE
        cell["moves"] += 1
        cell["mistakes"] += mistake
        cell["blunders"] += r["loss"] >= PR.BLUNDER
        for key, name in (("phase", "by_phase"), ("situation", "by_situation")):
            c = cell[name].setdefault(r[key], [0, 0])
            c[0] += 1
            c[1] += mistake
        if mistake:
            cell["kinds"][r["kind"]] = cell["kinds"].get(r["kind"], 0) + 1


def tally(items, *, nodes, multipv, source=""):
    """Reference counts from `items` = iterable of (speed, rating of each side {color: rating}, analysis). Both players of a game count, each in the band of
    their own rating, so a band holds the moves of players rated in it."""
    cells = {}
    for speed, ratings, analysis in items:
        for color, rating in ratings.items():
            cell = cells.setdefault(f"{speed}|{band_of(rating)}", _empty())
            add_rows(cell, PR.player_rows(analysis, color))
    return {"version": 1, "nodes": nodes, "multipv": multipv, "source": source, "mistake": PR.MISTAKE, "blunder": PR.BLUNDER, "cells": cells}


def save(ref, path):
    Path(path).write_text(json.dumps(ref, indent=1, sort_keys=True), encoding="utf-8")


def load(path=None):
    """The reference counts, or None when there is no file."""
    p = Path(path) if path else DEFAULT
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ---- the comparison -------------------------------------------------------------------------------------------------------------------------

def _z(k, n, k_ref, n_ref):
    """Two-sample z of the rate k/n against the reference k_ref/n_ref (pooled variance); 0 when it cannot be told."""
    if n == 0 or n_ref == 0:
        return 0.0
    p = (k + k_ref) / (n + n_ref)
    if p <= 0 or p >= 1:
        return 0.0
    return (k / n - k_ref / n_ref) / math.sqrt(p * (1 - p) * (1 / n + 1 / n_ref))


def compare(rows, rating, speed, ref, nodes=None, multipv=None):
    """The player's rows against the reference cell of the player's band and speed. Returns None when there is no such cell; otherwise
    {'band', 'speed', 'ref_moves', 'comparable', 'overall': {...}, 'areas': {...}, 'findings': [...]} where each area has you / reference rates and z."""
    cell = (ref or {}).get("cells", {}).get(f"{speed}|{band_of(rating)}")
    if not cell or not cell["moves"] or not rows:
        return None
    n, k = len(rows), sum(r["loss"] >= PR.MISTAKE for r in rows)
    out = {"band": band_of(rating), "speed": speed, "ref_moves": cell["moves"], "ref_nodes": ref.get("nodes"),
           "comparable": all(mine is None or theirs is None or mine == theirs for mine, theirs in ((nodes, ref.get("nodes")), (multipv, ref.get("multipv")))),
           "overall": {"moves": n, "you": k / n, "ref": cell["mistakes"] / cell["moves"], "z": _z(k, n, cell["mistakes"], cell["moves"])},
           "areas": {}, "findings": []}
    for key, name in (("phase", "by_phase"), ("situation", "by_situation")):
        for value in sorted({r[key] for r in rows}):
            sub = [r for r in rows if r[key] == value]
            ref_n, ref_k = cell[name].get(value, [0, 0])
            ks = sum(r["loss"] >= PR.MISTAKE for r in sub)
            z = _z(ks, len(sub), ref_k, ref_n)
            out["areas"][f"{key}: {value}"] = {"moves": len(sub), "you": ks / len(sub), "ref": ref_k / ref_n if ref_n else None, "z": z}
            if len(sub) >= MIN_N and ref_n >= MIN_N and abs(z) >= Z_CUT:
                out["findings"].append({"area": f"{key}: {value}", "moves": len(sub), "you": ks / len(sub), "ref": ref_k / ref_n, "z": z})
    out["findings"].sort(key=lambda f: -abs(f["z"]))
    return out


def sentences(cmp):
    """Plain sentences for a comparison (empty when nothing is clear)."""
    if not cmp:
        return []
    who = f"players rated {cmp['band']} to {cmp['band'] + BAND - 1}" if cmp["band"] < HIGHEST else f"players rated {HIGHEST} and above"
    o = cmp["overall"]
    out = []
    if o["moves"] >= MIN_N and abs(o["z"]) >= Z_CUT:
        out.append(f"Overall you give away points on {100 * o['you']:.0f}% of your moves, {'more' if o['z'] > 0 else 'less'} than {who} in {cmp['speed']} ({100 * o['ref']:.0f}%).")
    for f in cmp["findings"]:
        area = f["area"].split(": ")[1]
        out.append(f"In the {area} situations you give away points on {100 * f['you']:.0f}% of your moves, "
                   f"{'more' if f['z'] > 0 else 'less'} than {who} ({100 * f['ref']:.0f}%).")
    if not cmp["comparable"]:
        out.append(f"(The reference was made with {cmp['ref_nodes']:,} nodes per position; your reviews used another budget or number of lines, so treat the comparison as rough.)")
    return out
