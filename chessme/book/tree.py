"""Position graph of a player's own games -> opening book entries.

Nodes are keyed by (board, side to move, castling) so transpositions merge, as in OpeningTree. For positions
where the *player* was to move we record which move they chose (weighted by the profile's recency and
time-control weights); for positions where the *opponent* was to move we only count replies (used by the report).
"""
from collections import Counter
from dataclasses import dataclass, field

import chess

from .format import Entry
from .keys import book_key

RESULT_SCORE = {"win": 1.0, "draw": 0.5, "loss": 0.0}


@dataclass
class MoveStat:
    weight: float = 0.0
    games: int = 0
    score_sum: float = 0.0


@dataclass
class Node:
    fen: str  # a representative FEN (move counters normalised), for engine checks and reports
    games: int = 0  # games that reached this position with the player to move
    moves: dict = field(default_factory=dict)  # (from, to, promo) -> MoveStat


def _norm_fen(board):
    return " ".join(board.fen().split()[:4]) + " 0 1"


def move_id(move):
    return (move.from_square, move.to_square, move.promotion or 0)


class BookTree:
    def __init__(self, max_ply=30):
        self.max_ply = max_ply
        self.mine = {}  # key -> Node (player to move)
        self.opp = {}  # key -> Counter of the opponent's replies (uci) with games
        self.opp_fen = {}
        self.games_used = 0

    def add_game(self, row, weighter):
        """Add one normalised game row. Returns False if it carries no weight (filtered out)."""
        gw = weighter.game_weight(row)
        if gw <= 0:
            return False
        score = RESULT_SCORE.get(row.get("my_result"))
        if score is None:
            return False
        my_white = row["color"] == "white"
        board = chess.Board()
        self.games_used += 1
        for ply, san in enumerate(row["moves"].split()[: self.max_ply]):
            try:
                move = board.parse_san(san)
            except ValueError:
                break  # keep the prefix that replayed correctly
            key = book_key(board)
            if (board.turn == chess.WHITE) == my_white:
                node = self.mine.get(key)
                if node is None:
                    node = self.mine[key] = Node(_norm_fen(board))
                node.games += 1
                stat = node.moves.setdefault(move_id(move), MoveStat())
                stat.weight += gw * weighter.time_class_weight(row, ply)
                stat.games += 1
                stat.score_sum += score
            else:
                self.opp.setdefault(key, Counter())[move.uci()] += 1
                self.opp_fen.setdefault(key, _norm_fen(board))
            board.push(move)
        return True

    def entries(self, min_games=2, min_position_games=3, min_share=0.05):
        """Apply the habit filters and return (entries, stats about what was dropped)."""
        out = []
        dropped = Counter()
        for key, node in self.mine.items():
            if node.games < min_position_games:
                dropped["positions below min_position_games"] += 1
                continue
            total = sum(s.weight for s in node.moves.values())
            kept = 0
            for (f, t, promo), s in node.moves.items():
                if s.games < min_games:
                    dropped["moves below min_games"] += 1
                elif total <= 0 or s.weight / total < min_share:
                    dropped["moves below min_share"] += 1
                elif s.weight > 0:
                    out.append(Entry(key, f, t, promo, float(s.weight), s.games,
                                     round(1000 * s.score_sum / s.games)))
                    kept += 1
            if kept == 0:
                dropped["positions left with no move"] += 1
        return out, dropped
