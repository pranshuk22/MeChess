"""The coach's data: drills from the player's own mistakes (Leitner boxes), and the weakness profile from their analysed games."""
import time

import chess
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...coach import exercises as X
from ...coach import profile as PR
from ...coach import reference as REF
from ...coach.drills import INTERVALS, MAX_BOX
from ...coach.session import Judge
from ..models import Analysis, Drill, Game

OK_LOSS = 0.03                                                                 # a different move that costs this little is accepted as good as the engine's


def analysis_moves(game: Game, a: Analysis) -> list[dict]:
    """The stored rows in the shape the coach code reads (`analysis.runner` records)."""
    out = []
    for i, m in enumerate(a.moves):
        out.append({"ply": i + 1, "uci": m["uci"], "best_move": m["best"], "color": "white" if i % 2 == 0 else "black", "loss": m["loss"], "win_before": m["winBefore"],
                    "win_after": m["winAfter"], "phase": m.get("phase") or "middlegame", "class": m["cls"]})
    return out


def add_game_drills(session: Session, game: Game, a: Analysis, max_n=5) -> int:
    """Drills from one analysed game of the player (when their side is known): the biggest mistakes, at least four plies apart."""
    if game.user_colour not in ("white", "black") or not a.moves:
        return 0
    rows = analysis_moves(game, a)
    board, fens = chess.Board(), {}
    for r in rows:
        fens[r["ply"]] = board.fen()
        try:
            board.push_uci(r["uci"])
        except ValueError:
            break
    colour = game.user_colour
    cands = [r for r in rows if r["color"] == colour and r["loss"] >= X.MIN_LOSS and r["win_before"] >= X.MIN_WIN_BEFORE and r["uci"] != r["best_move"] and r["ply"] in fens]
    chosen = []
    for r in sorted(cands, key=lambda r: -r["loss"]):
        if all(abs(r["ply"] - c["ply"]) >= 4 for c in chosen):
            chosen.append(r)
        if len(chosen) == max_n:
            break
    added = 0
    now = time.time()
    for r in sorted(chosen, key=lambda r: r["ply"]):
        ex = X.exercise(fens[r["ply"]], r["uci"], r["best_move"], r["loss"], r["win_before"], r["win_after"], r["ply"], r["phase"], r["class"])
        if session.get(Drill, ex["id"]) is None:
            session.add(Drill(id=ex["id"], game_id=game.id, ply=r["ply"], fen=ex["fen"], colour=ex["color"], played_uci=ex["played_uci"], best_uci=ex["best_uci"], exercise=ex, box=0, due=now, history=[]))
            added += 1
    return added


def refresh(session: Session) -> int:
    """Drills from every analysed game that has none yet (safe to repeat)."""
    have = set(session.scalars(select(Drill.game_id).where(Drill.game_id.is_not(None))))
    added = 0
    for g, a in session.execute(select(Game, Analysis).join(Analysis, Analysis.game_id == Game.id).where(Game.user_colour.in_(("white", "black")))):
        if g.id not in have:
            added += add_game_drills(session, g, a)
            session.flush()
    return added


def due(session: Session, limit=5, now=None) -> list[Drill]:
    now = time.time() if now is None else now
    return list(session.scalars(select(Drill).where(Drill.due <= now).order_by(Drill.due).limit(limit)))


def stats(session: Session, now=None) -> dict:
    now = time.time() if now is None else now
    total = session.scalar(select(func.count()).select_from(Drill)) or 0
    due_n = session.scalar(select(func.count()).select_from(Drill).where(Drill.due <= now)) or 0
    boxes = [0] * (MAX_BOX + 1)
    for b, n in session.execute(select(Drill.box, func.count()).group_by(Drill.box)):
        boxes[b] = n
    return {"total": total, "due": due_n, "boxes": boxes}


def record(session: Session, d: Drill, success: bool, now=None):
    """Note an attempt: up a box on success (first try, no hint), back to box 0 otherwise; due again after the box's interval."""
    now = time.time() if now is None else now
    d.box = min(d.box + 1, MAX_BOX) if success else 0
    d.due = now + INTERVALS[d.box]
    d.history = (list(d.history or []) + [[now, bool(success)]])[-20:]


def judge(search, d: Drill, uci: str) -> dict:
    """The verdict on a try: 'found' (the engine's move), 'ok' (a different move that costs almost nothing) or 'wrong'."""
    board = chess.Board(d.fen)
    try:
        mv = chess.Move.from_uci(uci)
    except ValueError:
        return {"verdict": "illegal", "loss": None}
    if mv not in board.legal_moves:
        return {"verdict": "illegal", "loss": None}
    if uci == d.best_uci:
        return {"verdict": "found", "loss": 0.0}
    loss = Judge(search).loss(d.fen, uci)
    return {"verdict": "ok" if loss <= OK_LOSS else "wrong", "loss": round(loss, 4)}


def reference_comparison(rows, games_meta, ref, nodes=None, multipv=None):
    """The weakness profile's comparison with players of the same rating (when a reference exists): median rating and the most played speed of the games."""
    if not ref or not games_meta:
        return None
    by_speed: dict = {}
    for speed, rating, rws in games_meta:
        if speed and rating:
            by_speed.setdefault(speed, []).append((rating, rws))
    if not by_speed:
        return None
    speed = max(by_speed, key=lambda k: len(by_speed[k]))
    ratings = sorted(r for r, _ in by_speed[speed])
    return REF.compare([x for _, rws in by_speed[speed] for x in rws], ratings[len(ratings) // 2], speed, ref, nodes=nodes, multipv=multipv)


def profile(session: Session, limit=200, ref=None, nodes=None, multipv=None) -> dict:
    """The weakness profile from the player's most recent analysed games (see `coach.profile`), with the comparison against players of their rating when possible."""
    rows, games_meta, n = [], [], 0
    q = (select(Game, Analysis).join(Analysis, Analysis.game_id == Game.id).where(Game.user_colour.in_(("white", "black")))
         .order_by(Game.played_at.desc().nulls_last(), Game.played_time.desc().nulls_last(), Game.created_at.desc()).limit(limit))
    for g, a in session.execute(q):
        mine = PR.player_rows({"moves": analysis_moves(g, a)}, g.user_colour)
        rows += mine
        n += 1
        rating = g.white_elo if g.user_colour == "white" else g.black_elo
        games_meta.append((g.speed, rating, mine))
    prof = PR.profile(rows)
    prof["games"] = n
    prof["sentences"] = PR.sentences(prof)
    cmp = reference_comparison(rows, games_meta, ref, nodes, multipv)
    if cmp:
        prof["reference"] = cmp
        prof["sentences"] += REF.sentences(cmp)
    prof["foci"] = [{"id": f, "reason": r} for f, r in PR.suggest_foci(prof)]
    return prof
