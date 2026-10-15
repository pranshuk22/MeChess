"""The database: one SQLite file. Tables grow with the milestones; every change is a migration (`migrations/versions`)."""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Game(Base):
    __tablename__ = "games"
    id: Mapped[str] = mapped_column(String, primary_key=True)                  # stable per game: "lichess:AbCd1234", "chesscom:123", "pgn:<hash>", ...
    source: Mapped[str] = mapped_column(String, index=True)
    white: Mapped[str] = mapped_column(String)
    black: Mapped[str] = mapped_column(String)
    white_elo: Mapped[int | None] = mapped_column(Integer)
    black_elo: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(String)                                # "1-0", "0-1", "1/2-1/2", "*"
    played_at: Mapped[str | None] = mapped_column(String, index=True)         # ISO date (or just the year)
    speed: Mapped[str | None] = mapped_column(String)
    opening: Mapped[str | None] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String)
    user_colour: Mapped[str | None] = mapped_column(String)                    # which side is the player's, when known
    pgn: Mapped[str | None] = mapped_column(Text)
    plies: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Analysis(Base):
    __tablename__ = "analyses"
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), primary_key=True)
    nodes: Mapped[int] = mapped_column(Integer)
    multipv: Mapped[int] = mapped_column(Integer)
    engine: Mapped[str | None] = mapped_column(String)
    accuracy_white: Mapped[float | None] = mapped_column(Float)
    accuracy_black: Mapped[float | None] = mapped_column(Float)
    moves: Mapped[list] = mapped_column(JSON)                                  # [{san, uci, cls, loss, best, winBefore, winAfter, cp}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)                    # queued, running, done, failed, cancelled
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)


class PositionEval(Base):
    """The engine's verdict on an opening position (the first ten moves), kept so that the same opening is not searched again and again. Deleting the table's rows is always safe."""
    __tablename__ = "position_evals"
    key: Mapped[str] = mapped_column(String, primary_key=True)                 # the position without the move counters (placement, side, castling, en passant)
    ply: Mapped[int] = mapped_column(Integer, index=True)                      # half-moves played to reach it
    engine: Mapped[str | None] = mapped_column(String)
    nodes: Mapped[int] = mapped_column(Integer)                                # search effort behind the lines (live analysis counts its nodes)
    multipv: Mapped[int] = mapped_column(Integer)
    depth: Mapped[int | None] = mapped_column(Integer)
    lines: Mapped[list] = mapped_column(JSON)                                  # [{uci, cp (white's point of view), pv [uci]}], best first
    source: Mapped[str] = mapped_column(String)                                # analysis, live or build
    hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
