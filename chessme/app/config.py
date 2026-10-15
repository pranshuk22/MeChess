"""Where the app keeps things. Nothing here is personal: the data folder is the player's own (default `~/.mechess`)."""
from dataclasses import dataclass, field
from pathlib import Path

from ..config import ROOT


@dataclass
class AppConfig:
    data_dir: Path = field(default_factory=lambda: Path("~/.mechess").expanduser())
    research_dir: Path = field(default_factory=lambda: ROOT / "data")          # where the command line tools keep explorer, tablebases, models, old analyses
    legacy_coach_dir: Path = field(default_factory=lambda: Path("~/.mechess-coach").expanduser())
    bot_dir: Path = field(default_factory=lambda: ROOT / "bot")                  # the local lichess-bot checkout (see docs/lichess-bot.md)
    engine: str | None = None                                                   # path to Stockfish; None: look on the PATH
    port: int = 8765
    token: str | None = None                                                    # the access key of this run (None: no key, for tests); see security.TokenAuth
    host: str = "127.0.0.1"

    def __post_init__(self):
        self.data_dir = Path(self.data_dir).expanduser()
        self.research_dir = Path(self.research_dir).expanduser()
        self.legacy_coach_dir = Path(self.legacy_coach_dir).expanduser()
        self.bot_dir = Path(self.bot_dir).expanduser()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "mechess.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def explorer_path(self) -> Path:
        mine = self.data_dir / "explorer.db"
        return mine if mine.exists() else self.research_dir / "explorer" / "explorer.db"

    @property
    def syzygy_dir(self) -> Path:
        mine = self.data_dir / "syzygy"
        return mine if mine.is_dir() else self.research_dir / "syzygy"
