import asyncio
import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import legacy, workspace
from ..models import Game, Setting
from ..schemas import GameDetail, GamePage, JobOut, Settings, SettingsPatch, Workspace
from ..services import games as G

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


# ---- workspace ------------------------------------------------------------------------------------------------------------------------------------

@router.get("/workspace", response_model=Workspace)
def get_workspace(request: Request, s: Session = Depends(db)):
    return workspace.scan(request.app.state.config, s, current_settings(s).engine_path)


@router.post("/workspace/import-legacy", response_model=JobOut, status_code=202)
def import_legacy(request: Request):
    app = request.app
    job_id = app.state.jobs.submit("import-legacy", "Import earlier work", lambda ctx: legacy.import_legacy(app.state.config, app.state.sessions, ctx))
    return app.state.jobs.get(job_id)


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
