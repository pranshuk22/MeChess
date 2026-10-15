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
from . import endgames as EG
from . import exercises as X
from . import openings as OP
from . import profile as PR
from . import reference as REF
from . import session as S
from . import steering as ST

WEB = Path(__file__).parent / "web"
MAX_BODY = 2_000_000


class EngineBackend:
    """One Stockfish process shared by the analysis, the judge and the opponent (calls are serialised by a lock)."""

    def __init__(self, path=None, nodes=100_000, multipv=5):
        from ..uci_client import UciEngine
        path = path or shutil.which("stockfish")
        if not path:
            raise RuntimeError("Stockfish not found: install it or pass --engine")
        self.engine = UciEngine([path], options={"Threads": 1, "Hash": 64}).start()
        self._search = AR.engine_search(self.engine, nodes=nodes, multipv=multipv)
        self.nodes, self.multipv = nodes, multipv
        self._lock = threading.Lock()

    def search(self, board):
        with self._lock:
            return self._search(board)

    def close(self):
        self.engine.close()


class CoachApp:
    def __init__(self, search, max_sessions=20, opponent_seed=0, drills=None, data_dir=None, explorer=None, tablebase=None, reference=None, nodes=None, multipv=None):
        self.search = search
        self.explorer = explorer                                       # path of the opening explorer database, or a callable rating -> replies(fen) (tests)
        self.openings = {}
        self.tablebase = tablebase                                     # a chess.syzygy.Tablebase (or anything with probe_wdl / probe_dtz), or None
        self.endgames = {}
        self.steered = {}
        self.data_dir = Path(data_dir) if data_dir else None          # reviewed games are kept here (one small JSON each) for the weakness profile
        self.drills = drills if drills is not None else D.DrillStore()          # in memory unless a path is given
        self.reference = reference                                     # reference rates of players by rating (`reference.load()`), or None
        self.nodes, self.multipv = nodes, multipv                      # the settings of this analysis, to tell whether the reference is comparable
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
        return self._review(game, AR.analyse_game(game, self.search), color, max_n)

    def _review(self, game, analysis, color, max_n=5):
        """Store the analysed game and open a guided replay of the biggest mistakes of `color`."""
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

    def steer_start(self, color="white", foci=None, seed=None):
        foci = {k: float(v) for k, v in (foci or {}).items() if float(v) > 0}
        if color not in ("white", "black"):
            return {"error": "color must be white or black"}
        if not foci:
            return {"error": "choose at least one thing to practise"}
        if any(k not in ST.FOCI for k in foci):
            return {"error": "unknown focus"}
        sid = secrets.token_urlsafe(8)
        if len(self.steered) >= self.max_sessions:
            self.steered.pop(next(iter(self.steered)))
        self.steered[sid] = ST.SteeredGame(self.search, color, foci, seed=secrets.randbits(16) if seed is None else seed)
        return {"session": sid, "view": self.steered[sid].view(), "tips": [ST.FOCI[f]["tip"] for f in foci]}

    def steer_move(self, sid, uci):
        g = self.steered.get(sid)
        return {"error": "unknown session"} if g is None else g.move(uci)

    def steer_finish(self, sid, max_n=5):
        """End the game, analyse it, report how the player did in the situations the opponent steered toward and open the guided replay of the biggest mistakes."""
        g = self.steered.get(sid)
        if g is None:
            return {"error": "unknown session"}
        g.finish()
        if not g.board.move_stack:
            return {"error": "no moves were played"}
        game = chess.pgn.read_game(io.StringIO(g.pgn()))
        color = "white" if g.player == chess.WHITE else "black"
        analysis = AR.analyse_game(game, self.search)
        stats, lines = ST.focus_report(game, analysis, color, g.opponent.hits, g.foci)
        out = self._review(game, analysis, color, max_n)
        out["focus"], out["focus_lines"], out["result"] = stats, lines, g.result()
        return out

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

    def endgame_themes(self):
        return [{"id": k, "title": v["title"], "available": self.tablebase is not None and EG.available(self.tablebase, k)} for k, v in EG.THEMES.items()]

    def endgame_start(self, theme):
        if self.tablebase is None:
            return {"error": "no tablebase set up: download Syzygy files and start the coach with --syzygy DIR"}
        if theme not in EG.THEMES:
            return {"error": "unknown theme"}
        if not EG.available(self.tablebase, theme):
            return {"error": "the tablebase files for this theme are not in the folder"}
        g = EG.generate(theme, self.tablebase, __import__("random").Random(secrets.randbits(32)))
        if g is None:
            return {"error": "could not find a start position"}
        sid = secrets.token_urlsafe(8)
        if len(self.endgames) >= self.max_sessions:
            self.endgames.pop(next(iter(self.endgames)))
        self.endgames[sid] = EG.EndgameDrill(theme, self.tablebase, g[0], g[1], seed=secrets.randbits(16))
        return {"session": sid, "view": self.endgames[sid].view()}

    def endgame_act(self, sid, action, payload):
        d = self.endgames.get(sid)
        if d is None:
            return {"error": "unknown session"}
        if action == "move":
            return d.move(str(payload.get("uci", "")))
        if action == "hint":
            return {"hint": d.hint(int(payload.get("level", 1))), "view": d.view()}
        return {"error": "unknown action"}

    def _keep(self, game, analysis, color):
        if self.data_dir is None:
            return
        d = self.data_dir / "games"
        d.mkdir(parents=True, exist_ok=True)
        key = AR.game_key(game)                                             # the same game reviewed twice is stored once
        h = game.headers
        rec = {"color": color, "moves": analysis["moves"], "speed": REF.speed_of(h)}
        try:
            rec["rating"] = int(h["WhiteElo" if color == "white" else "BlackElo"])
        except (KeyError, ValueError):
            pass                                                            # a game without ratings is kept, only the comparison with other players skips it
        (d / f"{key}.json").write_text(json.dumps(rec), encoding="utf-8")

    def profile(self):
        """The weakness profile over all stored games, with plain sentences, and the comparison with players of the same rating when a reference exists."""
        rows, games, rated = [], 0, {}
        for path in sorted((self.data_dir / "games").glob("*.json")) if self.data_dir and (self.data_dir / "games").exists() else []:
            rec = json.loads(path.read_text(encoding="utf-8"))
            mine = PR.player_rows({"moves": rec["moves"]}, rec["color"])
            rows += mine
            games += 1
            if rec.get("rating") and rec.get("speed"):
                rated.setdefault(rec["speed"], []).append((rec["rating"], mine))
        prof = PR.profile(rows)
        prof["games"] = games
        prof["sentences"] = PR.sentences(prof)
        if self.reference and rated:
            speed = max(rated, key=lambda k: len(rated[k]))                 # the speed played most: ratings of different speeds are not the same scale
            ratings = sorted(r for r, _ in rated[speed])
            cmp = REF.compare([r for _, mine in rated[speed] for r in mine], ratings[len(ratings) // 2], speed, self.reference, nodes=self.nodes, multipv=self.multipv)
            if cmp:
                prof["reference"] = cmp
                prof["sentences"] += REF.sentences(cmp)
        return prof

    def steer_suggest(self):
        """The foci that fit the player's weaknesses, with the reason for each."""
        prof = self.profile()
        return {"foci": [{"id": f, "title": ST.FOCI[f]["title"], "reason": r} for f, r in PR.suggest_foci(prof)], "games": prof["games"]}

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


def chesscom_games(user, max_games=10, timeout=30):
    """Public games of a Chess.com user as PGN text: the latest monthly archives, newest first, until `max_games` games are collected."""
    import requests
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,30}", user or ""):
        raise ValueError("not a Chess.com user name")
    headers = {"User-Agent": "MeChess-coach (local study tool)"}
    base = f"https://api.chess.com/pub/player/{user.lower()}/games/archives"
    r = requests.get(base, headers=headers, timeout=timeout)
    r.raise_for_status()
    pgns = []
    for url in reversed(r.json().get("archives", [])):
        if len(pgns) >= max_games:
            break
        a = requests.get(url, headers=headers, timeout=timeout)
        a.raise_for_status()
        games = [g["pgn"] for g in a.json().get("games", []) if g.get("pgn") and g.get("rules", "chess") == "chess"]
        pgns += list(reversed(games))
    return "\n\n".join(pgns[:max(1, min(int(max_games), 30))])


def fetch_games(platform, user, max_games=10):
    if platform == "chesscom":
        return chesscom_games(user, max_games)
    return lichess_games(user, max_games)


def make_handler(app, fetch=fetch_games):
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
                    text = body.get("pgn") or fetch(body.get("platform", "lichess"), body.get("user", ""), body.get("max", 10))
                    return self._send(200, {"games": app.games_in(text), "pgn": text})
                if path == "/api/steer/suggest":
                    return self._send(200, app.steer_suggest())
                if path == "/api/steer/foci":
                    return self._send(200, {"foci": [{"id": k, "title": v["title"], "tip": v["tip"]} for k, v in ST.FOCI.items()]})
                if path == "/api/steer/start":
                    return self._send(200, app.steer_start(body.get("color", "white"), body.get("foci")))
                m4 = re.fullmatch(r"/api/steer/([\w-]+)/(move|finish)", path)
                if m4:
                    return self._send(200, app.steer_move(m4.group(1), str(body.get("uci", ""))) if m4.group(2) == "move" else app.steer_finish(m4.group(1)))
                if path == "/api/endgame/themes":
                    return self._send(200, {"themes": app.endgame_themes()})
                if path == "/api/endgame/start":
                    return self._send(200, app.endgame_start(body.get("theme", "")))
                m3 = re.fullmatch(r"/api/endgame/([\w-]+)/(move|hint)", path)
                if m3:
                    return self._send(200, app.endgame_act(m3.group(1), m3.group(2), body))
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


def serve(app, host="127.0.0.1", port=8765, fetch=fetch_games):
    """Run the app (blocking). Returns the server object when `port` is 0 is not supported here: use `make_server` in tests."""
    srv = ThreadingHTTPServer((host, port), make_handler(app, fetch))
    print(f"MeChess coach on http://{host}:{srv.server_address[1]}  (Ctrl+C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def make_server(app, host="127.0.0.1", port=0, fetch=fetch_games):
    return ThreadingHTTPServer((host, port), make_handler(app, fetch))
