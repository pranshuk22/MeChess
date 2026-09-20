"""A theory opening book for everyone (not a personal repertoire): known opening lines, weighted by what players actually play.

  lines    the named opening lines of the Lichess chess-openings dataset (CC0): the moves that count as *theory*
  games    real games (a rating band of the cohort, or any PGN files): how often each theory move is played at that level
  book     both colours; the move at a position is kept if it continues a named line, with weight = how often it is played
           (plus a small prior so a named but rarely seen move is not lost), and only if it has at least `min_share` of the position

The output is the same `book.bin` the controller already reads (`BookReader`), so the public bot can play sound, level-appropriate theory
instead of inventing openings. `theory_positions` also feeds the move classifier's Book class (a move that continues a named line)."""
from collections import Counter, defaultdict
from pathlib import Path

import chess
import chess.pgn

from .format import Entry
from .keys import book_key

LINE_PRIOR = 0.1          # weight of one named line containing the move, next to one game playing it


def load_lines(paths):
    """[(eco, name, [Move ...])] from the Lichess openings TSV files (columns eco, name, pgn); unparsable lines are skipped."""
    out = []
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            eco, name, pgn = parts[:3]
            board, moves = chess.Board(), []
            try:
                for tok in pgn.split():
                    if tok[0].isdigit():
                        continue
                    mv = board.push_san(tok)
                    moves.append(mv)
            except ValueError:
                continue
            out.append((eco, name, moves))
    return out


def theory_positions(lines):
    """{(book_key of the position, uci)} for every move of every named line: the moves that count as theory."""
    seen = set()
    for _, _, moves in lines:
        board = chess.Board()
        for mv in moves:
            seen.add((book_key(board), mv.uci()))
            board.push(mv)
    return seen


def is_theory(board, move, positions):
    """True if `move` in `board` continues a named opening line."""
    return (book_key(board), move.uci()) in positions


def games_from_cohort(data_dir, band=None):
    """Move lists (UCI) and the result for the player, from the cohort game files; `band=(lo, hi)` keeps the players rated in [lo, hi]."""
    from ..style.games_fetch import read_player
    for f in sorted((Path(data_dir) / "games").glob("*.json.gz")):
        d = read_player(f)
        if d.get("short"):
            continue
        for g in d["games"]:
            if band and not (band[0] <= g["elo"] <= band[1]):
                continue
            yield g["moves"].split(), g["meta"].get("color"), g["meta"].get("result")


def games_from_pgn(paths, band=None):
    """(moves, None, None) for every game of the PGN files (both players' ratings must be inside `band` when given and known)."""
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            while (g := chess.pgn.read_game(f)) is not None:
                try:
                    w, b = int(g.headers.get("WhiteElo", 0)), int(g.headers.get("BlackElo", 0))
                except ValueError:
                    w = b = 0
                if band and w and b and not (band[0] <= (w + b) / 2 <= band[1]):
                    continue
                yield [n.move.uci() for n in g.mainline()], None, None


def coverage(entries, games, plies=(4, 8, 12, 16, 20)):
    """{plies: share of games whose first `plies` moves are all in the book}: how deep the book carries a typical game."""
    keys = {(e.key, e.uci()) for e in entries}
    depth = []
    for moves, _, _ in games:
        board, d = chess.Board(), 0
        for uci in moves[: max(plies)]:
            if (book_key(board), uci) not in keys:
                break
            board.push(chess.Move.from_uci(uci))
            d += 1
        depth.append(d)
    n = max(len(depth), 1)
    return {p: sum(x >= p for x in depth) / n for p in plies}


def pick_book(directory, elo):
    """The book file `theory_LO_HI.bin` in `directory` whose band contains `elo` (else the nearest band)."""
    best, gap = None, None
    for f in Path(directory).glob("theory_*_*.bin"):
        try:
            lo, hi = (int(x) for x in f.stem.split("_")[1:3])
        except ValueError:
            continue
        g = 0 if lo <= elo <= hi else min(abs(elo - lo), abs(elo - hi))
        if gap is None or g < gap:
            best, gap = f, g
    return best


