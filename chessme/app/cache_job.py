"""Building the opening cache for the player's own openings: the positions (within the first ten moves) that occur in several of their games, optionally also
the positions of named opening lines, searched once each at the analysis strength and stored."""
import io
from collections import Counter
from pathlib import Path

import chess
import chess.pgn
from sqlalchemy import select

from ..analysis import runner as AR
from ..uci_client import UciEngine
from .config import AppConfig
from .models import Game
from .services import cache as CA
from .workspace import find_engine


def opening_positions(session, min_count: int) -> Counter:
    """How often each opening position occurs in the stored games (first MAX_PLY half-moves, positions after the moves)."""
    counts: Counter = Counter()
    for (pgn,) in session.execute(select(Game.pgn).where(Game.pgn.is_not(None))):
        game = chess.pgn.read_game(io.StringIO(pgn))
        if game is None:
            continue
        board, seen = game.board(), set()
        for i, mv in enumerate(game.mainline_moves()):
            if i >= CA.MAX_PLY:
                break
            board.push(mv)
            seen.add(board.fen())                                                # (counted once per game)
        counts.update(seen)
    return Counter({f: c for f, c in counts.items() if c >= min_count})


def theory_positions(config: AppConfig) -> list[str]:
    from ..book import theory as TH
    files = sorted((config.research_dir / "opening_names").glob("*.tsv"))
    out, seen = [], set()
    for _, _, moves in TH.load_lines(files):
        b = chess.Board()
        for i, mv in enumerate(moves):
            if i >= CA.MAX_PLY:
                break
            b.push(mv)
            f = CA.norm(b.fen())
            if f not in seen:
                seen.add(f)
                out.append(b.fen())
    return out


def build_cache(config: AppConfig, session_factory, settings, ctx, *, min_count=2, limit=300, include_theory=False, engine_factory=None) -> str:
    path = find_engine(config, settings.engine_path)
    if path is None and engine_factory is None:
        raise RuntimeError("Stockfish was not found: install it or set its path in Settings")
    with session_factory() as s:
        counts = opening_positions(s, min_count)
        have = {k for (k,) in s.execute(select(CA.PositionEval.key).where(CA.PositionEval.nodes >= settings.nodes, CA.PositionEval.multipv >= settings.multipv))}
    todo = [f for f, _ in counts.most_common() if CA.norm(f) not in have]
    if include_theory:
        todo += [f for f in theory_positions(config) if CA.norm(f) not in have and f not in todo]
    todo = todo[:limit]
    if not todo:
        return "nothing to add: the positions of your games are already in the cache"
    eng = (engine_factory or (lambda: UciEngine([path], options={"Threads": settings.threads, "Hash": settings.hash_mb}).start()))()
    done = 0
    try:
        search = CA.CachedSearch(AR.engine_search(eng, nodes=settings.nodes, multipv=settings.multipv), session_factory, nodes=settings.nodes, multipv=settings.multipv,
                                 engine=getattr(eng, "name", None), source="build")
        for i, fen in enumerate(todo):
            ctx.check()
            eng.new_game()
            search(chess.Board(fen))
            done += 1
            ctx.progress((i + 1) / len(todo), f"position {i + 1:,} of {len(todo):,}")
    finally:
        eng.close()
    return f"{done:,} opening positions added to the cache"
