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
start (`find_frame_at_or_after`): fetch a small buffer past the nominal boundary and scan it for the skip-frame + zstd-magic signature.
A window then downloads exactly the whole frames from its snapped start up to (but not including) the next window's snapped start, and
decodes them with an ordinary zstd multi-frame reader - the same one `explorer.open_dump` already uses for the single-stream case.

Accepted loss: a game whose PGN text straddles a window boundary is dropped (each half lands in a different window, and nothing stitches
them back together) - at most one incomplete game per window, negligible against tens of millions of games. Also accepted: unlike the
single-stream scan, a window does not stop early when a band fills up (each worker only sees its own slice, not the running total across
the whole scan), so this counts every qualifying game in every window rather than mostly the first part of the file - which is the whole
point (see the existing note in plan.md: ranges spread over the whole month remove the bias of scanning only its first third)."""
import http.client
import re
import struct
import time
import urllib.request
from pathlib import Path

import zstandard

from . import explorer as EX

ZSTD_MAGIC = bytes([0x28, 0xB5, 0x2F, 0xFD])
SKIP_MAGIC_LOW, SKIP_MAGIC_HIGH = 0x50, 0x5F        # skippable-frame first byte; bytes 1-3 are always 2A 4D 18 (little-endian 0x184D2A5x)
SEARCH_WINDOW = 8 * 1024 * 1024                     # generous vs. the ~4.7 MB observed frame spacing


# ---- byte-level frame detection (no network; pure functions over a buffer) -----------------------------------------------

def frame_starts(buf, base=0):
    """Absolute offsets in `buf` (which begins at file offset `base`) where a frame starts: a skippable-frame header immediately
    followed, right after its declared payload, by a zstd data-frame magic number. In order, none skipped."""
    out = []
    i, n = 0, len(buf)
    while i + 8 <= n:
        b0, b1, b2, b3 = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
        if b1 == 0x2A and b2 == 0x4D and b3 == 0x18 and SKIP_MAGIC_LOW <= b0 <= SKIP_MAGIC_HIGH:
            size = struct.unpack_from("<I", buf, i + 4)[0]
            data_start = i + 8 + size
            if data_start + 4 <= n and buf[data_start:data_start + 4] == ZSTD_MAGIC:
                out.append(base + i)
                i = data_start + 4
                continue
        i += 1
    return out


def find_frame_at_or_after(fetch, offset, search=SEARCH_WINDOW):
    """The absolute offset of the first frame starting at or after `offset` (`fetch(start, length) -> bytes`). Raises ValueError if none
    is found within `search` bytes of `offset` - should not happen with the default: real frame spacing is under 5 MB."""
    buf = fetch(offset, search)
    starts = frame_starts(buf, base=offset)
    if not starts:
        raise ValueError(f"no frame start found in {search:,} bytes from offset {offset:,} (dump format changed? re-probe it)")
    return starts[0]


def partition_bytes(total, n):
    """`n` (start, end) byte windows evenly covering [0, total); the last ends exactly at `total`. Nominal only - each is snapped to a
    real frame start before it is fetched (`window_bounds`)."""
    edges = [round(i * total / n) for i in range(n)] + [total]
    return list(zip(edges, edges[1:]))


def _snap(fetch, total, offset):
    """The first frame start at or after `offset`; `total` when there is none because `offset` lies inside the file's last frame."""
    if offset >= total:
        return total
    try:
        return find_frame_at_or_after(fetch, offset)
    except ValueError:
        if offset + SEARCH_WINDOW >= total:           # the search reached the end of the file: no later frame starts
            return total
        raise


def window_bounds(fetch, total, start, end):
    """(true_start, true_end): `start`/`end` snapped to real frame starts, so [true_start, true_end) is a whole number of complete
    frames (empty when both snap to the same frame - a window smaller than one frame). The scan's very first byte (0) is always a frame
    start; the last window always ends exactly at `total`."""
    true_start = 0 if start == 0 else _snap(fetch, total, start)
    true_end = total if end >= total else _snap(fetch, total, end)
    return true_start, max(true_start, true_end)


def decode_window_text(buf):
    """A text stream over a byte buffer that is a whole number of complete, back-to-back zstd frames (see `window_bounds`) - the same
    decompression `explorer.open_dump` uses for the single-stream case, just fed from memory instead of a live connection."""
    import io
    dec = zstandard.ZstdDecompressor(max_window_size=2 ** 31)
    reader = dec.stream_reader(io.BytesIO(buf), read_across_frames=True)
    return io.TextIOWrapper(reader, encoding="utf-8", errors="replace", newline="\n")


# ---- fetching a real dump over HTTP ----------------------------------------------------------------------------------------

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


# ---- scanning and merging windows ------------------------------------------------------------------------------------------

