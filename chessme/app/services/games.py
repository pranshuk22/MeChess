"""Games and their analyses: converting what the analysis code produces into stored rows, and reading them back for the API."""
import io

import chess
import chess.pgn
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

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
        out.append({"san": m["move"], "uci": m["uci"], "cls": m["class"], "loss": round(float(m["loss"]), 4), "best": m["best_move"],
                    "winBefore": round(float(m["win_before"]), 4), "winAfter": round(float(m["win_after"]), 4), "cp": int(max(-CP_CAP, min(CP_CAP, cp)))})
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
    return time_class_of(*tc) if tc else None


def store(session: Session, *, id, source, headers, user_colour, analysis=None, nodes=0, multipv=0, engine=None, pgn=None, uci_moves=None, title=None):
    """Insert a game (and its analysis) unless it exists; returns True when it was new. `analysis` is the dict `analyse_game` returns."""
    if session.get(Game, id) is not None:
        return False
    h = headers or {}
    date = (h.get("UTCDate") or h.get("Date") or "").replace(".", "-")
    date = None if not date or "?" in date[:4] else date
    moves = uci_moves if uci_moves is not None else [m["uci"] for m in (analysis or {}).get("moves", [])]
    elo = lambda k: int(h[k]) if str(h.get(k, "")).isdigit() else None
    session.add(Game(id=id, source=source, white=h.get("White") or "White", black=h.get("Black") or "Black", white_elo=elo("WhiteElo"), black_elo=elo("BlackElo"),
                     result=h.get("Result") or "*", played_at=date, speed=speed_of(h.get("TimeControl")), opening=h.get("Opening") or None, title=title,
                     user_colour=user_colour, pgn=pgn or pgn_from_moves(moves, h), plies=len(moves)))
    session.flush()                                                            # the game row first: the analysis points at it
    if analysis and analysis.get("moves"):
        summary = analysis.get("summary") or AR.summarise(analysis["moves"], h)
        session.add(Analysis(game_id=id, nodes=nodes, multipv=multipv, engine=engine, accuracy_white=summary["white"]["accuracy"], accuracy_black=summary["black"]["accuracy"],
                             moves=moves_from_analysis(analysis["moves"])))
    return True


def _mine(moves, user):
    if user not in ("white", "black"):
        return []
    return [m for i, m in enumerate(moves) if (i % 2 == 0) == (user == "white")]


def spark(moves, n=40):
    if not moves:
        return []
    step = max(1, len(moves) // n)
    return [m["cp"] for m in moves[::step]][: n + 1]


def summary(game: Game, analysis: Analysis | None) -> dict:
    moves = analysis.moves if analysis else []
    mistakes = sum(1 for m in _mine(moves, game.user_colour) if m["cls"] in BAD and m["loss"] >= 0.1) if analysis and game.user_colour else None
    return {"id": game.id, "source": game.source, "white": game.white, "black": game.black, "whiteElo": game.white_elo, "blackElo": game.black_elo, "result": game.result,
            "date": game.played_at, "speed": game.speed, "opening": game.opening, "title": game.title, "user": game.user_colour, "plies": game.plies,
            "analysed": analysis is not None,
            "accuracy": {"white": analysis.accuracy_white, "black": analysis.accuracy_black} if analysis and analysis.accuracy_white is not None else None,
            "mistakes": mistakes, "spark": spark(moves)}


def detail(game: Game, analysis: Analysis | None) -> dict:
    return {**summary(game, analysis), "moves": analysis.moves if analysis else [], "pgn": game.pgn}


def page(session: Session, *, q=None, colour=None, result=None, analysed=None, limit=100, offset=0):
    """(total, [summary dicts]) newest first, with optional filters: text in players/opening/title, the player's colour, the player's result, analysed or not."""
    cond = []
    if q:
        like = f"%{q.strip().lower()}%"
        cond.append(or_(func.lower(Game.white).like(like), func.lower(Game.black).like(like), func.lower(func.coalesce(Game.opening, "")).like(like), func.lower(func.coalesce(Game.title, "")).like(like)))
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
                           .order_by(Game.played_at.desc().nulls_last(), Game.created_at.desc()).limit(limit).offset(offset)).all()
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
