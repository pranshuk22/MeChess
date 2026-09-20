"""Engine-vs-engine matches: paired openings, adjudication, parallel workers, SPRT early stopping."""
import multiprocessing
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import chess
import chess.pgn

from . import sprt as sprt_mod
from .uci_client import STARTPOS_FEN, EngineError, UciEngine

MATE_CP = 10000


@dataclass(frozen=True)
class EngineSpec:
    name: str
    command: tuple
    options: tuple = ()  # ((name, value), ...) so specs are hashable / picklable

    @staticmethod
    def make(name, command, options=None):
        cmd = (command,) if isinstance(command, str) else tuple(command)
        return EngineSpec(name, cmd, tuple(sorted((options or {}).items())))


@dataclass(frozen=True)
class SearchLimit:
    nodes: Optional[int] = None
    depth: Optional[int] = None
    movetime: Optional[int] = None

    def kwargs(self):
        return {k: v for k, v in (("nodes", self.nodes), ("depth", self.depth), ("movetime", self.movetime)) if v}


@dataclass(frozen=True)
class Adjudication:
    resign_cp: int = 1000  # 0 disables
    resign_plies: int = 6
    draw_cp: int = 10  # 0 disables
    draw_plies: int = 12
    draw_min_ply: int = 80
    max_plies: int = 300


@dataclass
class GameResult:
    start_fen: str
    moves: list
    evals: list  # white-point-of-view centipawns per ply (None if the engine reported no score)
    result: str  # "1-0", "0-1", "1/2-1/2"
    reason: str
    white: str = ""
    black: str = ""
    error: Optional[str] = None  # set if an engine crashed / timed out / played an illegal move


# ---- pure helpers (unit-tested without any engine) -----------------------------------------------------------

def white_pov(kind, score, white_to_move):
    """Convert an engine score (side-to-move point of view) to White's point of view, in centipawns."""
    if kind is None or score is None:
        return None
    value = score if kind == "cp" else (MATE_CP - abs(score)) * (1 if score > 0 else -1)
    return value if white_to_move else -value


def check_adjudication(evals, adj):
    """Return (result, reason) if the game should end now on the evidence in `evals`, else None."""
    n = len(evals)
    if n >= adj.max_plies:
        return "1/2-1/2", "adjudicated: max plies"
    if adj.resign_cp and n >= adj.resign_plies:
        tail = evals[-adj.resign_plies:]
        if all(e is not None for e in tail):
            if all(e >= adj.resign_cp for e in tail):
                return "1-0", "adjudicated: winning evaluation"
            if all(e <= -adj.resign_cp for e in tail):
                return "0-1", "adjudicated: winning evaluation"
    if adj.draw_cp and n >= max(adj.draw_min_ply, adj.draw_plies):
        tail = evals[-adj.draw_plies:]
        if all(e is not None and abs(e) <= adj.draw_cp for e in tail):
            return "1/2-1/2", "adjudicated: drawn evaluation"
    return None


def a_points(game, a_is_white):
    """Points (1 / 0.5 / 0) that engine A scored in `game`."""
    if game.result == "1/2-1/2":
        return 0.5
    white_won = game.result == "1-0"
    return 1.0 if white_won == a_is_white else 0.0


def game_to_pgn(game, event="chessme match"):
    g = chess.pgn.Game()
    g.headers["Event"] = event
    g.headers["White"], g.headers["Black"] = game.white, game.black
    g.headers["Result"] = game.result
    g.headers["Termination"] = game.reason
    if game.start_fen != STARTPOS_FEN:
        g.setup(chess.Board(game.start_fen))
    node = g
    board = chess.Board(game.start_fen)
    for i, uci in enumerate(game.moves):
        move = chess.Move.from_uci(uci)
        node = node.add_variation(move)
        board.push(move)
        if i < len(game.evals) and game.evals[i] is not None:
            node.comment = f"{game.evals[i] / 100:+.2f}"
    return str(g)


# ---- playing games ------------------------------------------------------------------------------------------

def play_game(white, black, start_fen, limit, adj, timeout=120):
    """Play one game between two started UciEngine objects. Never raises for engine faults: it scores them."""
    board = chess.Board(start_fen)
    moves, evals = [], []
    res = GameResult(start_fen, moves, evals, "1/2-1/2", "", white.name, black.name)
    while True:
        outcome = board.outcome(claim_draw=True)
        if outcome:
            res.result, res.reason = outcome.result(), outcome.termination.name.lower()
            return res
        adjudicated = check_adjudication(evals, adj)
        if adjudicated:
            res.result, res.reason = adjudicated
            return res
        mover, mover_is_white = (white, True) if board.turn == chess.WHITE else (black, False)
        try:
            r = mover.go(start_fen, moves, timeout=timeout, **limit.kwargs())
            move = chess.Move.from_uci(r.bestmove)
        except (EngineError, ValueError) as e:
            res.result, res.reason, res.error = ("0-1" if mover_is_white else "1-0"), "engine error", f"{mover.name}: {e}"
            return res
        if move not in board.legal_moves:
            res.result, res.reason = ("0-1" if mover_is_white else "1-0"), "illegal move"
            res.error = f"{mover.name} played illegal move {r.bestmove}"
            return res
        evals.append(white_pov(r.score_kind, r.score, mover_is_white))
        board.push(move)
        moves.append(move.uci())


