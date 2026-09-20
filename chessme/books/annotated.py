"""Annotated games (plan 8n): the ChessGPT/ChessCLIP "free" annotated-PGN archive (GameKnot, PGN Library, Path to Chess Mastery,
Lichess studies), read as a stream so the archive never has to be unpacked.

For every move that carries a human comment or a glyph (! ? !! ?? !? ?!) we keep the position before the move, the move, the
glyph, the comment and the concepts the comment mentions. That is the material for (1) a classifier trained on human move
judgements, (2) concept detectors checked against what annotators say, (3) explanation text.

Terms: the archive's data card says each source keeps its own terms ("annotated PGNs: various sources"). Use it for research and
learning, do not redistribute the games or comments; the outputs stay local (git-ignored). Annotator names in Lichess studies are
never stored."""
import csv
import gzip
import io
import json
import logging
import tarfile
import urllib.request
from pathlib import Path

import chess
import chess.pgn

from . import glyphs as GL
from . import text as T
from .fetch import UA

URL = "https://huggingface.co/datasets/Waterhorse/chess_data/resolve/main/chessclip_data/annotated_pgn/annotated_pgn_free.tar.gz"
ARCHIVE = "annotated_pgn_free.tar.gz"
# Icannos/chess_studies on Hugging Face (CC0-1.0): annotated Lichess studies and other annotated games, one PGN chapter per CSV row
CSV_BASE = "https://huggingface.co/datasets/Icannos/chess_studies/resolve/main/"
CSV_FILES = {"chess_studies_lichess": "lichess_studies.csv", "chess_studies_others": "others.csv"}
SOURCES = ("gameknot", "pgnlib", "pathtochessmastery", "lichess_studies")


