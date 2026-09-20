"""Training data for the "me" model: samples of (position, move played, ratings, result), stored as compact shards.

A sample is one move made by one player: the position before it (canonical mover view, see encoding.py), the
policy slot of the move actually played, both players' ratings, the rating scale, the game result from the mover's
point of view (0 loss / 1 draw / 2 win), the ply, and a sample weight.
"""
import hashlib
import io
import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import chess
import chess.pgn
import numpy as np

from ..ingest.normalize import time_class_from_tc
from . import encoding as enc

LEGAL_WIDTH = 256  # max legal moves in any position is 218
RESULT_CLASS = {"1-0": (2, 0), "0-1": (0, 2), "1/2-1/2": (1, 1)}  # (white's class, black's class)
ARRAYS = ("board", "castle", "ep", "move", "ratings", "platform", "result", "ply", "weight")


@dataclass
class GameRecord:
    moves: list  # chess.Move objects, from the standard start position
    white_elo: int
    black_elo: int
    result: str
    platform: int = 0
    clocks: list = field(default_factory=list)  # seconds left after each ply (None if unknown)
    sides: tuple = (chess.WHITE, chess.BLACK)  # whose moves become samples
    weights: Optional[list] = None  # per-ply sample weights (default 1.0)
    start_fen: Optional[str] = None  # None = the standard start position


class SampleBuffer:
    """Accumulates samples and converts them to numpy arrays."""

    def __init__(self, with_extras=False):
        self.rows = {k: [] for k in ARRAYS}
        self.with_extras = with_extras
        self.legal, self.fen = [], []

    def __len__(self):
        return len(self.rows["move"])

    def add(self, board, move, ratings, platform, result, ply, weight, with_extras=None):
        arr, castle, ep = enc.canonical_state(board)
        r = self.rows
        r["board"].append(arr); r["castle"].append(castle); r["ep"].append(ep)
        r["move"].append(enc.move_index(move, board)); r["ratings"].append(ratings)
        r["platform"].append(platform); r["result"].append(result); r["ply"].append(min(ply, 255))
        r["weight"].append(weight)
        if self.with_extras if with_extras is None else with_extras:
            row = np.full(LEGAL_WIDTH, -1, np.int16)
            idx = enc.legal_indices(board)
            row[:len(idx)] = idx
            self.legal.append(row)
            self.fen.append(board.fen())

    def extend(self, other):
        for k in ARRAYS:
            self.rows[k].extend(other.rows[k])
        self.legal.extend(other.legal)
        self.fen.extend(other.fen)

    def to_arrays(self):
        r = self.rows
        n = len(self)
        out = {
            "board": np.array(r["board"], np.uint8).reshape(n, 64), "castle": np.array(r["castle"], np.uint8),
            "ep": np.array(r["ep"], np.uint8), "move": np.array(r["move"], np.uint16),
            "ratings": np.array(r["ratings"], np.int16).reshape(n, 2), "platform": np.array(r["platform"], np.uint8),
            "result": np.array(r["result"], np.uint8), "ply": np.array(r["ply"], np.uint8),
            "weight": np.array(r["weight"], np.float32),
        }
        if self.legal:
            out["legal"] = np.array(self.legal, np.int16).reshape(n, LEGAL_WIDTH)
            out["fen"] = np.array(self.fen)
        return out


def extract_samples(game, *, min_ply=10, keep_prob=1.0, rng=None, min_clock=0, skip_forced=True, extras=False):
    """All (sampled) moves of `game` by the sides listed in game.sides, as a SampleBuffer."""
    rng = rng or random.Random(0)
    buf = SampleBuffer(with_extras=extras)
    board = chess.Board(game.start_fen) if game.start_fen else chess.Board()
    classes = RESULT_CLASS.get(game.result)
    if classes is None:
        return buf
    for ply, move in enumerate(game.moves):
        mover = board.turn
        if ply >= min_ply and mover in game.sides:
            weight = 1.0 if game.weights is None else game.weights[ply]
            clock = game.clocks[ply] if ply < len(game.clocks) else None
            ok = weight > 0 and (clock is None or clock >= min_clock) and rng.random() < keep_prob
            if ok and skip_forced and board.legal_moves.count() < 2:
                ok = False
            if ok:
                mine, theirs = (game.white_elo, game.black_elo) if mover == chess.WHITE else (game.black_elo, game.white_elo)
                buf.add(board, move, (mine, theirs), game.platform, classes[0 if mover == chess.WHITE else 1], ply, weight)
        board.push(move)
    return buf


