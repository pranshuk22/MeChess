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
import multiprocessing
import random
import re
import shutil
from collections import Counter
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
    late: bool = False        # strictly AFTER the first position at which EITHER player had under 30 s: the rule that defines the Allie / Maia-3 test
                              # set (reproduced exactly on the 18,239 Allie test games: 884,049 positions); the position of the first event is kept


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
    event_seen = False                                                      # has either player been under 30 s at an EARLIER position?
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
        late = event_seen
        if clock_before[mover] < LOW_CLOCK or clock_before[not mover] < LOW_CLOCK:
            event_seen = True
        rows.append(Position(gid, len(played), board.fen(), node.move.uci(), ratings[mover], ratings[not mover], base, inc,
                             clock_before[mover], clock_before[not mover], spent, low[mover], board.legal_moves.count(),
                             " ".join(played), h["Result"], late))
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


# ---- files, and balanced sets built from many windows -------------------------------------------------------------------

def _write_lines(path, positions):
    """Write positions as gzip JSON lines. Returns (count, sha256 of the content)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    h, n = hashlib.sha256(), 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for p in positions:
            line = json.dumps(asdict(p), separators=(",", ":"))
            f.write(line + "\n")
            h.update(line.encode())
            n += 1
    return n, h.hexdigest()


def write_testset(path, positions, meta=None):
    """Write positions as JSON lines (gzip) plus `<path>.manifest.json` with the count, the parameters and a SHA-256 of the content."""
    path = Path(path)
    n, sha = _write_lines(path, positions)
    manifest = {"file": path.name, "positions": n, "sha256": sha, **(meta or {})}
    Path(str(path) + ".manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def iter_testset(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield Position(**json.loads(line))


def read_testset(path, index=None):
    """All positions of a test set, or only those at the given row numbers (in the order of `index`, which must be sorted): a score file
    covers a subset, and loading 900k positions only to use 100k would cost gigabytes."""
    if index is None:
        return list(iter_testset(path))
    wanted = iter(int(i) for i in index)
    nxt = next(wanted, None)
    out = []
    for row, p in enumerate(iter_testset(path)):
        if nxt is None:
            break
        if row == nxt:
            out.append(p)
            nxt = next(wanted, None)
    return out


def rating_bin_of(p):
    """The 100-point bin of the GAME's average rating (Maia-3's balancing), as an int."""
    from .metrics import rating_bin
    return int(rating_bin((p.me + p.opp) / 2.0))


def keep_fraction_hash(gid, ply, seed):
    """A deterministic number in [0, 1) for a position: a position is kept when it is below its rating bin's keep fraction."""
    return int.from_bytes(hashlib.sha256(f"{seed}:keep:{gid}:{ply}".encode()).digest()[:8], "big") / 2.0 ** 64


def _window_task(task):
    source, parts, window, kw, shard = task
    positions = list(iter_window_positions(source, parts, [window], **kw))
    n, _ = _write_lines(shard, positions)
    return str(shard), dict(Counter(rating_bin_of(p) for p in positions)), n


def build_balanced(source, parts, windows, out, *, workers=1, cap_per_bin=None, shard_dir=None, keep_shards=False, seed=2026, log=print, **kw):
    """A test set from byte windows of a dump, built in parallel and balanced over rating.

    Each window is parsed by one worker into a shard file. Then, per 100-point bin of the game's average rating, positions are thinned to at
    most `cap_per_bin` by a deterministic hash of the position (no randomness, so the same inputs give the same set for any `workers`).
    Without a cap nothing is thinned. The manifest records the counts per bin before and after."""
    out = Path(out)
    shard_dir = Path(shard_dir) if shard_dir else out.parent / (out.name + ".shards")
    shard_dir.mkdir(parents=True, exist_ok=True)
    kw = dict(kw, seed=seed)
    tasks = [(source, parts, w, kw, shard_dir / f"w{w:04d}.jsonl.gz") for w in windows]
    if workers > 1:
        with multiprocessing.get_context("spawn").Pool(workers) as pool:
            results = list(pool.imap(_window_task, tasks))
    else:
        results = [_window_task(t) for t in tasks]
    before = Counter()
    for shard, counts, n in results:
        before.update(counts)
        log(f"  {Path(shard).name}: {n:,} positions")
    fraction = {b: (1.0 if not cap_per_bin else min(1.0, cap_per_bin / n)) for b, n in before.items()}
    after = Counter()

    def kept():
        for shard, _, _ in results:
            for p in iter_testset(shard):
                b = rating_bin_of(p)
                if keep_fraction_hash(p.gid, p.ply, seed) < fraction[b]:
                    after[b] += 1
                    yield p
    meta = {"source": Path(str(source)).name, "parts": parts, "windows": list(windows), "cap_per_bin": cap_per_bin, "seed": seed, **{k: v for k, v in kw.items() if k != "seed"}}
    manifest = write_testset(out, kept(), meta)
    manifest["rating_bins_before"] = {str(b): n for b, n in sorted(before.items())}
    manifest["rating_bins_after"] = {str(b): n for b, n in sorted(after.items())}
    Path(str(out) + ".manifest.json").write_text(json.dumps(manifest, indent=1))
    if not keep_shards:
        shutil.rmtree(shard_dir, ignore_errors=True)
    return manifest


def to_items(positions):
    """`compare.EvalItem`s for the scorers (the clock fields are carried along; the current Maia scorers ignore them)."""
    from ..model.compare import EvalItem
    return [EvalItem(p.fen, p.played, p.me, p.opp, 0, p.ply, tuple(p.moves.split()), clock=p.clock, opp_clock=p.opp_clock, base=p.base,
                     inc=p.inc, game=p.gid) for p in positions]


def parse_text(text, **kw):
    """Convenience for tests and small files: positions of the games in a PGN string."""
    return list(iter_positions(io.StringIO(text), **kw))
