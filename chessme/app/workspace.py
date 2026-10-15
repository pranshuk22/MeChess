"""What exists already? A plain checklist of the player's workspace: engine, games, analyses, old files that can be imported, optional extras.
The same scan runs on every start, so nothing has to be done twice."""
import os
import shutil
import subprocess
from pathlib import Path

from .config import AppConfig
from .models import Setting
from .services import games as G


def find_engine(config: AppConfig, setting: str | None = None) -> str | None:
    for cand in (setting, config.engine, shutil.which("stockfish")):
        if cand and Path(cand).expanduser().is_file() and os.access(Path(cand).expanduser(), os.X_OK):
            return str(Path(cand).expanduser())
    return None


_NAMES: dict[str, str | None] = {}


def engine_label(path: str, stored: str | None = None) -> str | None:
    """The engine's name for the workspace checklist. A path the player set was checked when they set it (the name is stored); a program found on the PATH or given on the
    command line is asked once per run. Nothing is started by a plain GET after that."""
    if stored:
        return stored
    if path not in _NAMES:
        _NAMES[path] = engine_name(path)
    return _NAMES[path]


def engine_name(path: str) -> str | None:
    """The engine's own name line (for example "Stockfish 17"), or None when it does not answer as a UCI engine."""
    try:
        out = subprocess.run([path], input="uci\nquit\n", capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        if line.startswith("id name "):
            return line[8:].strip()
    return None


def legacy_sources(config: AppConfig):
    """[(kind, folder, number of game files)] for old work that can be imported: the coach's reviewed games and `analyse` result folders."""
    found = []
    coach = config.legacy_coach_dir / "games"
    if coach.is_dir():
        found.append(("coach", coach, sum(1 for _ in coach.glob("*.json"))))
    base = config.research_dir / "analysis"
    if base.is_dir():
        for d in sorted(base.iterdir()):
            g = d / "games"
            if g.is_dir():
                n = sum(1 for _ in g.glob("*.json"))
                if n:
                    found.append(("analysis", g, n))
    return found


def scan(config: AppConfig, session, engine_setting: str | None = None) -> dict:
    checks = []
    engine = find_engine(config, engine_setting)
    if engine:
        row = session.get(Setting, "app")
        stored = (row.value or {}).get("_engine_name") if row and row.value and engine == str(Path(engine_setting or "").expanduser()) else None
        checks.append({"id": "engine", "title": "Stockfish engine", "state": "ok", "detail": engine_label(engine, stored) or "found", "action": None})
    else:
        checks.append({"id": "engine", "title": "Stockfish engine", "state": "todo", "detail": "not found: install Stockfish or set its path in Settings", "action": "set-engine"})
    n_games, n_analysed = G.counts(session)
    if n_games:
        checks.append({"id": "games", "title": "Games imported", "state": "ok", "detail": f"{n_games:,} games", "action": None})
    else:
        checks.append({"id": "games", "title": "Games imported", "state": "todo", "detail": "none yet: import your games from Lichess, Chess.com or a PGN file", "action": "import"})
    if n_games:
        left = n_games - n_analysed
        checks.append({"id": "analysed", "title": "Games analysed", "state": "ok" if left == 0 else "todo", "detail": f"{n_analysed:,} of {n_games:,}", "action": None if left == 0 else "analyse"})
    old = legacy_sources(config)
    total = sum(n for _, _, n in old)
    done = session.get(Setting, "legacy_import")
    if total and (done is None or (done.value or {}).get("files", 0) < total):
        checks.append({"id": "legacy", "title": "Earlier work found", "state": "todo", "detail": f"{total:,} analysed games from the coach and command-line tools can be imported", "action": "import-legacy"})
    for cid, title, path, missing in (
        ("explorer", "Opening explorer", config.explorer_path, "not built: optional (needed for opening practice and the explorer page)"),
        ("tablebases", "Endgame tablebases", config.syzygy_dir, "not found: optional (needed for endgame practice)"),
    ):
        ok = path.is_dir() and any(path.iterdir()) if cid == "tablebases" else path.is_file()
        checks.append({"id": cid, "title": title, "state": "ok" if ok else "optional", "detail": "found" if ok else missing, "action": None})
    models = list((config.research_dir / "me").rglob("*.pt")) if (config.research_dir / "me").is_dir() else []
    checks.append({"id": "model", "title": "Your personal model", "state": "ok" if models else "optional", "detail": f"{len(models)} checkpoint(s) found" if models else "not trained yet: optional", "action": None})
    order = ["engine", "legacy", "games", "analysed"]
    todo = {c["id"]: c for c in checks if c["state"] == "todo"}
    nxt = next((todo[i] for i in order if i in todo), None)
    return {"data_dir": str(config.data_dir), "checks": checks, "next_step": nxt["action"] if nxt else None}
