from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ...coach import reference as REF
from ..models import Drill, Setting
from ..services import coach as CO

router = APIRouter(prefix="/api/coach")


class Attempt(BaseModel):
    uci: str
    tries: int = Field(0, ge=0, description="wrong tries before this one")
    hints: int = Field(0, ge=0, le=3, description="hints used")


def _settings(request: Request) -> dict:
    with request.app.state.sessions() as s:
        row = s.get(Setting, "app")
        return dict(row.value) if row and row.value else {}


def _search(request: Request):
    return request.app.state.quick.searcher(_settings(request).get("engine_path"))


def _drill(s, drill_id: str) -> Drill:
    d = s.get(Drill, drill_id)
    if d is None:
        raise HTTPException(404, "no such drill")
    return d


def _public(d: Drill) -> dict:
    ex = d.exercise
    return {"id": d.id, "fen": d.fen, "colour": d.colour, "ply": d.ply, "move": (d.ply + 1) // 2 if d.ply else None, "phase": ex.get("phase"), "class": ex.get("class"), "loss": ex.get("loss"),
            "playedSan": ex["played_san"], "gameId": d.game_id, "box": d.box}


def _answer(d: Drill) -> dict:
    ex = d.exercise
    return {"bestSan": ex["best_san"], "bestUci": d.best_uci, "explanation": ex["explanation"], "playedSan": ex["played_san"]}


@router.get("/drills")
def drills(request: Request):
    with request.app.state.sessions() as s:
        return CO.stats(s)


@router.post("/drills/refresh")
def drills_refresh(request: Request):
    with request.app.state.sessions() as s:
        added = CO.refresh(s)
        s.commit()
        return {"added": added, **CO.stats(s)}


@router.get("/drills/next")
def drills_next(request: Request, limit: int = Query(5, ge=1, le=20)):
    with request.app.state.sessions() as s:
        return {"items": [_public(d) for d in CO.due(s, limit)], **CO.stats(s)}


@router.get("/drills/{drill_id}/hint")
def drill_hint(drill_id: str, request: Request, level: int = Query(1, ge=1, le=3)):
    with request.app.state.sessions() as s:
        return {"level": level, "text": _drill(s, drill_id).exercise["hints"][level - 1]}


@router.post("/drills/{drill_id}/attempt")
def drill_attempt(drill_id: str, body: Attempt, request: Request):
    with request.app.state.sessions() as s:
        d = _drill(s, drill_id)
        try:
            res = CO.judge(_search(request), d, body.uci)
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        if res["verdict"] == "illegal":
            raise HTTPException(422, "that is not a legal move here")
        if res["verdict"] in ("found", "ok"):
            first_try = body.tries == 0 and body.hints == 0
            CO.record(s, d, first_try)
            s.commit()
            return {**res, **_answer(d), "recorded": "up" if first_try else "again", **CO.stats(s)}
        return res


@router.post("/drills/{drill_id}/reveal")
def drill_reveal(drill_id: str, request: Request):
    with request.app.state.sessions() as s:
        d = _drill(s, drill_id)
        CO.record(s, d, False)
        s.commit()
        return {"verdict": "revealed", **_answer(d), **CO.stats(s)}


@router.get("/profile")
def profile(request: Request):
    settings = _settings(request)
    ref = getattr(request.app.state, "reference", None)
    with request.app.state.sessions() as s:
        return CO.profile(s, ref=ref, nodes=settings.get("nodes", 100_000), multipv=settings.get("multipv", 5))
