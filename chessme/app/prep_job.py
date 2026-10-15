"""Preparing against an opponent as a background job: fetch their public games, analyse them (the openings of all, whole games for the most recent), then build the report
(`chessme.prep`). Their games are kept for this preparation only (never in the player's library) and can be deleted with it. One engine for the whole job; opening positions
come from (and go to) the same evaluation cache the analysis uses."""
import io
from dataclasses import asdict
from datetime import datetime, timezone

import chess
import chess.pgn
from sqlalchemy import select

from ..analysis import runner as AR
from ..prep import games as PG
from ..prep import report as RP
from ..uci_client import UciEngine
from . import importers
from .config import AppConfig
from .models import Analysis, Game, Prep, PrepGame
from .services import cache as CA
from .services import coach as CO
from .workspace import find_engine

OPEN_PLIES = 24
MAX_FULL_PLIES = 140
KEEP = ("ply", "uci", "color", "loss", "win_before", "win_after", "phase", "class", "best_move", "move", "accuracy")
# how deep to go: nodes per position, how many of the most recent games get a whole-game analysis, how many engine searches the plan may use
DEPTHS = {"quick": {"nodes": 20_000, "full": 0, "budget": 300}, "standard": {"nodes": 50_000, "full": 40, "budget": 700}, "deep": {"nodes": 100_000, "full": 120, "budget": 1600}}
SPEEDS = ("bullet", "blitz", "rapid", "classical")


def to_data(g: PG.OppGame) -> dict:
    return asdict(g)


def from_data(d: dict) -> PG.OppGame:
    return PG.OppGame(**d)


def prune(moves) -> list[dict]:
    return [{k: m[k] for k in KEEP if k in m} for m in moves]


def user_games(session, limit=1500):
    """The player's own games as `OppGame`s (from the library, with their side known) and their analyses, newest first."""
    out, analyses = [], {}
    q = (select(Game, Analysis).outerjoin(Analysis, Analysis.game_id == Game.id).where(Game.user_colour.in_(("white", "black")))
         .order_by(Game.played_at.desc().nulls_last(), Game.played_time.desc().nulls_last(), Game.created_at.desc()).limit(limit))
    for g, a in session.execute(q):
        game = chess.pgn.read_game(io.StringIO(g.pgn)) if g.pgn else None
        if game is None:
            continue
        moves = [m.uci() for m in game.mainline_moves()]
        if not moves:
            continue
        result = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}.get(g.result)
        score = None if result is None else (result if g.user_colour == "white" else 1.0 - result)
        mine, theirs = (g.white_elo, g.black_elo) if g.user_colour == "white" else (g.black_elo, g.white_elo)
        og = PG.OppGame(id=g.id, colour=g.user_colour, moves=moves, score=score, speed=g.speed, date=g.played_at, opening=g.opening, family=PG.family_of(g.opening), opp_elo=mine, their_elo=theirs, termination=None)
        out.append(og)
        if a is not None:
            analyses[g.id] = CO.analysis_moves(g, a)
    return out, analyses


def fetch_games(app_state, prep_id, handles, params, ctx, pgn_text=None):
    """Download (or read from pasted PGN) the opponent's games into `prep_games`; returns the number of new games."""
    names = [h["name"] for h in handles]
    added = 0
    sf = app_state.sessions

    def keep(text):
        nonlocal added
        g = PG.parse(text, names)
        if g is None or (g.speed and params.get("speeds") and g.speed not in params["speeds"]):
            return
        with sf() as s:
            if s.get(PrepGame, (prep_id, g.id)) is None:
                s.add(PrepGame(prep_id=prep_id, id=g.id, data=to_data(g), analysis=None, full=0))
                s.commit()
                added += 1

    if pgn_text is not None:
        for t in importers.split_pgn(pgn_text.splitlines()):
            ctx.check()
            keep(t)
        return added
    for i, h in enumerate(handles):
        lock = app_state.site_locks[h["site"]]
        while not lock.acquire(timeout=0.5):
            ctx.progress(0.0, "Waiting for the other download from this site to finish")
        try:
            fetch = app_state.fetchers[h["site"]]
            n = 0
            for text in fetch(h["name"], params["max_games"], sleep=ctx.sleep, rated_only=params.get("rated_only", True)):
                ctx.check()
                keep(text)
                n += 1
                if n % 10 == 0:
                    ctx.progress(0.2 * (i + min(0.99, n / params["max_games"])) / len(handles), f"{h['name']}: {n:,} games read")
        finally:
            lock.release()
    return added


def make_search(config: AppConfig, sf, settings, nodes, search_factory=None):
    """(search, close): the engine behind the opening cache. `search_factory(nodes, multipv)` replaces Stockfish in tests."""
    multipv = 3
    if search_factory is not None:
        return search_factory(nodes, multipv)
    path = find_engine(config, settings.engine_path)
    if path is None:
        raise RuntimeError("Stockfish was not found: install it or set its path in Settings")
    eng = UciEngine([path], options={"Threads": settings.threads, "Hash": settings.hash_mb}).start()
    raw = AR.engine_search(eng, nodes=nodes, multipv=multipv)
    return CA.CachedSearch(raw, sf, nodes=nodes, multipv=multipv, engine=getattr(eng, "name", None), source="prep"), eng.close