def record_from_pgn_game(game, platform=0):
    """GameRecord from a python-chess Game (Lichess format with [%clk] comments), or None if unusable."""
    h = game.headers
    try:
        white_elo, black_elo = int(h["WhiteElo"]), int(h["BlackElo"])
    except (KeyError, ValueError):
        return None
    moves, clocks = [], []
    for node in game.mainline():
        moves.append(node.move)
        c = node.clock()
        clocks.append(c)
    if game.errors or not moves:
        return None
    return GameRecord(moves, white_elo, black_elo, h.get("Result", "*"), platform, clocks)


def record_from_row(row, weighter=None, only_mine=True):
    """GameRecord from a normalised game row (data/processed/games.jsonl), or None if it cannot be replayed."""
    board, moves = chess.Board(), []
    try:
        for san in row["moves"].split():
            m = board.parse_san(san)
            moves.append(m)
            board.push(m)
    except ValueError:
        return None
    if not moves or row.get("my_rating") is None or row.get("opp_rating") is None:
        return None
    mine_white = row["color"] == "white"
    white_elo, black_elo = (row["my_rating"], row["opp_rating"]) if mine_white else (row["opp_rating"], row["my_rating"])
    weights = None
    if weighter is not None:
        weights = [weighter.move_weight(row, i) for i in range(len(moves))]
    return GameRecord(moves, white_elo, black_elo, row["result"], enc.PLATFORM_ID[row["platform"]],
                      list(row.get("clocks") or []), sides=(chess.WHITE if mine_white else chess.BLACK,), weights=weights)


# ---- shards ---------------------------------------------------------------------------------------------------

def save_shard(path, buf):
    arrays = buf.to_arrays() if isinstance(buf, SampleBuffer) else buf
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, **arrays)


def load_shards(paths):
    """Concatenate shard files into one dict of arrays."""
    parts = [dict(np.load(p, allow_pickle=False)) for p in paths]
    keys = set(parts[0])
    for p in parts:
        if set(p) != keys:
            raise ValueError("shards have different fields")
    return {k: np.concatenate([p[k] for p in parts]) for k in keys}


# ---- Lichess database stream -------------------------------------------------------------------------------------

_TAG = re.compile(r'^\[(\w+) "(.*)"\]\s*$')
KEEP_CLASSES = ("blitz", "rapid", "classical")


def iter_game_texts(lines):
    """Split an iterable of PGN lines into one text per game."""
    cur = []
    for line in lines:
        if line.startswith("[Event ") and cur:
            yield "".join(cur)
            cur = []
        cur.append(line if line.endswith("\n") else line + "\n")
    if cur:
        yield "".join(cur)


def quick_headers(text):
    """Cheap header parse (no move parsing), so games can be filtered before the expensive work."""
    tags = {}
    for line in text.split("\n", 30):
        m = _TAG.match(line)
        if m:
            tags[m.group(1)] = m.group(2)
        elif line.strip() and not line.startswith("["):
            break
    return tags


def rating_bin(elo, lo, hi, width):
    if elo < lo or elo >= hi:
        return None
    return (elo - lo) // width


