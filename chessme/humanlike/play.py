"""Let a move model play: the models of this study give a probability for every legal move, so a game is played by SAMPLING a move from those
probabilities (no search), with a simulated clock. Games start from the position and clocks a real game had at a given ply, with the real
ratings, so the models play out the same kinds of games the humans did.

* `AdaptedScorer` wraps a frozen scorer with a trained adapter (`adapter.py`): the adapter re-weights the frozen model's 16 most probable moves using the clocks.
* `TimeModel` is how long a move takes. The models do not think about time, so a thinking time is drawn from what humans spent in the same situation (how
  much of the clock is left, which phase of the game): the clock then runs down the way a human's does, and the adapter sees realistic clocks.
* `play_games` plays many games in lockstep, one batched call to each model per ply. A move is drawn with a random generator keyed on (seed, game, ply), so the
  games do not depend on how many are played at once."""
import hashlib
import json
from dataclasses import dataclass, field

import chess
import numpy as np

from ..model.compare import EvalItem, Scorer
from . import adapter as A

CLOCK_SHARE_EDGES = (0.05, 0.10, 0.20, 0.50)          # clock left as a share of the base time
PLY_EDGES = (20, 60)


class AdaptedScorer(Scorer):
    """`base` scorer + a trained adapter. Moves outside the base model's 16 most probable share the adapter's tail mass in proportion to the base probabilities."""

    def __init__(self, base, bundle, name=None):
        self.base = base
        self.net, self.mean, self.std, self.meta = bundle
        self.name = name or f"{base.name} + adapter"

    def probs(self, items):
        base_probs = self.base.probs(items)
        n = len(items)
        order = [sorted(p, key=p.get, reverse=True) for p in base_probs]
        topk = np.zeros((n, A.K))
        for i, (p, o) in enumerate(zip(base_probs, order)):
            m = min(A.K, len(o))
            topk[i, :m] = [p[u] for u in o[:m]]
        ent = np.array([-sum(v * np.log(max(v, 1e-12)) for v in p.values()) for p in base_probs])
        arr = {"clock": np.array([it.clock for it in items], dtype=np.float64), "opp_clock": np.array([it.opp_clock for it in items], dtype=np.float64),
               "base": np.array([it.base for it in items]), "inc": np.array([it.inc for it in items]), "ply": np.array([it.ply for it in items]),
               "me": np.array([it.mover_elo for it in items]), "opp": np.array([it.opp_elo for it in items]), "n_legal": np.array([len(p) for p in base_probs])}
        scores = {"conf": topk[:, 0], "entropy": ent, "topk_p": topk.astype(np.float32), "rank": np.ones(n, np.int32), "p": topk[:, 0]}
        x = A.features(arr, scores)
        sl = A.slots(scores)
        out = A.apply(self.net, self.mean, self.std, x, sl)
        res = []
        for i, (p, o) in enumerate(zip(base_probs, order)):
            adapted = {u: float(out["probs"][i, j]) for j, u in enumerate(o[:A.K])}
            rest = o[A.K:]
            if rest:
                tail_base = sum(p[u] for u in rest)
                for u in rest:
                    adapted[u] = float(out["tail"][i]) * p[u] / max(tail_base, 1e-300)
            z = sum(adapted.values())
            res.append({u: v / z for u, v in adapted.items()})
        return res


@dataclass
class TimeModel:
    """Seconds a move takes, as a share of the time available (clock + increment), drawn from the shares humans used in the same situation."""
    shares: dict = field(default_factory=dict)         # (clock-share bin, phase bin) -> list of shares

    @staticmethod
    def key(clock, base, ply):
        return int(np.digitize(clock / max(base, 1), CLOCK_SHARE_EDGES)), int(np.digitize(ply, PLY_EDGES))

    @classmethod
    def fit(cls, positions, per_bin=3000, seed=0):
        """From test-set positions (any iterable; they carry the clock before the move and the time the move took). Keeps a random `per_bin` shares per bin."""
        rng = np.random.default_rng(seed)
        bins, seen = {}, {}
        for p in positions:
            avail = p.clock + p.inc
            if not (np.isfinite(p.spent) and avail > 0 and np.isfinite(p.clock)):
                continue
            k = cls.key(p.clock, p.base, p.ply)
            share = float(np.clip(p.spent / avail, 0.0, 1.0))
            seen[k] = seen.get(k, 0) + 1
            pool = bins.setdefault(k, [])
            if len(pool) < per_bin:
                pool.append(share)
            else:                                           # reservoir sampling: every position has the same chance of being kept
                j = int(rng.integers(seen[k]))
                if j < per_bin:
                    pool[j] = share
        return cls(bins)

    def sample(self, rng, clock, base, inc, ply):
        k = self.key(clock, base, ply)
        pool = self.shares.get(k)
        if not pool:                                   # unseen situation: the nearest clock bin with data in the same phase, else any
            same = [kk for kk in self.shares if kk[1] == k[1]] or list(self.shares)
            pool = self.shares[min(same, key=lambda kk: abs(kk[0] - k[0]))]
        return float(pool[rng.integers(len(pool))]) * (clock + inc)

    def to_json(self):
        return json.dumps({f"{a},{b}": v for (a, b), v in self.shares.items()})

    @classmethod
    def from_json(cls, text):
        return cls({tuple(int(x) for x in k.split(",")): v for k, v in json.loads(text).items()})


