"""An opening explorer built from the Lichess game database (CC0), one pass over a stream, no download of the whole file.

For every rating band, every position of the first `max_ply` plies and every move played there: how many games, and how they ended
(White / draw / Black). From those counts we write

  explorer.db          SQLite: the explorer (query by position and rating, like the Lichess opening explorer)
  theory_LO_HI.bin     one playable book per band (`book.bin` format; the controller and `mechess --book DIR` read it)
  report.md            how deep each book carries games it has never seen (held-out games)

Design points: positions are keyed by a 64-bit hash of "placement turn castling" (transpositions merge), so no FEN is stored;
the counts of one entry (games, White wins, draws) are packed into one integer; memory is bounded by `max_entries` (rare entries are
dropped first); a checkpoint lets a stopped run continue; the stream is re-opened and fast-forwarded if the connection drops."""
import gzip
import hashlib
import io
import pickle
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

import chess

from .format import Entry, write_book
from .keys import book_key, key_text

UA = {"User-Agent": "MeChess-opening-explorer (research; CC0 Lichess database)"}
DEFAULT_BANDS = (600, 1000, 1400, 1800, 2200, 3300)          # the 2200+ band is one: games above 2600 are too rare for a band of their own
MASK24 = (1 << 24) - 1
_COMMENT = re.compile(r"\{[^}]*\}|\([^)]*\)|\$\d+")
_MOVENUM = re.compile(r"\d+\.+")
_TAG = re.compile(r'\[(\w+) "([^"]*)"\]')


# ---- keys and packed counts ----------------------------------------------------------------------------------------------

def pos_key(board):
    """64-bit key of a position (placement, side to move, castling: transpositions merge)."""
    return int.from_bytes(hashlib.blake2b(key_text(board).encode(), digest_size=8).digest(), "big")


def move16(move):
    return move.from_square | (move.to_square << 6) | ((move.promotion or 0) << 12)


def unmove16(m):
    return chess.Move(m & 63, (m >> 6) & 63, (m >> 12) or None)


def pack(result_white):
    """One game's contribution: 1 game, +1 White win in bits 24.., +1 draw in bits 48.."""
    return 1 + ((1 << 24) if result_white == 1.0 else 0) + ((1 << 48) if result_white == 0.5 else 0)


def unpack(v):
    g, w, d = v & MASK24, (v >> 24) & MASK24, (v >> 48) & MASK24
    return g, w, d, g - w - d


def signed64(k):
    return k - (1 << 64) if k >= (1 << 63) else k


# ---- reading games -------------------------------------------------------------------------------------------------------

def open_dump(source, skip_bytes=0):
    """A text stream of a PGN dump: a path or URL, `.zst` or plain. (`skip_bytes` is not used: resuming fast-forwards by games.)"""
    if str(source).startswith("http"):
        raw = urllib.request.urlopen(urllib.request.Request(source, headers=UA), timeout=120)
    else:
        raw = open(source, "rb")
    if str(source).endswith(".zst"):
        import zstandard
        raw = zstandard.ZstdDecompressor().stream_reader(raw)
    return io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="\n")


def iter_games(stream, max_ply=16):
    """Yield {"white", "black", "base", "result", "termination", "moves": [SAN...]} for every game of a PGN text stream. Only the first
    `max_ply` moves are read (the rest of the movetext is skipped without parsing)."""
    tags, moves_done = {}, False
    for line in stream:
        if line.startswith("["):
            if moves_done:                                   # a new game began
                yield tags
                tags, moves_done = {}, False
            m = _TAG.match(line)
            if m:
                tags[m.group(1)] = m.group(2)
        elif line.strip() and not moves_done:
            text = _MOVENUM.sub(" ", _COMMENT.sub(" ", line))
            toks = [t for t in text.split() if t not in ("1-0", "0-1", "1/2-1/2", "*")]
            tags["_moves"] = toks[:max_ply]
            moves_done = True
    if moves_done:
        yield tags


