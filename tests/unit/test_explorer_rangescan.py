import struct

import pytest
import zstandard

from chessme.book import explorer as EX
from chessme.book import rangescan as RS

EDGES = (600, 1000, 1400, 1800, 2200)


def game(w, b, result, moves, tc="300+0"):
    r = {1.0: "1-0", 0.5: "1/2-1/2", 0.0: "0-1"}[result]
    parts = [(f"{i // 2 + 1}. " if i % 2 == 0 else "") + m for i, m in enumerate(moves)]
    body = " ".join(parts) + f" {r}"
    return (f'[Event "x"]\n[Site "s"]\n[White "a"]\n[Black "b"]\n[Result "{r}"]\n[WhiteElo "{w}"]\n[BlackElo "{b}"]\n[TimeControl "{tc}"]\n'
            f'[Termination "Normal"]\n\n{body}\n\n')


ITALIAN = "e4 e5 Nf3 Nc6 Bc4 Bc5".split()
SCOTCH = "e4 e5 Nf3 Nc6 d4 exd4".split()


def skip_frame(payload=b"\x00\x00\x00\x00"):
    """A real skippable-frame header: magic 0x184D2A50, a 4-byte little-endian size, then that many payload bytes."""
    return struct.pack("<I", 0x184D2A50) + struct.pack("<I", len(payload)) + payload


def make_dump(chunks):
    """A real multi-frame .zst byte blob: each of `chunks` (text) compressed as its own zstd frame, preceded by a skippable frame -
    exactly the pattern found live in a real Lichess dump (see rangescan.py's module docstring)."""
    cctx = zstandard.ZstdCompressor()
    buf = b""
    starts = []
    for chunk in chunks:
        starts.append(len(buf))
        buf += skip_frame() + cctx.compress(chunk.encode("utf-8"))
    return buf, starts


def fetcher(buf):
    def fetch(start, length):
        return buf[start:start + length]
    return fetch


# ---- byte-level frame detection --------------------------------------------------------------------------------------------

def test_frame_starts_finds_every_real_frame_boundary():
    buf, starts = make_dump(["a" * 500, "b" * 900, "c" * 300])
    assert RS.frame_starts(buf) == starts


def test_frame_starts_finds_nothing_in_plain_data():
    assert RS.frame_starts(b"just some random bytes, no zstd frames here at all" * 10) == []


def test_find_frame_at_or_after_snaps_forward_to_the_next_real_start():
    buf, starts = make_dump(["a" * 500, "b" * 900, "c" * 300])
    fetch = fetcher(buf)
    assert RS.find_frame_at_or_after(fetch, 0) == starts[0]
    assert RS.find_frame_at_or_after(fetch, starts[0] + 1) == starts[1]         # mid-first-frame: snaps to the second
    assert RS.find_frame_at_or_after(fetch, starts[1]) == starts[1]             # already exactly on a boundary: stays put


def test_find_frame_at_or_after_raises_when_none_exists_in_range():
    buf, starts = make_dump(["a" * 500])
    fetch = fetcher(buf)
    with pytest.raises(ValueError, match="no frame start found"):
        RS.find_frame_at_or_after(fetch, starts[0] + 1, search=4)               # nothing left after the only frame


# ---- partitioning and window snapping --------------------------------------------------------------------------------------

def test_partition_bytes_covers_the_range_exactly_with_no_gaps_or_overlap():
    parts = RS.partition_bytes(1_000_003, 7)
    assert len(parts) == 7
    assert parts[0][0] == 0 and parts[-1][1] == 1_000_003
    assert all(a[1] == b[0] for a, b in zip(parts, parts[1:]))                  # each window's end is the next one's start


def test_window_bounds_snaps_both_ends_to_real_frame_starts():
    buf, starts = make_dump(["a" * 500, "b" * 900, "c" * 300])
    fetch = fetcher(buf)
    true_start, true_end = RS.window_bounds(fetch, len(buf), starts[1] - 5, starts[2] - 3)
    assert (true_start, true_end) == (starts[1], starts[2])


