"""Numbers for the home page: how the player is doing, from their own analysed games (games where their side is known)."""
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Analysis, Game
from .games import BAD

RECENT = 20


def _outcome(g: Game):
    if g.result == "1/2-1/2":
        return "draw"
    if g.result not in ("1-0", "0-1") or g.user_colour not in ("white", "black"):
        return None
    return "win" if (g.user_colour == "white") == (g.result == "1-0") else "loss"


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def compute(session: Session) -> dict:
    total = session.scalar(select(func.count()).select_from(Game)) or 0
    analysed = session.scalar(select(func.count()).select_from(Analysis)) or 0
    rows = session.execute(select(Game, Analysis).outerjoin(Analysis, Analysis.game_id == Game.id).where(Game.user_colour.in_(("white", "black")))
                           .order_by(Game.played_at.desc().nulls_last(), Game.created_at.desc()).limit(400)).all()
    results = {"win": 0, "draw": 0, "loss": 0}
    acc, mistakes, openings = [], [], defaultdict(lambda: [0, 0.0])
    for g, a in rows:                                                      # newest first
        o = _outcome(g)
        if o:
            results[o] += 1
            if g.opening:
                e = openings[(g.opening.split(":")[0], g.user_colour)]
                e[0] += 1
                e[1] += {"win": 1.0, "draw": 0.5, "loss": 0.0}[o]
        if a is not None:
            mine = a.accuracy_white if g.user_colour == "white" else a.accuracy_black
            if mine is not None:
                acc.append(mine)
            mine_moves = a.moves[0::2] if g.user_colour == "white" else a.moves[1::2]
            mistakes.append(sum(1 for m in mine_moves if m["cls"] in BAD and m["loss"] >= 0.1))
    top = sorted(openings.items(), key=lambda kv: -kv[1][0])[:6]
    return {
        "games": total, "analysed": analysed, "results": results,
        "accuracy": {"recent": _mean(acc[:RECENT]), "previous": _mean(acc[RECENT:2 * RECENT]), "series": [round(x, 1) for x in reversed(acc[:30])]},
        "mistakesPerGame": {"recent": _mean(mistakes[:RECENT]), "previous": _mean(mistakes[RECENT:2 * RECENT])},
        "openings": [{"name": name, "colour": colour, "games": n, "score": s / n} for (name, colour), (n, s) in top],
    }
