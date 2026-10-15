"""A position graph from games: for every position (transpositions merged, move counters ignored) how often it occurred in the games and which moves were played from
it, each with how often and how many points the tracked player (the opponent, or you) scored in those games. Only the first `max_ply` half-moves are kept: the
opening is where a few games share positions."""
import chess

MAX_PLY = 24


def key_of(board: chess.Board) -> str:
    return " ".join(board.fen().split()[:4])


class Graph:
    def __init__(self, max_ply=MAX_PLY):
        self.max_ply = max_ply
        self.nodes: dict[str, dict] = {}

    def add(self, moves, pts, colour):
        """One game: its UCI moves, the tracked player's points (None when unfinished) and their colour."""
        board = chess.Board()
        for i, uci in enumerate(moves[: self.max_ply]):
            node = self.nodes.setdefault(key_of(board), {"n": 0, "moves": {}})
            node["n"] += 1
            e = node["moves"].setdefault(uci, [0, 0.0, 0])                     # games, points of the tracked player, games with a result
            e[0] += 1
            if pts is not None:
                e[1] += pts
                e[2] += 1
            try:
                board.push_uci(uci)
            except ValueError:
                return

    def node(self, board: chess.Board):
        return self.nodes.get(key_of(board))

    def moves(self, board: chess.Board, min_n=1):
        """[(uci, games, score)] played from this position, most played first; score is the tracked player's mean points (None when no game had a result)."""
        node = self.node(board)
        if not node:
            return []
        out = [(u, e[0], e[1] / e[2] if e[2] else None) for u, e in node["moves"].items() if e[0] >= min_n]
        return sorted(out, key=lambda t: (-t[1], t[0]))

    def visits(self, board: chess.Board) -> int:
        node = self.node(board)
        return node["n"] if node else 0


def build(games, max_ply=MAX_PLY) -> Graph:
    """Graph of `games`: objects with `.moves`, `.score` and `.colour` (the tracked player's)."""
    g = Graph(max_ply)
    for game in games:
        g.add(game.moves, game.score, game.colour)
    return g