def normalise(tags):
    """A compact game record from the tags of `iter_games`, or None when the game does not qualify (no ratings, no result...)."""
    try:
        w, b = int(tags["WhiteElo"]), int(tags["BlackElo"])
        base = int(tags.get("TimeControl", "0+0").split("+")[0] or 0)
    except (KeyError, ValueError):
        return None
    res = {"1-0": 1.0, "1/2-1/2": 0.5, "0-1": 0.0}.get(tags.get("Result"))
    if res is None or not tags.get("_moves"):
        return None
    return {"white": w, "black": b, "base": base, "result": res, "termination": tags.get("Termination", ""), "moves": tags["_moves"]}


def band_of(game, edges, max_diff=300, min_base=180):
    """Band index for a game, or None: both players inside a common band region (average rating), similar strength, no bullet, normal end."""
    if game["base"] < min_base or game["termination"] not in ("Normal", "Time forfeit") or abs(game["white"] - game["black"]) > max_diff:
        return None
    avg = (game["white"] + game["black"]) / 2
    for i in range(len(edges) - 1):
        if edges[i] <= avg < edges[i + 1]:
            return i
    return None


# ---- counting -----------------------------------------------------------------------------------------------------------

class Counts:
    """counts[band][(pos_key << 16) | move16] = packed (games, White wins, draws)."""

    def __init__(self, n_bands):
        self.tables = [dict() for _ in range(n_bands)]
        self.games = [0] * n_bands
        self.held_out = [[] for _ in range(n_bands)]
        self.scanned = 0
        self.hit_deadline = False

    def size(self):
        return sum(len(t) for t in self.tables)

    def add_game(self, band, san_moves, result, max_ply):
        board = chess.Board()
        table = self.tables[band]
        inc = pack(result)
        for san in san_moves[:max_ply]:
            try:
                mv = board.parse_san(san)
            except ValueError:
                break
            k = (pos_key(board) << 16) | move16(mv)
            table[k] = table.get(k, 0) + inc
            board.push(mv)
        self.games[band] += 1

    def prune(self, max_entries):
        """Drop the rarest entries until the tables fit: singletons first, then pairs, ..."""
        threshold = 1
        while self.size() > max_entries and threshold < 50:
            for t in self.tables:
                for k in [k for k, v in t.items() if (v & MASK24) <= threshold]:
                    del t[k]
            threshold += 1
        return threshold - 1


def save_state(path, counts, games_scanned):
    tmp = Path(str(path) + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=1) as f:
        pickle.dump({"tables": counts.tables, "games": counts.games, "held_out": counts.held_out, "scanned": games_scanned}, f, protocol=4)
    tmp.replace(path)


def load_state(path):
    with gzip.open(path, "rb") as f:
        st = pickle.load(f)
    c = Counts(len(st["tables"]))
    c.tables, c.games, c.held_out, c.scanned = st["tables"], st["games"], st["held_out"], st["scanned"]
    return c


def count_stream(open_stream, counts, *, edges=DEFAULT_BANDS, max_ply=16, sample_every=1, max_scan=None, holdout=2000, max_entries=30_000_000,
                 deadline=None, checkpoint=None, checkpoint_every=1_000_000, log=print):
    """Read games from `open_stream()` (a callable returning a text stream; called again to reconnect), counting one of every `sample_every`
    games that qualifies, up to `max_scan` games scanned. `counts.scanned` makes it resumable: already scanned games are skipped."""
    t0 = time.time()
    failures = 0
    while True:
        try:
            stream = open_stream()
            for i, tags in enumerate(iter_games(stream, max_ply)):
                if i < counts.scanned:
                    continue                                       # fast-forward after a resume or a reconnect
                if max_scan and i >= max_scan:
                    return counts
                if not (sample_every > 1 and i % sample_every):
                    g = normalise(tags)
                    band = band_of(g, edges) if g else None
                    if band is not None:
                        if len(counts.held_out[band]) < holdout:
                            counts.held_out[band].append(g["moves"])      # kept aside: never counted, used to measure coverage
                        else:
                            counts.add_game(band, g["moves"], g["result"], max_ply)
                counts.scanned = i + 1                              # only now: a game is 'scanned' once it has been counted
                if counts.scanned % 100_000 == 0:
                    if counts.size() > max_entries:
                        log(f"  pruning rare entries (limit {max_entries}): threshold {counts.prune(max_entries)}")
                    log(f"  scanned {counts.scanned:,} games, counted {sum(counts.games):,}, {counts.size():,} entries, {(time.time() - t0) / 60:.1f} min")
                if checkpoint and counts.scanned % checkpoint_every == 0:
                    save_state(checkpoint, counts, counts.scanned)
                if deadline and time.time() > deadline:
                    log("time budget reached: finishing with what has been counted")
                    counts.hit_deadline = True
                    return counts
            return counts                                            # the stream ended
        except (OSError, EOFError, ValueError) as e:
            failures += 1
            log(f"  stream error ({e!r}); reconnecting and skipping the {counts.scanned:,} games already scanned (attempt {failures})")
            if failures > 5:
                raise
            time.sleep(min(60, 5 * failures))


