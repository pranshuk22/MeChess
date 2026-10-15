"""What to play against this opponent, and where they go wrong early.

`Evaluator` wraps the engine search (`search(board) -> lines`, best first, scores for the side to move) with a memory and a budget of searches.
`find_traps` walks the positions the opponent reached in their games and reports the places where their usual move gives away points, with the way you get there.
`Planner` picks, for each of your turns, the move with the best EXPECTED result against what this opponent really plays (their observed replies, weighted by how often
they played them), while never giving up more than `TOLERANCE` expected points to the engine's best move: the plan is a tree of your moves and their likely replies.

Scores are expected points for one side (win probability of the evaluation), the same scale as the rest of the app (mistake = 0.10, blunder = 0.20)."""
import chess
import chess.pgn

from ..analysis import classify as C
from .graph import Graph, key_of

TOLERANCE = 0.05                # you never give up more than this to the engine's best move ...
GAMBLE = 0.12                   # ... unless the opponent has been seen at least `GAMBLE_VISITS` times in the position it leads to: then up to this much, for the expected gain
GAMBLE_VISITS = 4
MISTAKE = 0.10
PRIOR = 2                       # pseudo-games for "the engine's best reply": a reply seen once does not mean the opponent always plays it


def wp(cp):
    return C.win_prob(cp, cap=C.LICHESS_CP_CAP)


class Evaluator:
    """Engine lines per position, remembered; `budget` limits the number of new searches (None = no limit)."""

    def __init__(self, search, budget=None):
        self.search, self.budget, self.memo, self.searches, self.exhausted = search, budget, {}, 0, False

    def lines(self, board: chess.Board):
        if board.is_game_over():
            return []
        k = key_of(board)
        if k in self.memo:
            return self.memo[k]
        if self.budget is not None and self.searches >= self.budget:
            self.exhausted = True
            return []
        self.searches += 1
        self.memo[k] = self.search(board) or []
        return self.memo[k]

    def mover_wp(self, board: chess.Board) -> float:
        """Expected points of the side to move, by the engine."""
        if board.is_checkmate():
            return 0.0
        if board.is_game_over():
            return 0.5
        lines = self.lines(board)
        return wp(lines[0].cp) if lines else 0.5

    def wp_for(self, board: chess.Board, colour: bool) -> float:
        v = self.mover_wp(board)
        return v if board.turn == colour else 1.0 - v

    def loss(self, board: chess.Board, move: chess.Move) -> float:
        """Expected points the mover gives away with `move` compared with the engine's best move."""
        lines = self.lines(board)
        if not lines:
            return 0.0
        if lines[0].move == move.uci():
            return 0.0
        child = board.copy()
        child.push(move)
        return max(0.0, self.mover_wp(board) - (1.0 - self.mover_wp(child)))


def _san_line(board: chess.Board, ucis, limit=6):
    b, out = board.copy(), []
    for u in ucis[:limit]:
        try:
            mv = chess.Move.from_uci(u)
            out.append(b.san(mv))
            b.push(mv)
        except ValueError:
            break
    return out


def _path_text(sans):
    out = []
    for i, s in enumerate(sans):
        out.append(f"{i // 2 + 1}.{s}" if i % 2 == 0 else (f"{s}" if out else f"{i // 2 + 1}...{s}"))
    return " ".join(out)


# ---- places where the opponent's usual move gives away points ---------------------------------------------------------------------------------

def find_traps(graph: Graph, ev: Evaluator, opp_colour: str, *, min_visits=3, min_share=0.2, min_loss=0.08, max_ply=22, limit=12):
    """Positions in the opponent's games where they (the side `opp_colour`) to move played a move that loses at least `min_loss` expected points, in at least `min_share`
    of the games that reached the position. Each comes with the way there (taken from the games; the moves of yours on it are checked), the punishing reply and
    the evaluation afterwards. Strongest first (how often it happens x how much it gives away)."""
    opp = chess.WHITE if opp_colour == "white" else chess.BLACK
    seen, queue, found = set(), [(chess.Board(), [])], []
    while queue:
        board, path = queue.pop(0)
        k = key_of(board)
        if k in seen or len(path) > max_ply:
            continue
        seen.add(k)
        node = graph.node(board)
        if not node:
            continue
        if board.turn == opp and node["n"] >= min_visits:
            for uci, e in sorted(node["moves"].items(), key=lambda kv: -kv[1][0]):
                share = e[0] / node["n"]
                if e[0] < 2 or share < min_share:
                    continue
                mv = chess.Move.from_uci(uci)
                loss = ev.loss(board, mv)
                if loss < min_loss:
                    continue
                lines = ev.lines(board)
                child = board.copy()
                child.push(mv)
                after = ev.wp_for(child, not opp)
                reply = ev.lines(child)                                                # what you play after it: the punishment
                your_losses = _your_losses(path, ev, opp)
                found.append({"path": _path_text([t[2] for t in path]), "pathMoves": [t[1] for t in path], "fen": board.fen(), "fenAfter": child.fen(), "move": board.san(mv), "uci": uci, "games": e[0], "visits": node["n"], "share": share,
                              "loss": loss, "better": board.san(chess.Move.from_uci(lines[0].move)) if lines else None, "betterUci": lines[0].move if lines else None,
                              "punish": child.san(chess.Move.from_uci(reply[0].move)) if reply else None, "punishUci": reply[0].move if reply else None, "punishLine": _san_line(child, reply[0].pv) if reply else [],
                              "youStand": after, "score": e[1] / e[2] if e[2] else None, "yourWorstLoss": max(your_losses) if your_losses else 0.0,
                              "sound": all(l <= TOLERANCE for l in your_losses), "ply": len(path)})
        for uci in node["moves"]:
            mv = chess.Move.from_uci(uci)
            nb = board.copy()
            san = board.san(mv)
            nb.push(mv)
            queue.append((nb, path + [(len(path), uci, san)]))
    found.sort(key=lambda t: -(t["games"] * t["loss"]))
    return found[:limit]


