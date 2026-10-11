"""Partitioned range-scan of a Lichess `.pgn.zst` dump: cuts the file into byte windows, downloaded and decoded independently, instead
of one long-lived stream from byte 0.

Why: `explorer.count_stream` reads the whole dump as a single connection; on a drop it reconnects and re-opens from byte 0, fast-forwarding
past every game already counted (`explorer.py`'s `open_dump`/`CheckedReader`). In practice a real run hits a ~17-minute connection limit,
so as the scan progresses each reconnect wastes more and more time just re-skipping games, and the second real run stalled at 36% of the
month for exactly this reason (see plan.md 8r).

This only works because two things are true of the file, checked live against `lichess_db_standard_rated_2026-06.pgn.zst` (28.2 GB) on
2026-09-23, not assumed from the format spec:
  1. The server answers HTTP range requests (`Accept-Ranges: bytes`, a `Range` request gets `206 Partial Content`).
  2. The `.zst` is a back-to-back sequence of independently-decodable zstd frames (no shared dictionary/window across frames), each
     preceded by an 8-byte skippable frame (magic `0x184D2A5x`, then a 4-byte little-endian size for its own tiny payload - NOT the size
     of the data frame that follows, so it cannot be used to skip ahead without decoding). Frames were about 4.68-4.70 MB apart in a
     32 MB probe of the real file, with no false-positive frame-magic match found in that range.

Because there is no explicit index of frame lengths, a byte window's start and end are found by *snapping forward* to the next real frame
start: the window's bytes plus a few MB of tail are fetched in ONE request and the frame signatures (skippable frame + zstd magic) are
located in that buffer (`read_window`). A window then holds exactly the whole frames from its snapped start up to (but not including) the
next window's snapped start - both windows snap the same nominal byte, so they share the edge exactly - and is decoded with an ordinary
zstd multi-frame reader, the same one `explorer.open_dump` uses for the single-stream case.

Exactness (plan.md 8u):
  - A window is never pruned. If its tables pass `max_entries` the scan stops with `EntryLimitExceeded` ("use more --parts"); windows are
    small (about 700 of them) so that does not happen on the real dump.
  - Each window is saved as `S` slice files, split by the hash of the position key, plus a `meta` file written last (the "done" marker).
    The merge adds up ONE slice at a time across all windows, so its peak memory is one slice, and entries with fewer games than the
    explorer database / books will ever keep are dropped only after their position's exact total has been recorded (`position_totals`),
    so "other moves" and move shares stay exact. What is dropped is recorded in `pruned_below`.
  - A manifest in the windows folder records what the windows were made with (source, size, windows, bands, depth ...): a rerun with other
    settings refuses to mix them.

Accepted loss: a game whose PGN text straddles a window boundary is cut: the first half is counted with the moves it has (the text
ends there), the second half has no tags and is ignored - at most one game per window (about 700 in 88 million). Also accepted: unlike
the single-stream scan, a window does not stop early when a band fills up (each worker only sees its own slice, not the running total
across the whole scan), so this counts every qualifying game in every window rather than mostly the first part of the file - which is the
whole point (ranges spread over the whole month remove the bias of scanning only its first third)."""
import gzip
import http.client
import json
import math
import os
import pickle
import re
import struct
import time
import urllib.request
from pathlib import Path

import zstandard

from . import explorer as EX

ZSTD_MAGIC = bytes([0x28, 0xB5, 0x2F, 0xFD])
SKIP_MAGIC = re.compile(rb"[\x50-\x5f]\x2a\x4d\x18")  # skippable-frame magic 0x184D2A5x, little-endian: first byte 0x50-0x5F, then 2A 4D 18
SEARCH_WINDOW = 8 * 1024 * 1024                       # generous vs. the ~4.7 MB observed frame spacing
TAIL_START = 5 * 1024 * 1024                          # fetched past a window's end in the same request: normally enough to contain the next frame start
TAIL_STEP = 4 * 1024 * 1024                           # added when it is not
TAIL_MAX = 16 * 1024 * 1024
DEFAULT_PARTS = 700                                   # about 40 MB of the real dump each: ~125k games, ~1.5M table entries, ~300 MB per worker
DEFAULT_SLICES = 64
WINDOW_FORMAT = 1


