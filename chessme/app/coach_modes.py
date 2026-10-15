"""The coach's guided modes (opening practice, endgames with tablebases, steered games) on top of `coach.server.CoachApp`, whose sessions live in memory. The app adds the
parts that need its database: saved repertoires, and a finished steered game that is saved to the library with its analysis and its mistakes as practice positions."""
import io
import threading

import chess
import chess.pgn
from sqlalchemy.orm import Session

from ..analysis import runner as AR
from ..coach import server as CS
from ..coach import steering as ST
from .models import Analysis, Game
from .services import coach as CO
from .services import games as G


class ModeError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.message, self.status = message, status


class CoachModes:
    def __init__(self, config, sessions, quick):
        self.config, self.sessions, self.quick = config, sessions, quick
        self._app: CS.CoachApp | None = None
        self._tb = None
        self.tablebase_override = None                                           # tests give a fake tablebase
        self._lock = threading.RLock()
        self.engine_path = None

    def _coach(self) -> CS.CoachApp:
        if self._app is None:
            search = lambda board: self.quick.searcher(self.engine_path)(board)       # noqa: E731
            explorer = self.config.explorer_path if self.config.explorer_path.is_file() else None
            tb = self.tablebase_override
            if tb is None and self.config.syzygy_dir.is_dir() and any(self.config.syzygy_dir.iterdir()):
                import chess.syzygy
                tb = self._tb = chess.syzygy.open_tablebase(str(self.config.syzygy_dir))
            self._app = CS.CoachApp(search, explorer=explorer, tablebase=tb)
        return self._app

    def status(self):
        a = self._coach()
        return {"explorer": a.explorer is not None, "tablebase": a.tablebase is not None}

    @staticmethod
    def _check(res):
        if isinstance(res, dict) and res.get("error"):
            raise ModeError(res["error"], 404 if "unknown session" in res["error"] else 422)
        return res

    def call(self, method: str, *args, **kw):
        with self._lock:
            return self._check(getattr(self._coach(), method)(*args, **kw))

    def finish_steered(self, sid: str, colour_hint=None) -> dict:
        """End a steered game: analyse it, report on the situations the opponent steered toward, save game and analysis, add the mistakes as practice positions."""
        with self._lock:
            app = self._coach()
            g = app.steered.get(sid)
            if g is None:
                raise ModeError("unknown session", 404)
            g.finish()
            if not g.board.move_stack:
                raise ModeError("no moves were played", 422)
            game = chess.pgn.read_game(io.StringIO(g.pgn()))
            colour = "white" if g.player == chess.WHITE else "black"
            analysis = AR.analyse_game(game, app.search)
            stats, lines = ST.focus_report(game, analysis, colour, g.opponent.hits, g.foci)
            result = g.result()
        import hashlib
        gid = "steer:" + hashlib.sha1((sid + g.pgn()).encode()).hexdigest()[:12]
        with self.sessions() as s:
            added = self._save(s, gid, game, analysis, colour)
            s.commit()
        return {"focus": stats, "focus_lines": lines, "result": result, "gameId": gid, "drillsAdded": added}

    @staticmethod
    def _save(s: Session, gid, game, analysis, colour) -> int:
        headers = dict(game.headers)
        headers["Event"] = "Steered practice game"
        G.store(s, id=gid, source="steer", headers=headers, user_colour=colour, analysis=analysis, nodes=20_000, multipv=2, pgn=str(game), uci_moves=[m.uci() for m in game.mainline_moves()])
        s.flush()
        row, a = s.get(Game, gid), s.get(Analysis, gid)
        return CO.add_game_drills(s, row, a) if row and a else 0

    def close(self):
        if self._tb is not None:
            try:
                self._tb.close()
            except Exception:
                pass
