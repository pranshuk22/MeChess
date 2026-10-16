"""The player's profile: how they play, with filters (speed, colour, period)."""
import threading
import time

from fastapi import APIRouter, Query, Request

from ..services import profile as PF

router = APIRouter(prefix="/api")
_lock = threading.Lock()
TTL = 60


@router.get("/profile")
def profile(request: Request, speed: str | None = Query(None, pattern="^(bullet|blitz|rapid|classical|ultrabullet|correspondence)$"), colour: str | None = Query(None, pattern="^(white|black)$"),
            days: int | None = Query(None, ge=1, le=3650)):
    """Everything about how the player plays, from their games: summary, openings, habits, phases and endgames, tactics, the clock, converting. Kept for a minute per filter."""
    key = (speed, colour, days)
    cache = request.app.__dict__.setdefault("_profile_cache", {})                      # per app (a new app starts with nothing remembered)
    with _lock:
        hit = cache.get(key)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    with request.app.state.sessions() as s:
        out = PF.compute(s, speed=speed, colour=colour, days=days, ref=getattr(request.app.state, "reference", None))
    with _lock:
        cache[key] = (time.time(), out)
    return out
