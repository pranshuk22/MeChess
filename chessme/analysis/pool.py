"""Analyse many games in parallel: one Stockfish per worker process, one JSON file per finished game (atomic, so a stopped run resumes exactly).

`analyse_task` is the worker: it starts its engine on the first game it gets and keeps it for the rest; the theory book (opening names) is loaded once
per worker. A game the engine cannot finish is reported, not raised, so one bad game does not stop a batch of a thousand."""
import io
import json
from pathlib import Path

import chess.pgn

from . import runner as AR

_STATE = {}


def _start(engine, nodes, openings_dir):
    from ..uci_client import UciEngine
    eng = UciEngine([engine], options={"Threads": 1, "Hash": 64}).start()
    book = None
    tsvs = sorted(Path(openings_dir).glob("*.tsv")) if openings_dir else []
    if tsvs:
        from ..book import theory as TH
        positions = TH.theory_positions(TH.load_lines(tsvs))
        book = lambda board, move: TH.is_theory(board, move, positions)
    return {"engine": eng, "search": AR.engine_search(eng, nodes=nodes, multipv=2), "book": book, "nodes": nodes}


def analyse_task(task):
    """(key, plies analysed or None, error text or None). `task` = (key, pgn text, output path, engine, nodes, openings dir, player name)."""
    key, text, path, engine, nodes, openings_dir, player = task
    st = _STATE.get("k")
    if st is None or st["nodes"] != nodes:
        st = _STATE["k"] = _start(engine, nodes, openings_dir)
    try:
        st["engine"].new_game()                                  # a clean transposition table: the analysis of a game does not depend on the games before it
        game = chess.pgn.read_game(io.StringIO(text))
        res = AR.analyse_game(game, st["search"], book=st["book"])
    except Exception as e:                                       # a game the engine cannot finish must not stop the batch
        return key, None, repr(e)
    res["player_color"] = AR.side_of(game, player)
    res["headers"] = {k: game.headers.get(k, "") for k in ("White", "Black", "Result", "Date", "Site", "Opening", "TimeControl", "ECO", "UTCDate", "UTCTime")}
    path = Path(path)
    path.with_suffix(".tmp").write_text(json.dumps(res))
    path.with_suffix(".tmp").replace(path)
    return key, len(res["moves"]), None


def close():
    """Stop this process's engine (the pool's workers end with their processes)."""
    st = _STATE.pop("k", None)
    if st:
        st["engine"].close()
