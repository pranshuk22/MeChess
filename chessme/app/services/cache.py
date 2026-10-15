"""The opening evaluation cache: engine lines for positions within the first ten moves, keyed by the position, kept in the database.

Used three ways: the analysis job takes a position's lines from here instead of searching again (the same openings recur in many games); live analysis shows
the stored lines at once while the engine works toward something deeper; and the player can build it for their own openings. Only positions up to `MAX_PLY`
half-moves are stored (deeper positions rarely repeat). A stored entry is used only when its search was at least as strong as the one asked for."""
from datetime import datetime, timezone

import chess
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ...analysis.runner import SimpleLine
from ..models import PositionEval

MAX_PLY = 20
DEEP_NODES = 1_000_000                       # positions searched at least this far are counted as deep
KEEP_PV = 8


def norm(fen: str) -> str:
    return " ".join(fen.split()[:4])


def ply_of(fen: str) -> int:
    f = fen.split()
    return (int(f[5]) - 1) * 2 + (0 if f[1] == "w" else 1) if len(f) >= 6 else 0


def eligible(fen: str) -> bool:
    return ply_of(fen) <= MAX_PLY


def to_stored(board_turn_white: bool, lines) -> list[dict]:
    """Engine lines (objects with move, cp for the side to move, pv) as stored lines (white's point of view)."""
    sign = 1 if board_turn_white else -1
    return [{"uci": l.move, "cp": int(sign * l.cp), "pv": list(l.pv)[:KEEP_PV]} for l in lines]


def from_stored(board_turn_white: bool, lines: list[dict]) -> list[SimpleLine]:
    sign = 1 if board_turn_white else -1
    return [SimpleLine(l["uci"], sign * l["cp"], l["pv"]) for l in lines]


def get(session: Session, fen: str, *, min_nodes=0, min_multipv=1, touch=True) -> PositionEval | None:
    row = session.get(PositionEval, norm(fen))
    if row is None or row.nodes < min_nodes or row.multipv < min_multipv:
        return None
    if touch:
        row.hits += 1
    return row


def put(session: Session, fen: str, stored_lines: list[dict], *, nodes: int, multipv: int, depth: int | None = None, engine: str | None = None, source: str) -> bool:
    """Store (or improve) an entry; returns True when something was written. Positions beyond the first ten moves are not kept."""
    if not eligible(fen) or not stored_lines:
        return False
    key, now = norm(fen), datetime.now(timezone.utc)
    row = session.get(PositionEval, key)
    if row is None:
        session.add(PositionEval(key=key, ply=ply_of(fen), engine=engine, nodes=nodes, multipv=multipv, depth=depth, lines=stored_lines, source=source, created_at=now, updated_at=now))
        return True
    better = (nodes, multipv) > (row.nodes, row.multipv) or (depth or 0) > (row.depth or 0) and nodes >= row.nodes
    if not better:
        return False
    row.engine, row.nodes, row.multipv, row.depth, row.lines, row.source, row.updated_at = engine, nodes, multipv, depth, stored_lines, source, now
    return True


def stats(session: Session) -> dict:
    n = session.scalar(select(func.count()).select_from(PositionEval)) or 0
    hits = session.scalar(select(func.coalesce(func.sum(PositionEval.hits), 0))) or 0
    by_ply = {int(p): c for p, c in session.execute(select(PositionEval.ply, func.count()).group_by(PositionEval.ply))}
    by_source = {s: c for s, c in session.execute(select(PositionEval.source, func.count()).group_by(PositionEval.source))}
    size = sum(len(str(l)) for (l,) in session.execute(select(PositionEval.lines))) if n and n <= 50_000 else n * 400                 # about, in bytes
    deepest = session.scalar(select(func.coalesce(func.max(PositionEval.nodes), 0))) or 0
    deep = session.scalar(select(func.count()).select_from(PositionEval).where(PositionEval.nodes >= DEEP_NODES)) or 0
    oldest, newest = session.execute(select(func.min(PositionEval.created_at), func.max(PositionEval.updated_at))).one()
    return {"positions": n, "hits": int(hits), "bytes": int(size), "byMove": [{"move": m, "positions": sum(c for p, c in by_ply.items() if (p + 1) // 2 == m)} for m in range(0, MAX_PLY // 2 + 1)],
            "bySource": by_source, "oldest": oldest.isoformat() if oldest else None, "newest": newest.isoformat() if newest else None, "maxMoves": MAX_PLY // 2, "deepest": int(deepest), "deep": int(deep)}


def clear(session: Session, source: str | None = None) -> int:
    q = delete(PositionEval)
    if source:
        q = q.where(PositionEval.source == source)
    return session.execute(q).rowcount or 0


class CachedSearch:
    """Wraps a `search(board)` so that opening positions come from the cache and new results are stored. `session_factory` gives a fresh session per call, so the
    wrapper is safe on any thread."""

    def __init__(self, search, session_factory, *, nodes: int, multipv: int, engine: str | None = None, source="analysis"):
        self.search, self.sf, self.nodes, self.multipv, self.engine, self.source = search, session_factory, nodes, multipv, engine, source
        self.hits = self.misses = 0

    def __call__(self, board: chess.Board):
        fen = board.fen()
        if not eligible(fen) or board.is_game_over():
            return self.search(board)
        with self.sf() as s:
            row = get(s, fen, min_nodes=self.nodes, min_multipv=self.multipv)
            if row is not None:
                s.commit()
                self.hits += 1
                return from_stored(board.turn == chess.WHITE, row.lines)
        lines = self.search(board)
        self.misses += 1
        if lines:
            with self.sf() as s:
                put(s, fen, to_stored(board.turn == chess.WHITE, lines), nodes=self.nodes, multipv=self.multipv, engine=self.engine, source=self.source)
                s.commit()
        return lines