@dataclass
class Game:
    gid: str
    board: chess.Board
    start_moves: list
    ratings: dict            # chess.WHITE / chess.BLACK -> rating
    clocks: dict             # seconds left
    base: int
    inc: int
    models: dict
    moves: list = field(default_factory=list)
    spent: list = field(default_factory=list)
    clock_after: list = field(default_factory=list)
    result: str = "*"
    termination: str = ""

    @property
    def ply(self):
        return len(self.start_moves) + len(self.moves)


def game_from_position(p, models, gid=None):
    """The game continuing from a test-set position: its history, clocks and ratings (the side to move is the position's mover)."""
    board = chess.Board()
    start = p.moves.split()
    for u in start:
        board.push_uci(u)
    if board.fen().split()[:4] != p.fen.split()[:4]:
        raise ValueError("the move history does not lead to the position")
    mover, other = board.turn, (not board.turn)
    return Game(gid or f"{p.gid}@{p.ply}", board, start, {mover: p.me, other: p.opp}, {mover: float(p.clock), other: float(p.opp_clock)}, p.base, p.inc, models)


def is_start_candidate(p, min_ply=8, max_ply=14, min_clock=60.0):
    """Can a game be started from this test-set position? Early in the game, a real choice to make, and time left on both clocks."""
    return min_ply <= p.ply <= max_ply and p.n_legal >= 2 and p.clock >= min_clock and p.opp_clock >= min_clock


def choose_starts(candidates, n, seed=0):
    """At most `n` starting positions, at most one per game (a classifier trained on the games must not see a game on both sides of a split), in an
    order given by a hash of the position, so that the first n of a larger choice are the choice of n."""
    key = lambda p: hashlib.sha256(f"{seed}:start:{p.gid}:{p.ply}".encode()).digest()
    seen, out = set(), []
    for p in sorted(candidates, key=key):
        if p.gid not in seen:
            seen.add(p.gid)
            out.append(p)
    return out[:n]


def _rng(seed, gid, ply):
    return np.random.default_rng(int.from_bytes(hashlib.sha256(f"{seed}:{gid}:{ply}".encode()).digest()[:8], "big"))


def _finish_if_over(g, max_plies):
    outcome = g.board.outcome(claim_draw=True)
    if outcome is not None:
        g.result, g.termination = outcome.result(), outcome.termination.name.lower()
        return True
    if g.ply >= max_plies:
        g.result, g.termination = "1/2-1/2", "max_plies"
        return True
    return False


def play_games(games, time_model, *, seed=0, max_plies=300, batch=256, progress=None):
    """Play the `games` (see `game_from_position`) to the end. Each model is called with all the positions it has to move in, at most `batch` at once."""
    active = [g for g in games if not _finish_if_over(g, max_plies)]
    rounds = 0
    while active:
        by_model = {}
        for g in active:
            by_model.setdefault(id(g.models[g.board.turn]), []).append(g)
        for group in by_model.values():
            scorer = group[0].models[group[0].board.turn]
            for i in range(0, len(group), batch):
                part = group[i:i + batch]
                items = [EvalItem(g.board.fen(), "", g.ratings[g.board.turn], g.ratings[not g.board.turn], 0, g.ply, tuple(g.start_moves + g.moves),
                                  clock=g.clocks[g.board.turn], opp_clock=g.clocks[not g.board.turn], base=g.base, inc=g.inc, game=g.gid) for g in part]
                for g, probs in zip(part, scorer.probs(items)):
                    mover = g.board.turn
                    rng = _rng(seed, g.gid, g.ply)
                    ucis = sorted(probs)                                   # a fixed order, so the draw does not depend on dict order
                    p = np.array([probs[u] for u in ucis], dtype=np.float64)
                    move = ucis[int(rng.choice(len(ucis), p=p / p.sum()))]
                    spent = time_model.sample(rng, g.clocks[mover], g.base, g.inc, g.ply)
                    if spent >= g.clocks[mover]:                                   # the clock runs out before the move is made
                        winner = not mover
                        g.result = "1/2-1/2" if g.board.has_insufficient_material(winner) else ("1-0" if winner == chess.WHITE else "0-1")
                        g.termination = "time_forfeit"
                        g.clocks[mover] = 0.0
                        continue
                    g.board.push_uci(move)
                    g.moves.append(move)
                    g.spent.append(spent)
                    g.clocks[mover] = g.clocks[mover] - spent + g.inc
                    g.clock_after.append(g.clocks[mover])
        active = [g for g in active if g.result == "*" and not _finish_if_over(g, max_plies)]
        rounds += 1
        if progress and rounds % 20 == 0:
            progress(sum(1 for g in games if g.result != "*"), len(games))
    return games


def game_record(g):
    return {"gid": g.gid, "white": g.ratings[chess.WHITE], "black": g.ratings[chess.BLACK], "base": g.base, "inc": g.inc,
            "models": {"white": g.models[chess.WHITE].name, "black": g.models[chess.BLACK].name}, "start": " ".join(g.start_moves), "moves": " ".join(g.moves),
            "spent": [round(s, 2) for s in g.spent], "clock_after": [round(c, 2) for c in g.clock_after], "result": g.result, "termination": g.termination,
            "plies": g.ply}
