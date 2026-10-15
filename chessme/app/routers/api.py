import asyncio
import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import analysis_job, cache_job, importers, legacy, workspace
from ..models import Game, Setting
from ..schemas import CacheBuild, CacheStats, Stats, Accounts, AnalyseRequest, GameDetail, GamePage, ImportPgn, ImportUser, JobOut, Settings, SettingsPatch, Workspace
from ..services import games as G
from ..services import cache as CA
from ..services import stats as ST

router = APIRouter(prefix="/api")


def db(request: Request):
    with request.app.state.sessions() as s:
        yield s


def current_settings(s: Session) -> Settings:
    row = s.get(Setting, "app")
    return Settings(**(row.value if row else {}))


# ---- games ---------------------------------------------------------------------------------------------------------------------------------------

@router.get("/games", response_model=GamePage)
def list_games(q: str | None = None, colour: str | None = None, result: str | None = None, analysed: bool | None = None,
               limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), s: Session = Depends(db)):
    total, items = G.page(s, q=q, colour=colour, result=result, analysed=analysed, limit=limit, offset=offset)
    return {"total": total, "items": items}


@router.get("/games/{game_id}", response_model=GameDetail)
def get_game(game_id: str, s: Session = Depends(db)):
    g = G.one(s, game_id)
    if g is None:
        raise HTTPException(404, "no such game")
    return g


@router.delete("/games/{game_id}", status_code=204)
def delete_game(game_id: str, s: Session = Depends(db)):
    g = s.get(Game, game_id)
    if g is None:
        raise HTTPException(404, "no such game")
    s.delete(g)
    s.commit()


@router.get("/stats", response_model=Stats)
def get_stats(s: Session = Depends(db)):
    return ST.compute(s)


# ---- workspace ------------------------------------------------------------------------------------------------------------------------------------

@router.get("/workspace", response_model=Workspace)
def get_workspace(request: Request, s: Session = Depends(db)):
    return workspace.scan(request.app.state.config, s, current_settings(s).engine_path)


@router.post("/workspace/import-legacy", response_model=JobOut, status_code=202)
def import_legacy(request: Request):
    app = request.app
    job_id = app.state.jobs.submit("import-legacy", "Import earlier work", lambda ctx: legacy.import_legacy(app.state.config, app.state.sessions, ctx))
    return app.state.jobs.get(job_id)


# ---- accounts and importing ---------------------------------------------------------------------------------------------------------------------

def accounts(s: Session) -> dict:
    row = s.get(Setting, "accounts")
    return dict(row.value) if row and row.value else {}


def players(s: Session) -> list[str]:
    return [v for v in accounts(s).values() if v]


@router.get("/accounts", response_model=Accounts)
def get_accounts(s: Session = Depends(db)):
    return Accounts(**accounts(s))


@router.put("/accounts", response_model=Accounts)
def put_accounts(body: Accounts, s: Session = Depends(db)):
    for v in (body.lichess, body.chesscom):
        if v and not importers.valid_user(v):
            raise HTTPException(422, "user names are 2 to 30 letters, digits, dash or underscore")
    row = s.get(Setting, "accounts")
    if row is None:
        s.add(Setting(key="accounts", value=body.model_dump()))
    else:
        row.value = body.model_dump()
    s.commit()
    return body


def _import_user(request: Request, platform: str, body: ImportUser, s: Session):
    if not importers.valid_user(body.username):
        raise HTTPException(422, "user names are 2 to 30 letters, digits, dash or underscore")
    app = request.app
    fetch = app.state.fetchers[platform]
    names = [body.username] + players(s)
    acc = accounts(s)
    acc[platform] = body.username                                              # remembered for next time and to recognise your side in PGN files
    row = s.get(Setting, "accounts")
    if row is None:
        s.add(Setting(key="accounts", value=acc))
    else:
        row.value = acc
    s.commit()
    title = f"Import {body.max:,} games from {'Lichess' if platform == 'lichess' else 'Chess.com'}"
    stop = 30 if body.only_new else None
    job = app.state.jobs.submit(f"import-{platform}", title, lambda ctx: importers.import_stream(app.state.sessions, fetch(body.username, body.max), names, platform, ctx, total=body.max, stop_after_known=stop))
    return app.state.jobs.get(job)


@router.post("/import/lichess", response_model=JobOut, status_code=202)
def import_lichess(body: ImportUser, request: Request, s: Session = Depends(db)):
    return _import_user(request, "lichess", body, s)


