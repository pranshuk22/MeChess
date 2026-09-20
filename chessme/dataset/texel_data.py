"""Tuning positions from the player's own games: quiet positions labelled with the game result.

Human games are noisier training signal than engine self-play (blunders decide many results), so these
positions carry a weight: the profile's recency / time-control weights times a global `weight_scale`.
"""
import random

import chess

RESULT_VALUE = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}


def from_games(rows, weighter, *, min_ply=10, keep_prob=0.2, weight_scale=0.3, seed=1):
    """Yield (fen, white_result, weight) for sampled quiet positions of every kept game."""
    rng = random.Random(seed)
    for row in rows:
        gw = weighter.game_weight(row)
        if gw <= 0 or row.get("result") not in RESULT_VALUE:
            continue
        value = RESULT_VALUE[row["result"]]
        board = chess.Board()
        try:
            for i, san in enumerate(row["moves"].split()):
                move = board.parse_san(san)
                weight = gw * weighter.time_class_weight(row, i) * weight_scale
                quiet = not board.is_check() and not board.is_capture(move) and not move.promotion
                if i >= min_ply and quiet and weight > 0 and rng.random() < keep_prob:
                    yield board.fen(), value, weight
                board.push(move)
        except ValueError:
            continue  # a game that fails to replay is skipped from that point on