def test_window_bounds_the_first_window_starts_at_zero_and_the_last_ends_at_total():
    buf, starts = make_dump(["a" * 500, "b" * 900])
    fetch = fetcher(buf)
    assert RS.window_bounds(fetch, len(buf), 0, starts[1])[0] == 0
    assert RS.window_bounds(fetch, len(buf), starts[1], len(buf) + 999)[1] == len(buf)


# ---- decoding and end-to-end window counting ---------------------------------------------------------------------------------

def test_decode_window_text_reconstructs_the_original_text_across_frames():
    original = "hello " * 10 + "world " * 10
    buf, starts = make_dump([original[:60], original[60:]])
    got = RS.decode_window_text(buf).read()
    assert got == original


def test_scan_window_counts_every_game_in_its_slice_and_is_resumable(tmp_path):
    buf, starts = make_dump([game(1500, 1500, 1.0, ITALIAN) + game(1500, 1500, 0.5, SCOTCH), game(1500, 1500, 0.0, ITALIAN)])
    fetch = fetcher(buf)
    out = tmp_path / "window.pkl.gz"
    counts = RS.scan_window(fetch, len(buf), 0, len(buf), edges=EDGES, max_ply=4, out=out, log=lambda *a: None)
    assert counts.scanned == 3 and sum(counts.games) == 3

    def boom(start, length):
        raise AssertionError("should not fetch again: the window was already saved")
    again = RS.scan_window(boom, len(buf), 0, len(buf), edges=EDGES, max_ply=4, out=out, log=lambda *a: None)
    assert again.scanned == 3 and sum(again.games) == 3


def test_scan_window_never_marks_a_band_full():
    buf, _ = make_dump([game(1500, 1500, 1.0, ITALIAN)])
    counts = RS.scan_window(fetcher(buf), len(buf), 0, len(buf), edges=EDGES, max_ply=4, log=lambda *a: None)
    assert all(w is None for w in counts.window_end)


# ---- merging ------------------------------------------------------------------------------------------------------------------

def test_merge_counts_sums_two_windows_scanned_separately():
    buf1, _ = make_dump([game(1500, 1500, 1.0, ITALIAN), game(1500, 1500, 0.5, SCOTCH)])
    buf2, _ = make_dump([game(900, 900, 0.0, ITALIAN)])
    c1 = RS.scan_window(fetcher(buf1), len(buf1), 0, len(buf1), edges=EDGES, max_ply=4, log=lambda *a: None)
    c2 = RS.scan_window(fetcher(buf2), len(buf2), 0, len(buf2), edges=EDGES, max_ply=4, log=lambda *a: None)
    merged = RS.merge_counts([c1, c2])
    assert merged.scanned == 3 and sum(merged.games) == 3
    assert sum(merged.games) == sum(c1.games) + sum(c2.games)
    # the two Italian games (one at 1500, one at 900) land in different bands and both survive the merge
    band_1500, band_900 = EX.rating_band(1500, EDGES), EX.rating_band(900, EDGES)
    assert merged.games[band_1500] >= 1 and merged.games[band_900] >= 1


def test_merge_counts_refuses_an_empty_list():
    with pytest.raises(ValueError, match="nothing to merge"):
        RS.merge_counts([])


# ---- the max_entries memory guard must actually run within a window ----------------------------------------------------------

FIRST_MOVES = ["a3", "a4", "b3", "b4", "c3", "c4", "d3", "d4", "e3", "e4", "f3", "f4", "g3", "g4", "h3", "h4", "Na3", "Nc3", "Nf3", "Nh3"]