@router.post("/import/chesscom", response_model=JobOut, status_code=202)
def import_chesscom(body: ImportUser, request: Request, s: Session = Depends(db)):
    return _import_user(request, "chesscom", body, s)


@router.post("/import/pgn", response_model=JobOut, status_code=202)
def import_pgn(body: ImportPgn, request: Request, s: Session = Depends(db)):
    app = request.app
    names = ([body.player] if body.player else []) + players(s)
    job = app.state.jobs.submit("import-pgn", "Import PGN games", lambda ctx: importers.import_stream(app.state.sessions, importers.split_pgn(body.text.splitlines()), names, "pgn", ctx))
    return app.state.jobs.get(job)


@router.post("/analyse", response_model=JobOut, status_code=202)
def analyse(body: AnalyseRequest, request: Request, s: Session = Depends(db)):
    app = request.app
    ids = body.ids if body.ids else analysis_job.unanalysed_ids(s, body.limit)
    if not ids:
        raise HTTPException(409, "every game is already analysed")
    settings = current_settings(s)
    if body.nodes:
        settings = settings.model_copy(update={"nodes": body.nodes})
    title = f"Analyse {len(ids):,} game{'s' if len(ids) != 1 else ''}"
    job = app.state.jobs.submit("analyse", title, lambda ctx: analysis_job.analyse_games(app.state.config, app.state.sessions, ids, settings, ctx, app.state.engine_factory(settings)), {"ids": len(ids)})
    return app.state.jobs.get(job)


# ---- the opening evaluation cache -----------------------------------------------------------------------------------------------------------------

@router.get("/cache", response_model=CacheStats)
def cache_stats(s: Session = Depends(db)):
    return CA.stats(s)


@router.delete("/cache")
def cache_clear(source: str | None = None, s: Session = Depends(db)):
    n = CA.clear(s, source)
    s.commit()
    return {"deleted": n}


@router.post("/cache/build", response_model=JobOut, status_code=202)
def cache_build(body: CacheBuild, request: Request, s: Session = Depends(db)):
    app = request.app
    settings = current_settings(s)
    if body.nodes:
        settings = settings.model_copy(update={"nodes": body.nodes})
    job = app.state.jobs.submit("cache-build", "Build the opening cache", lambda ctx: cache_job.build_cache(app.state.config, app.state.sessions, settings, ctx, min_count=body.min_count, limit=body.limit,
                                                                                                           include_theory=body.include_theory, engine_factory=app.state.engine_factory(settings)))
    return app.state.jobs.get(job)


# ---- jobs -----------------------------------------------------------------------------------------------------------------------------------------

@router.get("/jobs", response_model=list[JobOut])
def list_jobs(request: Request, limit: int = Query(50, ge=1, le=200)):
    return request.app.state.jobs.list(limit)


@router.post("/jobs/{job_id}/cancel", status_code=202)
def cancel_job(job_id: str, request: Request):
    if not request.app.state.jobs.cancel(job_id):
        raise HTTPException(404, "no such running job")
    return {"ok": True}


@router.get("/events")
async def events(request: Request):
    """Server-sent events: the current jobs first, then every change as it happens."""
    jobs = request.app.state.jobs
    q = jobs.subscribe(asyncio.get_running_loop())

    async def stream():
        try:
            for j in jobs.list(20):
                yield f"event: job\ndata: {json.dumps(j)}\n\n"
            while not await request.is_disconnected():
                try:
                    j = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"event: job\ndata: {json.dumps(j)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            jobs.unsubscribe(q)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# ---- settings -------------------------------------------------------------------------------------------------------------------------------------

@router.get("/settings", response_model=Settings)
def get_settings(s: Session = Depends(db)):
    return current_settings(s)


@router.patch("/settings", response_model=Settings)
def patch_settings(patch: SettingsPatch, s: Session = Depends(db)):
    cur = current_settings(s).model_dump()
    changes = patch.model_dump(exclude_unset=True)
    path = changes.get("engine_path")
    if path:
        p = Path(path).expanduser()
        if not (p.is_file() and os.access(p, os.X_OK)):
            raise HTTPException(422, "that path is not an executable file")
        changes["engine_path"] = str(p)
    cur.update(changes)
    row = s.get(Setting, "app")
    if row is None:
        s.add(Setting(key="app", value=cur))
    else:
        row.value = cur
    s.commit()
    return Settings(**cur)


@router.get("/health")
def health():
    return {"ok": True}
