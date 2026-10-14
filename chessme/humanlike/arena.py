"""Matches between engines and the human-like bot (track S, S1): turn a strength knob into Elo.

Players are `Scorer`s of the self-play harness (`play.py`), so the same game loop plays them:
  * `StockfishScorer`: the engine's best move under a node limit (the ladder; nodes is the knob);
  * `ReweightedScorer`: the human-like bot: the human prior's 16 most probable moves (a Maia-3 scorer), each judged by the engine, and the move drawn from
    prior * exp(-beta * loss) (beta = 0: the prior; large: the engine's choice), the policy of `frontier.py` played for real.
Games start from the opening moves of real games (both colours, same openings for every pair), have no clocks, and are adjudicated by a fixed referee
engine (a decisive evaluation held for several plies; a long dead-equal stretch), so the results do not depend on the players' own opinions.
Searches keep the engine's transposition table between calls (clearing it per search costs 40 to 100 ms, more than a small search), so a rerun gives
statistically equal, not identical, games; the openings and the pairings are fixed."""
import itertools
import queue
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import chess
import chess.engine
import numpy as np

from ..model.compare import Scorer
from . import judge as J
from .play import Game


class NoTime:
    """Moves take no time (matches without clocks)."""

    def sample(self, rng, clock, base, inc, ply):
        return 0.0


class EnginePool:
    """A few engine processes handed out one search at a time."""

    def __init__(self, path=None, workers=1, hash_mb=16, engines=None):
        self.q = queue.Queue()
        self.owned = engines is None
        for e in (engines if engines is not None else [self._open(path, hash_mb) for _ in range(workers)]):
            self.q.put(e)
        self.workers = self.q.qsize()

    @staticmethod
    def _open(path, hash_mb):
        e = chess.engine.SimpleEngine.popen_uci(path)
        e.configure({"Hash": hash_mb, "Threads": 1})
        return e

    def run(self, fn):
        e = self.q.get()
        try:
            return fn(e)
        finally:
            self.q.put(e)

    def map(self, fn, items):
        with ThreadPoolExecutor(self.workers) as ex:
            return list(ex.map(lambda it: self.run(lambda e: fn(e, it)), items))

    def close(self):
        if self.owned:
            while not self.q.empty():
                try:
                    self.q.get().quit()
                except Exception:
                    pass


def search(engine, board, nodes, fresh=False):
    """Analyse under a node limit. `fresh` clears the engine's state first (`ucinewgame`): a move then depends only on the position, but it costs 40 to 100 ms
    per search; the default keeps the transposition table, so results are statistical, not bit-for-bit reproducible."""
    return engine.analyse(board, chess.engine.Limit(nodes=nodes), game=object() if fresh else None)


class StockfishScorer(Scorer):
    def __init__(self, pool, nodes, name=None):
        self.pool, self.nodes, self.name = pool, nodes, name or f"sf-{nodes}"

    def probs(self, items):
        def best(engine, item):
            board = chess.Board(item.fen)
            return {search(engine, board, self.nodes)["pv"][0].uci(): 1.0}
        return self.pool.map(best, items)


class ReweightedScorer(Scorer):
    def __init__(self, base, pool, beta, nodes_child=10_000, nodes_root=20_000, rating=None, k=16, name=None):
        self.base, self.pool, self.beta, self.k, self.rating = base, pool, beta, k, rating
        self.nodes_child, self.nodes_root = nodes_child, nodes_root
        self.name = name or f"{base.name} beta={beta:g}"

    def probs(self, items):
        if self.rating is not None:
            items = [replace(it, mover_elo=self.rating, opp_elo=self.rating) for it in items]
        priors = self.base.probs(items)

        def one(engine, pair):
            item, p = pair
            board = chess.Board(item.fen)
            top = sorted(p, key=lambda u: -p[u])[:self.k]
            cp = [self._child(engine, board, u) for u in top]
            root = J.cp_of(search(engine, board, self.nodes_root)["score"])
            loss = J.losses(max([root] + cp), np.array(cp))
            q = np.array([p[u] for u in top], dtype=np.float64)
            q = q / q.sum()
            logit = np.log(np.maximum(q, 1e-300)) - self.beta * loss
            w = np.exp(logit - logit.max())
            return dict(zip(top, (w / w.sum()).tolist()))
        return self.pool.map(one, list(zip(items, priors)))

    def _child(self, engine, board, uci):
        board.push(chess.Move.from_uci(uci))
        try:
            if board.is_checkmate():
                return float(J.MATE)
            if board.is_stalemate() or board.is_insufficient_material() or board.can_claim_draw():
                return 0.0
            return -J.cp_of(search(engine, board, self.nodes_child)["score"])
        finally:
            board.pop()


class Referee:
    """Adjudicates with its own engine, the same for every player: a decisive evaluation (|cp| >= `win_cp`) for `win_plies` plies in a row ends the game for the
    side that is ahead; from ply `draw_after` on, an evaluation within `draw_cp` of zero for `draw_plies` plies in a row is a draw."""

    def __init__(self, pool, nodes=1000, win_cp=1000, win_plies=6, draw_cp=10, draw_after=80, draw_plies=16):
        self.pool, self.nodes = pool, nodes
        self.win_cp, self.win_plies, self.draw_cp, self.draw_after, self.draw_plies = win_cp, win_plies, draw_cp, draw_after, draw_plies
        self.state = {}

    def check(self, games):
        """Updates the streaks with one evaluation per game and ends the games the rules end."""
        cps = self.pool.map(lambda engine, g: search(engine, g.board, self.nodes)["score"].white().score(mate_score=J.MATE), games)
        for g, cp in zip(games, cps):
            streak, flat = self.state.get(g.gid, (0, 0))
            side = 1 if cp >= self.win_cp else (-1 if cp <= -self.win_cp else 0)
            streak = 0 if side == 0 else (streak + side if streak != 0 and (streak > 0) == (side > 0) else side)
            flat = flat + 1 if abs(cp) <= self.draw_cp else 0
            self.state[g.gid] = (streak, flat)
            if abs(streak) >= self.win_plies:
                g.result, g.termination = ("1-0" if streak > 0 else "0-1"), "adjudicated_win"
            elif g.ply >= self.draw_after and flat >= self.draw_plies:
                g.result, g.termination = "1/2-1/2", "adjudicated_draw"


def game_from_start(start, models, gid, rating=2000):
    board = chess.Board()
    moves = start.split()
    for u in moves:
        board.push_uci(u)
    return Game(gid, board, moves, {chess.WHITE: rating, chess.BLACK: rating}, {chess.WHITE: 1e9, chess.BLACK: 1e9}, 0, 0, models)


def pairings(names, groups, bot_vs_bot=False):
    """All pairs of players, except two players of the group 'bot' unless `bot_vs_bot`."""
    return [(a, b) for a, b in itertools.combinations(names, 2) if bot_vs_bot or not (groups[a] == "bot" and groups[b] == "bot")]


def schedule(players, pairs, starts):
    """Games for every pair and start, both colours: [(game id, white name, black name, start index, start moves)]."""
    out = []
    for a, b in pairs:
        for i, s in enumerate(starts):
            out.append((f"{a}|{b}|{i}|w", a, b, i, s))
            out.append((f"{a}|{b}|{i}|b", b, a, i, s))
    return out


def result_for(white, black, result, a, b):
    """Score of player `a` (one of the two) from a result string."""
    s = {"1-0": 1.0, "0-1": 0.0}.get(result, 0.5)
    return s if a == white else 1.0 - s
