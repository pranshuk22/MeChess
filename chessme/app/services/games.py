"""Games and their analyses: converting what the analysis code produces into stored rows, and reading them back for the API."""
import io

import chess
import chess.pgn
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ... import openings_db as OD
import functools

from ...analysis import accuracy as ACC
from ...analysis import explain as EXP
from ...analysis import performance as PERF
from ...coach import reference as REF
from ...analysis import runner as AR
from ...humanlike.testset import parse_tc
from ...ingest.normalize import time_class_of
from ..models import Analysis, Game

BAD = ("mistake", "miss", "blunder")
CP_CAP = 1500


def moves_from_analysis(analysis_moves):
    """Per-move rows in the API's shape from the `analyse_game` / `analyse` JSON moves (evaluation after the move from white's point of view)."""
    out = []
    for m in analysis_moves:
        cp = m["played_cp"] if m["color"] == "white" else -m["played_cp"]
        sign = 1 if m["color"] == "white" else -1
        lines = [{"uci": l["uci"], "cp": int(max(-CP_CAP, min(CP_CAP, sign * l["cp"]))), "pv": list(l["pv"])} for l in m.get("top", [])]
        out.append({"san": m["move"], "uci": m["uci"], "cls": m["class"], "loss": round(float(m["loss"]), 4), "best": m["best_move"],
                    "winBefore": round(float(m["win_before"]), 4), "winAfter": round(float(m["win_after"]), 4), "cp": int(max(-CP_CAP, min(CP_CAP, cp))),
                    "acc": round(float(m["accuracy"]), 1) if m.get("accuracy") is not None else None, "phase": m.get("phase"), "lines": lines or None})
    return out


def pgn_from_moves(uci_moves, headers):
    """A PGN text for a game given as UCI moves (the analysis files do not keep the original text)."""
    game = chess.pgn.Game()
    for k, v in headers.items():
        if v:
            game.headers[k] = str(v)
    node, board = game, chess.Board()
    for u in uci_moves:
        mv = chess.Move.from_uci(u)
        if mv not in board.legal_moves:
            break
        node = node.add_variation(mv)
        board.push(mv)
    return str(game)


def speed_of(time_control):
    tc = parse_tc(time_control)
    if tc is None and str(time_control or "").isdigit():                      # Chess.com writes a plain number of seconds: "600"
        tc = (int(time_control), 0)
    return time_class_of(*tc) if tc else None


def opening_name(headers, uci_moves) -> str | None:
    """The opening of a game: the name the site gave, else the one in Chess.com's ECOUrl, else the longest named line the moves follow."""
    h = headers or {}
    given = (h.get("Opening") or "").strip()
    if given and given not in ("?", "-"):
        return given
    url = h.get("ECOUrl") or ""
    if "/openings/" in url:
        words = []
        for w in url.rsplit("/openings/", 1)[1].split("-"):
            if any(c.isdigit() for c in w):
                break
            words.append(w)
        if words:
            return " ".join(words)
    hit = OD.name_for(uci_moves or [])
    return hit[1] if hit else None


def name_missing_openings(session: Session, limit=None) -> int:
    """Give every game without an opening name the one its moves follow (games from files, Chess.com, games played here). Returns how many were named."""
    q = select(Game).where(or_(Game.opening.is_(None), Game.opening == "", Game.opening == "?"))
    if limit:
        q = q.limit(limit)
    n = 0
    for g in session.scalars(q):
        game = chess.pgn.read_game(io.StringIO(g.pgn)) if g.pgn else None
        if game is None:
            continue
        moves = []
        for mv in game.mainline_moves():
            moves.append(mv.uci())
            if len(moves) >= OD.MAX_PLIES:
                break
        name = opening_name(dict(game.headers), moves)
        if name:
            g.opening = name
            n += 1
    return n


