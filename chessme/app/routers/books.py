from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..services import books as B

router = APIRouter(prefix="/api/books")


@router.get("")
def status(request: Request):
    with request.app.state.sessions() as s:
        return B.status(s, request.app.state.config.research_dir)


@router.post("/index", status_code=202)
def index(request: Request):
    app = request.app
    job = app.state.jobs.submit("books-index", "Index the book comments", lambda ctx: B.index(app.state.sessions, app.state.config.research_dir, ctx))
    return app.state.jobs.get(job)


@router.get("/search")
def search(request: Request, q: str | None = None, concept: str | None = None, limit: int = Query(24, ge=1, le=100), offset: int = Query(0, ge=0)):
    with request.app.state.sessions() as s:
        return B.search(s, q, concept, limit, offset)