def analyse_opponent(sf, prep_id, search, depth, ctx, base=0.2, span=0.6):
    """Analyse every game's opening part, and whole games for the most recent `depth['full']`; skips what is already analysed."""
    with sf() as s:
        rows = [(g.id, g.data, g.analysis is not None, bool(g.full)) for g in s.scalars(select(PrepGame).where(PrepGame.prep_id == prep_id))]
    rows.sort(key=lambda r: r[1].get("date") or "", reverse=True)
    want_full = {r[0] for r in rows[: depth["full"]]}
    todo = [r for r in rows if (not r[2]) or (r[0] in want_full and not r[3])]
    for k, (gid, data, _, _) in enumerate(todo):
        ctx.check()
        g = from_data(data)
        full = gid in want_full
        moves = g.moves[:MAX_FULL_PLIES] if full else g.moves[:OPEN_PLIES]
        board, game = chess.Board(), chess.pgn.Game()
        node = game
        for u in moves:
            node = node.add_variation(chess.Move.from_uci(u))
        res = AR.analyse_game(game, search)
        with sf() as s:
            row = s.get(PrepGame, (prep_id, gid))
            row.analysis, row.full = prune(res["moves"]), int(full)
            s.commit()
        ctx.progress(base + span * (k + 1) / len(todo), f"analysed {k + 1:,} of {len(todo):,} games")
    return len(todo)


def run_prep(config: AppConfig, app_state, prep_id: str, settings, ctx, *, pgn_text=None, ref=None, search_factory=None) -> str:
    sf = app_state.sessions
    with sf() as s:
        prep = s.get(Prep, prep_id)
        handles, params = list(prep.handles), dict(prep.params)
    depth = DEPTHS[params.get("depth", "standard")]
    try:
        ctx.progress(0.01, "downloading their games")
        fetch_games(app_state, prep_id, handles, params, ctx, pgn_text)
        with sf() as s:
            n = len(list(s.scalars(select(PrepGame.id).where(PrepGame.prep_id == prep_id))))
        if n == 0:
            raise RuntimeError("No games of this opponent were found (check the name, the speeds and the rating filter).")
        search, close = make_search(config, sf, settings, depth["nodes"], search_factory)
        try:
            analyse_opponent(sf, prep_id, search, depth, ctx)
            ctx.progress(0.8, "building the report")
            with sf() as s:
                opp_rows = list(s.scalars(select(PrepGame).where(PrepGame.prep_id == prep_id)))
                opp_games = [from_data(r.data) for r in opp_rows]
                analyses = {r.id: r.analysis for r in opp_rows if r.analysis}
                mine, mine_an = user_games(s)
            you = next((g.opp_elo for g in mine if g.opp_elo), None)                         # (in a user game, `opp_elo` is the player's own rating)
            report = RP.build(opp_games, analyses, mine, mine_an, search, handles=handles, you=you, ref=ref, nodes=depth["nodes"], multipv=3, budget=depth["budget"],
                              progress=lambda f, m: ctx.progress(0.8 + 0.2 * f, m))
        finally:
            close()
        urls = {g.id: g.url for g in opp_games}
        for m in report["weakness"]["moments"]:
            m["url"] = urls.get(m["game"])
        report["recent"] = [{"id": g.id, "url": g.url, "date": g.date, "colour": g.colour, "score": g.score, "opening": g.opening, "speed": g.speed, "plies": len(g.moves), "rating": g.opp_elo, "against": g.their_elo}
                            for g in sorted(opp_games, key=lambda g: g.date or "", reverse=True)[:15]]
        report["made"] = {"depth": params.get("depth", "standard"), "nodes": depth["nodes"], "at": datetime.now(timezone.utc).isoformat(), "fullGames": 0}
        with sf() as s:
            prep = s.get(Prep, prep_id)
            report["made"]["fullGames"] = sum(1 for r in s.scalars(select(PrepGame).where(PrepGame.prep_id == prep_id)) if r.full)
            prep.report, prep.status, prep.error, prep.updated_at = report, "done", None, datetime.now(timezone.utc)
            s.commit()
    except BaseException as e:                                                                   # (a cancel too: the preparation says so instead of staying "running")
        with sf() as s:
            prep = s.get(Prep, prep_id)
            if prep is not None:
                prep.status, prep.error, prep.updated_at = "failed", ("cancelled" if type(e).__name__ == "Cancelled" else str(e)), datetime.now(timezone.utc)
                s.commit()
        raise
    return f"Prepared against {', '.join(h['name'] for h in handles)}: {len(opp_games):,} games"