def test_scan_window_prunes_when_over_max_entries():
    # Regression: scan_window used to hard-code count_stream's progress_every so large that the max_entries prune check inside
    # count_stream never ran for a realistic window size (it is gated by the same counter as the progress log) - the cap was silently
    # not enforced. 20 distinct legal first moves from the start position make 20 distinct table entries in one window.
    buf, _ = make_dump(["".join(game(1500, 1500, 1.0, [m]) for m in FIRST_MOVES)])
    counts = RS.scan_window(fetcher(buf), len(buf), 0, len(buf), edges=EDGES, max_ply=1, max_entries=5, progress_every=5, log=lambda *a: None)
    assert counts.scanned == 20
    assert counts.size() <= 5
    assert counts.pruned_below > 0


def test_scan_window_with_a_generous_max_entries_prunes_nothing():
    buf, _ = make_dump(["".join(game(1500, 1500, 1.0, [m]) for m in FIRST_MOVES)])
    counts = RS.scan_window(fetcher(buf), len(buf), 0, len(buf), edges=EDGES, max_ply=1, max_entries=1000, progress_every=5, log=lambda *a: None)
    assert counts.size() == 20 and counts.pruned_below == 0


# ---- the HTTP range fetcher validates every response ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, body, status=206, content_range=None, headers=None):
        self.body, self.status = body, status
        self.headers = headers if headers is not None else ({"Content-Range": content_range} if content_range else {})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body

    def getcode(self):
        return self.status


def range_server(blob, *, status=206, shorten=0, shift=0, ignore_range=False):
    """An `opener` serving `blob` the way a (possibly misbehaving) HTTP server would; records the Range headers it was asked for."""
    asked = []

    def opener(req):
        rng = req.get_header("Range")
        asked.append(rng)
        a, b = (int(x) for x in rng.split("=")[1].split("-"))
        if ignore_range:
            return FakeResponse(blob, status=200)
        b = min(b, len(blob) - 1)
        body = blob[a:b + 1]
        return FakeResponse(body[:len(body) - shorten] if shorten else body, status=status, content_range=f"bytes {a + shift}-{b}/{len(blob)}")
    opener.asked = asked
    return opener


def test_fetcher_returns_exactly_the_requested_bytes_and_the_total_size():
    blob = bytes(range(256)) * 4
    f = RS.HttpRangeFetcher("http://x", opener=range_server(blob), sleep=lambda s: None)
    assert f.fetch(10, 100) == blob[10:110]
    assert f.total_size() == len(blob)
    assert f.fetch(len(blob) - 5, 100) == blob[-5:]                    # a range running past the end is clamped by the server


def test_fetcher_rejects_a_server_that_ignores_the_range_header():
    # Regression: a 200 answer (the whole 28 GB file) used to be read into memory as if it were the window.
    f = RS.HttpRangeFetcher("http://x", opener=range_server(b"x" * 1000, ignore_range=True), tries=3, sleep=lambda s: None)
    with pytest.raises(ConnectionError, match="206"):
        f.fetch(0, 10)


def test_fetcher_rejects_a_short_body_and_a_misplaced_range_and_retries():
    blob = b"abcdefghij" * 100
    for kwargs, message in (({"shorten": 3}, "promised"), ({"shift": 1}, "does not start")):
        opener = range_server(blob, **kwargs)
        f = RS.HttpRangeFetcher("http://x", opener=opener, tries=3, sleep=lambda s: None)
        with pytest.raises(ConnectionError, match=message):
            f.fetch(0, 50)
        assert len(opener.asked) == 3                                     # retried, then gave up


def test_fetcher_recovers_from_a_transient_failure():
    blob = b"0123456789" * 50
    good = range_server(blob)
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("connection reset")
        return good(req)
    f = RS.HttpRangeFetcher("http://x", opener=flaky, sleep=lambda s: None)
    assert f.fetch(5, 20) == blob[5:25] and calls["n"] == 2


def test_fetcher_never_sends_an_empty_range():
    # Regression: a zero-length window produced `Range: bytes=S-(S-1)`, which servers ignore by sending the whole file.
    opener = range_server(b"x" * 100)
    assert RS.HttpRangeFetcher("http://x", opener=opener).fetch(40, 0) == b"" and opener.asked == []


