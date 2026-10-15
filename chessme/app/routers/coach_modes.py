import hashlib

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..coach_modes import ModeError
from ..models import Repertoire, Setting
from ..services import coach as CO

router = APIRouter(prefix="/api/coach")


class PlayedMove(BaseModel):
    uci: str


class OpeningStart(BaseModel):
    pgn: str = Field(max_length=2_000_000)
    colour: str = "white"
    rating: int = Field(1500, ge=0, le=3500)


class RepertoireBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    colour: str
    pgn: str = Field(min_length=1, max_length=2_000_000)


class EndgameStart(BaseModel):
    theme: str


class Hint(BaseModel):
    level: int = Field(1, ge=1, le=3)


class SteerStart(BaseModel):
    colour: str = "white"
    foci: dict[str, float]


def modes(request: Request):
    m = request.app.state.modes
    with request.app.state.sessions() as s:
        row = s.get(Setting, "app")
        m.engine_path = (row.value or {}).get("engine_path") if row and row.value else None
    return m


def run(request: Request, method: str, *args, **kw):
    try:
        return modes(request).call(method, *args, **kw)
    except ModeError as e:
        raise HTTPException(e.status, e.message)
    except RuntimeError as e:                                                       # no engine, for example
        raise HTTPException(409, str(e))


@router.get("/status")
def status(request: Request):
    return modes(request).status()


# ---- repertoires and opening practice ------------------------------------------------------------------------------------------------------------------

@router.get("/repertoires")
def repertoires(request: Request):
    with request.app.state.sessions() as s:
        from sqlalchemy import select
        return [{"id": r.id, "name": r.name, "colour": r.colour, "moves": r.pgn.count(".")} for r in s.scalars(select(Repertoire).order_by(Repertoire.created_at))]


@router.post("/repertoires", status_code=201)
def repertoire_add(body: RepertoireBody, request: Request):
    from ...coach import openings as OP
    if body.colour not in ("white", "black"):
        raise HTTPException(422, "colour must be white or black")
    if OP.Repertoire.from_pgn(body.pgn, body.colour).size == 0:
        raise HTTPException(422, "no moves of your colour were found in that PGN")
    rid = hashlib.sha1((body.name + body.colour + body.pgn).encode()).hexdigest()[:10]
    with request.app.state.sessions() as s:
        if s.get(Repertoire, rid) is None:
            s.add(Repertoire(id=rid, name=body.name, colour=body.colour, pgn=body.pgn))
            s.commit()
    return {"id": rid}


@router.delete("/repertoires/{rid}", status_code=204)
def repertoire_delete(rid: str, request: Request):
    with request.app.state.sessions() as s:
        r = s.get(Repertoire, rid)
        if r is None:
            raise HTTPException(404, "no such repertoire")
        s.delete(r)
        s.commit()


def _pgn_of(request: Request, body: OpeningStart):
    return body.pgn


@router.post("/openings/start")
def opening_start(body: OpeningStart, request: Request):
    return run(request, "opening_start", body.pgn, body.colour, body.rating)


@router.post("/openings/coverage")
def opening_coverage(body: OpeningStart, request: Request):
    return run(request, "opening_coverage", body.pgn, body.colour, body.rating)


@router.post("/openings/{sid}/move")
def opening_move(sid: str, body: PlayedMove, request: Request):
    return run(request, "opening_move", sid, body.uci)


@router.post("/repertoires/{rid}/start")
def repertoire_start(rid: str, request: Request, rating: int = 1500):
    with request.app.state.sessions() as s:
        r = s.get(Repertoire, rid)
        if r is None:
            raise HTTPException(404, "no such repertoire")
        pgn, colour = r.pgn, r.colour
    return run(request, "opening_start", pgn, colour, rating)


@router.get("/repertoires/{rid}/coverage")
def repertoire_coverage(rid: str, request: Request, rating: int = 1500):
    with request.app.state.sessions() as s:
        r = s.get(Repertoire, rid)
        if r is None:
            raise HTTPException(404, "no such repertoire")
        pgn, colour = r.pgn, r.colour
    return run(request, "opening_coverage", pgn, colour, rating)


# ---- endgames ------------------------------------------------------------------------------------------------------------------------------------------

@router.get("/endgames")
def endgames(request: Request):
    return {"themes": run(request, "endgame_themes")}


@router.post("/endgames/start")
def endgame_start(body: EndgameStart, request: Request):
    return run(request, "endgame_start", body.theme)


@router.post("/endgames/{sid}/move")
def endgame_move(sid: str, body: PlayedMove, request: Request):
    return run(request, "endgame_act", sid, "move", {"uci": body.uci})


@router.post("/endgames/{sid}/hint")
def endgame_hint(sid: str, body: Hint, request: Request):
    return run(request, "endgame_act", sid, "hint", {"level": body.level})


# ---- steered games -------------------------------------------------------------------------------------------------------------------------------------

@router.get("/steer/foci")
def steer_foci(request: Request):
    from ...coach import steering as ST
    with request.app.state.sessions() as s:
        suggested = {f["id"]: f["reason"] for f in CO.profile(s, limit=100).get("foci", [])}
    return {"foci": [{"id": k, "title": v["title"], "tip": v["tip"], "suggested": suggested.get(k)} for k, v in ST.FOCI.items()]}


@router.post("/steer/start")
def steer_start(body: SteerStart, request: Request):
    return run(request, "steer_start", body.colour, body.foci)


@router.post("/steer/{sid}/move")
def steer_move(sid: str, body: PlayedMove, request: Request):
    return run(request, "steer_move", sid, body.uci)


@router.post("/steer/{sid}/finish")
def steer_finish(sid: str, request: Request):
    try:
        return modes(request).finish_steered(sid)
    except ModeError as e:
        raise HTTPException(e.status, e.message)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