def _your_losses(path, ev, opp_colour):
    """Expected points lost by each of YOUR moves (the side that is not `opp_colour`) along a path of (ply, uci, san)."""
    board, out = chess.Board(), []
    for ply, uci, _ in path:
        mv = chess.Move.from_uci(uci)
        if board.turn != opp_colour:
            out.append(ev.loss(board, mv))
        board.push(mv)
    return out


# ---- the plan ---------------------------------------------------------------------------------------------------------------------------------

class Planner:
    def __init__(self, ev: Evaluator, opp_graph: Graph, user_graph: Graph | None, user_colour: str, *, depth=5, min_obs=2, max_candidates=3, max_replies=4):
        self.ev, self.opp, self.you_graph = ev, opp_graph, user_graph or Graph()
        self.you = chess.WHITE if user_colour == "white" else chess.BLACK
        self.depth, self.min_obs, self.max_candidates, self.max_replies = depth, min_obs, max_candidates, max_replies
        self.memo_you, self.memo_opp = {}, {}

    # candidate moves of yours: the engine's best lines within the tolerance, plus moves you have played before that are as good
    def candidates(self, board):
        lines = self.ev.lines(board)
        if not lines:
            return []
        best = wp(lines[0].cp)
        cands = {}
        for l in lines[: self.max_candidates]:
            if best - wp(l.cp) <= TOLERANCE:
                cands[l.move] = wp(l.cp)
        known = self.you_graph.moves(board, min_n=2)[:3] + self.opp.moves(board, min_n=2)[:3]      # what you have played, and what others played against this opponent
        for uci, n, score in known:
            if uci not in cands:
                child = board.copy()
                child.push(chess.Move.from_uci(uci))
                static = self.ev.wp_for(child, self.you)
                if best - static <= TOLERANCE or (best - static <= GAMBLE and self.opp.visits(child) >= GAMBLE_VISITS):
                    cands[uci] = static
        return [(u, v) for u, v in sorted(cands.items(), key=lambda kv: -kv[1])]

    def user_value(self, board, d):
        """(expected points for you, ranked [(uci, value, static)]) with you to move."""
        k = (key_of(board), d)
        if k in self.memo_you:
            return self.memo_you[k]
        static_here = self.ev.wp_for(board, self.you)
        if board.is_game_over() or d <= 0:
            return static_here, []
        ranked = []
        for uci, static in self.candidates(board):
            child = board.copy()
            child.push(chess.Move.from_uci(uci))
            v = self.opp_value(child, d)
            familiar = next((n for u, n, _ in self.you_graph.moves(board, min_n=1) if u == uci), 0)
            ranked.append((uci, v, static, familiar))
        ranked.sort(key=lambda t: -(t[1] + min(0.01, 0.002 * t[3])))                  # a move you already know breaks near-ties
        value = ranked[0][1] if ranked else static_here
        self.memo_you[k] = (value, ranked)
        return self.memo_you[k]

    def replies(self, board):
        """The opponent's observed replies here: [(uci, probability, games, score)] and the probability left for "something else"."""
        moves = self.opp.moves(board)
        total = self.opp.visits(board)
        top = moves[: self.max_replies]
        out = [(u, n / (total + PRIOR), n, s) for u, n, s in top]
        return out, max(0.0, 1.0 - sum(p for _, p, _, _ in out))

    def opp_value(self, board, d):
        """Expected points for you with the opponent to move, using what they actually play."""
        k = (key_of(board), d)
        if k in self.memo_opp:
            return self.memo_opp[k]
        static = self.ev.wp_for(board, self.you)
        if board.is_game_over() or self.opp.visits(board) < self.min_obs:
            return static
        replies, rest = self.replies(board)
        total = 0.0
        lines = self.ev.lines(board)
        best_uci = lines[0].move if lines else None
        for uci, p, _, _ in replies:
            child = board.copy()
            child.push(chess.Move.from_uci(uci))
            total += p * self.user_value(child, d - 1)[0]
        if rest > 0:
            if best_uci:
                child = board.copy()
                child.push(chess.Move.from_uci(best_uci))
                total += rest * self.user_value(child, d - 1)[0]
            else:
                total += rest * static
        self.memo_opp[k] = total
        return total

    # ---- the tree to show --------------------------------------------------------------------------------------------------------------------
    def tree(self, board=None, *, node_cap=160, min_p=0.08):
        board = board or chess.Board()
        self.budget = [node_cap]
        root_value = self.user_value(board, self.depth)[0] if board.turn == self.you else self.opp_value(board, self.depth)
        children = self._children(board, self.depth, 1.0, min_p)
        base = self.ev.wp_for(board, self.you)
        return {"fen": board.fen(), "value": root_value, "engine": base, "gain": root_value - base, "children": children}

    def _children(self, board, d, reach, min_p):
        if self.budget[0] <= 0 or board.is_game_over():
            return []
        if board.turn == self.you:
            if d <= 0:
                return []
            value, ranked = self.user_value(board, d)
            if not ranked:
                return []
            uci, v, static, familiar = ranked[0]
            self.budget[0] -= 1
            mv = chess.Move.from_uci(uci)
            san = board.san(mv)
            child = board.copy()
            child.push(mv)
            usual = self.you_graph.moves(board)
            alts = [{"san": board.san(chess.Move.from_uci(u)), "value": val, "engine": st, "games": f} for u, val, st, f in ranked[1:4]]
            node = {"san": san, "uci": uci, "by": "you", "value": v, "engine": static, "reach": reach, "yourGames": familiar, "cost": max(0.0, self.ev.wp_for(board, self.you) - static),
                    "yourScore": next((s for u, n, s in usual if u == uci), None), "alts": alts, "fen": child.fen(),
                    "usual": {"san": board.san(chess.Move.from_uci(usual[0][0])), "games": usual[0][1], "score": usual[0][2]} if usual else None}
            node["children"] = self._children(child, d, reach, min_p)
            return [node]
        if self.opp.visits(board) < self.min_obs:
            return []
        replies, rest = self.replies(board)
        out = []
        for uci, p, n, score in replies:
            if p < min_p or self.budget[0] <= 0:
                continue
            mv = chess.Move.from_uci(uci)
            self.budget[0] -= 1
            loss = self.ev.loss(board, mv)
            child = board.copy()
            child.push(mv)
            node = {"san": board.san(mv), "uci": uci, "by": "opp", "p": p, "games": n, "score": score, "loss": loss, "engine": self.ev.wp_for(child, self.you),
                    "reach": reach * p, "fen": child.fen()}
            node["children"] = self._children(child, d - 1, reach * p, min_p)
            out.append(node)
        return out