_ENGINE_CACHE = {}  # per worker process: started engines, reused across games


def _engine_for(spec):
    eng = _ENGINE_CACHE.get(spec)
    if eng is None or eng.proc is None or eng.proc.poll() is not None:
        eng = UciEngine(list(spec.command), options=dict(spec.options), name=spec.name).start()
        _ENGINE_CACHE[spec] = eng
    return eng


def _discard(spec):
    eng = _ENGINE_CACHE.pop(spec, None)
    if eng:
        eng.close()


def play_pair(job):
    """Worker: one opening, both colours. Returns (pair_index, [game with A white, game with B white])."""
    idx, fen, spec_a, spec_b, limit, adj = job
    games = []
    for a_white in (True, False):
        a, b = _engine_for(spec_a), _engine_for(spec_b)
        a.new_game(); b.new_game()
        g = play_game(a, b, fen, limit, adj) if a_white else play_game(b, a, fen, limit, adj)
        games.append(g)
        if g.error:  # restart whichever engine misbehaved
            _discard(spec_a); _discard(spec_b)
    return idx, games


# ---- running a match ----------------------------------------------------------------------------------------

@dataclass
class MatchResult:
    a: str
    b: str
    wins: int = 0
    draws: int = 0
    losses: int = 0
    penta: list = field(default_factory=lambda: [0, 0, 0, 0, 0])
    games: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    llr: float = 0.0
    status: Optional[str] = None
    elapsed: float = 0.0

    @property
    def pairs(self):
        return sum(self.penta)

    def summary(self, elo0=None, elo1=None):
        elo, err = sprt_mod.elo_estimate(self.penta)
        n = self.wins + self.draws + self.losses
        score = (self.wins + 0.5 * self.draws) / n if n else 0.5
        lines = [
            f"{self.a}  vs  {self.b}",
            f"games {n}  (W {self.wins} / D {self.draws} / L {self.losses})   score {100 * score:.1f}%",
            f"pairs {self.pairs}   penta [LL LD LW|DD WD WW] = {self.penta}",
            f"Elo {elo:+.1f} +/- {err:.1f} (95%)   LOS {100 * sprt_mod.los(self.penta):.1f}%",
        ]
        if elo0 is not None:
            lo, hi = sprt_mod.bounds()
            lines.append(f"SPRT [{elo0}, {elo1}]  LLR {self.llr:+.2f} (bounds {lo:.2f}, {hi:.2f})  -> {self.status or 'undecided'}")
        if self.errors:
            lines.append(f"engine faults: {len(self.errors)} (first: {self.errors[0]})")
        lines.append(f"time {self.elapsed:.1f}s")
        return "\n".join(lines)


def record_pair(result, games, sprt_params=None):
    g1, g2 = games  # g1: A white, g2: B white
    p1, p2 = a_points(g1, True), a_points(g2, False)
    for p in (p1, p2):
        if p == 1.0: result.wins += 1
        elif p == 0.5: result.draws += 1
        else: result.losses += 1
    result.penta[sprt_mod.penta_index(p1 + p2)] += 1
    result.games.extend(games)
    result.errors.extend(g.error for g in games if g.error)
    if sprt_params:
        elo0, elo1, alpha, beta = sprt_params
        result.llr = sprt_mod.llr(result.penta, elo0, elo1)
        result.status = sprt_mod.sprt_status(result.penta, elo0, elo1, alpha, beta)


def run_match(a, b, openings, limit, adj=Adjudication(), *, concurrency=1, max_pairs=None, sprt=None,
              pgn_path=None, progress=None):
    """Play up to `max_pairs` opening pairs of A vs B. `sprt` = (elo0, elo1[, alpha, beta]) stops early."""
    sprt_params = None
    if sprt:
        elo0, elo1, *rest = sprt
        sprt_params = (elo0, elo1, *(rest + [0.05, 0.05][len(rest):]))
    n = min(max_pairs or len(openings), len(openings))
    jobs = [(i, openings[i], a, b, limit, adj) for i in range(n)]
    result = MatchResult(a.name, b.name)
    t0 = time.time()

    def consume(item):
        _, games = item
        record_pair(result, games, sprt_params)
        if progress:
            progress(result)
        return result.status is not None

    if concurrency <= 1:
        try:
            for job in jobs:
                if consume(play_pair(job)):
                    break
        finally:
            for spec in (a, b):
                _discard(spec)
    else:
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(concurrency) as pool:
            for item in pool.imap_unordered(play_pair, jobs):
                if consume(item):
                    pool.terminate()
                    break
    result.elapsed = time.time() - t0
    if pgn_path:
        path = Path(pgn_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for g in result.games:
                f.write(game_to_pgn(g) + "\n\n")
    return result