# ---- windows smaller than a frame, and the end of the file --------------------------------------------------------------------

def test_a_window_that_contains_no_frame_start_is_empty_and_harmless(tmp_path):
    buf, starts = make_dump([game(1500, 1500, 1.0, ITALIAN) * 3, game(1500, 1500, 0.0, SCOTCH)])
    lo, hi = starts[1] - 30, starts[1] - 10                                 # strictly inside frame 0: both ends snap to frame 1
    assert RS.window_bounds(fetcher(buf), len(buf), lo, hi) == (starts[1], starts[1])
    out = tmp_path / "w.pkl.gz"
    counts = RS.scan_window(fetcher(buf), len(buf), lo, hi, edges=EDGES, max_ply=4, out=out, log=lambda *a: None)
    assert counts.scanned == 0 and sum(counts.games) == 0 and out.exists()


def test_a_window_starting_inside_the_last_frame_ends_at_the_end_of_the_file():
    # Regression: no later frame starts, so snapping raised "no frame start found" and killed the whole scan.
    buf, starts = make_dump([game(1500, 1500, 1.0, ITALIAN), game(1500, 1500, 0.0, SCOTCH)])
    inside_last = starts[1] + 20
    assert RS.window_bounds(fetcher(buf), len(buf), inside_last, len(buf)) == (len(buf), len(buf))


def test_every_game_is_counted_exactly_once_whatever_the_number_of_windows():
    games = [game(1500, 1500, [1.0, 0.5, 0.0][i % 3], ITALIAN if i % 2 else SCOTCH) for i in range(12)]
    buf, _ = make_dump(["".join(games[i:i + 2]) for i in range(0, 12, 2)])
    for parts in (1, 2, 3, 6, 40):
        merged = RS.merge_counts([RS.scan_window(fetcher(buf), len(buf), s, e, edges=EDGES, max_ply=4, log=lambda *a: None)
                                  for s, e in RS.partition_bytes(len(buf), parts)])
        assert merged.scanned == 12 and sum(merged.games) == 12, parts


# ---- merging one window at a time ---------------------------------------------------------------------------------------------

def test_merge_windows_matches_merge_counts_and_adds_up_the_pruning_bounds(tmp_path):
    paths, counts = [], []
    for i in range(3):
        buf, _ = make_dump(["".join(game(1500, 1500, 1.0, [m]) for m in FIRST_MOVES[:10 + i])])
        c = RS.scan_window(fetcher(buf), len(buf), 0, len(buf), edges=EDGES, max_ply=1, max_entries=5, progress_every=5, log=lambda *a: None)
        p = tmp_path / f"{i}.pkl.gz"
        EX.save_state(p, c, c.scanned)
        paths.append(p)
        counts.append(c)
    merged = RS.merge_windows(paths, max_merged_entries=0, log=lambda *a: None)
    assert merged.size() == RS.merge_counts(counts).size() and merged.scanned == sum(c.scanned for c in counts)
    # Regression: the report said "entries with at most N games may be missing" with N the largest single-window threshold.
    assert merged.pruned_below == sum(c.pruned_below for c in counts) > max(c.pruned_below for c in counts)


def test_merge_windows_caps_the_merged_table(tmp_path):
    paths = []
    for i in range(3):
        buf, _ = make_dump(["".join(game(1500, 1500, 1.0, [m]) for m in FIRST_MOVES)])
        c = RS.scan_window(fetcher(buf), len(buf), 0, len(buf), edges=EDGES, max_ply=1, log=lambda *a: None)
        EX.save_state(tmp_path / f"{i}.pkl.gz", c, c.scanned)
        paths.append(tmp_path / f"{i}.pkl.gz")
    merged = RS.merge_windows(paths, max_merged_entries=8, log=lambda *a: None)
    assert merged.size() <= 8 and merged.pruned_below > 0
    with pytest.raises(ValueError, match="nothing to merge"):
        RS.merge_windows([], log=lambda *a: None)
