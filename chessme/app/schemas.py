"""The API contract (pydantic). The frontend's TypeScript types are generated from the OpenAPI schema these produce."""
from pydantic import BaseModel, Field


class Move(BaseModel):
    san: str
    uci: str
    cls: str
    loss: float
    best: str
    winBefore: float
    winAfter: float
    cp: int = Field(description="evaluation after the move, white's point of view, centipawns (capped at 1500)")


class Accuracy(BaseModel):
    white: float
    black: float


class GameSummary(BaseModel):
    id: str
    source: str
    white: str
    black: str
    whiteElo: int | None
    blackElo: int | None
    result: str
    date: str | None
    speed: str | None
    opening: str | None
    title: str | None
    user: str | None = Field(description="'white' or 'black' when the player's side is known")
    plies: int
    analysed: bool
    accuracy: Accuracy | None
    mistakes: int | None = Field(description="the player's moves that gave away at least 10% win chance (mistake, miss, blunder)")
    spark: list[int] = Field(default_factory=list, description="a few evaluation points (centipawns, white's view) for a sparkline")


class GameDetail(GameSummary):
    moves: list[Move]
    pgn: str | None


class GamePage(BaseModel):
    total: int
    items: list[GameSummary]


class Check(BaseModel):
    id: str
    title: str
    state: str = Field(description="ok | todo | optional")
    detail: str
    action: str | None = Field(default=None, description="id of the action the UI can offer (for example import-legacy)")


class Workspace(BaseModel):
    data_dir: str
    checks: list[Check]
    next_step: str | None


class JobOut(BaseModel):
    id: str
    kind: str
    title: str
    status: str
    progress: float
    message: str | None
    createdAt: str
    startedAt: str | None
    finishedAt: str | None


class Settings(BaseModel):
    engine_path: str | None = None
    nodes: int = Field(100_000, ge=1_000, le=50_000_000)
    multipv: int = Field(5, ge=1, le=10)
    threads: int = Field(1, ge=1, le=64)
    hash_mb: int = Field(64, ge=1, le=65_536)


class SettingsPatch(BaseModel):
    engine_path: str | None = None
    nodes: int | None = Field(None, ge=1_000, le=50_000_000)
    multipv: int | None = Field(None, ge=1, le=10)
    threads: int | None = Field(None, ge=1, le=64)
    hash_mb: int | None = Field(None, ge=1, le=65_536)
