"""Optional engine check: drop book moves that lose material or worse compared with the engine's best move."""
from dataclasses import dataclass

import chess

from .format import Entry

MATE_CP = 10000


def cp_of(kind, score):
    if kind is None or score is None:
        return None
    if kind == "cp":
        return score
    return (MATE_CP - abs(score)) * (1 if score > 0 else -1)


@dataclass
class Dropped:
    fen: str
    move: str
    loss_cp: int


def sanity_filter(tree, entries, engine, depth=10, max_cp_loss=80):
    """Return (kept entries, dropped list). `engine` is a started UciEngine (or anything with go/new_game).

    For each book position we search the position (the engine's best score) and the position after each book
    move; a move that scores more than `max_cp_loss` centipawns below the best is dropped. Positions whose
    scores cannot be determined are left alone.
    """
    by_key = {}
    for e in entries:
        by_key.setdefault(e.key, []).append(e)
    kept, dropped = [], []
    for key, cands in by_key.items():
        fen = tree.mine[key].fen
        engine.new_game()
        r = engine.go(fen, depth=depth)
        best = cp_of(r.score_kind, r.score)
        if best is None:
            kept.extend(cands)
            continue
        for e in cands:
            engine.new_game()
            child = engine.go(fen, [e.uci()], depth=depth)
            after = cp_of(child.score_kind, child.score)
            after = None if after is None else -after  # the child's score is from the opponent's point of view
            if after is not None and best - after > max_cp_loss:
                dropped.append(Dropped(fen, e.uci(), best - after))
            else:
                kept.append(e)
    return kept, dropped
