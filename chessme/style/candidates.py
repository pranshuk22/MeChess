"""Choice-level style data: for each position, the engine-approved candidate moves, their style features, and which
one the player actually chose.

A position contributes to the style fit only when the played move is itself a candidate (within `window` centipawns of
the engine's best): otherwise the player did not *choose among good moves*, they made a mistake, which is a different
question (the blunder model). Such positions are still counted so the mistake rate can be reported.
"""
import os
from dataclasses import dataclass

import chess
import numpy as np

from .features import FEATURE_NAMES, move_features

MATE_CP = 90000


def engine_options(engine, multipv):
    """UCI options for a judge: MultiPV always; for Stockfish also one thread and a small hash (memory-tight laptop)."""
    opts = {"MultiPV": multipv}
    if os.path.basename(str(engine)).lower().startswith("stockfish"):
        opts.update(Threads=1, Hash=64)
    return opts


def judge_label(engine, nodes):
    return f"{os.path.basename(str(engine)).lower()}@{nodes}n"


@dataclass
class Position:
    """One decision: candidates (uci), their features and centipawn losses, and the index chosen (-1 = not a candidate)."""
    fen: str
    played: str
    rating: int
    ply: int
    cands: list
    feats: np.ndarray  # (n, F)
    loss: np.ndarray   # (n,) centipawns below the best candidate
    chosen: int
    played_loss: float  # loss of the played move if the engine scored it, else nan
    platform: int = 0  # 0 lichess, 1 chess.com
    game: int = 0  # which of the player's games the decision came from (for split-half tests)


def candidates_for(engine, item, *, nodes, multipv, window):
    """Search `item` (an EvalItem: .fen, .played, .mover_elo, .ply) and return a Position, or None when there is nothing to choose."""
    board = chess.Board(item.fen)
    engine.new_game()
    res = engine.go(item.fen, nodes=nodes)
    lines = [l for l in res.lines if l.pv and chess.Move.from_uci(l.pv[0]) in board.legal_moves]
    lines.sort(key=lambda l: -l.cp)  # best first whatever order the engine printed them in
    if not lines:
        return None
    best = lines[0].cp
    kept = [l for l in lines if best - l.cp <= window]
    cands = [l.pv[0] for l in kept]
    chosen = cands.index(item.played) if item.played in cands else -1
    if len(cands) < 2 and chosen >= 0:
        return None  # a single good move: no choice, no style information
    played_line = next((l for l in lines if l.pv[0] == item.played), None)
    feats = np.array([[move_features(board, chess.Move.from_uci(c))[n] for n in FEATURE_NAMES] for c in cands],
                     dtype=np.float32)
    loss = np.array([min(best - l.cp, 1000) for l in kept], dtype=np.float32)
    return Position(item.fen, item.played, item.mover_elo, item.ply, cands, feats, loss, chosen,
                    float(min(best - played_line.cp, 1000)) if played_line else float("nan"),
                    getattr(item, "platform", 0), getattr(item, "game", 0))


def save(positions, path, judge=""):
    """`judge` names the engine and budget that produced the candidates (e.g. 'stockfish@20000n'); results from different
    judges must never be mixed."""
    n = np.array([len(p.cands) for p in positions], dtype=np.int32)
    np.savez_compressed(
        path, offsets=np.concatenate([[0], np.cumsum(n)]).astype(np.int64),
        feats=np.concatenate([p.feats for p in positions]) if positions else np.zeros((0, len(FEATURE_NAMES)), np.float32),
        loss=np.concatenate([p.loss for p in positions]) if positions else np.zeros(0, np.float32),
        chosen=np.array([p.chosen for p in positions], dtype=np.int32),
        played_loss=np.array([p.played_loss for p in positions], dtype=np.float32),
        rating=np.array([p.rating for p in positions], dtype=np.int32),
        ply=np.array([p.ply for p in positions], dtype=np.int32),
        platform=np.array([p.platform for p in positions], dtype=np.int8),
        game=np.array([p.game for p in positions], dtype=np.int32),
        fens=np.array([p.fen for p in positions]), played=np.array([p.played for p in positions]),
        cands=np.array([" ".join(p.cands) for p in positions]), names=np.array(FEATURE_NAMES), judge=np.array(judge))


def load(path):
    # Read every array ONCE: indexing an NpzFile (z["name"]) decompresses the whole array on each access, so doing
    # it inside the per-position loop was quadratic in time and memory.
    with np.load(path, allow_pickle=False) as z:
        a = {k: z[k] for k in z.files}
    off = a["offsets"]
    has_platform, has_game = "platform" in a, "game" in a
    out = []
    for i in range(len(a["chosen"])):
        lo, hi = off[i], off[i + 1]
        out.append(Position(str(a["fens"][i]), str(a["played"][i]), int(a["rating"][i]), int(a["ply"][i]),
                            str(a["cands"][i]).split(), a["feats"][lo:hi], a["loss"][lo:hi], int(a["chosen"][i]),
                            float(a["played_loss"][i]), int(a["platform"][i]) if has_platform else 0,
                            int(a["game"][i]) if has_game else 0))
    return out


def judge_of(path):
    """The judge label stored with a dataset ('' for files made before labels existed)."""
    with np.load(path, allow_pickle=False) as z:
        return str(z["judge"]) if "judge" in z.files else ""
