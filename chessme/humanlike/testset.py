"""Build a fixed test set of positions from Lichess games, with everything a human-likeness study needs per position:
the move played, both ratings, the clocks (mover and opponent), the time spent, the move history, and whether the mover has
already been under 30 s (the filter the published Maia/Allie numbers use).

Selection depends only on the game (a seeded hash of its id), never on the position's features, so the same games give the same
set and every filter (opening, low clock, forced moves) can be applied AFTERWARDS: one set serves the comparable and the full-coverage
evaluations. A manifest with a content hash pins the set, so a result can say exactly which positions it was computed on."""
import gzip
import hashlib
import io
import json
import random
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import chess
import chess.pgn

from ..ingest.normalize import time_class_of

LOW_CLOCK = 30.0
_NO_TITLE_BOT = "BOT"
_BAD_TERMINATION = ("Abandoned", "Rules infraction")
_RESULTS = ("1-0", "0-1", "1/2-1/2")


@dataclass
class Position:
    gid: str
    ply: int                  # half-moves played before this position
    fen: str
    played: str               # UCI
    me: int                   # mover's rating
    opp: int
    base: int                 # seconds
    inc: int
    clock: float              # mover's seconds left before the move (the base time on its first move)
    opp_clock: float
    spent: float              # seconds the mover used on this move (clock + increment - clock after)
    after_low: bool           # the mover had under 30 s before this move or an earlier one
    n_legal: int
    moves: str                # UCI moves from the standard start position to this position
    result: str


def parse_tc(tc):
    """(base, increment) seconds from a Lichess TimeControl tag such as '180+2'; None for '-' (correspondence) or junk."""
    m = re.fullmatch(r"(\d+)\+(\d+)", tc or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def game_ok(headers, time_class="blitz", allow_bots=False):
    """Does a game qualify? Standard rated game of the given Lichess speed class, finished normally, with both ratings and (unless
    `allow_bots`) no BOT account. Returns (base, inc) or None."""
    if headers.get("Variant", "Standard") != "Standard" or "Rated" not in headers.get("Event", ""):
        return None
    if headers.get("Termination") in _BAD_TERMINATION or headers.get("Result") not in _RESULTS:
        return None
    if not allow_bots and _NO_TITLE_BOT in (headers.get("WhiteTitle"), headers.get("BlackTitle")):
        return None
    tc = parse_tc(headers.get("TimeControl"))
    if tc is None or (time_class and time_class_of(*tc) != time_class):
        return None
    try:
        int(headers["WhiteElo"]), int(headers["BlackElo"])
    except (KeyError, ValueError):
        return None
    return tc


def game_positions(game, *, per_game=4, seed=0, time_class="blitz", allow_bots=False, require_clocks=True):
    """The sampled positions of one python-chess game (a list of Position; empty when the game does not qualify)."""
    h = game.headers
    tc = game_ok(h, time_class, allow_bots)
    if tc is None or game.errors:
        return []
    base, inc = tc
    gid = h.get("Site", "").rsplit("/", 1)[-1] or h.get("GameId", "")
    rows, board, played = [], game.board(), []
    clock_before = {chess.WHITE: float(base), chess.BLACK: float(base)}   # seconds left before the next move of each colour
    low = {chess.WHITE: False, chess.BLACK: False}
    ratings = {chess.WHITE: int(h["WhiteElo"]), chess.BLACK: int(h["BlackElo"])}
    for node in game.mainline():
        mover = board.turn
        after = node.clock()
        if after is None:
            if require_clocks:
                return []
            after = float("nan")
        if clock_before[mover] < LOW_CLOCK:
            low[mover] = True
        spent = clock_before[mover] + inc - after
        rows.append(Position(gid, len(played), board.fen(), node.move.uci(), ratings[mover], ratings[not mover], base, inc,
                             clock_before[mover], clock_before[not mover], spent, low[mover], board.legal_moves.count(),
                             " ".join(played), h["Result"]))
        clock_before[mover] = after
        played.append(node.move.uci())
        board.push(node.move)
    if not rows:
        return []
    rng = random.Random(int.from_bytes(hashlib.sha256(f"{seed}:{gid}".encode()).digest()[:8], "big"))
    return [rows[i] for i in sorted(rng.sample(range(len(rows)), min(per_game, len(rows))))]


def iter_positions(stream, *, skip_edges=False, **kw):
    """Sampled positions of every qualifying game of a PGN text stream. `skip_edges` drops the first and the last game: a window of a
    compressed dump starts and ends in the middle of a game."""
    previous = None
    for i, game in enumerate(iter(lambda: chess.pgn.read_game(stream), None)):
        if previous is not None:
            yield from game_positions(previous, **kw)
        previous = None if (skip_edges and i == 0) else game
    if previous is not None and not skip_edges:
        yield from game_positions(previous, **kw)


def iter_window_positions(source, parts, windows, **kw):
    """Positions from byte windows of a Lichess `.pgn.zst` dump (URL or file) cut into `parts` windows (see book/rangescan.py): reading a
    few windows spread over a month samples the whole month without streaming from byte 0."""
    from ..book import rangescan as RS
    fetcher = RS.make_fetcher(source)
    total = fetcher.total_size()
    spans = RS.partition_bytes(total, parts)
    for w in windows:
        start, end = spans[w]
        _, _, data = RS.read_window(fetcher.fetch, total, start, end)
        if data:
            yield from iter_positions(RS.decode_window_text(data), skip_edges=True, **kw)


# ---- files -----------------------------------------------------------------------------------------------------------------

def write_testset(path, positions, meta=None):
    """Write positions as JSON lines (gzip) plus `<path>.manifest.json` with the count, the parameters and a SHA-256 of the content."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    h, n = hashlib.sha256(), 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for p in positions:
            line = json.dumps(asdict(p), separators=(",", ":"))
            f.write(line + "\n")
            h.update(line.encode())
            n += 1
    manifest = {"file": path.name, "positions": n, "sha256": h.hexdigest(), **(meta or {})}
    Path(str(path) + ".manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def read_testset(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [Position(**json.loads(line)) for line in f]


def to_items(positions):
    """`compare.EvalItem`s for the scorers (the clock fields are carried along; the current Maia scorers ignore them)."""
    from ..model.compare import EvalItem
    return [EvalItem(p.fen, p.played, p.me, p.opp, 0, p.ply, tuple(p.moves.split()), clock=p.clock, opp_clock=p.opp_clock, base=p.base,
                     inc=p.inc, game=p.gid) for p in positions]


def parse_text(text, **kw):
    """Convenience for tests and small files: positions of the games in a PGN string."""
    return list(iter_positions(io.StringIO(text), **kw))
