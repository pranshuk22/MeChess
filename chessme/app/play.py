"""Playing against the computer: Stockfish at eight levels, or the MeChess controller (book + engine candidates + a rating dial that plays human-like mistakes).
Games are kept in memory while they last; a finished game is saved to the library (and analysed in the background when an engine is available)."""
import random
import sys
import threading
import uuid
from datetime import date

import chess
import chess.pgn

from ..uci_client import UciEngine
from .config import AppConfig
from .workspace import find_engine

# level: (label, Stockfish skill level, search nodes (None: 1 second), chance of a random move)
STOCKFISH_LEVELS = {
    1: ("Beginner", 0, 1, 0.30), 2: ("Casual", 2, 10, 0.15), 3: ("Club", 4, 50, 0.07), 4: ("Intermediate", 7, 200, 0.0),
    5: ("Advanced", 10, 1000, 0.0), 6: ("Strong", 14, 5000, 0.0), 7: ("Expert", 18, 20000, 0.0), 8: ("Maximum", 20, None, 0.0),
}
MECHESS_ELO = (800, 2600)
MAX_SESSIONS = 20


class PlayError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


class Opponent:
    """Something that answers a position with a move."""
    label = "Opponent"

    def move(self, board: chess.Board) -> chess.Move:
        raise NotImplementedError

    def close(self):
        pass


class StockfishOpponent(Opponent):
    def __init__(self, engine, level: int, lock: threading.Lock):
        self.engine, self.level, self.lock = engine, level, lock
        self.label = f"Stockfish, {STOCKFISH_LEVELS[level][0].lower()} level"
        self.rng = random.Random()

    def move(self, board):
        _, skill, nodes, rnd = STOCKFISH_LEVELS[self.level]
        if rnd and self.rng.random() < rnd:
            return self.rng.choice(list(board.legal_moves))
        with self.lock:
            self.engine._send(f"setoption name Skill Level value {skill}")
            res = self.engine.go(board.root().fen(), [m.uci() for m in board.move_stack], nodes=nodes) if nodes else self.engine.go(board.root().fen(), [m.uci() for m in board.move_stack], movetime=1000)
        return chess.Move.from_uci(res.bestmove)

    def close(self):
        pass                                                                      # the engine is shared


class MeChessOpponent(Opponent):
    """The MeChess controller as a UCI engine of its own (one process per game)."""

    def __init__(self, elo: int, config: AppConfig, prior: str = "uniform"):
        self.label = f"MeChess, about {elo}"
        book = config.explorer_path.parent if config.explorer_path.is_file() else None
        cmd = [sys.executable, "-m", "chessme", "mechess", "--elo", str(elo), "--prior", prior] + (["--book", str(book)] if book else [])
        self.engine = UciEngine(cmd).start()

    def move(self, board):
        res = self.engine.go(board.root().fen(), [m.uci() for m in board.move_stack], movetime=400)
        return chess.Move.from_uci(res.bestmove)

    def close(self):
        self.engine.close()


class Session:
    def __init__(self, sid, colour, opponent, opponent_kind, level):
        self.id, self.colour, self.opponent, self.kind, self.level = sid, colour, opponent, opponent_kind, level
        self.board = chess.Board()
        self.result: str | None = None
        self.reason: str | None = None
        self.game_id: str | None = None
        self.lock = threading.Lock()

    @property
    def over(self):
        return self.result is not None

    def moves(self):
        b = chess.Board()
        out = []
        for m in self.board.move_stack:
            out.append({"uci": m.uci(), "san": b.san(m)})
            b.push(m)
        return out

    def state(self):
        return {"id": self.id, "fen": self.board.fen(), "colour": self.colour, "turn": "white" if self.board.turn else "black", "moves": self.moves(),
                "status": "over" if self.over else "playing", "result": self.result, "reason": self.reason, "gameId": self.game_id, "opponent": self.opponent.label,
                "inCheck": self.board.is_check()}

    def check_end(self):
        out = self.board.outcome(claim_draw=True)
        if out is not None:
            self.result = out.result()
            self.reason = {chess.Termination.CHECKMATE: "checkmate", chess.Termination.STALEMATE: "stalemate", chess.Termination.INSUFFICIENT_MATERIAL: "insufficient material",
                           chess.Termination.FIFTY_MOVES: "the fifty-move rule", chess.Termination.THREEFOLD_REPETITION: "repetition"}.get(out.termination, out.termination.name.lower().replace("_", " "))
        return self.over

    def pgn(self):
        game = chess.pgn.Game()
        you, opp = "You", self.opponent.label
        game.headers.update({"Event": "Casual game against the computer", "Site": "MeChess", "Date": date.today().strftime("%Y.%m.%d"), "White": you if self.colour == "white" else opp,
                             "Black": opp if self.colour == "white" else you, "Result": self.result or "*"})
        node = game
        for m in self.board.move_stack:
            node = node.add_variation(m)
        return game


