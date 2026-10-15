"""Analysing games with Stockfish as a background job: one engine process for the whole job (a fresh game for each), settings from the player's settings."""
import io

import chess.pgn
from sqlalchemy import select

from ..analysis import runner as AR
from ..uci_client import UciEngine
from .config import AppConfig
from .models import Analysis, Game
from .models import Analysis
from .services import cache as CA
from .services import coach as CO
from .services import games as G
from .workspace import find_engine


def unanalysed_ids(session, limit=None):
    q = select(Game.id).where(Game.id.not_in(select(Analysis.game_id))).order_by(Game.played_at.desc().nulls_last(), Game.played_time.desc().nulls_last(), Game.created_at.desc())
    return list(session.scalars(q.limit(limit) if limit else q))


def analyse_games(config: AppConfig, session_factory, ids, settings, ctx, engine_factory=None) -> str:
    path = find_engine(config, settings.engine_path)
    if path is None and engine_factory is None:
        raise RuntimeError("Stockfish was not found: install it or set its path in Settings")
    eng = (engine_factory or (lambda: UciEngine([path], options={"Threads": settings.threads, "Hash": settings.hash_mb}).start()))()
    done = skipped = drills = 0
    try:
        search = AR.engine_search(eng, nodes=settings.nodes, multipv=settings.multipv)
        if settings.use_cache:                                                  # opening positions are looked up (and stored) instead of searched again
            search = CA.CachedSearch(search, session_factory, nodes=settings.nodes, multipv=settings.multipv, engine=getattr(eng, "name", None))
        s = session_factory()
        try:
            for i, gid in enumerate(ids):
                ctx.check()
                g = s.get(Game, gid)
                game = chess.pgn.read_game(io.StringIO(g.pgn)) if g and g.pgn else None
                if game is None or not any(True for _ in game.mainline_moves()):
                    skipped += 1
                    continue
                eng.new_game()
                res = AR.analyse_game(game, search)
                G.save_analysis(s, gid, res, nodes=settings.nodes, multipv=settings.multipv, engine=getattr(eng, "name", None))
                s.flush()
                drills += CO.add_game_drills(s, g, s.get(Analysis, gid))            # the player's biggest mistakes in this game become drills
                s.commit()
                done += 1
                ctx.progress((i + 1) / len(ids), f"game {i + 1:,} of {len(ids):,}")
        finally:
            s.close()
    finally:
        eng.close()
    hits = getattr(search, "hits", 0)
    return f"{done:,} games analysed" + (f", {skipped:,} skipped" if skipped else "") + (f" ({hits:,} opening positions came from the cache)" if hits else "") + (f"; {drills:,} new practice positions" if drills else "")
