"""Self-play data generation for evaluation tuning (Texel-style: position | game result)."""
import multiprocessing
import random
from pathlib import Path

import chess

from .match import Adjudication, EngineSpec, SearchLimit, _discard, _engine_for, play_game

RESULT_VALUE = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}


def randomise(fen, plies, rng):
    """Play `plies` random legal moves from `fen` (adds variety when openings are reused)."""
    board = chess.Board(fen)
    for _ in range(plies):
        moves = list(board.legal_moves)
        if not moves:
            break
        board.push(rng.choice(moves))
    return board.fen() if not board.is_game_over() else fen


def positions_from_game(game, rng, min_ply=8, keep_prob=0.35, max_abs_cp=1500):
    """Quiet, non-mate positions from a finished game, each labelled with the game's result (White's score).

    A position qualifies when: not in check, the engine's chosen move is not a capture/promotion, and the
    engine's own score says the game is still balanced enough to be informative.
    """
    if game.error:
        return []
    value = RESULT_VALUE[game.result]
    board = chess.Board(game.start_fen)
    out = []
    for i, uci in enumerate(game.moves):
        move = chess.Move.from_uci(uci)
        score = game.evals[i] if i < len(game.evals) else None
        quiet = not board.is_check() and not board.is_capture(move) and not move.promotion
        if i >= min_ply and quiet and score is not None and abs(score) <= max_abs_cp and rng.random() < keep_prob:
            out.append((board.fen(), value))
        board.push(move)
    return out


def _worker(job):
    idx, fen, spec, limit, adj, seed, extra, min_ply, keep_prob = job
    rng = random.Random(seed * 1000003 + idx)
    start = randomise(fen, extra, rng) if extra else fen
    eng = _engine_for(spec)
    eng.new_game()
    game = play_game(eng, eng, start, limit, adj)
    if game.error:
        _discard(spec)
    return idx, game, positions_from_game(game, rng, min_ply, keep_prob)


def generate(spec: EngineSpec, openings, games, out_path, limit: SearchLimit, adj=Adjudication(), *,
             concurrency=1, seed=1, min_ply=8, keep_prob=0.35, progress=None):
    """Play `games` self-play games (cycling openings, adding random plies on reuse) and write
    "FEN | result" lines to `out_path`. Returns (games_played, positions_written, games_with_errors)."""
    jobs = []
    for i in range(games):
        cycle = i // len(openings)
        jobs.append((i, openings[i % len(openings)], spec, limit, adj, seed, cycle * 2, min_ply, keep_prob))
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    positions = errors = played = 0
    with open(path, "w") as out:
        def consume(item):
            nonlocal positions, errors, played
            _, game, rows = item
            played += 1
            errors += bool(game.error)
            for fen, value in rows:
                out.write(f"{fen} | {value}\n")
            positions += len(rows)
            if progress:
                progress(played, positions)

        if concurrency <= 1:
            try:
                for job in jobs:
                    consume(_worker(job))
            finally:
                _discard(spec)
        else:
            with multiprocessing.get_context("spawn").Pool(concurrency) as pool:
                for item in pool.imap_unordered(_worker, jobs):
                    consume(item)
    return played, positions, errors