def store(session: Session, *, id, source, headers, user_colour, analysis=None, nodes=0, multipv=0, engine=None, pgn=None, uci_moves=None, title=None):
    """Insert a game (and its analysis) unless it exists; returns True when it was new. `analysis` is the dict `analyse_game` returns."""
    if session.get(Game, id) is not None:
        return False
    h = headers or {}
    date = (h.get("UTCDate") or h.get("Date") or "").replace(".", "-")
    date = None if not date or "?" in date[:4] else date
    if date and "?" in date:                                                   # 2024.??.?? : keep what is known
        date = date.split("-?")[0].rstrip("-") if date[:4].isdigit() else None
    clock = h.get("UTCTime") or h.get("EndTime") or h.get("StartTime") or h.get("Time")
    moves = uci_moves if uci_moves is not None else [m["uci"] for m in (analysis or {}).get("moves", [])]
    elo = lambda k: int(h[k]) if str(h.get(k, "")).isdigit() else None
    session.add(Game(id=id, source=source, white=h.get("White") or "White", black=h.get("Black") or "Black", white_elo=elo("WhiteElo"), black_elo=elo("BlackElo"),
                     result=h.get("Result") or "*", played_at=date, played_time=clock if clock and len(clock) >= 5 and clock[2] == ":" else None, speed=speed_of(h.get("TimeControl")), opening=opening_name(h, moves), title=title,
                     user_colour=user_colour, pgn=pgn or pgn_from_moves(moves, h), plies=len(moves)))
    session.flush()                                                            # the game row first: the analysis points at it
    if analysis and analysis.get("moves"):
        summary = analysis.get("summary") or AR.summarise(analysis["moves"], h)
        session.add(Analysis(game_id=id, nodes=nodes, multipv=multipv, engine=engine, accuracy_white=summary["white"]["accuracy"], accuracy_black=summary["black"]["accuracy"],
                             moves=moves_from_analysis(analysis["moves"])))
    return True


def save_analysis(session: Session, game_id: str, analysis: dict, *, nodes: int, multipv: int, engine: str | None = None):
    """Add (or replace) the analysis of a stored game; `analysis` is the dict `analyse_game` returns."""
    game = session.get(Game, game_id)
    summary_ = analysis.get("summary") or AR.summarise(analysis["moves"], {"Result": game.result})
    row = session.get(Analysis, game_id)
    values = dict(nodes=nodes, multipv=multipv, engine=engine, accuracy_white=summary_["white"]["accuracy"], accuracy_black=summary_["black"]["accuracy"], moves=moves_from_analysis(analysis["moves"]))
    if row is None:
        session.add(Analysis(game_id=game_id, **values))
    else:
        for k, v in values.items():
            setattr(row, k, v)


def _mine(moves, user):
    if user not in ("white", "black"):
        return []
    return [m for i, m in enumerate(moves) if (i % 2 == 0) == (user == "white")]


def spark(moves, n=40):
    """About `n` evenly spaced evaluation points over the whole game, always including the last one."""
    if not moves:
        return []
    if len(moves) <= n + 1:
        return [m["cp"] for m in moves]
    idx = sorted({round(i * (len(moves) - 1) / n) for i in range(n + 1)})
    return [moves[i]["cp"] for i in idx]


@functools.lru_cache(maxsize=1)
def reference():
    """The packaged reference counts (None when the file is missing); the performance estimates are made against them."""
    return REF.load()


def performance(game: Game, analysis: Analysis | None) -> dict:
    """{'perf': {colour: estimate or None}, 'resultPerf': {colour: rating by the 400 rule or None}} for a game: how each side played (against the reference rates of the game's
    speed) and what the result says given the opponent's rating."""
    perf = {"white": None, "black": None}
    if analysis and analysis.moves:
        for colour, mine in (("white", analysis.moves[0::2]), ("black", analysis.moves[1::2])):
            perf[colour] = PERF.estimate([m["loss"] for m in mine], game.speed, reference())
    pts = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}.get(game.result)
    res = {"white": None, "black": None}
    if pts is not None:
        for colour, own, opp in (("white", pts, game.black_elo), ("black", 1.0 - pts, game.white_elo)):
            res[colour] = PERF.by_result(opp, int(own == 1.0), int(own == 0.0), int(own == 0.5))
    return {"perf": perf, "resultPerf": res}


def summary(game: Game, analysis: Analysis | None) -> dict:
    moves = analysis.moves if analysis else []
    mistakes = sum(1 for m in _mine(moves, game.user_colour) if m["cls"] in BAD and m["loss"] >= 0.1) if analysis and game.user_colour else None
    return {"id": game.id, "source": game.source, "white": game.white, "black": game.black, "whiteElo": game.white_elo, "blackElo": game.black_elo, "result": game.result,
            "date": game.played_at, "speed": game.speed, "opening": game.opening, "title": game.title, "user": game.user_colour, "plies": game.plies,
            "analysed": analysis is not None,
            "accuracy": {"white": analysis.accuracy_white, "black": analysis.accuracy_black} if analysis and analysis.accuracy_white is not None else None,
            "mistakes": mistakes, "spark": spark(moves), **performance(game, analysis)}


