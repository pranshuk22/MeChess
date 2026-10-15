"""The app: API under /api, the built frontend for everything else, one SQLite file, local only."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from . import db as DB
from .config import AppConfig
from .jobs import JobManager
from .routers import api
from .security import LocalOnly, allowed

HERE = Path(__file__).parent


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
        DB.migrate(config.db_url)
        engine = DB.make_engine(config.db_url)
        app.state.engine = engine
        app.state.sessions = DB.session_factory(engine)
        app.state.jobs = JobManager(app.state.sessions)
        yield
        app.state.jobs.shutdown()
        engine.dispose()

    app = FastAPI(title="MeChess", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.config = config
    hosts, origins = allowed(config.host, config.port, extra_hosts, extra_origins)
    app.add_middleware(LocalOnly, hosts=hosts, origins=origins)
    app.include_router(api.router)

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
