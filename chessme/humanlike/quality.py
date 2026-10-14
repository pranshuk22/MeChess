"""Engine-judged quality of the moves of whole games (the Irwin-style features of the classifier test, E13 of the research plan).

For each move of the first `max_moves` half-moves after the start of a game record (`play.game_record` format, also the real continuations of
`humanlike-humangames`), a fixed engine (a pinned node budget, so the numbers are reproducible) searches the position before the move once. The loss of
the move is what it gives away compared with the engine's own evaluation of that position, in expected points of the mover (0 to 1, the Lichess
win-probability curve): evaluation before the move minus the evaluation of the position AFTER it, which is the next position's search with the sign
flipped. One search per position, so a game costs `moves + 1` searches. Per move we keep: the loss, whether it is an error (> 0.10) or a blunder (> 0.20),
whether it is the engine's first choice, and the expected score of the mover before the move (the state the move was played in).
These features need the engine; the plain classifier test of `c2st.py` does not."""
import multiprocessing
import shutil

import chess
import chess.engine
import numpy as np

from . import judge as J

QUALITY_FEATURES = ["engine_loss", "error", "blunder", "engine_best", "mover_score"]
ERROR, BLUNDER = 0.10, 0.20


def _search(engine, board, nodes):
    """(evaluation in centipawns for the side to move, the engine's first move or None). Finished games are not searched."""
    if board.is_checkmate():
        return -float(J.MATE), None
    if board.is_stalemate() or board.is_insufficient_material() or board.can_claim_draw():
        return 0.0, None
    info = engine.analyse(board, chess.engine.Limit(nodes=nodes))
    pv = info.get("pv") or [None]
    return J.cp_of(info["score"]), pv[0]


def annotate(engine, record, max_moves=40, nodes=20_000):
    """Per-move quality of the first `max_moves` moves of the record after its start: an array (moves x len(QUALITY_FEATURES))."""
    board = chess.Board()
    for u in record["start"].split():
        board.push_uci(u)
    moves = [chess.Move.from_uci(u) for u in record["moves"].split()[:max_moves]]
    cp, best = _search(engine, board, nodes)
    rows = []
    for move in moves:
        before = J.win(cp)
        board.push(move)
        cp_next, best_next = _search(engine, board, nodes)
        loss = max(0.0, before - J.win(-cp_next))                    # the position after the move, for the mover
        rows.append([loss, loss > ERROR, loss > BLUNDER, best is not None and move == best, before])
        cp, best = cp_next, best_next
    return np.array(rows, dtype=np.float32).reshape(len(rows), len(QUALITY_FEATURES))


_ENGINE = {}


def _init(path, hash_mb):
    _ENGINE["e"] = chess.engine.SimpleEngine.popen_uci(path)
    _ENGINE["e"].configure({"Hash": hash_mb, "Threads": 1})


def _task(args):
    record, max_moves, nodes = args
    return record["gid"], annotate(_ENGINE["e"], record, max_moves, nodes)


def annotate_games(records, *, engine_path=None, workers=1, max_moves=40, nodes=20_000, hash_mb=16, progress=None, engine=None):
    """{gid: array} for the records. Pass `engine` (an object with `analyse`) to run in-process; otherwise `workers` Stockfish processes are started."""
    if engine is not None:
        results = ((r["gid"], annotate(engine, r, max_moves, nodes)) for r in records)
    else:
        path = engine_path or shutil.which("stockfish")
        if not path:
            raise SystemExit("Stockfish not found: pass --engine")
        pool = multiprocessing.get_context("spawn").Pool(workers, initializer=_init, initargs=(path, hash_mb))
        results = pool.imap(_task, [(r, max_moves, nodes) for r in records], chunksize=8)
    out = {}
    try:
        for i, (gid, rows) in enumerate(results):
            out[gid] = rows
            if progress and (i + 1) % 200 == 0:
                progress(i + 1, len(records))
    finally:
        if engine is None:
            pool.terminate()                                          # never close()+join(): see judge.judge_positions
            pool.join()
    return out


def write(path, annotated):
    """One JSON line per game: gid and the rows (rounded; booleans as 0/1)."""
    import json
    with open(path, "w", encoding="utf-8") as f:
        for gid, rows in annotated.items():
            f.write(json.dumps({"gid": gid, "rows": np.round(rows, 4).tolist()}) + "\n")


def read(path):
    import json
    with open(path, encoding="utf-8") as f:
        return {d["gid"]: np.array(d["rows"], dtype=np.float32).reshape(-1, len(QUALITY_FEATURES)) for d in map(json.loads, filter(str.strip, f))}
