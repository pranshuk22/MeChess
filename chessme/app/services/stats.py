"""Numbers for the home page: how the player is doing, from their own analysed games (games where their side is known)."""
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Analysis, Game
from .games import BAD

PHASES = ("opening", "middlegame", "endgame")
DAYS = 182

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
                           .order_by(Game.played_at.desc().nulls_last(), Game.played_time.desc().nulls_last(), Game.created_at.desc()).limit(400)).all()
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
        **insights(session, rows),
    }


def insights(session: Session, rows) -> dict:
    """More of the same, for the insights page: calendar, accuracy by phase, move kinds, rating over time, results by colour and by speed."""
    since = (date.today() - timedelta(days=DAYS)).isoformat()
    per_day = [{"date": d, "games": n} for d, n in session.execute(select(func.substr(Game.played_at, 1, 10), func.count()).where(Game.played_at >= since, func.length(Game.played_at) >= 10)
                                                                      .group_by(func.substr(Game.played_at, 1, 10)).order_by(func.substr(Game.played_at, 1, 10)))]
    phase_acc: dict[str, list[float]] = defaultdict(list)
    classes: Counter = Counter()
    rating, colours, speeds = [], defaultdict(lambda: [0, 0.0]), defaultdict(lambda: [0, 0.0])
    analysed_seen = 0
    for g, a in rows:
        o = _outcome(g)
        pts = {"win": 1.0, "draw": 0.5, "loss": 0.0}.get(o) if o else None
        if pts is not None:
            colours[g.user_colour][0] += 1
            colours[g.user_colour][1] += pts
            if g.speed:
                speeds[g.speed][0] += 1
                speeds[g.speed][1] += pts
        elo = g.white_elo if g.user_colour == "white" else g.black_elo
        if elo and g.played_at and len(g.played_at) >= 10:
            rating.append({"date": g.played_at[:10], "rating": elo})
        if a is not None and analysed_seen < 100:
            analysed_seen += 1
            mine = a.moves[0::2] if g.user_colour == "white" else a.moves[1::2]
            for m in mine:
                classes[m["cls"]] += 1
                if m.get("acc") is not None and m.get("phase") in PHASES:
                    phase_acc[m["phase"]].append(m["acc"])
    return {
        "perDay": per_day,
        "phaseAccuracy": {p: _mean(phase_acc[p]) for p in PHASES},
        "classCounts": dict(classes),
        "ratingSeries": list(reversed(rating))[-120:],
        "colours": [{"name": c, "games": n, "score": p / n} for c, (n, p) in sorted(colours.items())],
        "speeds": [{"name": c, "games": n, "score": p / n} for c, (n, p) in sorted(speeds.items(), key=lambda kv: -kv[1][0])],
    }
