"""The name of an opening from the moves of a game: the longest named line (Lichess chess-openings dataset, CC0, packed in `opening_names.tsv.gz`) that the game's first moves
follow. Used when a game does not come with an opening name (Chess.com PGNs, files, games played here), and by the coach's opening library."""
import functools
import gzip
from pathlib import Path

DATA = Path(__file__).with_name("opening_names.tsv.gz")
MAX_PLIES = 40


@functools.lru_cache(maxsize=1)
def table() -> dict[tuple[str, ...], tuple[str, str]]:
    """{moves in UCI: (eco, name)}; empty when the data file is missing."""
    out: dict[tuple[str, ...], tuple[str, str]] = {}
    if not DATA.is_file():
        return out
    with gzip.open(DATA, "rt", encoding="utf-8") as f:
        next(f, None)
        for line in f:
            eco, name, moves = line.rstrip("\n").split("\t")
            out[tuple(moves.split())] = (eco, name)
    return out


def name_for(uci_moves, max_plies=MAX_PLIES) -> tuple[str, str] | None:
    """(eco, name) of the longest named line that is a prefix of `uci_moves`, or None."""
    t = table()
    moves = tuple(uci_moves[:max_plies])
    for n in range(len(moves), 0, -1):
        hit = t.get(moves[:n])
        if hit:
            return hit
    return None


def lines(prefix: str | None = None) -> list[tuple[str, str, tuple[str, ...]]]:
    """[(eco, name, moves)] of all named lines, optionally only those whose name starts with `prefix`."""
    return [(eco, name, moves) for moves, (eco, name) in table().items() if not prefix or name.startswith(prefix)]