class PlayService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.sessions: dict[str, Session] = {}
        self._sf: UciEngine | None = None
        self._sf_lock = threading.Lock()
        self._guard = threading.Lock()

    def options(self, settings_engine_path=None):
        sf = find_engine(self.config, settings_engine_path) is not None
        from ..cli import ENGINE_BIN
        mech = ENGINE_BIN.exists()
        return {"stockfish": {"available": sf, "levels": [{"id": k, "label": v[0]} for k, v in STOCKFISH_LEVELS.items()]},
                "mechess": {"available": mech, "min": MECHESS_ELO[0], "max": MECHESS_ELO[1]}}

    def _stockfish(self, settings_engine_path):
        with self._guard:
            if self._sf is None or self._sf.proc.poll() is not None:
                path = find_engine(self.config, settings_engine_path)
                if path is None:
                    raise PlayError(409, "Stockfish was not found: install it or set its path in Settings")
                self._sf = UciEngine([path], options={"Threads": 1, "Hash": 64}).start()
            return self._sf

    def start(self, colour: str, kind: str, level: int, settings_engine_path=None):
        if colour == "random":
            colour = random.choice(["white", "black"])
        if colour not in ("white", "black"):
            raise PlayError(422, "colour must be white, black or random")
        if kind == "stockfish":
            if level not in STOCKFISH_LEVELS:
                raise PlayError(422, "unknown level")
            opponent: Opponent = StockfishOpponent(self._stockfish(settings_engine_path), level, self._sf_lock)
        elif kind == "mechess":
            if not MECHESS_ELO[0] <= level <= MECHESS_ELO[1]:
                raise PlayError(422, f"the rating must be between {MECHESS_ELO[0]} and {MECHESS_ELO[1]}")
            try:
                opponent = MeChessOpponent(level, self.config)
            except Exception as e:
                raise PlayError(409, f"MeChess could not be started (build the engine with `make -C engine`): {e}")
        else:
            raise PlayError(422, "opponent must be stockfish or mechess")
        with self._guard:
            while len(self.sessions) >= MAX_SESSIONS:                               # the oldest game makes room
                old = self.sessions.pop(next(iter(self.sessions)))
                old.opponent.close()
        s = Session(uuid.uuid4().hex[:10], colour, opponent, kind, level)
        self.sessions[s.id] = s
        if colour == "black":
            self._reply(s)
        return s

    def get(self, sid) -> Session:
        s = self.sessions.get(sid)
        if s is None:
            raise PlayError(404, "no such game (it may have been closed)")
        return s

    def _reply(self, s: Session):
        if s.over or s.board.turn == (s.colour == "white"):
            return
        mv = s.opponent.move(s.board)
        if mv not in s.board.legal_moves:                                           # an engine answer that is not legal must not corrupt the game
            mv = random.choice(list(s.board.legal_moves))
        s.board.push(mv)
        s.check_end()

    def move(self, sid, uci: str) -> Session:
        s = self.get(sid)
        with s.lock:
            if s.over:
                raise PlayError(409, "the game is over")
            if s.board.turn != (s.colour == "white"):
                raise PlayError(409, "it is not your move")
            try:
                mv = chess.Move.from_uci(uci)
            except ValueError:
                raise PlayError(422, "that is not a move")
            if mv not in s.board.legal_moves:
                raise PlayError(422, "that move is not legal")
            s.board.push(mv)
            if not s.check_end():
                self._reply(s)
        return s

    def takeback(self, sid) -> Session:
        s = self.get(sid)
        with s.lock:
            if s.over:
                raise PlayError(409, "the game is over")
            undo = 2 if s.board.turn == (s.colour == "white") else 1                 # back to your own turn
            if len(s.board.move_stack) < undo or not s.board.move_stack:
                raise PlayError(409, "nothing to take back")
            for _ in range(min(undo, len(s.board.move_stack))):
                s.board.pop()
        return s

    def resign(self, sid) -> Session:
        s = self.get(sid)
        with s.lock:
            if not s.over:
                s.result = "0-1" if s.colour == "white" else "1-0"
                s.reason = "resignation"
        return s

    def close(self):
        for s in self.sessions.values():
            s.opponent.close()
        self.sessions.clear()
        if self._sf is not None:
            self._sf.close()
            self._sf = None
