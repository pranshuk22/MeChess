"""Reference points for the "me" model: how often does the strong engine's best move equal the human's move?"""
import chess
import numpy as np

from ..uci_client import UciEngine
from . import encoding as enc


def engine_match(engine_command, data, nodes=5000, limit=2000, seed=1, options=None):
    """Top-1 agreement between an engine's best move and the moves in `data` (needs a shard with FENs).

    Returns {"n", "top1", "by_rating": {bin: top1}} over a random subset of `limit` samples.
    """
    if "fen" not in data:
        raise ValueError("needs a shard with FENs (val/test shards have them)")
    n = len(data["move"])
    idx = np.random.default_rng(seed).permutation(n)[: min(limit, n)]
    hits, per = [], {}
    with UciEngine(engine_command, options=options) as eng:
        for i in idx:
            fen = str(data["fen"][i])
            eng.new_game()
            best = eng.go(fen, nodes=nodes).bestmove
            board = chess.Board(fen)
            hit = enc.move_index(chess.Move.from_uci(best), board) == int(data["move"][i])
            hits.append(hit)
            per.setdefault(int(data["ratings"][i][0]) // 200 * 200, []).append(hit)
    return {"n": len(hits), "top1": float(np.mean(hits)), "by_rating": {k: float(np.mean(v)) for k, v in sorted(per.items())}}
