"""Live analysis over a WebSocket, and the opening explorer."""
import asyncio
import os
import traceback

import chess
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

from .. import workspace
from ..live import lines_from_stored, snapshot_to_stored, to_lines
from ..services import cache as CA
from ..models import Setting
from ..schemas import Settings

router = APIRouter(prefix="/api")
MIN_STORE_DEPTH = 14                                                           # live lines are kept for the cache only from this depth on
MIN_INTERVAL = 0.12                                                            # at most about 8 updates a second to the browser


def _settings(app) -> Settings:
    with app.state.sessions() as s:
        row = s.get(Setting, "app")
        return Settings(**(row.value if row else {}))


@router.websocket("/ws/analysis")
async def analysis_socket(ws: WebSocket):
    """Messages in: {"fen": "...", "multipv": 3} (start or change the analysis) or {"stop": true}. Messages out: {"type": "lines", "fen", "lines": [...]} and
    {"type": "error", "message"}."""
    app = ws.app
    await ws.accept()
    loop = asyncio.get_running_loop()
    latest: dict = {}
    wake = asyncio.Event()
    cur = {"fen": None, "floor": 0, "snapshot": None, "use_cache": True, "engine_name": None}

    def on_snapshot(snapshot, fen):
        latest["data"] = (fen, snapshot)
        loop.call_soon_threadsafe(wake.set)

    def persist():
        """Keep what the engine found for an opening position the player has left (deep enough to be worth keeping)."""
        fen, snap = cur["fen"], cur["snapshot"]
        if not (cur["use_cache"] and fen and snap and CA.eligible(fen)) or min(i["depth"] for i in snap.values()) < MIN_STORE_DEPTH:
            return
        try:
            with app.state.sessions() as s:
                CA.put(s, fen, snapshot_to_stored(fen, snap), nodes=max(i["nodes"] for i in snap.values()), multipv=len(snap), depth=min(i["depth"] for i in snap.values()),
                       engine=cur["engine_name"], source="live")
                s.commit()
        except Exception:
            traceback.print_exc()                                             # the cache is an optimisation: report it, but never break the analysis for it

    async def sender():
        while True:
            await wake.wait()
            wake.clear()
            fen, snapshot = latest["data"]
            if fen == cur["fen"] and min(i["depth"] for i in snapshot.values()) >= cur["floor"]:
                cur["snapshot"] = snapshot
                await ws.send_json({"type": "lines", "fen": fen, "lines": to_lines(fen, snapshot), "cached": False})
            await asyncio.sleep(MIN_INTERVAL)

    task = asyncio.create_task(sender())
    engine = None
    try:
        while True:
            msg = await ws.receive_json()
            persist()
            if msg.get("stop"):
                if engine:
                    engine.stop()
                cur.update(fen=None, snapshot=None)
                continue
            fen = str(msg.get("fen", ""))
            try:
                chess.Board(fen)
            except ValueError:
                await ws.send_json({"type": "error", "message": "that is not a position"})
                continue
            settings = _settings(app)
            path = workspace.find_engine(app.state.config, settings.engine_path)
            if path is None:
                await ws.send_json({"type": "error", "message": "Stockfish was not found: install it or set its path in Settings"})
                continue
            try:
                engine = await loop.run_in_executor(None, app.state.live.get, path, settings.threads, settings.hash_mb)
            except Exception as e:
                await ws.send_json({"type": "error", "message": f"the engine could not be started: {e}"})
                continue
            cur.update(fen=fen, snapshot=None, floor=0, use_cache=settings.use_cache, engine_name=os.path.basename(path))
            if settings.use_cache and CA.eligible(fen):
                with app.state.sessions() as s:
                    row = CA.get(s, fen, touch=True)
                    s.commit()
                    stored = (row.lines, row.depth) if row else None
                if stored:
                    lines = lines_from_stored(fen, *stored)
                    if lines:
                        cur["floor"] = stored[1] or MIN_STORE_DEPTH                      # the engine's first, shallow lines would look worse than the stored ones
                        await ws.send_json({"type": "lines", "fen": fen, "lines": lines, "cached": True})
            engine.analyse(fen, int(msg.get("multipv", 3)), lambda snap, fen=fen: on_snapshot(snap, fen))
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        persist()
        if engine is not None:
            engine.stop()


@router.get("/explorer")
def explorer(request: Request, fen: str, rating: int = Query(1500, ge=0, le=3500)):
    """What players play in a position (from the explorer database built by `explorer-build`), for the rating band around `rating`."""
    path = request.app.state.config.explorer_path
    if not path.is_file():
        raise HTTPException(404, "the opening explorer is not built yet (see the workspace checklist)")
    try:
        chess.Board(fen)
    except ValueError:
        raise HTTPException(422, "that is not a position")
    from ...book import explorer as E
    out = E.query_position(str(path), fen, rating=rating)
    try:
        named = E.opening_at(str(path), fen)
    except Exception:
        named = None
    return {**out, "opening": {"eco": named[0], "name": named[1]} if named else None}