# ---- byte-level frame detection (no network; pure functions over a buffer) -----------------------------------------------

def _frame_at(buf, at):
    """(offset in buf, offset of the zstd data after the skippable frame) of the first frame start at or after `at`, else None. A frame start
    is a skippable-frame header immediately followed, right after its declared payload, by a zstd data-frame magic number."""
    n = len(buf)
    for m in SKIP_MAGIC.finditer(buf, at):
        i = m.start()
        if i + 8 > n:
            return None
        data_start = i + 8 + struct.unpack_from("<I", buf, i + 4)[0]
        if data_start + 4 <= n and bytes(buf[data_start:data_start + 4]) == ZSTD_MAGIC:
            return i, data_start
    return None


def first_frame_start(buf, base=0, at=0):
    """Absolute offset of the first frame start at or after position `at` of `buf` (which begins at file offset `base`), or None."""
    found = _frame_at(buf, at)
    return None if found is None else base + found[0]


def frame_starts(buf, base=0):
    """Absolute offsets in `buf` (which begins at file offset `base`) where a frame starts, in order, none skipped."""
    out, at = [], 0
    while True:
        found = _frame_at(buf, at)
        if found is None:
            return out
        out.append(base + found[0])
        at = found[1] + 4


def find_frame_at_or_after(fetch, offset, search=SEARCH_WINDOW):
    """The absolute offset of the first frame starting at or after `offset` (`fetch(start, length) -> bytes`). Raises ValueError if none
    is found within `search` bytes of `offset` - should not happen with the default: real frame spacing is under 5 MB."""
    start = first_frame_start(fetch(offset, search), base=offset)
    if start is None:
        raise ValueError(f"no frame start found in {search:,} bytes from offset {offset:,} (dump format changed? re-probe it)")
    return start


def partition_bytes(total, n):
    """`n` (start, end) byte windows evenly covering [0, total); the last ends exactly at `total`. Nominal only - each is snapped to a
    real frame start when it is read (`read_window`)."""
    edges = [round(i * total / n) for i in range(n)] + [total]
    return list(zip(edges, edges[1:]))


def read_window(fetch, total, start, end, *, tail=TAIL_START, step=TAIL_STEP, max_tail=TAIL_MAX):
    """(true_start, true_end, data): the nominal window [start, end) snapped forward to real frame starts, and its bytes, which are a whole
    number of complete frames (empty when both ends snap to the same frame - a window smaller than one frame). Normally ONE request: the
    window plus `tail` bytes, in which the next frame start after `end` is found; the tail grows by `step` if it is not in there. The scan's
    very first byte (0) is always a frame start; the last window always ends exactly at `total`; a nominal edge inside the file's last frame
    snaps to `total`."""
    stop = min(end + tail, total)
    buf = fetch(start, stop - start)
    while True:
        ts = 0 if start == 0 else first_frame_start(buf, base=start, at=0)
        te = total if end >= total else first_frame_start(buf, base=start, at=end - start)
        reached_end = stop >= total
        if (ts is not None and te is not None) or reached_end:
            ts = total if ts is None else ts                    # nothing starts after the nominal edge: the rest of the file is one cut frame
            te = total if te is None else te
            te = max(ts, te)
            return ts, te, bytes(memoryview(buf)[ts - start:te - start]) if te > ts else b""
        if stop - end >= max_tail:
            raise ValueError(f"no frame start found within {stop - end:,} bytes past offset {end:,} (dump format changed? re-probe it)")
        more = min(step, total - stop)
        buf += fetch(stop, more)
        stop += more


def window_bounds(fetch, total, start, end):
    """(true_start, true_end) of a nominal window (see `read_window`)."""
    return read_window(fetch, total, start, end)[:2]


def decode_window_text(buf):
    """A text stream over a byte buffer that is a whole number of complete, back-to-back zstd frames (see `read_window`) - the same
    decompression `explorer.open_dump` uses for the single-stream case, just fed from memory instead of a live connection."""
    import io
    dec = zstandard.ZstdDecompressor(max_window_size=2 ** 31)
    reader = dec.stream_reader(io.BytesIO(buf), read_across_frames=True)
    return io.TextIOWrapper(reader, encoding="utf-8", errors="replace", newline="\n")


