"""A fixed engine judges the moves of a test set: for every position, how much expected score the human's move and the model's most probable
moves give away compared with the best move. With these losses we can compare the errors humans make with the errors a model would make when
it SAMPLES its moves (axis A3), position by position, without playing any game.

Losses are in expected points of the mover (0 to 1, the Lichess win-probability curve, evaluation clamped to +-1000 cp). The engine's search is
pinned by a node budget, so the numbers are reproducible. Each candidate is judged by searching the position AFTER the move (sign flipped);
the best move is the largest of the root search and the candidates, so a loss is never negative."""
import multiprocessing
import shutil

import numpy as np

from ..analysis import classify as CL

K_CAND = 8                      # the model's most probable moves that are judged next to the human's move
MATE = 10000


def cp_of(score):
    """Centipawns for the side to move in the searched position (mate scores become +-MATE)."""
    return float(score.relative.score(mate_score=MATE))


def eval_after(engine, board, move, nodes):
    """Evaluation of `move` in centipawns for the player making it."""
    board.push(move)
    try:
        if board.is_checkmate():
            return float(MATE)
        if board.is_stalemate() or board.is_insufficient_material() or board.can_claim_draw():
            return 0.0
        import chess.engine
        info = engine.analyse(board, chess.engine.Limit(nodes=nodes))
        return -cp_of(info["score"])
    finally:
        board.pop()


def judge_position(engine, fen, human, candidates, nodes_child=10_000, nodes_root=20_000):
    """(best_cp, human_cp, [cp of each candidate]) for one position, all for the mover."""
    import chess
    import chess.engine
    board = chess.Board(fen)
    cache = {}

    def value(uci):
        if uci not in cache:
            cache[uci] = eval_after(engine, board, chess.Move.from_uci(uci), nodes_child)
        return cache[uci]
    cands = [value(u) if u else float("nan") for u in candidates]
    human_cp = value(human)
    root = cp_of(engine.analyse(board, chess.engine.Limit(nodes=nodes_root))["score"])
    best = max([root, human_cp] + [c for c in cands if c == c])
    return best, human_cp, cands


def win(cp):
    return CL.win_prob(cp, cap=CL.LICHESS_CP_CAP)


def losses(best_cp, cp):
    """Expected points given away by a move of value `cp` when the best move has `best_cp` (NaN stays NaN)."""
    cp = np.asarray(cp, dtype=np.float64)
    wb = np.vectorize(win)(np.asarray(best_cp, dtype=np.float64))
    wm = np.where(np.isnan(cp), np.nan, np.vectorize(win)(np.where(np.isnan(cp), 0.0, cp)))
    return np.maximum(0.0, wb.reshape(wb.shape + (1,) * (wm.ndim - wb.ndim)) - wm)


_ENGINE = {}


def _init(path, hash_mb):
    import chess.engine
    _ENGINE["e"] = chess.engine.SimpleEngine.popen_uci(path)
    _ENGINE["e"].configure({"Hash": hash_mb, "Threads": 1})


def _task(args):
    fen, human, cands, nc, nr = args
    return judge_position(_ENGINE["e"], fen, human, cands, nc, nr)


def judge_positions(items, *, engine_path=None, workers=1, nodes_child=10_000, nodes_root=20_000, hash_mb=16, progress=None, engine=None):
    """`items` = [(fen, human uci, [candidate ucis; '' = none])]. Returns arrays best_cp, human_cp, cand_cp (n x K, NaN where there is no candidate).
    Pass `engine` (an object with `analyse`) to run in-process; otherwise `workers` Stockfish processes are started from `engine_path`."""
    n = len(items)
    best, human, cand = np.zeros(n), np.zeros(n), np.full((n, K_CAND), np.nan)
    tasks = [(f, h, list(c)[:K_CAND] + [""] * (K_CAND - len(c)), nodes_child, nodes_root) for f, h, c in items]
    if engine is not None:
        results = (judge_position(engine, *t[:3], t[3], t[4]) for t in tasks)
    else:
        path = engine_path or shutil.which("stockfish")
        if not path:
            raise SystemExit("Stockfish not found: pass --engine")
        pool = multiprocessing.get_context("spawn").Pool(workers, initializer=_init, initargs=(path, hash_mb))
        results = pool.imap(_task, tasks, chunksize=16)
    try:
        for i, (b, h, c) in enumerate(results):
            best[i], human[i], cand[i] = b, h, c
            if progress and (i + 1) % 500 == 0:
                progress(i + 1, n)
    finally:
        if engine is None:
            # terminate, never close()+join(): on Python 3.13 a worker waits for the engine's reader thread before running any exit hook, so join() hangs
            # forever (it cost a 3.5-hour Kaggle run). The engines see their pipe close and exit by themselves.
            pool.terminate()
            pool.join()
    return {"best_cp": best, "human_cp": human, "cand_cp": cand}