def download(out_dir, url=URL, opener=None):
    """Fetch the archive once (about 58 MB); an existing file with the right size is kept. Returns its path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / ARCHIVE
    opener = opener or (lambda u: urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120))
    if path.exists() and path.stat().st_size > 1_000_000:
        return path
    tmp = path.with_suffix(".part")
    with opener(url) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(path)
    return path


def download_csv(out_dir, opener=None):
    """Fetch the two CSV files of the CC0 studies dataset (about 11 MB together); returns {source: path}."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    opener = opener or (lambda u: urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120))
    paths = {}
    for source, name in CSV_FILES.items():
        path = out / name
        if not (path.exists() and path.stat().st_size > 100_000):
            tmp = path.with_suffix(".part")
            with opener(CSV_BASE + name) as r, open(tmp, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            tmp.replace(path)
        paths[source] = path
    return paths


def iter_csv_games(paths, limit_per_source=None):
    """Yield (source, game) from CSV files whose `text` column holds one PGN game per row."""
    csv.field_size_limit(1 << 30)
    for source, path in paths.items():
        n = 0
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            for row in csv.DictReader(f):
                if limit_per_source and n >= limit_per_source:
                    break
                try:
                    game = chess.pgn.read_game(io.StringIO(row.get("text", "")))
                except Exception:
                    continue
                if game is not None:
                    n += 1
                    yield source, game


def iter_games(archive, sources=SOURCES, limit_per_source=None):
    """Yield (source, chess.pgn.Game) from the archive (a .tar.gz path), source by source, `limit_per_source` games at most each."""
    counts = {}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if not member.isfile() or not member.name.lower().endswith(".pgn"):
                continue
            parts = member.name.strip("./").split("/")
            source = parts[0]
            if source not in sources or (limit_per_source and counts.get(source, 0) >= limit_per_source):
                continue
            stream = io.TextIOWrapper(tar.extractfile(member), encoding="utf-8", errors="replace")
            while limit_per_source is None or counts.get(source, 0) < limit_per_source:
                try:
                    game = chess.pgn.read_game(stream)
                except Exception:
                    break
                if game is None:
                    break
                counts[source] = counts.get(source, 0) + 1
                yield source, game


def iter_pgn_files(directory, source="lichess_api", limit=None):
    """Yield (source, game) from every .pgn file in a folder (for example studies exported through the Lichess API)."""
    n = 0
    for f in sorted(Path(directory).glob("*.pgn")):
        with open(f, encoding="utf-8", errors="replace") as stream:
            while limit is None or n < limit:
                try:
                    game = chess.pgn.read_game(stream)
                except Exception:
                    break
                if game is None:
                    break
                n += 1
                yield source, game


def annotated_moves(game, openings=None):
    """Mainline moves that have a comment or a glyph: [{"ply", "color", "fen", "uci", "san", "nags", "glyph", "eval", "comment",
    "concepts", "text_nags"}]. `fen` is the position before the move; `nags` are all its glyph numbers, `glyph` the move judgement
    (! ? !! ?? !? ?!), `eval` the position evaluation symbol; `text_nags` are glyphs written inside the comment (`Nf3!`, `±`).
    Variations are ignored; a comment before the first move is returned as ply 0. Figurine pieces in comments become letters.
    With an `openings` table ({epd: name}) each record also carries the `opening` the position before the move belongs to."""
    out = []
    board = game.board()
    if game.comment.strip():
        c0 = GL.normalise_figurines(game.comment.strip())
        out.append({"ply": 0, "color": None, "fen": board.fen(), "uci": None, "san": None, "nags": [], "glyph": None, "eval": None,
                    "comment": c0, "concepts": T.concept_counts(c0), "text_nags": GL.symbols_in(c0), "opening": None})
    node, ply = game, 0
    while node.variations:
        node = node.variations[0]
        ply += 1
        move = node.move
        try:
            san = board.san(move)
        except ValueError:
            break                                                   # the game record is broken from here on
        nags = sorted(node.nags)
        glyph = next((GL.symbol(n) for n in nags if GL.info(n)[2] == "judgement" and GL.symbol(n)), None)
        ev = next((GL.symbol(n) for n in nags if GL.info(n)[2] == "evaluation"), None)
        comment = GL.normalise_figurines(" ".join(node.comment.split()))
        if comment or nags:
            out.append({"ply": ply, "color": "white" if board.turn == chess.WHITE else "black", "fen": board.fen(), "uci": move.uci(),
                        "san": san, "nags": nags, "glyph": glyph, "eval": ev, "comment": comment, "concepts": T.concept_counts(comment),
                        "text_nags": GL.symbols_in(comment), "opening": openings.get(board.epd()) if openings else None})
        board.push(move)
    return out


def extract(archive, out_dir, *, sources=SOURCES, limit_per_source=None, max_comment=600, extra_pgn_dir=None, csv_paths=None,
            openings=None, extra_iters=(), ctl=None, log=print):
    """Write `annotated_moves.jsonl.gz` (one record per annotated move, plus source and game index) and return the statistics:
    games and annotated moves per source, glyph counts, share of moves with comments, concept mentions."""
    logging.getLogger("chess.pgn").setLevel(logging.CRITICAL)      # broken game records are skipped, not reported one by one
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stats = {"games": {}, "annotated_moves": {}, "glyphs": {}, "nags": {}, "text_nags": {}, "with_comment": 0, "with_glyph": 0, "concepts": {}}
    path = out / "annotated_moves.jsonl.gz"
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        games = iter_games(archive, sources, limit_per_source) if archive else iter([])
        import itertools
        if extra_pgn_dir:
            games = itertools.chain(games, iter_pgn_files(extra_pgn_dir, limit=limit_per_source))
        if csv_paths:
            games = itertools.chain(games, iter_csv_games(csv_paths, limit_per_source))
        for extra in extra_iters:
            games = itertools.chain(games, extra)
        seen_studies = set()
        for n, (source, game) in enumerate(games, 1):
            site = game.headers.get("Site", "")
            if "lichess.org/study/" in site:
                if site in seen_studies:                     # the same study chapter can sit in two of the sources
                    stats["duplicates"] = stats.get("duplicates", 0) + 1
                    continue
                seen_studies.add(site)
            if ctl and n % 200 == 0:
                ctl.checkpoint()
            stats["games"][source] = stats["games"].get(source, 0) + 1
            gi = stats["games"][source]
            for m in annotated_moves(game, openings):
                m = {**m, "comment": m["comment"][:max_comment], "source": source, "game": gi}
                fh.write(json.dumps(m) + "\n")
                stats["annotated_moves"][source] = stats["annotated_moves"].get(source, 0) + 1
                stats["with_comment"] += bool(m["comment"])
                if m["glyph"]:
                    stats["with_glyph"] += 1
                    stats["glyphs"][m["glyph"]] = stats["glyphs"].get(m["glyph"], 0) + 1
                for n in m["nags"]:
                    stats["nags"][str(n)] = stats["nags"].get(str(n), 0) + 1
                for n in m["text_nags"]:
                    stats["text_nags"][str(n)] = stats["text_nags"].get(str(n), 0) + 1
                for k in m["concepts"]:
                    stats["concepts"][k] = stats["concepts"].get(k, 0) + 1
            if n % 2000 == 0:
                log(f"  {n} games read")
    tmp.replace(path)
    return stats
