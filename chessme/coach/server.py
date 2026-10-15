"""The local coach: a small web server (standard library only) that serves one page and a JSON API. It listens on 127.0.0.1 only; games, sessions and the
player's mistakes stay in memory and on this machine (the only network use is fetching public games of a Lichess user when asked).

`CoachApp` holds the logic and is tested without HTTP; `serve` wraps it in a `ThreadingHTTPServer`. The engine is one Stockfish process behind a lock
(`EngineBackend`); tests pass a fake `search` instead."""
import io
import json
import re
import secrets
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import chess
import chess.pgn

from ..analysis import runner as AR
from . import drills as D
from . import exercises as X
from . import openings as OP
from . import profile as PR
from . import session as S

WEB = Path(__file__).parent / "web"
MAX_BODY = 2_000_000


class EngineBackend:
    """One Stockfish process shared by the analysis, the judge and the opponent (calls are serialised by a lock)."""

    def __init__(self, path=None, nodes=100_000, multipv=3):
        from ..uci_client import UciEngine
        path = path or shutil.which("stockfish")
        if not path:
            raise RuntimeError("Stockfish not found: install it or pass --engine")
        self.engine = UciEngine([path], options={"Threads": 1, "Hash": 64}).start()
        self._search = AR.engine_search(self.engine, nodes=nodes, multipv=multipv)
        self._lock = threading.Lock()

    def search(self, board):
        with self._lock:
            return self._search(board)

    def close(self):
        self.engine.close()


class CoachApp:
    def __init__(self, search, max_sessions=20, opponent_seed=0, drills=None, data_dir=None, explorer=None):
        self.search = search
        self.explorer = explorer                                       # path of the opening explorer database, or a callable rating -> replies(fen) (tests)
        self.openings = {}
        self.data_dir = Path(data_dir) if data_dir else None          # reviewed games are kept here (one small JSON each) for the weakness profile
        self.drills = drills if drills is not None else D.DrillStore()          # in memory unless a path is given
        self.sessions = {}
        self.max_sessions = max_sessions
        self.seed = opponent_seed

    # ---- games ------------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def games_in(pgn_text, limit=50):
        """[{index, white, black, result, date, plies}] for the games of a PGN text."""
        out, f = [], io.StringIO(pgn_text)
        while len(out) < limit and (g := chess.pgn.read_game(f)) is not None:
            h = g.headers
            out.append({"index": len(out), "white": h.get("White", "?"), "black": h.get("Black", "?"), "result": h.get("Result", "*"),
                        "date": h.get("UTCDate", h.get("Date", "")), "plies": sum(1 for _ in g.mainline_moves())})
        return out

    def start(self, pgn_text, index=0, color="white", max_n=5):
        """Analyse game `index` of the PGN and open a guided replay of the biggest mistakes of `color`. Returns {"session", "exercises", "view"}."""
        if color not in ("white", "black"):
            return {"error": "color must be white or black"}
        f = io.StringIO(pgn_text)
        game = None
        for _ in range(index + 1):
            game = chess.pgn.read_game(f)
            if game is None:
                return {"error": "no such game in the PGN"}
        if not any(True for _ in game.mainline_moves()):
            return {"error": "the game has no moves"}
        analysis = AR.analyse_game(game, self.search)
        self._keep(game, analysis, color)
        ex = [X.enrich(e, self.search) for e in X.from_analysis(game, analysis, color, max_n=max_n)]
        summary = analysis["summary"][color]
        if not ex:
            return {"error": None, "none": True, "message": "No move in this game gave away more than 10 points of expected score from a position that was still fair: nothing to replay.",
                    "accuracy": summary["accuracy"]}
        sid = secrets.token_urlsafe(8)
        if len(self.sessions) >= self.max_sessions:
            self.sessions.pop(next(iter(self.sessions)))
        replay = S.Replay(ex, S.Judge(self.search), S.EngineOpponent(self.search, seed=self.seed))
        self.sessions[sid] = replay
        return {"session": sid, "n": len(ex), "accuracy": summary["accuracy"], "classes": summary["classes"], "view": replay.view()}

    def _replies(self, rating):
        if self.explorer is None:
            return None
        return self.explorer(rating) if callable(self.explorer) else OP.explorer_replies(str(self.explorer), rating)

    def opening_start(self, pgn, color="white", rating=1500, max_plies=24):
        """Start a drill of the repertoire in `pgn` (variations welcome) for `color` against replies typical of `rating`."""
        replies = self._replies(int(rating))
        if replies is None:
            return {"error": "the opening explorer database is not set up (see docs/opening-explorer.md; start the coach with --explorer PATH)"}
        if color not in ("white", "black"):
            return {"error": "color must be white or black"}
        rep = OP.Repertoire.from_pgn(pgn, color)
        if rep.size == 0:
            return {"error": "no moves of your colour found in that PGN"}
        sid = secrets.token_urlsafe(8)
        if len(self.openings) >= self.max_sessions:
            self.openings.pop(next(iter(self.openings)))
        self.openings[sid] = OP.OpeningDrill(rep, replies, max_plies=int(max_plies), seed=self.seed + len(self.openings))
        return {"session": sid, "moves": rep.size, "view": self.openings[sid].view()}

    def opening_move(self, sid, uci):
        d = self.openings.get(sid)
        return {"error": "unknown session"} if d is None else d.move(uci)

    def opening_coverage(self, pgn, color="white", rating=1500):
        replies = self._replies(int(rating))
        if replies is None:
            return {"error": "the opening explorer database is not set up"}
        rep = OP.Repertoire.from_pgn(pgn, color)
        return OP.coverage(rep, replies) if rep.size else {"error": "no moves of your colour found in that PGN"}

    def _keep(self, game, analysis, color):
        if self.data_dir is None:
            return
        d = self.data_dir / "games"
        d.mkdir(parents=True, exist_ok=True)
        key = AR.game_key(game)                                             # the same game reviewed twice is stored once
        (d / f"{key}.json").write_text(json.dumps({"color": color, "moves": analysis["moves"]}), encoding="utf-8")

    def profile(self):
        """The weakness profile over all stored games, with plain sentences."""
        rows, games = [], 0
        for path in sorted((self.data_dir / "games").glob("*.json")) if self.data_dir and (self.data_dir / "games").exists() else []:
            rec = json.loads(path.read_text(encoding="utf-8"))
            rows += PR.player_rows({"moves": rec["moves"]}, rec["color"])
            games += 1
        prof = PR.profile(rows)
        prof["games"] = games
        prof["sentences"] = PR.sentences(prof)
        return prof

    def start_drills(self, limit=10):
        """A replay of the mistake positions that are due."""
        ex = self.drills.due(limit=limit)
        if not ex:
            return {"none": True, "message": "Nothing is due. Review a game, and the positions you missed come back here.", "stats": self.drills.stats()}
        sid = secrets.token_urlsafe(8)
        if len(self.sessions) >= self.max_sessions:
            self.sessions.pop(next(iter(self.sessions)))
        replay = S.Replay(ex, S.Judge(self.search), S.EngineOpponent(self.search, seed=self.seed))
        self.sessions[sid] = replay
        return {"session": sid, "n": len(ex), "view": replay.view(), "stats": self.drills.stats()}

    # ---- a session ------------------------------------------------------------------------------------------------------------------------
    def act(self, sid, action, payload=None):
        r = self.sessions.get(sid)
        if r is None:
            return {"error": "unknown session (it may have been closed)"}
        payload = payload or {}
        if action == "hint":
            out = r.hint()
        elif action == "attempt":
            ex, hints, tries = r.ex, r.hints_used, r.tries
            out = r.attempt(str(payload.get("uci", "")))
            if ex is not None and out.get("verdict") in ("found", "ok"):
                self.drills.record(ex, success=hints == 0 and tries == 0)         # first try, no hint (tries counts attempts before this one)
        elif action == "reveal":
            ex = r.ex
            out = r.reveal()
            if ex is not None and out.get("verdict") == "revealed":
                self.drills.record(ex, success=False)
        elif action == "play":
            out = r.play(str(payload.get("uci", "")))
        elif action == "reset":
            out = r.reset()
        elif action == "next":
            if r.ex is not None and r.mode == "find":                                # skipped without finding it: counts as missed
                self.drills.record(r.ex, success=False)
            out = r.next()
        elif action == "view":
            out = {}
        else:
            return {"error": "unknown action"}
        out["view"] = r.view()
        return out