def extend(entries, games, *, max_ply=20, min_games=15, min_share=0.08, rounds=8):
    """Follow the book past the named lines: a move that no opening name covers joins the book when, at a position the book reaches,
    at least `min_games` games play it and it is at least `min_share` of the games that arrive there. Repeats (a new move opens new
    positions) for up to `rounds`. Returns (entries + extension entries, number added)."""
    keys = {(e.key, e.uci()) for e in entries}
    added = 0
    entries = list(entries)
    for _ in range(rounds):
        visits, cand = Counter(), defaultdict(Counter)
        for moves, _, _ in games:
            board = chess.Board()
            for uci in moves[:max_ply]:
                k = book_key(board)
                visits[k] += 1
                if (k, uci) not in keys:
                    cand[k][uci] += 1
                    break
                board.push(chess.Move.from_uci(uci))
        new = [(k, u, c) for k, cnt in cand.items() for u, c in cnt.items() if c >= min_games and c / visits[k] >= min_share]
        if not new:
            break
        for k, u, c in new:
            mv = chess.Move.from_uci(u)
            entries.append(Entry(k, mv.from_square, mv.to_square, mv.promotion or 0, float(c), int(c), 500))
            keys.add((k, u))
        added += len(new)
    return entries, added


def build(lines, games=(), *, max_ply=20, min_games=1, min_share=0.03, extend_min_games=15, extend_min_share=0.08):
    """(entries, stats): the theory book. `games` is an iterable of (uci moves, colour, result). Set `extend_min_games=0` to keep to
    named lines only."""
    games = list(games)
    positions = theory_positions(lines)
    named = defaultdict(Counter)                       # key -> uci -> number of named lines that play it
    fen_of = {}
    for _, _, moves in lines:
        board = chess.Board()
        for mv in moves[:max_ply]:
            k = book_key(board)
            named[k][mv.uci()] += 1
            fen_of[k] = board.fen()
            board.push(mv)
    played = defaultdict(Counter)
    score = defaultdict(lambda: defaultdict(float))
    n_games = left_theory = 0
    for moves, colour, result in games:
        n_games += 1
        board = chess.Board()
        for ply, uci in enumerate(moves[:max_ply]):
            k = book_key(board)
            if (k, uci) not in positions:
                left_theory += 1
                break                                  # the game left known theory here
            played[k][uci] += 1
            if result is not None and colour is not None:
                mover_is_player = (board.turn == chess.WHITE) == (colour == "white")
                score[k][uci] += result if mover_is_player else 1.0 - result
            board.push(chess.Move.from_uci(uci))
    entries, dropped = [], Counter()
    for k, cnt in named.items():
        weights = {u: played[k][u] + LINE_PRIOR * named[k][u] for u in cnt}
        total = sum(weights.values())
        for u, w in weights.items():
            if played[k][u] < min_games and n_games:
                dropped["below min_games"] += 1
                continue
            if w / total < min_share:
                dropped["below min_share"] += 1
                continue
            mv = chess.Move.from_uci(u)
            sc = round(1000 * score[k][u] / played[k][u]) if played[k][u] and score[k][u] else 500
            entries.append(Entry(k, mv.from_square, mv.to_square, mv.promotion or 0, float(w), int(played[k][u]), sc))
    cov_named = coverage(entries, games) if games else {}
    added = 0
    if games and extend_min_games:
        entries, added = extend(entries, games, max_ply=max_ply, min_games=extend_min_games, min_share=extend_min_share)
    stats = {"lines": len(lines), "positions": len({e.key for e in entries}), "entries": len(entries), "games": n_games,
             "left_theory": left_theory, "dropped": dict(dropped), "coverage": coverage(entries, games) if games else {},
             "coverage_named_only": cov_named, "extension_moves": added}
    return entries, stats


def render(stats, band=None):
    return (f"# Theory opening book{f' (players rated {band[0]}-{band[1]})' if band else ''}\n\n"
            f"- {stats['lines']} named opening lines, {stats['positions']} positions, {stats['entries']} book moves.\n"
            f"- Popularity from {stats['games']} games.\n"
            + ("- How deep the book carries a typical game (share of games still in book after N plies): "
               + ", ".join(f"{p}: {100 * v:.0f}%" for p, v in stats["coverage"].items()) + ".\n" if stats.get("coverage") else "")
            + (f"- Named lines alone would carry: " + ", ".join(f"{p}: {100 * v:.0f}%" for p, v in stats["coverage_named_only"].items())
               + f". {stats['extension_moves']} popular moves beyond the names were added (played at least {15} times and 8% of the games at that position).\n"
               if stats.get("coverage_named_only") else "")
            + f"- Dropped: {stats['dropped'] or 'nothing'}.\n")
