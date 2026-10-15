"""The app: API under /api, the built frontend for everything else, one SQLite file, local only."""
import hmac
from contextlib import asynccontextmanager
from pathlib import Path

import threading

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from ..coach import reference as REF
from . import db as DB
from .config import AppConfig
from .jobs import JobManager
from . import importers
from .live import LiveManager
from .play import PlayService
from .bot_service import BotService
from .coach_modes import CoachModes
from .quick import QuickEngine
from .routers import api, books, bot, coach, coach_modes, live, play, themes
from .security import COOKIE, LocalOnly, SecurityHeaders, TokenAuth, allowed, key_ok

HERE = Path(__file__).parent


def _lock_folder(folder: Path):
    """Hold a lock on the data folder while the app runs, so that a second app cannot mark the first one's jobs as interrupted. (No lock where `fcntl` is missing.)"""
    try:
        import fcntl
    except ImportError:
        return None
    f = open(folder / ".lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        raise RuntimeError(f"another MeChess is already using {folder}: close it first (or use another --data-dir)")
    return f


def static_dir() -> Path | None:
    """The built frontend: packaged with the app, or `frontend/dist` in a source checkout."""
    for d in (HERE / "static", HERE.parent.parent / "frontend" / "dist"):
        if (d / "index.html").is_file():
            return d
    return None


def create_app(config: AppConfig | None = None, *, extra_hosts=(), extra_origins=(), static: Path | None | bool = True) -> FastAPI:
    config = config or AppConfig()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config.data_dir.mkdir(parents=True, exist_ok=True)
        lock = _lock_folder(config.data_dir)                                    # one app per data folder
        DB.migrate(config.db_url)
        engine = DB.make_engine(config.db_url)
        app.state.engine = engine
        app.state.sessions = DB.session_factory(engine)
        app.state.jobs = JobManager(app.state.sessions)
        app.state.live = LiveManager()
        app.state.play = PlayService(config)
        app.state.quick = QuickEngine(config, app.state.sessions)
        app.state.modes = CoachModes(config, app.state.sessions, app.state.quick)
        app.state.bot = BotService(config.bot_dir)
        app.state.reference = REF.load()
        yield
        app.state.bot.close()
        app.state.modes.close()
        app.state.quick.close()
        app.state.play.close()
        app.state.live.close()
        app.state.jobs.shutdown()
        engine.dispose()
        if lock is not None:
            lock.close()

    app = FastAPI(title="MeChess", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.config = config
    app.state.site_locks = {"lichess": threading.Lock(), "chesscom": threading.Lock()}        # one import at a time per site
    app.state.fetchers = {"lichess": importers.lichess_games, "chesscom": importers.chesscom_games}      # replaced in tests
    app.state.engine_factory = lambda settings: None                                                        # tests pass a fake engine; None: start Stockfish
    hosts, origins = allowed(config.host, config.port, extra_hosts, extra_origins)
    app.add_middleware(TokenAuth, token=config.token)
    app.add_middleware(SecurityHeaders)
    app.add_middleware(LocalOnly, hosts=hosts, origins=origins)
    app.include_router(api.router)

    @app.get("/api/health")
    def health(request: Request):
        return {"ok": True, "auth": key_ok({k.decode().lower(): v.decode() for k, v in request.scope["headers"]}, config.token)}

    @app.post("/api/session", status_code=204)
    def session(body: dict, response: Response):
        if config.token is not None:
            if not hmac.compare_digest(str(body.get("token", "")).encode(), config.token.encode()):
                raise HTTPException(403, "wrong key")
            response.set_cookie(COOKIE, config.token, httponly=True, samesite="strict", path="/", max_age=60 * 60 * 24 * 30)

    app.include_router(live.router)
    app.include_router(coach.router)
    app.include_router(coach_modes.router)
    app.include_router(bot.router)
    app.include_router(books.router)
    app.include_router(play.router)
    app.include_router(themes.router)

    root = static_dir() if static is True else (static or None)
    if root:
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            f = (root / path).resolve()
            if path and f.is_file() and root.resolve() in f.parents:             # never a file outside the frontend folder
                return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"} if "/assets/" in f"/{path}" else None)
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})
    return app