# ---- outputs ------------------------------------------------------------------------------------------------------------

def to_sqlite(counts, path, edges, *, min_games=20, meta=None):
    """Write the explorer database: entries with at least `min_games` games per band."""
    path = Path(path)
    if path.exists():
        path.unlink()
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE bands(id INTEGER PRIMARY KEY, lo INTEGER, hi INTEGER, games INTEGER);
                        CREATE TABLE moves(band INTEGER, pos INTEGER, move INTEGER, uci TEXT, games INTEGER, white INTEGER, draws INTEGER, black INTEGER);
                        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);""")
    rows = 0
    for b, table in enumerate(counts.tables):
        db.execute("INSERT INTO bands VALUES (?,?,?,?)", (b, edges[b], edges[b + 1], counts.games[b]))
        batch = []
        for k, v in table.items():
            g, w, d, bl = unpack(v)
            if g >= min_games:
                m = k & 0xFFFF
                batch.append((b, signed64(k >> 16), m, unmove16(m).uci(), g, w, d, bl))
        db.executemany("INSERT INTO moves VALUES (?,?,?,?,?,?,?,?)", batch)
        rows += len(batch)
    db.execute("CREATE INDEX moves_by_position ON moves(band, pos)")
    for k, v in {**(meta or {}), "min_games": min_games, "rows": rows}.items():
        db.execute("INSERT INTO meta VALUES (?,?)", (str(k), str(v)))
    db.commit()
    db.close()
    return rows


def query(db_path, fen, rating=None, band=None):
    """Explorer rows for a position: [{"san", "uci", "games", "share", "white", "draw", "black"}] most played first, for the band that
    contains `rating` (or `band` id)."""
    db = sqlite3.connect(db_path)
    if band is None:
        r = db.execute("SELECT id FROM bands WHERE lo <= ? AND ? < hi", (rating, rating)).fetchone()
        if r is None:
            r = db.execute("SELECT id FROM bands ORDER BY ABS((lo + hi) / 2 - ?) LIMIT 1", (rating or 1500,)).fetchone()
        band = r[0]
    board = chess.Board(fen)
    key = signed64(pos_key(board))
    rows = db.execute("SELECT uci, games, white, draws, black FROM moves WHERE band=? AND pos=? ORDER BY games DESC", (band, key)).fetchall()
    db.close()
    total = sum(r[1] for r in rows) or 1
    out = []
    for uci, g, w, d, b in rows:
        mv = chess.Move.from_uci(uci)
        if mv in board.legal_moves:
            out.append({"san": board.san(mv), "uci": uci, "games": g, "share": g / total, "white": w / g, "draw": d / g, "black": b / g})
    return out


def build_books(counts, edges, out_dir, *, max_ply=16, min_games=50, min_share=0.03):
    """Walk each band's counts from the start position and write `theory_LO_HI.bin`: a move joins the book when at least `min_games`
    games play it and it is at least `min_share` of the games at that position. Returns {band: (entries, positions)}."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = {}
    for b, table in enumerate(counts.tables):
        entries, seen = [], set()
        stack = [(chess.Board(), 0)]
        while stack:
            board, ply = stack.pop()
            pk = pos_key(board)
            if pk in seen or ply >= max_ply:
                continue
            seen.add(pk)
            found = []
            for mv in board.legal_moves:
                v = table.get((pk << 16) | move16(mv))
                if v:
                    found.append((mv, unpack(v)))
            total = sum(x[1][0] for x in found)
            for mv, (g, w, d, bl) in found:
                if g >= min_games and g / total >= min_share:
                    mover_white = board.turn == chess.WHITE
                    score = ((w + 0.5 * d) if mover_white else (bl + 0.5 * d)) / g
                    entries.append(Entry(book_key(board), mv.from_square, mv.to_square, mv.promotion or 0, float(g), min(g, 65535), round(1000 * score)))
                    nxt = board.copy()
                    nxt.push(mv)
                    stack.append((nxt, ply + 1))
        write_book(out / f"theory_{edges[b]}_{edges[b + 1]}.bin", entries)
        result[b] = (len(entries), len(seen))
    return result


