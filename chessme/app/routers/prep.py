"""Preparing against an opponent: start one from their handles (or a pasted PGN of their games), follow it as a job, read the report, save the plan as a repertoire."""
import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import importers, prep_job
from ..models import Prep, PrepGame, Repertoire
from .api import current_settings, db

router = APIRouter(prefix="/api/prep")


class Handle(BaseModel):
    site: str
    name: str


class PrepStart(BaseModel):
    handles: list[Handle] = Field(default_factory=list, max_length=4, description="the opponent's accounts (on Lichess and Chess.com, several when they use more than one)")
    pgn: str | None = Field(None, max_length=20_000_000, description="or a PGN with the opponent's games (then `handles` names them, one name per account used in the file)")
    depth: str = Field("standard", pattern="^(quick|standard|deep)$")
    max_games: int = Field(300, ge=20, le=2000)
    speeds: list[str] = Field(default_factory=lambda: ["blitz", "rapid", "classical"])
    rated_only: bool = True


class SaveRepertoire(BaseModel):
    colour: str
    name: str | None = Field(None, max_length=60)


def _check(body: PrepStart):
    if not body.handles:
        raise HTTPException(422, "give the opponent's user name")
    for h in body.handles:
        if h.site not in ("lichess", "chesscom"):
            raise HTTPException(422, "the site is lichess or chesscom")
        if not importers.valid_user(h.name):
            raise HTTPException(422, f"{h.name!r} is not a user name (2 to 30 letters, digits, dash or underscore)")
    if any(s not in prep_job.SPEEDS for s in body.speeds) or not body.speeds:
        raise HTTPException(422, "speeds are bullet, blitz, rapid or classical")


def _row(p: Prep, games: int | None = None) -> dict:
    rep = p.report or {}
    opp = rep.get("opponent") or {}
    return {"id": p.id, "title": p.title, "status": p.status, "error": p.error, "handles": p.handles, "params": p.params, "jobId": p.job_id, "games": opp.get("games", games), "rating": opp.get("rating"),
            "createdAt": p.created_at.replace(tzinfo=timezone.utc).isoformat() if p.created_at and p.created_at.tzinfo is None else (p.created_at.isoformat() if p.created_at else None),
            "updatedAt": p.updated_at.replace(tzinfo=timezone.utc).isoformat() if p.updated_at and p.updated_at.tzinfo is None else (p.updated_at.isoformat() if p.updated_at else None)}


def _submit(request: Request, prep_id: str, title: str, pgn: str | None):
    app = request.app
    with app.state.sessions() as s:
        settings = current_settings(s)
    job = app.state.jobs.submit("prepare", title, lambda ctx: prep_job.run_prep(app.state.config, app.state, prep_id, settings, ctx, pgn_text=pgn, ref=getattr(app.state, "reference", None),
                                                                              search_factory=getattr(app.state, "prep_search_factory", None)), {"prep": prep_id})
    return job


@router.post("", status_code=202)
def start(body: PrepStart, request: Request, s: Session = Depends(db)):
    _check(body)
    pid = uuid.uuid4().hex[:10]
    names = ", ".join(h.name for h in body.handles)
    s.add(Prep(id=pid, title=f"Prepare against {names}", status="running", handles=[h.model_dump() for h in body.handles], params={"depth": body.depth, "max_games": body.max_games, "speeds": body.speeds, "rated_only": body.rated_only},
               created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
    s.commit()
    job = _submit(request, pid, f"Prepare against {names}", body.pgn)
    p = s.get(Prep, pid)
    p.job_id = job
    s.commit()
    return {"id": pid, "jobId": job}


@router.get("")
def list_preps(s: Session = Depends(db)):
    return [_row(p) for p in s.scalars(select(Prep).order_by(Prep.created_at.desc()).limit(50))]


def _prep(s: Session, pid: str) -> Prep:
    p = s.get(Prep, pid)
    if p is None:
        raise HTTPException(404, "no such preparation")
    return p


@router.get("/{pid}")
def get_prep(pid: str, request: Request, s: Session = Depends(db)):
    p = _prep(s, pid)
    n = s.scalar(select(func.count()).select_from(PrepGame).where(PrepGame.prep_id == pid)) or 0
    analysed = s.scalar(select(func.count()).select_from(PrepGame).where(PrepGame.prep_id == pid, PrepGame.analysis.is_not(None))) or 0
    job = request.app.state.jobs.get(p.job_id) if p.job_id else None
    return {**_row(p, n), "report": p.report, "downloaded": n, "analysed": analysed, "job": job}


@router.post("/{pid}/refresh", status_code=202)
def refresh(pid: str, request: Request, s: Session = Depends(db)):
    """Fetch their newest games and make the report again (games already kept and analysed are not redone)."""
    p = _prep(s, pid)
    if p.status == "running":
        raise HTTPException(409, "this preparation is still running")
    p.status, p.error = "running", None
    s.commit()
    job = _submit(request, pid, p.title, None)
    p.job_id = job
    s.commit()
    return {"id": pid, "jobId": job}


@router.delete("/{pid}", status_code=204)
def delete(pid: str, s: Session = Depends(db)):
    p = _prep(s, pid)
    s.query(PrepGame).filter(PrepGame.prep_id == pid).delete()
    s.delete(p)
    s.commit()


@router.post("/{pid}/repertoire", status_code=201)
def save_repertoire(pid: str, body: SaveRepertoire, s: Session = Depends(db)):
    """The plan for one colour as a repertoire of the coach, to practise in the opening practice."""
    p = _prep(s, pid)
    if body.colour not in ("white", "black"):
        raise HTTPException(422, "colour must be white or black")
    plan = ((p.report or {}).get("plan") or {}).get(body.colour)
    if not plan or not plan.get("pgn"):
        raise HTTPException(409, "there is no plan for that colour (not enough of their games)")
    name = body.name or f"{p.title.replace('Prepare against ', 'Against ')} ({body.colour})"
    rid = hashlib.sha1((name + body.colour + plan["pgn"]).encode()).hexdigest()[:10]
    if s.get(Repertoire, rid) is None:
        s.add(Repertoire(id=rid, name=name[:60], colour=body.colour, pgn=plan["pgn"]))
        s.commit()
    return {"id": rid, "name": name[:60]}
