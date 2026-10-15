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
    acc: float | None = Field(default=None, description="the move's accuracy, 0 to 100")
    phase: str | None = Field(default=None, description="opening, middlegame or endgame")


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


class Accounts(BaseModel):
    lichess: str | None = None
    chesscom: str | None = None


class ImportUser(BaseModel):
    username: str
    max: int = Field(200, ge=1, le=20_000)
    only_new: bool = Field(True, description="stop when 30 games in a row are already in the library (the games come newest first)")


class ImportPgn(BaseModel):
    text: str = Field(max_length=50_000_000)
    player: str | None = Field(None, description="the player's name in the PGN, to know which side is theirs")


class AnalyseRequest(BaseModel):
    ids: list[str] | None = Field(None, description="games to analyse; none: every game that has no analysis yet")
    limit: int | None = Field(None, ge=1, description="with no ids: at most this many, newest first")
    nodes: int | None = Field(None, ge=1_000, le=50_000_000)


class Results(BaseModel):
    win: int
    draw: int
    loss: int


class AccuracyStats(BaseModel):
    recent: float | None
    previous: float | None
    series: list[float]


class MistakeStats(BaseModel):
    recent: float | None
    previous: float | None


class OpeningStat(BaseModel):
    name: str
    colour: str
    games: int
    score: float = Field(description="points per game from the player's side, 0 to 1")


class Stats(BaseModel):
    games: int
    analysed: int
    results: Results
    accuracy: AccuracyStats
    mistakesPerGame: MistakeStats
    openings: list[OpeningStat]
