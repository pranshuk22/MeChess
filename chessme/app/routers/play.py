import hashlib

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..models import Game, Setting
from ..play import PlayError

router = APIRouter(prefix="/api/play")


class StartBody(BaseModel):
    colour: str = Field("white", description="white, black or random")
    opponent: str = Field("stockfish", description="stockfish or mechess")
    level: int = Field(4, description="Stockfish level 1 to 8, or the MeChess rating (800 to 2600)")
    base: int | None = Field(None, description="seconds each side has (None: no clock)")
    inc: int = Field(0, description="increment in seconds after each move")
    pace: bool = Field(True, description="the computer takes its time like a person (the page waits before showing its move)")
    style: str = Field("auto", description="MeChess's move choice: auto (the best it has learned), population, me or none")


class MoveBody(BaseModel):
    uci: str


def _engine_path(request: Request):
    with request.app.state.sessions() as s:
        row = s.get(Setting, "app")
        return (row.value or {}).get("engine_path") if row else None


def _call(fn, *a):
    try:
        return fn(*a)
    except PlayError as e:
        raise HTTPException(e.status, e.message)


def _finish(request: Request, session):
    """A finished game goes to the library (once) and is analysed in the background when an engine is there."""
    state = session.state()
    if session.over and session.game_id is None and session.board.move_stack:
        app = request.app
        game = session.pgn()
        gid = "play:" + hashlib.sha1((session.id + str(len(session.board.move_stack))).encode()).hexdigest()[:12]
        with app.state.sessions() as s:
            from ..services import games as G
            moves = [m.uci() for m in session.board.move_stack]
            headers = dict(game.headers)
            if s.get(Game, gid) is None:
                G.store(s, id=gid, source="play", headers=headers, user_colour=session.colour, pgn=str(game), uci_moves=moves, title=None)
                s.commit()
        session.game_id = gid
        state = session.state()
    return state


@router.get("/options")
def options(request: Request):
    return request.app.state.play.options(_engine_path(request))


@router.post("/start")
def start(body: StartBody, request: Request):
    s = _call(request.app.state.play.start, body.colour, body.opponent, body.level, _engine_path(request), body.base, body.inc, body.pace, body.style)
    return _finish(request, s)


@router.get("/{sid}")
def get_game(sid: str, request: Request):
    return _finish(request, _call(request.app.state.play.get, sid))


@router.post("/{sid}/move")
def move(sid: str, body: MoveBody, request: Request):
    return _finish(request, _call(request.app.state.play.move, sid, body.uci))


@router.post("/{sid}/takeback")
def takeback(sid: str, request: Request):
    return _finish(request, _call(request.app.state.play.takeback, sid))


@router.post("/{sid}/resign")
def resign(sid: str, request: Request):
    return _finish(request, _call(request.app.state.play.resign, sid))


@router.post("/{sid}/flag")
def flag(sid: str, request: Request):
    return _finish(request, _call(request.app.state.play.flag, sid))


class TrainBody(BaseModel):
    scope: str = Field("population", description="population (every move of your library) or me (your own moves)")
    decisions: int = Field(3000, ge=500, le=20000)


@router.post("/train-style", status_code=202)
def train_style(body: TrainBody, request: Request):
    """Teach MeChess to choose like a person from your library (a background job: the engine looks at a few thousand of the positions)."""
    from .. import style_job
    from .api import current_settings
    app = request.app
    if body.scope not in style_job.SCOPES:
        raise HTTPException(422, "scope is population or me")
    with app.state.sessions() as s:
        settings = current_settings(s)
    job = app.state.jobs.submit("train-style", "Teach MeChess to choose like a person" if body.scope == "population" else "Teach MeChess your style",
                                lambda ctx: style_job.train(app.state.config, app.state.sessions, settings, ctx, scope=body.scope, decisions=body.decisions, engine_factory=getattr(app.state, "style_engine_factory", None)))
    return app.state.jobs.get(job)
