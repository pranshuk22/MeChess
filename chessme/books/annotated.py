"""Annotated games (plan 8n): the ChessGPT/ChessCLIP "free" annotated-PGN archive (GameKnot, PGN Library, Path to Chess Mastery,
Lichess studies), read as a stream so the archive never has to be unpacked.

For every move that carries a human comment or a glyph (! ? !! ?? !? ?!) we keep the position before the move, the move, the
glyph, the comment and the concepts the comment mentions. That is the material for (1) a classifier trained on human move
judgements, (2) concept detectors checked against what annotators say, (3) explanation text.

Terms: the archive's data card says each source keeps its own terms ("annotated PGNs: various sources"). Use it for research and
learning, do not redistribute the games or comments; the outputs stay local (git-ignored). Annotator names in Lichess studies are
never stored."""
import gzip
import io
import json
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


def annotated_moves(game):
    """Mainline moves that have a comment or a glyph: [{"ply", "color", "fen", "uci", "san", "nags", "glyph", "eval", "comment",
    "concepts", "text_nags"}]. `fen` is the position before the move; `nags` are all its glyph numbers, `glyph` the move judgement
    (! ? !! ?? !? ?!), `eval` the position evaluation symbol; `text_nags` are glyphs written inside the comment (`Nf3!`, `±`).
    Variations are ignored; a comment before the first move is returned as ply 0. Figurine pieces in comments become letters."""
    out = []
    board = game.board()
    if game.comment.strip():
        c0 = GL.normalise_figurines(game.comment.strip())
        out.append({"ply": 0, "color": None, "fen": board.fen(), "uci": None, "san": None, "nags": [], "glyph": None, "eval": None,
                    "comment": c0, "concepts": T.concept_counts(c0), "text_nags": GL.symbols_in(c0)})
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
                        "text_nags": GL.symbols_in(comment)})
        board.push(move)
    return out


def extract(archive, out_dir, *, sources=SOURCES, limit_per_source=None, max_comment=600, extra_pgn_dir=None, ctl=None, log=print):
    """Write `annotated_moves.jsonl.gz` (one record per annotated move, plus source and game index) and return the statistics:
    games and annotated moves per source, glyph counts, share of moves with comments, concept mentions."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stats = {"games": {}, "annotated_moves": {}, "glyphs": {}, "nags": {}, "text_nags": {}, "with_comment": 0, "with_glyph": 0, "concepts": {}}
    path = out / "annotated_moves.jsonl.gz"
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        games = iter_games(archive, sources, limit_per_source) if archive else iter([])
        if extra_pgn_dir:
            import itertools
            games = itertools.chain(games, iter_pgn_files(extra_pgn_dir, limit=limit_per_source))
        for n, (source, game) in enumerate(games, 1):
            if ctl and n % 200 == 0:
                ctl.checkpoint()
            stats["games"][source] = stats["games"].get(source, 0) + 1
            gi = stats["games"][source]
            for m in annotated_moves(game):
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