# ---- fetching a real dump over HTTP, or reading a local copy ----------------------------------------------------------------

_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+|\*)")


class HttpRangeFetcher:
    """`fetch(start, length) -> bytes` over HTTP range requests, and the dump's total size. Every response is checked (206 Partial Content, a
    Content-Range that starts where asked, a body of exactly the promised length), so a server or CDN node that ignores `Range` or cuts the
    body short is an error and a retry - never a silently wrong window, or the whole 28 GB file read into memory."""

    def __init__(self, url, timeout=120, tries=4, sleep=time.sleep, opener=None):
        self.url, self.timeout, self.tries, self.sleep = url, timeout, tries, sleep
        self.opener = opener or (lambda req: urllib.request.urlopen(req, timeout=timeout))

    def _retrying(self, what, fn):
        last = None
        for attempt in range(self.tries):
            try:
                return fn()
            except (OSError, ValueError, http.client.HTTPException) as e:        # URLError and timeouts are OSErrors
                last = e
                if attempt + 1 < self.tries:
                    self.sleep(5 * (attempt + 1))
        raise ConnectionError(f"{what} failed after {self.tries} attempts: {last!r}")

    def _request(self, start, last_byte):
        req = urllib.request.Request(self.url, headers={**EX.UA, "Range": f"bytes={start}-{last_byte}"})
        with self.opener(req) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            if status != 206:
                raise ValueError(f"expected 206 Partial Content for a range request, got {status} (the server ignored the Range header?)")
            m = _CONTENT_RANGE.match(resp.headers.get("Content-Range", ""))
            if not m or int(m.group(1)) != start:
                raise ValueError(f"Content-Range {resp.headers.get('Content-Range')!r} does not start at the requested byte {start:,}")
            body = resp.read()
            promised = int(m.group(2)) - start + 1
            if len(body) != promised or promised > last_byte - start + 1:
                raise ValueError(f"the response body has {len(body):,} bytes, the server promised {promised:,}")
            return body, (int(m.group(3)) if m.group(3).isdigit() else None)

    def total_size(self):
        _, total = self._retrying("probing the dump size", lambda: self._request(0, 0))
        if total is None:
            raise ValueError("the server does not report the total size in Content-Range")
        return total

    def fetch(self, start, length):
        if length <= 0:
            return b""
        return self._retrying(f"fetching bytes {start:,}+{length:,}", lambda: self._request(start, start + length - 1)[0])


class FileRangeFetcher:
    """The same interface over a local `.pgn.zst` file (an already downloaded dump, or a test fixture)."""

    def __init__(self, path):
        self.path = str(path)

    def total_size(self):
        return os.path.getsize(self.path)

    def fetch(self, start, length):
        if length <= 0:
            return b""
        with open(self.path, "rb") as f:
            f.seek(start)
            return f.read(length)


def make_fetcher(source):
    return HttpRangeFetcher(source) if str(source).startswith(("http://", "https://")) else FileRangeFetcher(source)


# ---- one window on disk: S slice files by position-key hash + a meta file written last ----------------------------------------

def _write_pickle(path, obj):
    tmp = Path(str(path) + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=1) as f:
        pickle.dump(obj, f, protocol=4)
    tmp.replace(path)


def _read_pickle(path):
    with gzip.open(path, "rb") as f:
        return pickle.load(f)


def slice_of(key, slices):
    """The slice a table key belongs to: by the hash of its POSITION (the key without the move), so every move of a position is in one slice."""
    return (key >> 16) % slices


def window_done(window_dir):
    return (Path(window_dir) / "meta.pkl.gz").exists()


