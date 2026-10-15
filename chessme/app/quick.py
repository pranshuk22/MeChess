"""A small shared engine for short questions (judging a move in a drill, an endgame, the opponent of a steered game): one Stockfish process, calls serialised by a lock.
`search(board)` is the same kind of function the analysis code uses (the engine's best lines at a node budget), with the opening cache in front."""
import threading

import chess

from ..analysis import runner as AR
from ..uci_client import UciEngine
from .config import AppConfig
from .services import cache as CA
from .workspace import find_engine

NODES = 20_000
MULTIPV = 2


class QuickEngine:
    def __init__(self, config: AppConfig, session_factory):
        self.config, self.sf = config, session_factory
        self._eng: UciEngine | None = None
        self._lock = threading.Lock()
        self._search = None

    def _start(self, engine_path):
        path = find_engine(self.config, engine_path)
        if path is None:
            raise RuntimeError("Stockfish was not found: install it or set its path in Settings")
        if self._eng is None or self._eng.proc.poll() is not None:
            self._eng = UciEngine([path], options={"Threads": 1, "Hash": 64}).start()
            raw = AR.engine_search(self._eng, nodes=NODES, multipv=MULTIPV)
            self._search = CA.CachedSearch(raw, self.sf, nodes=NODES, multipv=MULTIPV, engine="Stockfish", source="analysis")
        return self._search

    def searcher(self, engine_path=None):
        """A `search(board)` callable that is safe to call from several threads."""
        def search(board: chess.Board):
            with self._lock:
                return self._start(engine_path)(board)
        return search

    def close(self):
        with self._lock:
            if self._eng is not None:
                self._eng.close()
                self._eng = None