@dataclass
class LichessFilter:
    rating_min: int = 1100
    rating_max: int = 2300
    bin_width: int = 100
    max_rating_gap: int = 400
    time_classes: tuple = KEEP_CLASSES  # which time controls to keep (default: blitz / rapid / classical, no bullet)

    def game_bin(self, tags):
        """Rating bin of an acceptable game (by the lower-rated player, so both players are in range), else None."""
        if tags.get("Variant", "Standard") != "Standard" or "Rated" not in tags.get("Event", ""):
            return None
        if tags.get("Termination") in ("Abandoned", "Rules infraction") or tags.get("Result") not in RESULT_CLASS:
            return None
        if time_class_from_tc(tags.get("TimeControl", "-")) not in self.time_classes:
            return None
        try:
            w, b = int(tags["WhiteElo"]), int(tags["BlackElo"])
        except (KeyError, ValueError):
            return None
        if abs(w - b) > self.max_rating_gap or min(w, b) < self.rating_min or max(w, b) >= self.rating_max:
            return None
        return rating_bin((w + b) // 2, self.rating_min, self.rating_max, self.bin_width)


def split_of(key, val_pct=1, test_pct=1):
    """Deterministic train/val/test assignment by game (never by position)."""
    h = int(hashlib.md5(key.encode()).hexdigest()[:8], 16) % 100
    return "test" if h < test_pct else "val" if h < test_pct + val_pct else "train"


def process_game_text(args):
    """Worker: parse one game and return (split, bin, SampleBuffer). Top-level so it can be pickled."""
    text, bin_id, seed, keep_prob, min_ply, min_clock, val_pct, test_pct = args
    game = chess.pgn.read_game(io.StringIO(text))
    rec = record_from_pgn_game(game) if game else None
    if rec is None:
        return None
    site = game.headers.get("Site", str(seed))
    split = split_of(site, val_pct, test_pct)
    rng = random.Random(f"{seed}:{site}")
    buf = extract_samples(rec, min_ply=min_ply, keep_prob=keep_prob, rng=rng, min_clock=min_clock,
                          extras=split != "train")
    return split, bin_id, buf


class CountingReader(io.RawIOBase):
    """Binary stream wrapper that counts bytes read and stops (returns EOF) once `limit` bytes were consumed.

    The limit is checked before each read, so it can be exceeded by at most one read chunk.
    """

    def __init__(self, raw, limit=None):
        super().__init__()
        self.raw, self.count, self.limit = raw, 0, limit

    def readable(self):
        return True

    def readinto(self, buffer):
        if self.limit is not None and self.count >= self.limit:
            return 0
        chunk = self.raw.read(len(buffer))
        buffer[:len(chunk)] = chunk
        self.count += len(chunk)
        return len(chunk)


def open_source(source):
    """(binary stream, closer) for a URL, a .pgn.zst file or a plain .pgn file."""
    if str(source).startswith(("http://", "https://")):
        import requests

        r = requests.get(source, stream=True, timeout=60)
        r.raise_for_status()
        return r.raw, r.close
    f = open(source, "rb")
    return f, f.close


def text_lines(binary, zst):
    import zstandard

    stream = zstandard.ZstdDecompressor().stream_reader(binary) if zst else io.BufferedReader(binary)
    return io.TextIOWrapper(stream, encoding="utf-8", errors="replace")


def build_lichess(source, out_dir, *, samples_per_bin=20000, flt=LichessFilter(), keep_prob=0.2, min_ply=10,
                  min_clock=30, budget_bytes=None, max_games=None, workers=1, seed=1, val_pct=1, test_pct=1,
                  shard_size=500_000, progress=None):
    """Stream games, keep a rating-balanced sample and write train shards plus val/test (with legal moves and FENs).

    Games are accepted while their rating bin still needs samples; `budget_bytes` caps how much of the (compressed)
    stream is read. Returns a summary dict (also written to meta.json).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    binary, close = open_source(source)
    zst = str(source).endswith(".zst")
    reader = CountingReader(binary, budget_bytes)
    n_bins = (flt.rating_max - flt.rating_min) // flt.bin_width
    bin_samples = [0] * n_bins
    bufs = {"train": SampleBuffer(), "val": SampleBuffer(True), "test": SampleBuffer(True)}
    train_shards, seen, accepted = [], 0, 0

    def jobs():
        nonlocal seen
        game_no = 0
        for text in iter_game_texts(text_lines(reader, zst)):
            seen += 1
            if max_games and seen > max_games:
                return
            tags = quick_headers(text)
            b = flt.game_bin(tags)
            if b is None or bin_samples[b] >= samples_per_bin:
                if all(c >= samples_per_bin for c in bin_samples):
                    return
                continue
            game_no += 1
            yield (text, b, seed, keep_prob, min_ply, min_clock, val_pct, test_pct)

    def consume(res):
        nonlocal accepted
        if res is None:
            return
        split, b, buf = res
        if split == "train" and bin_samples[b] >= samples_per_bin:
            return  # quota reached while this game was in flight
        bufs[split].extend(buf)
        if split == "train":
            bin_samples[b] += len(buf)
        accepted += 1
        if progress and accepted % 2000 == 0:
            progress(seen, accepted, sum(bin_samples), reader.count)
        if len(bufs["train"]) >= shard_size:
            flush_train()

    def flush_train():
        if len(bufs["train"]):
            p = out / f"train_{len(train_shards):04d}.npz"
            save_shard(p, bufs["train"])
            train_shards.append(p.name)
            bufs["train"] = SampleBuffer()

    try:
        if workers <= 1:
            for job in jobs():
                consume(process_game_text(job))
        else:
            import multiprocessing

            with multiprocessing.get_context("spawn").Pool(workers) as pool:
                for res in pool.imap(process_game_text, jobs(), chunksize=32):
                    consume(res)
    finally:
        close()
    flush_train()
    for name in ("val", "test"):
        save_shard(out / f"{name}.npz", bufs[name])
    meta = {"source": str(source), "games_seen": seen, "games_used": accepted, "compressed_bytes_read": reader.count,
            "train_shards": train_shards, "train_samples": sum(bin_samples), "val_samples": len(bufs["val"]),
            "test_samples": len(bufs["test"]),
            "per_bin": {f"{flt.rating_min + i * flt.bin_width}": n for i, n in enumerate(bin_samples)},
            "filter": flt.__dict__, "keep_prob": keep_prob, "min_ply": min_ply, "min_clock": min_clock, "seed": seed}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


# ---- the player's own games ---------------------------------------------------------------------------------------

def build_user(rows, weighter, out_dir, *, test_fraction=0.1, val_fraction=0.05, min_ply=8, train_time_classes=None):
    """Shards from the player's own games: only *their* moves, weighted by the profile's recency / time-control
    weights. Split by time: oldest -> train, next -> val (early stopping), newest -> test (never trained on)."""
    from ..book.evaluate import split_by_time

    usable, test_rows = split_by_time(rows, test_fraction)
    cut = int(len(usable) * (1 - val_fraction))
    train_rows, val_rows = usable[:cut], usable[cut:]
    if train_time_classes:  # e.g. ("blitz", "rapid"): train only on those time controls; val / test are unchanged
        train_rows = [r for r in train_rows if r["time_class"] in train_time_classes]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, part, extras in (("train", train_rows, False), ("val", val_rows, True), ("test", test_rows, True)):
        buf, games = SampleBuffer(extras), 0
        for row in part:
            rec = record_from_row(row, weighter)
            if rec is None or weighter.game_weight(row) <= 0:
                continue
            games += 1
            buf.extend(extract_samples(rec, min_ply=min_ply, keep_prob=1.0, extras=extras, skip_forced=True))
        save_shard(out / f"{name}.npz", buf)
        counts[name] = {"games": games, "samples": len(buf)}
    meta = {"kind": "user", "splits": counts, "min_ply": min_ply,
            "newest_test_game": test_rows[-1]["played_at"] if test_rows else None}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def fix_shard_ep(path):
    """Rewrite a shard in place so its en-passant field follows the rule in encoding.py. Returns how many changed."""
    arrays = dict(np.load(path, allow_pickle=False))
    fixed = enc.normalise_ep(arrays["board"], arrays["ep"])
    changed = int((fixed != arrays["ep"]).sum())
    if changed:
        arrays["ep"] = fixed
        np.savez(path, **arrays)
    return changed


def subset(data, mask):
    """Rows of a shard dict selected by a boolean mask (all fields, including legal / fen when present)."""
    return {k: v[mask] for k, v in data.items()}


def remap_platform(data, shift=300, source=1, target=0):
    """Copy of `data` with platform `source` samples moved onto the `target` rating scale by adding `shift` Elo.

    For evaluating a model that has only seen one scale (e.g. Lichess) on games from another (chess.com).
    """
    out = {k: v.copy() for k, v in data.items()}
    sel = out["platform"] == source
    out["ratings"][sel] = out["ratings"][sel] + shift
    out["platform"][sel] = target
    return out


def merge_datasets(sources, out_dir):
    """Combine several dataset folders (each with train*.npz, val.npz, test.npz) into one.

    Train shards are symlinked (no copy, disk is precious); val / test shards are concatenated. Returns a summary.
    """
    import os

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n_train = 0
    for k, src in enumerate(sources):
        for shard in sorted(Path(src).glob("train*.npz")):
            link = out / f"train_{k:02d}_{shard.name[len('train_'):]}"
            if link.is_symlink() or link.exists():
                link.unlink()
            os.symlink(shard.resolve(), link)
            n_train += 1
    counts = {}
    for name in ("val", "test"):
        merged = load_shards([Path(src) / f"{name}.npz" for src in sources])
        save_shard(out / f"{name}.npz", merged)
        counts[name] = len(merged["move"])
    meta = {"kind": "merged", "sources": [str(s) for s in sources], "train_shards": n_train, **{f"{k}_samples": v for k, v in counts.items()}}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta
