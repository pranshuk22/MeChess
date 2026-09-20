"""An opening explorer built from the Lichess game database (CC0), one pass over a stream, no download of the whole file.

For every rating band, every position of the first `max_ply` plies and every move played there: how many games, how they ended
(White / draw / Black), the average rating of the players and, from the ~6% of games that carry engine annotations, the average
evaluation after the move. Also per band: results, game length, and how long players think at each ply. From those counts we write

  explorer.db          SQLite: the explorer (query by position and rating, like the Lichess opening explorer, with the result bar)
  theory_LO_HI.bin     one playable book per band (`book.bin` format; the controller and `mechess --book DIR` read it)
  report.md            how deep each book carries games it has never seen (held-out games), and population statistics per band

Design points: positions are keyed by a 64-bit hash of "placement turn castling" (transpositions merge), so no FEN is stored;
the counts of one entry (games, White wins, draws, rating sum) are packed into one integer; memory is bounded by `max_entries` (rare
entries are dropped first); a checkpoint lets a stopped run continue; the stream is re-opened and fast-forwarded if the connection drops;
the movetext of a game is only parsed for the games that are counted."""
import glob
import gzip
import hashlib
import io
import pickle
import re
import shutil
import sqlite3
import time
import urllib.request
from pathlib import Path

import chess

from .format import Entry, write_book
from .keys import book_key, key_text

UA = {"User-Agent": "MeChess-opening-explorer (research; CC0 Lichess database)"}
# every rating range is kept: 200-point bands from 800 to 2600, and open-ended ends (Lichess ratings run from a few hundred to over 3000)
DEFAULT_BANDS = (0, 800, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 4000)
FULL_FROM = 2200                                             # bands starting here are rare: every game is counted, not one in `sample_every`
DEFAULT_MAX_PLY = 24
MASK24 = (1 << 24) - 1
EVAL_CLAMP = 1000                                            # centipawns: mates count as +-10 pawns
_MOVENUM = re.compile(r"\d+\.+")
_TAG = re.compile(r'\[(\w+) "([^"]*)"\]')
_SAN = re.compile(r"(?:\d+\.+\s*)?([A-Za-z][A-Za-z0-9+#=\-]*)(?:\s*\$\d+)*(?:\s*\{([^}]*)\})?")
_EVAL = re.compile(r"\[%eval (#?-?\d+(?:\.\d+)?)\]")
_CLK = re.compile(r"\[%clk (\d+):(\d\d):(\d\d(?:\.\d+)?)\]")
_LAST_MOVE_NO = re.compile(r"(\d+)\.")
_BRACES = re.compile(r"\{[^}]*\}")


# ---- keys and packed counts ----------------------------------------------------------------------------------------------

def pos_key(board):
    """64-bit key of a position (placement, side to move, castling: transpositions merge)."""
    return int.from_bytes(hashlib.blake2b(key_text(board).encode(), digest_size=8).digest(), "big")


def move16(move):
    return move.from_square | (move.to_square << 6) | ((move.promotion or 0) << 12)


def unmove16(m):
    return chess.Move(m & 63, (m >> 6) & 63, (m >> 12) or None)


def pack(result_white, avg_rating=0):
    """One game's contribution: 1 game, +1 White win in bits 24.., +1 draw in bits 48.., its average rating (summed) from bit 72."""
    return 1 + ((1 << 24) if result_white == 1.0 else 0) + ((1 << 48) if result_white == 0.5 else 0) + (int(avg_rating) << 72)


def unpack(v):
    g, w, d = v & MASK24, (v >> 24) & MASK24, (v >> 48) & MASK24
    return g, w, d, g - w - d


def avg_rating_of(v):
    g = v & MASK24
    return (v >> 72) / g if g else 0.0


def signed64(k):
    return k - (1 << 64) if k >= (1 << 63) else k


# ---- reading games -------------------------------------------------------------------------------------------------------

def open_dump(source):
    """A text stream of a PGN dump: a path or URL, `.zst` or plain."""
    if str(source).startswith("http"):
        raw = urllib.request.urlopen(urllib.request.Request(source, headers=UA), timeout=120)
    else:
        raw = open(source, "rb")
    if str(source).endswith(".zst"):
        import zstandard
        raw = zstandard.ZstdDecompressor().stream_reader(raw)
    return io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="\n")


def iter_games(stream):
    """Yield the tags of every game of a PGN text stream, with the raw movetext line under "_line" (parsed later, and only for the games
    that are counted)."""
    tags, have_line = {}, False
    for line in stream:
        if line.startswith("["):
            if have_line:                                    # a new game began
                yield tags
                tags, have_line = {}, False
            m = _TAG.match(line)
            if m:
                tags[m.group(1)] = m.group(2)
        elif line.strip() and not have_line:
            tags["_line"] = line
            have_line = True
    if have_line:
        yield tags


def eval_cp(text):
    """Evaluation of an `[%eval ...]` annotation in centipawns from White's point of view (None when absent), clamped to +-1000."""
    m = _EVAL.search(text or "")
    if not m:
        return None
    v = m.group(1)
    cp = (-EVAL_CLAMP if v.startswith("#-") else EVAL_CLAMP) if v.startswith("#") else int(round(float(v) * 100))
    return max(-EVAL_CLAMP, min(EVAL_CLAMP, cp))


def clock_seconds(text):
    m = _CLK.search(text or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def parse_moves(line, max_ply):
    """([SAN...], [eval cp or None...], [clock seconds or None...], last full-move number) from a movetext line, for the first `max_ply` plies."""
    sans, evals, clocks = [], [], []
    for m in _SAN.finditer(line):                      # move numbers are skipped by the pattern itself: comments hold decimals such as 0.3
        if len(sans) >= max_ply:
            break
        sans.append(m.group(1))
        evals.append(eval_cp(m.group(2)))
        clocks.append(clock_seconds(m.group(2)))
    nums = _LAST_MOVE_NO.findall(_BRACES.sub(" ", line))          # comments hold decimals such as 0.1: they are not move numbers
    return sans, evals, clocks, int(nums[-1]) if nums else 0


def header_record(tags):
    """A compact record from the tags of `iter_games` (no movetext parsing), or None when the game cannot be used (no ratings or result)."""
    try:
        w, b = int(tags["WhiteElo"]), int(tags["BlackElo"])
        base, _, inc = tags.get("TimeControl", "0+0").partition("+")
        base, inc = int(base or 0), int(inc or 0)
    except (KeyError, ValueError):
        return None
    res = {"1-0": 1.0, "1/2-1/2": 0.5, "0-1": 0.0}.get(tags.get("Result"))
    if res is None or "_line" not in tags:
        return None
    return {"white": w, "black": b, "base": base, "inc": inc, "result": res, "termination": tags.get("Termination", ""), "line": tags["_line"]}


def speed_of(base, inc):
    """blitz / rapid / classical from the estimated duration base + 40 x increment (bullet is excluded earlier)."""
    t = base + 40 * inc
    return "blitz" if t < 480 else "rapid" if t < 1500 else "classical"


def band_of(game, edges, max_diff=300, min_base=180):
    """Band index for a game, or None: average rating inside a band, similar strength, no bullet, normal end."""
    if game["base"] < min_base or game["termination"] not in ("Normal", "Time forfeit") or abs(game["white"] - game["black"]) > max_diff:
        return None
    avg = (game["white"] + game["black"]) / 2
    for i in range(len(edges) - 1):
        if edges[i] <= avg < edges[i + 1]:
            return i
    return None


# ---- counting -----------------------------------------------------------------------------------------------------------

class Counts:
    """counts.tables[band][(pos_key << 16) | move16] = packed (games, White wins, draws, rating sum). Also, per band: evaluation sums of
    the annotated games, how long players think per ply, and game-level totals."""

    def __init__(self, n_bands):
        self.tables = [dict() for _ in range(n_bands)]
        self.evals = [dict() for _ in range(n_bands)]           # key -> [n, sum of eval cp (White's point of view)]
        self.clock = [dict() for _ in range(n_bands)]           # (speed, ply) -> [n, seconds spent, instant moves]
        self.stats = [{"games": 0, "white": 0, "draws": 0, "moves": 0, "analysed": 0} for _ in range(n_bands)]
        self.games = [0] * n_bands
        self.held_out = [[] for _ in range(n_bands)]
        self.scanned = 0
        self.hit_deadline = False
        self.config = None

    def size(self):
        return sum(len(t) for t in self.tables)

    def add_game(self, band, game, max_ply):
        """Count one game (a `header_record`): its moves, evaluations, clock use and totals. Returns the SAN moves read."""
        sans, evals, clocks, last_no = parse_moves(game["line"], max_ply)
        board = chess.Board()
        table, ev = self.tables[band], self.evals[band]
        inc = pack(game["result"], (game["white"] + game["black"]) / 2)
        analysed = False
        for ply, san in enumerate(sans):
            try:
                mv = board.parse_san(san)
            except ValueError:
                sans = sans[:ply]
                break
            k = (pos_key(board) << 16) | move16(mv)
            table[k] = table.get(k, 0) + inc
            if evals[ply] is not None:
                analysed = True
                e = ev.setdefault(k, [0, 0])
                e[0] += 1
                e[1] += evals[ply]
            board.push(mv)
        # clock use: time spent = own previous clock - own clock + increment (the first own move starts from the base time)
        sp = speed_of(game["base"], game["inc"])
        for ply in range(len(sans)):
            cur = clocks[ply]
            prev = clocks[ply - 2] if ply >= 2 else float(game["base"])
            if cur is not None and prev is not None:
                spent = max(0.0, prev - cur + game["inc"])
                c = self.clock[band].setdefault((sp, ply + 1), [0, 0.0, 0])
                c[0] += 1
                c[1] += spent
                c[2] += spent <= 1.0
        st = self.stats[band]
        st["games"] += 1
        st["white"] += game["result"] == 1.0
        st["draws"] += game["result"] == 0.5
        st["moves"] += last_no
        st["analysed"] += analysed
        self.games[band] += 1
        return sans

    def prune(self, max_entries):
        """Drop the rarest entries until the tables fit: singletons first, then pairs, ..."""
        threshold = 1
        while self.size() > max_entries and threshold < 50:
            for t, ev in zip(self.tables, self.evals):
                for k in [k for k, v in t.items() if (v & MASK24) <= threshold]:
                    del t[k]
                    ev.pop(k, None)
            threshold += 1
        return threshold - 1


def save_state(path, counts, games_scanned, config=None):
    """Atomic checkpoint (write, then rename): an interrupted write never damages the previous one."""
    tmp = Path(str(path) + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=1) as f:
        pickle.dump({"tables": counts.tables, "games": counts.games, "held_out": counts.held_out, "scanned": games_scanned,
                     "evals": counts.evals, "clock": counts.clock, "stats": counts.stats, "config": config}, f, protocol=4)
    tmp.replace(path)


def load_state(path):
    with gzip.open(path, "rb") as f:
        st = pickle.load(f)
    c = Counts(len(st["tables"]))
    c.tables, c.games, c.held_out, c.scanned = st["tables"], st["games"], st["held_out"], st["scanned"]
    c.evals, c.clock, c.stats = st["evals"], st["clock"], st["stats"]
    c.config = st.get("config")
    return c


def rss_gb():
    """Current resident memory of this process in GB (Linux /proc; elsewhere the peak from `resource`)."""
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1e6
    except OSError:
        pass
    import resource, sys
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1e9 if sys.platform == "darwin" else 1e6)


def count_stream(open_stream, counts, *, edges=DEFAULT_BANDS, max_ply=DEFAULT_MAX_PLY, sample_every=1, full_from=FULL_FROM, max_scan=None,
                 holdout=2000, max_entries=30_000_000, max_memory_gb=None, deadline=None, should_stop=None, checkpoint=None,
                 checkpoint_every=1_000_000, checkpoint_minutes=15, config=None, progress_every=100_000, log=print):
    """Read games from `open_stream()` (a callable returning a text stream; called again to reconnect), counting one of every `sample_every`
    games that qualifies, up to `max_scan` games scanned. `counts.scanned` makes it resumable: already scanned games are skipped."""
    t0 = last_ck = time.time()
    failures = 0
    while True:
        try:
            stream = open_stream()
            for i, tags in enumerate(iter_games(stream)):
                if i < counts.scanned:
                    continue                                       # fast-forward after a resume or a reconnect
                if max_scan and i >= max_scan:
                    return counts
                g = header_record(tags)
                band = band_of(g, edges) if g else None
                if band is not None and (sample_every <= 1 or edges[band] >= full_from or i % sample_every == 0):
                    if len(counts.held_out[band]) < holdout:
                        counts.held_out[band].append(parse_moves(g["line"], max_ply)[0])      # kept aside: never counted, used for coverage
                    else:
                        counts.add_game(band, g, max_ply)
                counts.scanned = i + 1                              # only now: a game is 'scanned' once it has been counted
                if counts.scanned % progress_every == 0:
                    if counts.size() > max_entries:
                        log(f"  pruning rare entries (limit {max_entries}): threshold {counts.prune(max_entries)}")
                    if max_memory_gb and rss_gb() > max_memory_gb:
                        log(f"  memory {rss_gb():.1f} GB is over the {max_memory_gb} GB limit: pruning rare entries (threshold {counts.prune(int(counts.size() * 0.6))})")
                    log(f"  scanned {counts.scanned:,} games, counted {sum(counts.games):,}, {counts.size():,} entries, {rss_gb():.1f} GB, {(time.time() - t0) / 60:.1f} min")
                if checkpoint and (counts.scanned % checkpoint_every == 0 or (checkpoint_minutes and time.time() - last_ck > checkpoint_minutes * 60)):
                    save_state(checkpoint, counts, counts.scanned, config)
                    last_ck = time.time()
                    log(f"  checkpoint saved at {counts.scanned:,} games")
                if (deadline and time.time() > deadline) or (should_stop and should_stop()):
                    log("time budget reached or stop requested: finishing with what has been counted")
                    counts.hit_deadline = True
                    return counts
            return counts                                            # the stream ended
        except (OSError, EOFError, ValueError) as e:
            failures += 1
            log(f"  stream error ({e!r}); reconnecting and skipping the {counts.scanned:,} games already scanned (attempt {failures})")
            if failures > 5:
                raise
            time.sleep(min(60, 5 * failures))


def check(open_stream, n_games=300, edges=DEFAULT_BANDS, max_ply=DEFAULT_MAX_PLY):
    """Read the first `n_games` of the stream and report what was found; raises when nothing usable was read. Fails in seconds if the
    URL, the decompression or the parser is broken."""
    seen = usable = plies = with_eval = with_clock = 0
    for tags in iter_games(open_stream()):
        seen += 1
        g = header_record(tags)
        if g and band_of(g, edges) is not None:
            usable += 1
            sans, evals, clocks, _ = parse_moves(g["line"], max_ply)
            plies += len(sans)
            with_eval += any(e is not None for e in evals)
            with_clock += any(c is not None for c in clocks)
        if seen >= n_games:
            break
    if not seen or not usable:
        raise RuntimeError(f"read {seen} games, {usable} usable: the source is not a Lichess PGN dump (or nothing qualifies)")
    return {"games": seen, "usable": usable, "avg_plies": plies / usable, "with_eval": with_eval, "with_clock": with_clock}


# ---- outputs ------------------------------------------------------------------------------------------------------------

def opening_names(tsv_dir):
    """[(pos_key of the position after the line, eco, name)] from the Lichess opening TSV files in a folder."""
    from . import theory as TH
    out = []
    for eco, name, moves in TH.load_lines(sorted(Path(tsv_dir).glob("*.tsv"))):
        board = chess.Board()
        for mv in moves:
            board.push(mv)
        out.append((signed64(pos_key(board)), eco, name))
    return out


def to_sqlite(counts, path, edges, *, min_games=20, meta=None, openings=()):
    """Write the explorer database: entries with at least `min_games` games per band, plus the per-band statistics, clock use and opening names."""
    path = Path(path)
    if path.exists():
        path.unlink()
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE bands(id INTEGER PRIMARY KEY, lo INTEGER, hi INTEGER, games INTEGER);
        CREATE TABLE moves(band INTEGER, pos INTEGER, move INTEGER, uci TEXT, games INTEGER, white INTEGER, draws INTEGER, black INTEGER,
                           rating_sum INTEGER, eval_n INTEGER, eval_sum INTEGER);
        CREATE TABLE band_stats(band INTEGER PRIMARY KEY, games INTEGER, white INTEGER, draws INTEGER, moves_sum INTEGER, analysed INTEGER);
        CREATE TABLE clock(band INTEGER, speed TEXT, ply INTEGER, n INTEGER, spent_sum REAL, instant INTEGER);
        CREATE TABLE openings(pos INTEGER, eco TEXT, name TEXT);
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);""")
    rows = 0
    for b, table in enumerate(counts.tables):
        db.execute("INSERT INTO bands VALUES (?,?,?,?)", (b, edges[b], edges[b + 1], counts.games[b]))
        st = counts.stats[b]
        db.execute("INSERT INTO band_stats VALUES (?,?,?,?,?,?)", (b, st["games"], st["white"], st["draws"], st["moves"], st["analysed"]))
        db.executemany("INSERT INTO clock VALUES (?,?,?,?,?,?)", [(b, sp, ply, n, s, i) for (sp, ply), (n, s, i) in counts.clock[b].items()])
        batch = []
        for k, v in table.items():
            g, w, d, bl = unpack(v)
            if g >= min_games:
                m = k & 0xFFFF
                en, es = counts.evals[b].get(k, (0, 0))
                batch.append((b, signed64(k >> 16), m, unmove16(m).uci(), g, w, d, bl, v >> 72, en, es))
        db.executemany("INSERT INTO moves VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch)
        rows += len(batch)
    db.executemany("INSERT INTO openings VALUES (?,?,?)", list(openings))
    db.execute("CREATE INDEX moves_by_position ON moves(band, pos)")
    db.execute("CREATE INDEX openings_by_position ON openings(pos)")
    for k, v in {**(meta or {}), "min_games": min_games, "rows": rows}.items():
        db.execute("INSERT INTO meta VALUES (?,?)", (str(k), str(v)))
    db.commit()
    db.close()
    return rows


def bar(white, draw, black, width=30):
    """The Lichess-style result bar as text: White wins '░', draws '▒', Black wins '█' (shares 0..1)."""
    w = round(white * width)
    d = round(draw * width)
    return "░" * w + "▒" * d + "█" * max(0, width - w - d)


def query(db_path, fen, rating=None, band=None):
    """Explorer rows for a position: [{"san", "uci", "games", "share", "white", "draw", "black", "avg_rating", "eval", "eval_n"}] most played
    first, for the band that contains `rating` (or `band` id); `eval` is the average evaluation after the move in pawns from White's point
    of view (None when no annotated game reached it)."""
    db = sqlite3.connect(db_path)
    if band is None:
        r = db.execute("SELECT id FROM bands WHERE lo <= ? AND ? < hi", (rating, rating)).fetchone()
        if r is None:
            r = db.execute("SELECT id FROM bands ORDER BY ABS((lo + hi) / 2 - ?) LIMIT 1", (rating or 1500,)).fetchone()
        band = r[0]
    board = chess.Board(fen)
    key = signed64(pos_key(board))
    rows = db.execute("SELECT uci, games, white, draws, black, rating_sum, eval_n, eval_sum FROM moves WHERE band=? AND pos=? ORDER BY games DESC",
                      (band, key)).fetchall()
    db.close()
    total = sum(r[1] for r in rows) or 1
    out = []
    for uci, g, w, d, b, rs, en, es in rows:
        mv = chess.Move.from_uci(uci)
        if mv in board.legal_moves:
            out.append({"san": board.san(mv), "uci": uci, "games": g, "share": g / total, "white": w / g, "draw": d / g, "black": b / g,
                        "avg_rating": rs / g, "eval": (es / en / 100.0) if en else None, "eval_n": en})
    return out


def opening_at(db_path, fen):
    """(eco, name) of the position if it ends a named opening line, else None."""
    db = sqlite3.connect(db_path)
    r = db.execute("SELECT eco, name FROM openings WHERE pos=? LIMIT 1", (signed64(pos_key(chess.Board(fen))),)).fetchone()
    db.close()
    return r


def format_rows(rows, top=10):
    """The explorer as text, one line per move: games, share, average rating, evaluation and the result bar."""
    lines = []
    for r in rows[:top]:
        ev = f"{r['eval']:+.2f}" if r["eval"] is not None else "  n/a"
        lines.append(f"{r['san']:7s} {r['games']:>10,d} {100 * r['share']:5.1f}%  avg {r['avg_rating']:4.0f}  eval {ev} (n={r['eval_n']:<5d}) "
                     f"{bar(r['white'], r['draw'], r['black'])}  {100 * r['white']:.0f}/{100 * r['draw']:.0f}/{100 * r['black']:.0f}")
    return "\n".join(lines)


def build_books(counts, edges, out_dir, *, max_ply=DEFAULT_MAX_PLY, min_games=50, min_share=0.03, eval_margin_cp=None, min_eval_n=30):
    """Walk each band's counts from the start position and write `theory_LO_HI.bin`: a move joins the book when at least `min_games` games
    play it and it is at least `min_share` of the games at that position. With `eval_margin_cp`, a move is also dropped when its average
    evaluation (over at least `min_eval_n` annotated games) is worse for the mover than the best sibling's by more than the margin.
    Returns {band: (entries, positions, moves dropped by the evaluation test)}."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = {}
    for b, table in enumerate(counts.tables):
        ev = counts.evals[b]
        entries, seen, dropped_eval = [], set(), 0
        stack = [(chess.Board(), 0)]
        while stack:
            board, ply = stack.pop()
            pk = pos_key(board)
            if pk in seen or ply >= max_ply:
                continue
            seen.add(pk)
            found = []
            for mv in board.legal_moves:
                k = (pk << 16) | move16(mv)
                v = table.get(k)
                if v:
                    found.append((mv, unpack(v), ev.get(k)))
            total = sum(x[1][0] for x in found)
            sign = 1 if board.turn == chess.WHITE else -1                     # eval is White's point of view; the mover wants it high
            scored = [sign * e[1] / e[0] for _, _, e in found if e and e[0] >= min_eval_n]
            best = max(scored) if scored else None
            for mv, (g, w, d, bl), e in found:
                if g < min_games or g / total < min_share:
                    continue
                if eval_margin_cp is not None and best is not None and e and e[0] >= min_eval_n and best - sign * e[1] / e[0] > eval_margin_cp:
                    dropped_eval += 1
                    continue
                mover_white = board.turn == chess.WHITE
                score = ((w + 0.5 * d) if mover_white else (bl + 0.5 * d)) / g
                entries.append(Entry(book_key(board), mv.from_square, mv.to_square, mv.promotion or 0, float(g), min(g, 65535), round(1000 * score)))
                nxt = board.copy()
                nxt.push(mv)
                stack.append((nxt, ply + 1))
        write_book(out / f"theory_{edges[b]}_{edges[b + 1]}.bin", entries)
        result[b] = (len(entries), len(seen), dropped_eval)
    return result


def coverage(counts, edges, book_dir, plies=(4, 8, 12, 16, 20, 24)):
    """On the held-out games of each band: the share still in the band's book after N plies."""
    from ..mechess.controller import BookReader
    out = {}
    for b in range(len(counts.tables)):
        f = Path(book_dir) / f"theory_{edges[b]}_{edges[b + 1]}.bin"
        if not f.exists() or not counts.held_out[b]:
            continue
        reader = BookReader(f)
        depth = []
        for moves in counts.held_out[b]:
            board, d = chess.Board(), 0
            for san in moves[: max(plies)]:
                try:
                    mv = board.parse_san(san)
                except ValueError:
                    break
                if mv not in {m for m, _ in reader.moves(board)}:
                    break
                board.push(mv)
                d += 1
            depth.append(d)
        out[b] = {p: sum(x >= p for x in depth) / len(depth) for p in plies}
    return out


def render_report(counts, edges, books, cov, meta):
    L = ["# Opening explorer built from the Lichess database", "",
         f"- Source: {meta.get('source', '?')}; {counts.scanned:,} games scanned, every {meta.get('sample_every', 1)}th looked at, kept when it qualifies "
         "(no bullet, normal ending, both players within 300 points of each other).",
         f"- First {meta.get('max_ply', '?')} plies; a book move needs at least {meta.get('book_min_games', '?')} games and {100 * meta.get('book_min_share', 0):.0f}% of the games at its position.", "",
         "## Books and coverage (held-out games, never counted)", "",
         "| band | games counted | book positions | book moves | share of games still in book after N plies |", "|---|---|---|---|---|"]
    for b in range(len(counts.tables)):
        n, pos, _ = books.get(b, (0, 0, 0))
        c = cov.get(b, {})
        L.append(f"| {edges[b]}-{edges[b + 1]} | {counts.games[b]:,} | {pos} | {n} | " + ", ".join(f"{p}: {100 * c[p]:.0f}%" for p in sorted(c)) + " |")
    L += ["", "## Population statistics per band", "", "| band | games | White wins | draws | Black wins | avg game length (moves) | games with engine evaluation |", "|---|---|---|---|---|---|---|"]
    for b, st in enumerate(counts.stats):
        g = st["games"] or 1
        L.append(f"| {edges[b]}-{edges[b + 1]} | {st['games']:,} | {100 * st['white'] / g:.1f}% | {100 * st['draws'] / g:.1f}% | "
                 f"{100 * (g - st['white'] - st['draws']) / g:.1f}% | {st['moves'] / g:.1f} | {100 * st['analysed'] / g:.1f}% |")
    L += ["", "## Time per move (mean seconds, blitz games; and how often a move is instant, at most 1 s)", "",
          "| band | ply 1-2 | ply 5-8 | ply 13-24 |", "|---|---|---|---|"]
    for b in range(len(counts.tables)):
        def cell(lo, hi):
            n = s = i = 0
            for (sp, ply), (cn, cs, ci) in counts.clock[b].items():
                if sp == "blitz" and lo <= ply <= hi:
                    n, s, i = n + cn, s + cs, i + ci
            return f"{s / n:.1f} s, {100 * i / n:.0f}% instant" if n else "n/a"
        L.append(f"| {edges[b]}-{edges[b + 1]} | {cell(1, 2)} | {cell(5, 8)} | {cell(13, 24)} |")
    return "\n".join(L) + "\n"


def rebuild(state_path, out_dir, *, db_min_games=20, book_min_games=50, book_min_share=0.03, eval_margin_cp=None, max_ply=None,
            openings_dir=None, log=print):
    """Rebuild explorer.db, the books and the report from a saved checkpoint with different thresholds, without reading the stream again.
    `max_ply` can only lower the book depth (the counts stop at the depth they were made with)."""
    counts = load_state(state_path)
    cfg = counts.config or {}
    edges = tuple(cfg.get("edges", DEFAULT_BANDS))
    depth = min(max_ply or cfg.get("max_ply", DEFAULT_MAX_PLY), cfg.get("max_ply", DEFAULT_MAX_PLY))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meta = {"source": cfg.get("source", "?"), "scanned": counts.scanned, "sample_every": cfg.get("sample_every", 1), "max_ply": depth,
            "book_min_games": book_min_games, "book_min_share": book_min_share}
    names = opening_names(openings_dir) if openings_dir and list(Path(openings_dir).glob("*.tsv")) else []
    rows = to_sqlite(counts, out / "explorer.db", edges, min_games=db_min_games, meta=meta, openings=names)
    books = build_books(counts, edges, out, max_ply=depth, min_games=book_min_games, min_share=book_min_share, eval_margin_cp=eval_margin_cp)
    cov = coverage(counts, edges, out)
    (out / "report.md").write_text(render_report(counts, edges, books, cov, meta))
    log(f"rebuilt from {counts.scanned:,} scanned games: explorer.db {rows:,} rows; books {books}")
    return {"db_rows": rows, "books": books, "coverage": cov}