def opening_steps(uci_moves) -> tuple[list, int]:
    """([[ply, eco, name]] where the named opening changes along the game, the last ply that is still a named line)."""
    steps, last, book_end, table = [], None, 0, OD.table()
    for p in range(1, min(len(uci_moves), OD.MAX_PLIES) + 1):
        hit = OD.name_for(uci_moves[:p], max_plies=p)
        if hit and hit != last:
            steps.append([p, hit[0], hit[1]])
            last = hit
        if tuple(uci_moves[:p]) in table:
            book_end = p
    return steps, book_end


def clocks_of(pgn: str | None):
    """(seconds on the clock after each ply or None, base seconds, increment) from the clock comments of the stored PGN."""
    if not pgn:
        return [], None, None
    g = chess.pgn.read_game(io.StringIO(pgn))
    if g is None:
        return [], None, None
    clocks = [None if (c := n.clock()) is None else round(c, 1) for n in g.mainline()]
    tc = parse_tc(g.headers.get("TimeControl"))
    return (clocks if any(c is not None for c in clocks) else []), (tc[0] if tc else None), (tc[1] if tc else None)


def detail(game: Game, analysis: Analysis | None) -> dict:
    moves = [dict(m) for m in analysis.moves] if analysis else []
    if moves:
        for m, why in zip(moves, EXP.explain_all(moves)):
            m["why"] = why
    steps, book_end = opening_steps([m["uci"] for m in moves] if moves else _uci_of_pgn(game.pgn))
    clocks, base, inc = clocks_of(game.pgn)
    return {**summary(game, analysis), "moves": moves, "pgn": game.pgn, "phaseAccuracy": ACC.from_api_moves(analysis.moves)["by_phase"] if analysis and analysis.moves else {},
            "openingSteps": steps, "bookEnd": book_end, "clocks": clocks, "base": base, "inc": inc}


def _uci_of_pgn(pgn):
    g = chess.pgn.read_game(io.StringIO(pgn)) if pgn else None
    return [m.uci() for m in g.mainline_moves()] if g else []


def page(session: Session, *, q=None, colour=None, result=None, analysed=None, limit=100, offset=0):
    """(total, [summary dicts]) newest first, with optional filters: text in players/opening/title, the player's colour, the player's result, analysed or not."""
    cond = []
    if q:
        like = "%" + q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        cond.append(or_(func.lower(Game.white).like(like, escape="\\"), func.lower(Game.black).like(like, escape="\\"), func.lower(func.coalesce(Game.opening, "")).like(like, escape="\\"), func.lower(func.coalesce(Game.title, "")).like(like, escape="\\")))
    if colour in ("white", "black"):
        cond.append(Game.user_colour == colour)
    if result in ("win", "loss", "draw"):
        if result == "draw":
            cond.append(Game.result == "1/2-1/2")
        else:
            win_white = "1-0" if result == "win" else "0-1"
            win_black = "0-1" if result == "win" else "1-0"
            cond.append(or_(and_(Game.user_colour == "white", Game.result == win_white), and_(Game.user_colour == "black", Game.result == win_black)))
    if analysed is True:
        cond.append(Game.id.in_(select(Analysis.game_id)))
    elif analysed is False:
        cond.append(Game.id.not_in(select(Analysis.game_id)))
    total = session.scalar(select(func.count()).select_from(Game).where(*cond)) or 0
    rows = session.execute(select(Game, Analysis).outerjoin(Analysis, Analysis.game_id == Game.id).where(*cond)
                           .order_by(Game.played_at.desc().nulls_last(), Game.played_time.desc().nulls_last(), Game.created_at.desc()).limit(limit).offset(offset)).all()
    return total, [summary(g, a) for g, a in rows]


def one(session: Session, game_id: str):
    g = session.get(Game, game_id)
    return None if g is None else detail(g, session.get(Analysis, game_id))


def counts(session: Session):
    games = session.scalar(select(func.count()).select_from(Game)) or 0
    analysed = session.scalar(select(func.count()).select_from(Analysis)) or 0
    return games, analysed


def parse_pgn_headers(pgn_text):
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    return dict(game.headers) if game else {}
