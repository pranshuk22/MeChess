"""The Allie test set (Zhang et al., ICLR 2025; also the Maia-3 benchmark): 18,239 Lichess blitz games of 2022 with the moves and the
seconds spent on each, published as `lichess-2022-blitz-test/2022-test-annotated.jsonl` in the Hugging Face dataset `yimingzhang/allie-data`.

The papers describe the test positions only in words ("remove the first moves", "remove positions after a player has under 30 s").
This module turns the games into the same `testset.Position` records as our own sets, with the clocks rebuilt from the seconds spent
(clock before a move = base + sum over the player's earlier moves of (increment - seconds spent)). The filter definition was found by
search and reproduces the published size EXACTLY: **884,049 positions** = the first 10 plies removed, and each game cut at the first
position where EITHER player has under 30 s on the clock (that position is kept, everything after it dropped). So "the first 10 moves"
of the Chessformer text are 10 plies, i.e. Allie's "first 5 moves"."""
import json

import chess

from .testset import LOW_CLOCK, Position

PUBLISHED_POSITIONS = 884_049          # Allie paper, Section 4.1; Chessformer Section 4.1
OPENING_PLIES = 10


def read_games(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def game_positions(g, comparable_only=True):
    """Positions of one Allie test game. `comparable_only` keeps only the positions the published numbers are computed on."""
    moves = g["moves-uci"].split()
    seconds = g["moves-seconds"]
    if len(moves) != len(seconds):
        raise ValueError(f"{g['game-id']}: {len(moves)} moves but {len(seconds)} times")
    base, inc = (int(x) for x in g["time-control"].split("+"))
    ratings = {chess.WHITE: int(g["white-elo"]), chess.BLACK: int(g["black-elo"])}
    clock = {chess.WHITE: float(base), chess.BLACK: float(base)}
    low = {chess.WHITE: False, chess.BLACK: False}
    event_seen = False
    board, played, out = chess.Board(), [], []
    gid = g["game-id"].rsplit("/", 1)[-1]
    for i, (uci, spent) in enumerate(zip(moves, seconds)):
        mover = board.turn
        if clock[mover] < LOW_CLOCK:
            low[mover] = True
        late = event_seen
        if clock[mover] < LOW_CLOCK or clock[not mover] < LOW_CLOCK:
            event_seen = True
        if not comparable_only or (i >= OPENING_PLIES and not late):
            out.append(Position(gid, i, board.fen(), uci, ratings[mover], ratings[not mover], base, inc, clock[mover], clock[not mover],
                                float(spent), low[mover], board.legal_moves.count(), " ".join(played), g["result"], late))
        clock[mover] += inc - spent
        board.push_uci(uci)
        played.append(uci)
    return out


def iter_positions(path, comparable_only=True):
    for g in read_games(path):
        yield from game_positions(g, comparable_only)
