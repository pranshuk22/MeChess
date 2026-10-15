"""Import earlier work into the database: the coach's reviewed games (`~/.mechess-coach/games/*.json`) and the folders `chessme analyse` wrote
(`data/analysis/<name>/games/*.json`). Idempotent: a game that is already in is skipped, so it is safe to run again."""
import json
from pathlib import Path

from ..analysis import runner as AR
from .config import AppConfig
from .models import Setting
from .services import games as G
from .workspace import legacy_sources

BATCH = 100


def _coach_record(path: Path):
    rec = json.loads(path.read_text(encoding="utf-8"))
    analysis = {"moves": rec["moves"]}
    colour = rec.get("color")
    headers = {"Result": "*"}
    if rec.get("speed"):
        headers["TimeControl"] = {"bullet": "60+0", "blitz": "180+0", "rapid": "600+0", "classical": "1800+0"}.get(rec["speed"], "")
    if rec.get("rating") and colour in ("white", "black"):
        headers["WhiteElo" if colour == "white" else "BlackElo"] = str(rec["rating"])
    if colour in ("white", "black"):
        headers["White" if colour == "white" else "Black"] = "You"
        headers["Black" if colour == "white" else "White"] = "Opponent"
    return f"coach:{path.stem}", "coach", headers, colour, analysis


def _analyse_record(path: Path, set_name: str):
    rec = json.loads(path.read_text(encoding="utf-8"))
    h = rec.get("headers") or {}
    site = h.get("Site", "")
    gid = f"lichess:{site.rsplit('/', 1)[-1]}" if "lichess.org/" in site else f"analysis:{set_name}:{path.stem}"
    colour = rec.get("player_color")
    colour = {"white": "white", "black": "black"}.get(str(colour).lower()) if colour else None
    return gid, "lichess" if gid.startswith("lichess:") else "analysis", h, colour, {"moves": rec["moves"], "summary": rec.get("summary")}


def import_legacy(config: AppConfig, session_factory, ctx):
    """Job function: imports every game file of every source; returns a summary line."""
    sources = legacy_sources(config)
    total = sum(n for _, _, n in sources) or 1
    seen = added = skipped = failed = 0
    s = session_factory()
    try:
        for kind, folder, _ in sources:
            for path in sorted(folder.glob("*.json")):
                ctx.check()
                seen += 1
                try:
                    gid, source, headers, colour, analysis = _coach_record(path) if kind == "coach" else _analyse_record(path, folder.parent.name)
                except Exception:                                                              # an unreadable file must not stop the rest
                    failed += 1
                    continue
                if not analysis.get("moves"):
                    skipped += 1
                    continue
                nodes, multipv = (100_000, 5) if kind == "coach" else (0, 0)                  # analyse files do not record their settings
                try:
                    with s.begin_nested():                                                    # a savepoint: a failing game does not undo the others of the batch
                        new = G.store(s, id=gid, source=source, headers=headers, user_colour=colour, analysis=analysis, nodes=nodes, multipv=multipv)
                except Exception:
                    failed += 1
                    continue
                added += new
                skipped += not new
                if seen % BATCH == 0:
                    s.commit()
                    ctx.progress(seen / total, f"{seen:,} of {total:,} files")
        row = s.get(Setting, "legacy_import")
        if row is None:
            s.add(Setting(key="legacy_import", value={"files": seen}))
        else:
            row.value = {"files": seen}
        s.commit()
    finally:
        s.close()
    return f"{added:,} games added, {skipped:,} already there or empty" + (f", {failed:,} files could not be read" if failed else "")