def save_window(counts, window_dir, slices):
    """Write a window's counts as slice files and, last, the meta file (everything but the tables). A killed run leaves no meta: not done."""
    d = Path(window_dir)
    d.mkdir(parents=True, exist_ok=True)
    nb = len(counts.tables)
    parts = [None] * slices
    for b in range(nb):
        for field in ("tables", "evals", "top"):
            for k, v in getattr(counts, field)[b].items():
                j = slice_of(k, slices)
                if parts[j] is None:
                    parts[j] = {f: [dict() for _ in range(nb)] for f in ("tables", "evals", "top")}
                parts[j][field][b][k] = v
    for j, part in enumerate(parts):
        if part is not None:
            _write_pickle(d / f"slice_{j:03d}.pkl.gz", part)
        parts[j] = None
    meta = EX.Counts(nb)
    for name in ("games", "held_out", "scanned", "clock", "stats", "speed_games", "population", "rating_hist", "window_end"):
        setattr(meta, name, getattr(counts, name))
    EX.save_state(d / "meta.pkl.gz", meta, meta.scanned)


def load_window_meta(window_dir):
    return EX.load_state(Path(window_dir) / "meta.pkl.gz")


# ---- scanning a window ------------------------------------------------------------------------------------------------------

def scan_window(fetch, total, start, end, *, edges=EX.DEFAULT_BANDS, max_ply=EX.DEFAULT_MAX_PLY, min_base=30,
                max_entries=5_000_000, holdout=0, progress_every=50_000, out=None, slices=DEFAULT_SLICES, log=print):
    """The `explorer.Counts` of one byte window: snap to real frame boundaries, fetch the bytes (one request), decode, count every
    qualifying game (no per-band cap - see the module docstring) without pruning: past `max_entries` table entries it raises
    `explorer.EntryLimitExceeded`. `holdout` games per band are kept aside for the coverage test (counted afterwards). If `out` (a folder)
    is given the window is saved there, and an already saved window is not scanned again (its meta is returned: the tables stay on disk).

    `progress_every` also gates how often count_stream checks `max_entries`, not just its logging (logging is silenced here), so keep it
    real: a huge value would let a window grow far past its limit before the check runs."""
    if out and window_done(out):
        return load_window_meta(out)
    true_start, true_end, buf = read_window(fetch, total, start, end)
    counts = EX.Counts(len(edges) - 1)
    if true_end > true_start:
        try:
            EX.count_stream(lambda: decode_window_text(buf), counts, edges=edges, max_ply=max_ply, max_per_band=10 ** 9, min_base=min_base,
                            holdout=holdout, max_entries=max_entries, checkpoint=None, progress_every=progress_every, strict_entries=True,
                            reconnect=False, log=lambda *a: None)
        except EX.EntryLimitExceeded as e:
            raise EX.EntryLimitExceeded(f"window {start:,}-{end:,}: {e}; cut the dump into more windows (--parts) or raise --max-entries") from e
        if counts.size() > max_entries:
            raise EX.EntryLimitExceeded(f"window {start:,}-{end:,}: {counts.size():,} table entries, over the limit of {max_entries:,}; "
                                        "cut the dump into more windows (--parts) or raise --max-entries")
    log(f"  window {start:,}-{end:,} (snapped {true_start:,}-{true_end:,}, {(true_end - true_start) / 1e6:.1f} MB): "
        f"{counts.scanned:,} games scanned, {sum(counts.games):,} counted, {counts.size():,} entries")
    if out:
        save_window(counts, out, slices)
    return counts


# ---- merging windows --------------------------------------------------------------------------------------------------------

def merge_into(out, c):
    """Add the `Counts` of one window to `out` (in place). No band is ever marked full (`window_end` stays None): each window scanned
    without a per-band cap, so fullness is only meaningful over the merged total, not any one window."""
    for b in range(len(out.tables)):
        t = out.tables[b]
        for k, v in c.tables[b].items():
            t[k] = t.get(k, 0) + v
        for k, (n, s) in c.evals[b].items():
            e = out.evals[b].setdefault(k, [0, 0])
            e[0] += n
            e[1] += s
        for k, v in c.top[b].items():
            if v > out.top[b].get(k, 0):
                out.top[b][k] = v
        for k, (n, secs, instant) in c.clock[b].items():
            e = out.clock[b].setdefault(k, [0, 0.0, 0])
            e[0] += n
            e[1] += secs
            e[2] += instant
        for k, v in c.stats[b].items():
            out.stats[b][k] += v
        out.games[b] += c.games[b]
        out.held_out[b] += c.held_out[b]
        for k, v in c.speed_games[b].items():
            out.speed_games[b][k] = out.speed_games[b].get(k, 0) + v
        for k, v in c.population[b].items():
            out.population[b][k] = out.population[b].get(k, 0) + v
        if c.position_totals is not None:
            if out.position_totals is None:
                out.position_totals = [dict() for _ in out.tables]
            pt = out.position_totals[b]
            for pk, n in c.position_totals[b].items():
                pt[pk] = pt.get(pk, 0) + n
    for k, v in c.rating_hist.items():
        out.rating_hist[k] = out.rating_hist.get(k, 0) + v
    out.scanned += c.scanned
    out.pruned_below += c.pruned_below


