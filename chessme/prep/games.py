"""The opponent's games as compact records: which side they had, the moves, the result from their point of view, the clock they had before each of their moves,
how the game ended and the opening's name."""
import io
import re
from dataclasses import dataclass, field

import chess
import chess.pgn

from .. import openings_db as OD
from ..ingest.normalize import time_class_of
from ..humanlike.testset import parse_tc

NAME = re.compile(r"[A-Za-z0-9_-]{2,30}")


@dataclass
class OppGame:
    id: str
    colour: str                                   # the opponent's side: "white" or "black"
    moves: list[str]                              # UCI
    score: float | None                           # 1 win, 0.5 draw, 0 loss for the opponent; None when unfinished
    speed: str | None
    date: str | None
    opening: str | None
    family: str | None                            # the opening's name before the first colon
    opp_elo: int | None
    their_elo: int | None                         # the player the opponent faced
    termination: str | None
    clocks: list[float | None] = field(default_factory=list)      # seconds on the clock after each ply (None where the site gave none)
    base: int | None = None                       # base time in seconds
    url: str | None = None
    handle: str | None = None


def family_of(opening: str | None) -> str | None:
    if not opening or opening in ("?", "-"):
        return None
    return opening.split(":")[0].strip() or None


def opening_from_headers(h) -> str | None:
    """Lichess writes `Opening`; Chess.com writes `ECOUrl` (".../openings/Sicilian-Defense-Open-Najdorf-Variation-6.Be3")."""
    if h.get("Opening") and h["Opening"] not in ("?", ""):
        return h["Opening"]
    url = h.get("ECOUrl") or ""
    if "/openings/" in url:
        slug = url.rsplit("/openings/", 1)[1]
        words = []
        for w in slug.split("-"):
            if any(c.isdigit() for c in w):                                    # the move numbers that follow the name
                break
            words.append(w)
        return " ".join(words) or None
    return None


def _speed(h):
    tc = h.get("TimeControl")
    parsed = parse_tc(tc)
    if parsed is None and str(tc or "").isdigit():
        parsed = (int(tc), 0)
    return (time_class_of(*parsed) if parsed else None), (parsed[0] if parsed else None)


def parse(pgn_text: str, handles) -> OppGame | None:
    """One `OppGame` from a PGN text, from the point of view of whichever of `handles` played in it; None when the game is unusable (no moves, another start position
    or variant, none of the handles in it)."""
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None or game.errors:
        return None
    h = game.headers
    if h.get("Variant", "Standard") not in ("Standard", "Chess") or "FEN" in h:
        return None
    names = {n.lower() for n in handles}
    colour = "white" if (h.get("White") or "").lower() in names else "black" if (h.get("Black") or "").lower() in names else None
    nodes = list(game.mainline())
    if colour is None or not nodes:
        return None
    result = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}.get(h.get("Result", "*"))
    score = None if result is None else (result if colour == "white" else 1.0 - result)
    speed, base = _speed(h)
    me, other = ("White", "Black") if colour == "white" else ("Black", "White")
    elo = lambda k: int(h[k]) if str(h.get(k, "")).isdigit() else None
    date = (h.get("UTCDate") or h.get("Date") or "").replace(".", "-")
    date = None if not date or "?" in date[:4] else date[:10]
    site = h.get("Site") or ""
    link = h.get("Link") or site
    url = link if link.startswith("https://") and ("lichess.org/" in link or "chess.com/" in link) else None
    ucis = [n.move.uci() for n in nodes]
    opening = opening_from_headers(h) or (OD.name_for(ucis) or (None, None))[1]            # a game without a name from the site gets the one its moves follow
    clocks = [node.clock() for node in nodes]
    gid = (re.search(r"(?:lichess\.org|chess\.com)/(?:game/)?(?:live/|daily/)?(\w+)", link) or [None, None])[1]
    return OppGame(id=gid or f"{h.get('White')}-{h.get('Black')}-{date}-{len(nodes)}", colour=colour, moves=[n.move.uci() for n in nodes], score=score, speed=speed, date=date,
                   opening=opening, family=family_of(opening), opp_elo=elo(f"{me}Elo"), their_elo=elo(f"{other}Elo"), termination=h.get("Termination"),
                   clocks=[None if c is None else round(c, 1) for c in clocks], base=base, url=url)


def summarise(games: list[OppGame]) -> dict:
    """Who the opponent is, from their games: how many, as which colour and speed, their rating now, the period, their score."""
    dated = sorted(g.date for g in games if g.date)
    rated = [(g.date or "", g.opp_elo) for g in games if g.opp_elo]
    latest = max(rated)[1] if rated else None
    scored = [g.score for g in games if g.score is not None]
    speeds: dict[str, int] = {}
    for g in games:
        speeds[g.speed or "unknown"] = speeds.get(g.speed or "unknown", 0) + 1
    return {"games": len(games), "white": sum(g.colour == "white" for g in games), "black": sum(g.colour == "black" for g in games), "speeds": speeds, "rating": latest,
            "from": dated[0] if dated else None, "to": dated[-1] if dated else None, "score": sum(scored) / len(scored) if scored else None}
