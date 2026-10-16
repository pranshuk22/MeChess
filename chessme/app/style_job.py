"""Teaching MeChess to choose like a person from the player's own library: a background job that samples human decisions (the moves played in the stored games, from move 10 on), asks the engine
for its sound candidates at each (so the choice among good moves can be modelled), fits the move-choice model (`mechess.humanprior`) and stores it in the data folder. Two models: `population`
(every move of the library: how players of the pool the player meets choose) and `me` (the player's own moves)."""
import io
import json
from pathlib import Path

import chess.pgn
from sqlalchemy import select

from ..mechess import humanprior as HP
from ..uci_client import UciEngine
from .config import AppConfig
from .models import Game
from .workspace import find_engine

SCOPES = ("population", "me")


def style_dir(config: AppConfig) -> Path:
    return config.data_dir / "style"


def model_path(config: AppConfig, scope: str) -> Path:
    return style_dir(config) / f"{scope}.json"


def status(config: AppConfig) -> dict:
    """{scope: {'available', 'positions', 'trained'}} read from the stored models' notes."""
    out = {}
    for scope in SCOPES:
        p = model_path(config, scope)
        meta = {}
        if p.is_file():
            try:
                meta = json.loads(p.read_text()).get("meta", {})
            except (OSError, ValueError):
                meta = {}
        out[scope] = {"available": p.is_file() and bool(meta), "positions": meta.get("positions", 0), "top1": meta.get("top1"), "uniform_top1": meta.get("uniform_top1"), "trained": meta.get("trained")}
    return out


def library_games(session, limit=2000):
    """[(uci moves, white elo, black elo, user colour)] of the stored games that came from real play (not the computer's own)."""
    out = []
    for g in session.scalars(select(Game).where(Game.pgn.is_not(None), Game.source.in_(("lichess", "chesscom", "pgn"))).order_by(Game.played_at.desc().nulls_last()).limit(limit)):
        game = chess.pgn.read_game(io.StringIO(g.pgn))
        if game is not None:
            out.append(([m.uci() for m in game.mainline_moves()], g.white_elo, g.black_elo, g.user_colour))
    return out


def train(config: AppConfig, sessions, settings, ctx, *, scope="population", decisions=3000, engine_factory=None) -> str:
    from datetime import datetime, timezone
    from ..style import model as SM
    if scope not in SCOPES:
        raise ValueError("scope is population or me")
    path = find_engine(config, settings.engine_path)
    if path is None and engine_factory is None:
        raise RuntimeError("Stockfish was not found: install it or set its path in Settings")
    with sessions() as s:
        games = library_games(s)
    items = HP.sample_decisions(games, decisions, only="user" if scope == "me" else None)
    if len(items) < 200:
        raise RuntimeError("Not enough games in the library yet: import a few hundred of your games first")
    eng = (engine_factory or (lambda: UciEngine([path], options={"Threads": max(1, min(settings.threads, 2)), "Hash": 64}).start()))()
    try:
        model, rep = HP.fit_from_decisions(eng, items, nodes=15_000, multipv=5, cancel=ctx.check, target=decisions,
                                           progress=lambda k, n: ctx.progress(0.95 * k / n, f"looked at {k:,} of {n:,} positions"))
    finally:
        eng.close()
    ev = rep["held_out"]
    SM.save_model(model, model_path(config, scope), positions=rep["positions"], trained=datetime.now(timezone.utc).isoformat(), scope=scope, top=rep["top"],
                  top1=(ev.get("style") or {}).get("top1"), uniform_top1=(ev.get("uniform") or {}).get("top1"), held_out=ev.get("n", 0))
    guess = f"it picks the move a person chose {100 * ev['style']['top1']:.0f}% of the time where a random choice would be right {100 * ev['uniform']['top1']:.0f}%" if ev.get("n") else "trained"
    return f"MeChess learned the {'style of your own moves' if scope == 'me' else 'typical choices of the players in your library'} from {rep['positions']:,} decisions; {guess}"