def lichess_games(user, max_games=10, timeout=30):
    """Public games of a Lichess user as PGN text: one request, no token."""
    import requests
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,30}", user or ""):
        raise ValueError("not a Lichess user name")
    r = requests.get(f"https://lichess.org/api/games/user/{user}", params={"max": max(1, min(int(max_games), 30)), "opening": "true", "clocks": "false", "evals": "false"},
                     headers={"Accept": "application/x-chess-pgn", "User-Agent": "MeChess-coach"}, timeout=timeout)
    r.raise_for_status()
    return r.text


def make_handler(app, fetch=lichess_games):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._send(413, {"error": "too large"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._send(400, {"error": "bad JSON"})
            path = self.path.split("?")[0]
            try:
                if path == "/api/games":
                    text = body.get("pgn") or fetch(body.get("user", ""), body.get("max", 10))
                    return self._send(200, {"games": app.games_in(text), "pgn": text})
                if path == "/api/opening/start":
                    return self._send(200, app.opening_start(body.get("pgn", ""), body.get("color", "white"), body.get("rating", 1500)))
                if path == "/api/opening/coverage":
                    return self._send(200, app.opening_coverage(body.get("pgn", ""), body.get("color", "white"), body.get("rating", 1500)))
                m2 = re.fullmatch(r"/api/opening/([\w-]+)/move", path)
                if m2:
                    return self._send(200, app.opening_move(m2.group(1), str(body.get("uci", ""))))
                if path == "/api/profile":
                    return self._send(200, app.profile())
                if path == "/api/drills":
                    return self._send(200, app.drills.stats())
                if path == "/api/drills/start":
                    return self._send(200, app.start_drills(int(body.get("limit", 10))))
                if path == "/api/start":
                    return self._send(200, app.start(body.get("pgn", ""), int(body.get("index", 0)), body.get("color", "white"), int(body.get("max_n", 5))))
                m = re.fullmatch(r"/api/replay/([\w-]+)/(\w+)", path)
                if m:
                    return self._send(200, app.act(m.group(1), m.group(2), body))
            except Exception as e:                                        # never a stack trace to the page
                return self._send(500, {"error": f"{type(e).__name__}: {e}"})
            return self._send(404, {"error": "not found"})
    return Handler


def serve(app, host="127.0.0.1", port=8765, fetch=lichess_games):
    """Run the app (blocking). Returns the server object when `port` is 0 is not supported here: use `make_server` in tests."""
    srv = ThreadingHTTPServer((host, port), make_handler(app, fetch))
    print(f"MeChess coach on http://{host}:{srv.server_address[1]}  (Ctrl+C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def make_server(app, host="127.0.0.1", port=0, fetch=lichess_games):
    return ThreadingHTTPServer((host, port), make_handler(app, fetch))
