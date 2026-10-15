"""Numbers for the home page: how the player is doing, from their own analysed games (games where their side is known)."""
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...analysis import accuracy as ACC
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
            if g.user_colour in ("white", "black") and a.moves:
                for ph, v in ACC.from_api_moves(a.moves)["by_phase"][g.user_colour].items():
                    if v is not None and ph in PHASES:
                        phase_acc[ph].append(v)
    return {
        "perDay": per_day,
        "phaseAccuracy": {p: _mean(phase_acc[p]) for p in PHASES},
        "classCounts": dict(classes),
        "ratingSeries": list(reversed(rating))[-120:],
        "colours": [{"name": c, "games": n, "score": p / n} for c, (n, p) in sorted(colours.items())],
        "speeds": [{"name": c, "games": n, "score": p / n} for c, (n, p) in sorted(speeds.items(), key=lambda kv: -kv[1][0])],
    }


BANDS = (1000, 1200, 1400, 1500, 1600, 1800, 2000, 2200, 2400)              # the opening explorer's rating bands
STOCKFISH_FOR = ((900, 1), (1100, 2), (1300, 3), (1600, 4), (1900, 5), (2100, 6), (2300, 7))


def stockfish_level_for(rating: int | None) -> int:
    """The play page's level that is about right for a rating (a first guess: the levels are not calibrated to ratings)."""
    if not rating:
        return 4
    return next((lvl for top, lvl in STOCKFISH_FOR if rating < top), 8)


def me(session: Session, accounts: dict) -> dict:
    """What the app knows about the player, from their games (those with their side known): ratings by speed (the latest, and the change over the last 30 days), the
    speed they play most, the explorer band of that rating, their openings by colour and the best and the weakest of them (at least `MIN_OPENING` games)."""
    rows = list(session.scalars(select(Game).where(Game.user_colour.in_(("white", "black"))).order_by(Game.played_at.desc().nulls_last(), Game.played_time.desc().nulls_last(), Game.created_at.desc()).limit(3000)))
    by_speed: dict[str, list] = defaultdict(list)
    opens: dict[str, dict[str, list]] = {"white": defaultdict(lambda: [0, 0.0]), "black": defaultdict(lambda: [0, 0.0])}
    for g in rows:
        elo = g.white_elo if g.user_colour == "white" else g.black_elo
        if g.speed and elo and g.played_at and len(g.played_at) >= 10:
            by_speed[g.speed].append((g.played_at[:10], elo))
        o = _outcome(g)
        if o and g.opening:
            e = opens[g.user_colour][g.opening.split(":")[0]]
            e[0] += 1
            e[1] += {"win": 1.0, "draw": 0.5, "loss": 0.0}[o]
    ratings = []
    for speed, pts in by_speed.items():                                      # newest first
        latest_day, latest = pts[0]
        cutoff = (date.fromisoformat(latest_day) - timedelta(days=30)).isoformat()
        old = [r for d, r in pts if d <= cutoff]
        ratings.append({"speed": speed, "rating": latest, "games": len(pts), "change": latest - old[0] if old else None, "date": latest_day})
    ratings.sort(key=lambda r: -r["games"])
    main = ratings[0] if ratings else None
    declared = accounts.get("rating")
    rating = main["rating"] if main else declared                              # the rating in the games, else the one the player gave in Settings
    band = min(BANDS, key=lambda b: abs(b - rating)) if rating else None
    out_open = {}
    for colour, d in opens.items():
        rows_ = [{"name": n, "games": c, "score": s / c} for n, (c, s) in d.items()]
        rows_.sort(key=lambda r: -r["games"])
        solid = [r for r in rows_ if r["games"] >= MIN_OPENING]
        out_open[colour] = {"top": rows_[:4], "best": max(solid, key=lambda r: r["score"]) if solid else None, "weakest": min(solid, key=lambda r: r["score"]) if len(solid) > 1 else None}
    first = min((g.played_at for g in rows if g.played_at), default=None)
    return {"name": next((v for v in (accounts.get("lichess"), accounts.get("chesscom")) if v), None), "handles": {k: v for k, v in accounts.items() if v and k in ("lichess", "chesscom")}, "games": len(rows), "since": first,
            "ratings": ratings, "mainSpeed": main["speed"] if main else None, "rating": rating, "ratingSource": "games" if main else "settings" if declared else None, "band": band, "stockfishLevel": stockfish_level_for(rating),
            "openings": out_open}


MIN_OPENING = 5