def coverage(counts, edges, book_dir, plies=(4, 8, 12, 16)):
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
         f"- Source: {meta.get('source', '?')}; {counts.scanned:,} games scanned, every {meta.get('sample_every', 1)}th kept when it qualifies "
         "(no bullet, normal ending, both players within 300 points of each other).",
         f"- First {meta.get('max_ply', '?')} plies; a book move needs at least {meta.get('book_min_games', '?')} games and {100 * meta.get('book_min_share', 0):.0f}% of the games at its position.", "",
         "| band | games counted | book positions | book moves | in book after 4 / 8 / 12 / 16 plies (held-out games) |", "|---|---|---|---|---|"]
    for b in range(len(counts.tables)):
        n, pos = books.get(b, (0, 0))
        c = cov.get(b, {})
        L.append(f"| {edges[b]}-{edges[b + 1]} | {counts.games[b]:,} | {pos} | {n} | " + " / ".join(f"{100 * c[p]:.0f}%" for p in sorted(c)) + " |")
    return "\n".join(L) + "\n"


def run(source, out_dir, *, edges=DEFAULT_BANDS, max_ply=16, sample_every=4, max_scan=12_000_000, holdout=2000, db_min_games=20, book_min_games=50,
        book_min_share=0.03, max_entries=30_000_000, max_minutes=None, checkpoint_every=1_000_000, resume=True, opener=None, log=print):
    """The whole flow. Returns {"scanned", "counted", "db_rows", "books"}. `opener()` returns the text stream (default: `open_dump(source)`)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ck = out / "state.pkl.gz"
    counts = load_state(ck) if resume and ck.exists() else Counts(len(edges) - 1)
    if counts.scanned:
        log(f"resuming: {counts.scanned:,} games already scanned")
    deadline = time.time() + max_minutes * 60 if max_minutes else None
    count_stream(opener or (lambda: open_dump(source)), counts, edges=edges, max_ply=max_ply, sample_every=sample_every, max_scan=max_scan,
                 holdout=holdout, max_entries=max_entries, deadline=deadline, checkpoint=ck, checkpoint_every=checkpoint_every, log=log)
    save_state(ck, counts, counts.scanned)
    meta = {"source": str(source).rsplit("/", 1)[-1], "scanned": counts.scanned, "sample_every": sample_every, "max_ply": max_ply,
            "book_min_games": book_min_games, "book_min_share": book_min_share}
    rows = to_sqlite(counts, out / "explorer.db", edges, min_games=db_min_games, meta=meta)
    books = build_books(counts, edges, out, max_ply=max_ply, min_games=book_min_games, min_share=book_min_share)
    cov = coverage(counts, edges, out)
    (out / "report.md").write_text(render_report(counts, edges, books, cov, meta))
    log(f"explorer.db: {rows:,} rows; books: {books}")
    return {"scanned": counts.scanned, "counted": sum(counts.games), "db_rows": rows, "books": books, "coverage": cov,
            "finished": not counts.hit_deadline}


def check(open_stream, n_games=300, edges=DEFAULT_BANDS, max_ply=16):
    """Read the first `n_games` of the stream and report what was found; raises when nothing usable was read. Fails in seconds if the
    URL, the decompression or the parser is broken."""
    stream = open_stream()
    seen = usable = plies = 0
    for tags in iter_games(stream, max_ply):
        seen += 1
        g = normalise(tags)
        if g and band_of(g, edges) is not None:
            usable += 1
            plies += len(g["moves"])
        if seen >= n_games:
            break
    if not seen or not usable:
        raise RuntimeError(f"read {seen} games, {usable} usable: the source is not a Lichess PGN dump (or nothing qualifies)")
    return {"games": seen, "usable": usable, "avg_plies": plies / usable}