def merge_counts(counts_list):
    """Additively merge several in-memory `Counts` (one per scanned window) into one."""
    if not counts_list:
        raise ValueError("nothing to merge")
    out = EX.Counts(len(counts_list[0].tables))
    for c in counts_list:
        merge_into(out, c)
    return out


def keep_floors(games, thresholds):
    """Per band, the fewest games an entry needs to be kept: the lower of what the database and the books will ever ask for."""
    t = thresholds
    return [min(EX.scaled_min(t["db_min_games"], t["db_min_frac"], g), EX.scaled_min(t["book_min_games"], t["book_min_frac"], g)) for g in games]


def merge_windows(window_dirs, *, slices, thresholds, log=print):
    """Merge saved windows into one `Counts`, exactly, one slice at a time: the totals of every window's meta first (they decide each band's
    keep-floor), then for every slice the union over all windows. Entries with fewer games than the band's floor are dropped after their
    position's exact total has been recorded in `position_totals`; `pruned_below` says how many games a missing entry may have had."""
    if not window_dirs:
        raise ValueError("nothing to merge")
    first = load_window_meta(window_dirs[0])
    merged = EX.Counts(len(first.tables))
    merge_into(merged, first)
    for d in window_dirs[1:]:
        merge_into(merged, load_window_meta(d))
    floors = keep_floors(merged.games, thresholds)
    nb = len(merged.tables)
    merged.position_totals = [dict() for _ in range(nb)]
    kept = dropped = 0
    for j in range(slices):
        acc = {f: [dict() for _ in range(nb)] for f in ("tables", "evals", "top")}
        for d in window_dirs:
            path = Path(d) / f"slice_{j:03d}.pkl.gz"
            if not path.exists():
                continue
            part = _read_pickle(path)
            for b in range(nb):
                t = acc["tables"][b]
                for k, v in part["tables"][b].items():
                    t[k] = t.get(k, 0) + v
                for k, (n, s) in part["evals"][b].items():
                    e = acc["evals"][b].setdefault(k, [0, 0])
                    e[0] += n
                    e[1] += s
                for k, v in part["top"][b].items():
                    if v > acc["top"][b].get(k, 0):
                        acc["top"][b][k] = v
            del part
        for b in range(nb):
            tab = acc["tables"][b]
            totals = {}
            for k, v in tab.items():
                pk = k >> 16
                totals[pk] = totals.get(pk, 0) + (v & EX.FIELD_MASK)
            floor = floors[b]
            keep = {k: v for k, v in tab.items() if (v & EX.FIELD_MASK) >= floor}
            merged.tables[b].update(keep)
            for pk in {k >> 16 for k in keep}:
                merged.position_totals[b][pk] = totals[pk]
            for k in keep:
                if k in acc["evals"][b]:
                    merged.evals[b][k] = acc["evals"][b][k]
                if k in acc["top"][b]:
                    merged.top[b][k] = acc["top"][b][k]
            kept += len(keep)
            dropped += len(tab) - len(keep)
        del acc
        if (j + 1) % 8 == 0 or j + 1 == slices:
            log(f"  merge: slice {j + 1}/{slices}, {kept:,} entries kept, {dropped:,} below their band's floor dropped")
    merged.pruned_below = max(floors) - 1 if floors else 0
    return merged


# ---- orchestration: probe, partition, scan (parallel, resumable), merge ------------------------------------------------------