def run(source, out_dir, *, edges=DEFAULT_BANDS, max_ply=DEFAULT_MAX_PLY, sample_every=4, max_scan=20_000_000, holdout=2000, db_min_games=20,
        book_min_games=50, book_min_share=0.03, eval_margin_cp=None, max_entries=30_000_000, max_memory_gb=16.0, max_minutes=None,
        checkpoint_every=1_000_000, checkpoint_minutes=15, resume=True, resume_glob=None, drop_state_when_finished=False, openings_dir=None,
        should_stop=None, full_from=FULL_FROM, progress_every=100_000, opener=None, log=print):
    """The whole flow. `resume_glob` (e.g. an earlier run's output mounted as an input) is searched for a checkpoint when this folder has none.
    Returns {"scanned", "counted", "db_rows", "books", "coverage", "finished"}. `opener()` returns the text stream (default: `open_dump(source)`)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ck = out / "state.pkl.gz"
    if resume and resume_glob and not ck.exists():
        found = sorted(glob.glob(resume_glob, recursive=True))
        if found:
            shutil.copy(found[0], ck)
            log(f"restored the checkpoint of an earlier run: {found[0]}")
    config = {"edges": list(edges), "max_ply": max_ply, "sample_every": sample_every, "full_from": full_from, "holdout": holdout,
              "source": str(source).rsplit("/", 1)[-1]}
    counts = load_state(ck) if resume and ck.exists() else Counts(len(edges) - 1)
    if counts.scanned:
        if counts.config is not None and counts.config != config:
            raise ValueError(f"the checkpoint {ck} was made with different settings ({counts.config}); use --fresh or another --out")
        log(f"resuming: {counts.scanned:,} games already scanned")
    deadline = time.time() + max_minutes * 60 if max_minutes else None
    count_stream(opener or (lambda: open_dump(source)), counts, edges=edges, max_ply=max_ply, sample_every=sample_every, full_from=full_from,
                 max_scan=max_scan, holdout=holdout, max_entries=max_entries, max_memory_gb=max_memory_gb, deadline=deadline, should_stop=should_stop,
                 checkpoint=ck, checkpoint_every=checkpoint_every, checkpoint_minutes=checkpoint_minutes, config=config, progress_every=progress_every, log=log)
    save_state(ck, counts, counts.scanned, config)
    meta = {"source": str(source).rsplit("/", 1)[-1], "scanned": counts.scanned, "sample_every": sample_every, "max_ply": max_ply,
            "book_min_games": book_min_games, "book_min_share": book_min_share}
    names = opening_names(openings_dir) if openings_dir and list(Path(openings_dir).glob("*.tsv")) else []
    rows = to_sqlite(counts, out / "explorer.db", edges, min_games=db_min_games, meta=meta, openings=names)
    books = build_books(counts, edges, out, max_ply=max_ply, min_games=book_min_games, min_share=book_min_share, eval_margin_cp=eval_margin_cp)
    cov = coverage(counts, edges, out)
    (out / "report.md").write_text(render_report(counts, edges, books, cov, meta))
    finished = not counts.hit_deadline
    if finished and drop_state_when_finished and not counts.hit_deadline:
        ck.unlink()                                       # a complete run needs no checkpoint; a stopped one keeps it for resuming
    log(f"explorer.db: {rows:,} rows; {len(names)} opening names; books: {books}")
    res = {"scanned": counts.scanned, "counted": sum(counts.games), "db_rows": rows, "books": books, "coverage": cov, "finished": finished}
    log(str(res))
    return res
