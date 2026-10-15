"""Sample games for the end-to-end tests and demos: loads `frontend/src/samples/sample-games.json` (games with analysis, made by tools/make_ui_samples.py) into the
database. The sample ids (s01, s02 ...) are the game ids, the source is "sample"."""
import json
from pathlib import Path

from .models import Analysis, Game
from .services import games as G


def seed_samples(session, path) -> int:
    n = 0
    for rec in json.loads(Path(path).read_text(encoding="utf-8")):
        if session.get(Game, rec["id"]) is not None:
            continue
        moves = rec["moves"]
        headers = {"White": rec["white"], "Black": rec["black"], "Result": rec["result"]}
        session.add(Game(id=rec["id"], source="sample", white=rec["white"], black=rec["black"], white_elo=rec.get("whiteElo"), black_elo=rec.get("blackElo"), result=rec["result"],
                         played_at=str(rec.get("year")) if rec.get("year") else None, speed=rec.get("speed"), opening=rec.get("opening") or None, title=rec.get("title"),
                         user_colour=rec.get("user"), pgn=G.pgn_from_moves([m["uci"] for m in moves], headers), plies=len(moves)))
        session.flush()
        session.add(Analysis(game_id=rec["id"], nodes=30_000, multipv=3, engine="Stockfish", accuracy_white=rec["accuracy"]["white"], accuracy_black=rec["accuracy"]["black"], moves=moves))
        n += 1
    session.commit()
    return n
