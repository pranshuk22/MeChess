"""Opening positions for engine-vs-engine matches and self-play."""
import json
import random
from pathlib import Path

import chess

from .uci_client import UciEngine


def from_games(games_jsonl, plies=8, limit=None, seed=1, usable_only=True):
    """Unique positions reached after `plies` half-moves in the player's own games (their real repertoire)."""
    seen, fens = set(), []
    for line in open(games_jsonl):
        row = json.loads(line)
        if usable_only and not row.get("usable"):
            continue
        sans = row.get("moves", "").split()
        if len(sans) < plies:
            continue
        board = chess.Board()
        try:
            for san in sans[:plies]:
                board.push_san(san)
        except ValueError:
            continue
        key = board.epd()  # ignores move counters, so transpositions collapse
        if key in seen:
            continue
        seen.add(key)
        fens.append(board.fen())
    random.Random(seed).shuffle(fens)
    return fens[:limit] if limit else fens


def random_openings(count, plies=6, seed=1):
    """Random legal openings: a fallback for users with no game history yet."""
    rng = random.Random(seed)
    seen, fens = set(), []
    attempts = 0
    while len(fens) < count and attempts < count * 50:
        attempts += 1
        board = chess.Board()
        for _ in range(plies):
            moves = list(board.legal_moves)
            if not moves:
                break
            board.push(rng.choice(moves))
        if board.is_game_over() or board.epd() in seen:
            continue
        seen.add(board.epd())
        fens.append(board.fen())
    return fens


def write_openings(path, fens):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(fens) + "\n")


def read_openings(path):
    return [l.strip() for l in open(path) if l.strip() and not l.startswith("#")]


def filter_balanced(engine_command, fens, depth=6, max_cp=100, options=None):
    """Keep openings the engine evaluates within +-max_cp (avoids matches decided by the opening alone)."""
    kept = []
    with UciEngine(engine_command, options=options) as eng:
        for fen in fens:
            eng.new_game()  # clear the engine's hash so a position's score never depends on the ones before it
            r = eng.go(fen, depth=depth)
            if r.score_kind == "cp" and abs(r.score) <= max_cp:
                kept.append(fen)
    return kept