def to_pgn(tree, colour: str, name="Plan") -> str:
    """The plan as a PGN with variations (your moves and the replies the plan expects): saved as a repertoire it is practised in the coach's opening practice."""
    game = chess.pgn.Game()
    game.headers.update({"Event": name, "White": "?", "Black": "?"})

    def walk(node, kids):
        for i, k in enumerate(kids):
            mv = chess.Move.from_uci(k["uci"])
            child = node.add_variation(mv) if i == 0 else node.add_variation(mv)
            note = []
            if k["by"] == "opp":
                note.append(f"{round(100 * k['p'])}% of their games" + (f", gives away {round(100 * k['loss'])}%" if k["loss"] >= MISTAKE else ""))
            else:
                note.append(f"expected {round(100 * k['value'])}%")
            child.comment = "; ".join(note)
            walk(child, k.get("children", []))
    walk(game, tree["children"])
    return str(game)


def pick_lines(tree, board=None, limit=8):
    """The likeliest complete lines of a plan, each with how likely it is (the product of the opponent's reply shares) and the expected points at its end:
    [{'moves': 'e4 e5 ...', 'p': x, 'value': y}], most likely first."""
    out = []

    def walk(kids, board, path, p):
        if not kids:
            if path:
                out.append({"moves": _path_text(path), "p": p, "value": None})
            return
        for k in kids:
            b = board.copy()
            b.push(chess.Move.from_uci(k["uci"]))
            nxt = path + [k["san"]]
            if not k.get("children"):
                out.append({"moves": _path_text(nxt), "p": p * (k["p"] if k["by"] == "opp" else 1.0), "value": k["value"] if k["by"] == "you" else k["engine"]})
            else:
                walk(k["children"], b, nxt, p * (k["p"] if k["by"] == "opp" else 1.0))
    walk(tree["children"], board or chess.Board(), [], 1.0)
    out.sort(key=lambda t: -t["p"])
    return out[:limit]