def scan_window(fetch, total, start, end, *, edges=EX.DEFAULT_BANDS, max_ply=EX.DEFAULT_MAX_PLY, min_base=30,
                 max_entries=20_000_000, progress_every=50_000, out=None, log=print):
    """The `explorer.Counts` of one byte window: snap to real frame boundaries, fetch exactly those bytes once, decode, count every
    qualifying game (no per-band cap - see the module docstring). If `out` is given and already exists, the window is skipped (its
    saved counts are loaded instead), so a partitioned scan is resumable window by window.

    `progress_every` also gates count_stream's max_entries prune check, not just its logging (logging is always silenced here via a
    no-op log callback, so this only controls how often the memory guard actually runs - keep it real, do not set it to something huge
    to "quiet down" a window scan, or the max_entries cap silently stops being enforced)."""
    if out and Path(out).exists():
        return EX.load_state(out)
    true_start, true_end = window_bounds(fetch, total, start, end)
    counts = EX.Counts(len(edges) - 1)
    if true_end <= true_start:                                  # both ends snapped to the same frame: the neighbouring window owns it
        log(f"  window {start:,}-{end:,}: no frame starts inside it (empty)")
        if out:
            EX.save_state(out, counts, 0)
        return counts
    buf = fetch(true_start, true_end - true_start)
    EX.count_stream(lambda: decode_window_text(buf), counts, edges=edges, max_ply=max_ply, max_per_band=10 ** 9, min_base=min_base,
                     holdout=0, max_entries=max_entries, checkpoint=None, progress_every=progress_every, log=lambda *a: None)
    log(f"  window {start:,}-{end:,} (snapped {true_start:,}-{true_end:,}, {(true_end - true_start) / 1e6:.1f} MB): "
        f"{counts.scanned:,} games scanned, {sum(counts.games):,} counted")
    if out:
        EX.save_state(out, counts, counts.scanned)
    return counts


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
    for k, v in c.rating_hist.items():
        out.rating_hist[k] = out.rating_hist.get(k, 0) + v
    out.scanned += c.scanned
    # An entry pruned in one window can be missing up to that window's threshold of games, in every window: the bounds add up.
    out.pruned_below += c.pruned_below


def merge_counts(counts_list):
    """Additively merge several `Counts` (one per scanned window) into one."""
    if not counts_list:
        raise ValueError("nothing to merge")
    out = EX.Counts(len(counts_list[0].tables))
    for c in counts_list:
        merge_into(out, c)
    return out


def merge_windows(paths, *, max_merged_entries=60_000_000, log=print):
    """Merge saved window checkpoints one at a time (never all in memory), pruning the merged table when it passes `max_merged_entries`."""
    merged = None
    for i, path in enumerate(paths):
        c = EX.load_state(path)
        if merged is None:
            merged = EX.Counts(len(c.tables))
        merge_into(merged, c)
        del c
        if max_merged_entries and merged.size() > max_merged_entries:
            before = merged.pruned_below
            thr = merged.prune(max_merged_entries)
            merged.pruned_below = before + thr
            log(f"  merge: over {max_merged_entries:,} entries after window {i + 1}: entries with at most {thr} games are now incomplete")
    if merged is None:
        raise ValueError("nothing to merge")
    return merged


# ---- orchestration: probe, partition, scan (parallel, resumable), merge -----------------------------------------------------

def _scan_window_task(task):
    url, start, end, edges, max_ply, min_base, max_entries, out = task
    fetcher = HttpRangeFetcher(url)
    c = scan_window(fetcher.fetch, fetcher.total_size(), start, end, edges=edges, max_ply=max_ply, min_base=min_base,
                     max_entries=max_entries, out=out, log=lambda *a: None)
    return out, c.scanned, sum(c.games)


def run(url, n_parts, out_dir, *, edges=EX.DEFAULT_BANDS, max_ply=EX.DEFAULT_MAX_PLY, min_base=30, max_entries=20_000_000,
        max_merged_entries=60_000_000, workers=4, job="explorer-range", control_dir="data/control", log=print):
    """Partitioned scan of the whole dump: probe its size, cut it into `n_parts` byte windows, scan each independently in worker
    processes (resumable - a window already saved under `out_dir/windows/` is skipped), then merge every window into one `Counts`.
    Memory is bounded per window (`max_entries`) while scanning, and the merge loads one window at a time into a table that is itself capped
    (`max_merged_entries`, the rarest entries are dropped first and recorded in `pruned_below`)."""
    from .. import jobs as J
    out_dir = Path(out_dir)
    (out_dir / "windows").mkdir(parents=True, exist_ok=True)
    total = HttpRangeFetcher(url).total_size()
    windows = partition_bytes(total, n_parts)
    log(f"{url}: {total:,} bytes, {n_parts} windows of about {total / n_parts / 1e6:.0f} MB each")
    tasks = [(url, s, e, edges, max_ply, min_base, max_entries, str(out_dir / "windows" / f"{i:04d}.pkl.gz"))
             for i, (s, e) in enumerate(windows)]
    todo = [t for t in tasks if not Path(t[-1]).exists()]
    log(f"{len(tasks) - len(todo)} windows already done, {len(todo)} to scan")
    ctl = J.JobControl(job, control_dir, log=log)
    if todo:
        t0 = time.time()
        for i, (out, scanned, games) in enumerate(J.run_pool(_scan_window_task, todo, workers, ctl)):
            log(f"  [{i + 1}/{len(todo)}] {out}: {scanned:,} scanned, {games:,} counted "
                f"({(time.time() - t0) / 60 / (i + 1):.1f} min/window so far)")
    merged = merge_windows([t[-1] for t in tasks], max_merged_entries=max_merged_entries, log=log)
    log(f"merged {n_parts} windows: {merged.scanned:,} games scanned, {sum(merged.games):,} counted, {merged.size():,} entries")
    return merged
