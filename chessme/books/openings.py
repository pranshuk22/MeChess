"""Opening names from the Lichess chess-openings dataset (CC0): {position (EPD): (ECO, name)}. Gives every annotated position its opening
and, later, the 'book move' test of the move classifier."""
import urllib.request
from pathlib import Path

import chess

from .fetch import UA

BASE = "https://raw.githubusercontent.com/lichess-org/chess-openings/master/"
FILES = ("a.tsv", "b.tsv", "c.tsv", "d.tsv", "e.tsv")


def download(out_dir, opener=None):
    """The five TSV files (about 200 KB together); returns their paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    opener = opener or (lambda u: urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read())
    paths = []
    for name in FILES:
        path = out / name
        if not path.exists() or path.stat().st_size < 100:
            path.write_bytes(opener(BASE + name))
        paths.append(path)
    return paths


def load(paths):
    """{epd: name} from the TSV files (columns eco, name, pgn); the deepest named line wins when two share a position."""
    table = {}
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            eco, name, pgn = parts[:3]
            board = chess.Board()
            try:
                for tok in pgn.split():
                    if tok[0].isdigit():
                        continue
                    board.push_san(tok)
            except ValueError:
                continue
            table[board.epd()] = f"{eco} {name}"
    return table