def _window_dir(windows_dir, i):
    return Path(windows_dir) / f"{i:04d}"


def check_manifest(windows_dir, manifest):
    """Create the windows folder's manifest, or check that an existing one describes the same scan: windows made with other settings
    (another dump, bands, depth, window count ...) must never be merged with these."""
    path = Path(windows_dir) / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(json.dumps(manifest))                        # as JSON would round-trip it (tuples -> lists)
    if path.exists():
        old = json.loads(path.read_text())
        if old != manifest:
            diff = {k: (old.get(k), manifest.get(k)) for k in set(old) | set(manifest) if old.get(k) != manifest.get(k)}
            raise ValueError(f"{path.parent} holds windows made with other settings {diff}; use another --out (or delete the folder)")
    else:
        path.write_text(json.dumps(manifest, indent=1))


def _scan_window_task(task):
    source, total, start, end, edges, max_ply, min_base, max_entries, holdout, slices, out = task
    c = scan_window(make_fetcher(source).fetch, total, start, end, edges=edges, max_ply=max_ply, min_base=min_base, max_entries=max_entries,
                    holdout=holdout, slices=slices, out=out, log=lambda *a: None)
    return out, c.scanned, sum(c.games)


def run(source, n_parts, out_dir, *, edges=EX.DEFAULT_BANDS, max_ply=EX.DEFAULT_MAX_PLY, min_base=30, max_entries=5_000_000, holdout=1000,
        slices=DEFAULT_SLICES, thresholds=None, workers=4, job="explorer-range", control_dir="data/control", log=print):
    """Partitioned scan of the whole dump (an URL, or a local `.pgn.zst`): probe its size, cut it into `n_parts` byte windows, scan each
    independently in worker processes (resumable - a window already saved under `out_dir/windows_<n_parts>/` is skipped), then merge them
    exactly, slice by slice (see the module docstring). `thresholds` = the explorer's keep thresholds (db_min_games, db_min_frac,
    book_min_games, book_min_frac): entries below what the database and the books will keep are dropped in the merge."""
    from .. import jobs as J
    thresholds = thresholds or {"db_min_games": 5, "db_min_frac": 1e-5, "book_min_games": 20, "book_min_frac": 5e-5}
    out_dir = Path(out_dir)
    windows_dir = out_dir / f"windows_{n_parts}"
    total = make_fetcher(source).total_size()
    windows = partition_bytes(total, n_parts)
    check_manifest(windows_dir, {"format": WINDOW_FORMAT, "source": os.path.basename(str(source)), "total_bytes": total, "parts": n_parts,
                                 "edges": list(edges), "max_ply": max_ply, "min_base": min_base, "slices": slices,
                                 "holdout_per_window": math.ceil(holdout / n_parts) if holdout else 0})
    log(f"{source}: {total:,} bytes, {n_parts} windows of about {total / n_parts / 1e6:.0f} MB each, {slices} slices")
    per_window = math.ceil(holdout / n_parts) if holdout else 0
    dirs = [_window_dir(windows_dir, i) for i in range(n_parts)]
    todo = [(source, total, s, e, tuple(edges), max_ply, min_base, max_entries, per_window, slices, str(d))
            for (s, e), d in zip(windows, dirs) if not window_done(d)]
    log(f"{n_parts - len(todo)} windows already done, {len(todo)} to scan")
    ctl = J.JobControl(job, control_dir, log=log)
    if todo:
        t0 = time.time()
        for i, (out, scanned, games) in enumerate(J.run_pool(_scan_window_task, todo, workers, ctl)):
            log(f"  [{i + 1}/{len(todo)}] {out}: {scanned:,} scanned, {games:,} counted "
                f"({(time.time() - t0) / 60 / (i + 1):.1f} min/window so far)")
    merged = merge_windows([str(d) for d in dirs], slices=slices, thresholds=thresholds, log=log)
    log(f"merged {n_parts} windows: {merged.scanned:,} games scanned, {sum(merged.games):,} counted, {merged.size():,} entries kept "
        f"(entries with at most {merged.pruned_below} games in a band are not kept)")
    return merged
