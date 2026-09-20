"""Human-readable repertoire report for a built book."""
import statistics
from collections import defaultdict

import chess

from .keys import book_key


def _lookup(entries):
    by_key = defaultdict(list)
    for e in entries:
        by_key[e.key].append(e)
    return by_key


def san_of(fen, uci):
    board = chess.Board(fen)
    return board.san(chess.Move.from_uci(uci))


def main_line(tree, by_key, my_color, start=None, max_plies=24):
    """Follow the player's most-played book move and the opponent's most common reply, as far as the data goes."""
    board = start.copy() if start else chess.Board()
    parts, plies = [], 0
    while plies < max_plies:
        key = book_key(board)
        if (board.turn == chess.WHITE) == (my_color == chess.WHITE):
            cands = by_key.get(key)
            if not cands:
                break
            best = max(cands, key=lambda e: e.weight)
            move, note = chess.Move.from_uci(best.uci()), f"{best.games}"
        else:
            replies = tree.opp.get(key)
            if not replies:
                break
            uci, n = replies.most_common(1)[0]
            move, note = chess.Move.from_uci(uci), f"{n}"
        label = board.san(move)
        prefix = f"{board.fullmove_number}." if board.turn == chess.WHITE else (f"{board.fullmove_number}..." if not parts else "")
        parts.append(f"{prefix}{label} ({note})".strip())
        board.push(move)
        plies += 1
    return " ".join(parts), plies


def coverage(rows, weighter, entries, max_ply):
    """How many of the player's opening moves, from the start, are in the book (per game)."""
    by_key = _lookup(entries)
    in_book = {(e.key, e.from_sq, e.to_sq, e.promo) for e in entries}
    runs = []
    for row in rows:
        if weighter.game_weight(row) <= 0:
            continue
        my_white = row["color"] == "white"
        board, run = chess.Board(), 0
        for san in row["moves"].split()[:max_ply]:
            try:
                move = board.parse_san(san)
            except ValueError:
                break
            if (board.turn == chess.WHITE) == my_white:
                if (book_key(board), move.from_square, move.to_square, move.promotion or 0) not in in_book:
                    break
                run += 1
            board.push(move)
        runs.append(run)
    return runs


def build_report(tree, entries, dropped_stats, rows, weighter, params, sanity_dropped=None):
    by_key = _lookup(entries)
    lines = ["# Opening book report", ""]
    lines += [
        f"- Games used: **{tree.games_used}**, positions with me to move: **{len(tree.mine)}**",
        f"- Book: **{len(by_key)}** positions, **{len(entries)}** moves (max ply {tree.max_ply})",
        f"- Filters: min_games={params['min_games']}, min_position_games={params['min_position_games']}, "
        f"min_share={params['min_share']}",
    ]
    if dropped_stats:
        lines.append("- Dropped: " + ", ".join(f"{v} {k}" for k, v in dropped_stats.most_common()))
    if sanity_dropped is not None:
        lines.append(f"- Engine sanity check dropped **{len(sanity_dropped)}** moves")
    lines.append("")

    runs = coverage(rows, weighter, entries, tree.max_ply)
    if runs:
        lines += ["## Coverage", "",
                  f"Of {len(runs)} games, my moves stay in the book for a median of **{statistics.median(runs):.0f}** "
                  f"and a mean of **{statistics.mean(runs):.1f}** moves from the start "
                  f"(90th percentile {sorted(runs)[int(0.9 * (len(runs) - 1))]}).",
                  f"{100 * sum(r >= 5 for r in runs) / len(runs):.0f}% of games have their first 5 moves fully in the book, "
                  f"{100 * sum(r >= 8 for r in runs) / len(runs):.0f}% their first 8.", ""]

    lines += ["## Main lines (my move / opponent reply, with game counts)", ""]
    line, n = main_line(tree, by_key, chess.WHITE)
    lines += [f"**As White** ({n} plies): {line or '(no book moves)'}", ""]
    # as Black: one line per common first move of White
    black_roots = {}
    for row in rows:
        if row["color"] == "black" and row["moves"] and weighter.game_weight(row) > 0:
            black_roots[row["moves"].split()[0]] = black_roots.get(row["moves"].split()[0], 0) + 1
    for first, count in sorted(black_roots.items(), key=lambda kv: -kv[1])[:4]:
        b = chess.Board()
        try:
            b.push_san(first)
        except ValueError:
            continue
        line, n = main_line(tree, by_key, chess.BLACK, start=b)
        lines += [f"**As Black vs 1.{first}** ({count} games): 1.{first} {line or '(no book moves)'}", ""]

    lines += ["## Most-visited book positions", ""]
    rows_tbl = []
    for key, cands in by_key.items():
        node = tree.mine[key]
        total = sum(e.weight for e in cands)
        moves = ", ".join(f"{san_of(node.fen, e.uci())} {100 * e.weight / total:.0f}%" for e in
                          sorted(cands, key=lambda e: -e.weight))
        rows_tbl.append((node.games, node.fen.split()[0], moves))
    lines += ["| games | position (board) | my moves |", "|---|---|---|"]
    for games, board, moves in sorted(rows_tbl, reverse=True)[:15]:
        lines.append(f"| {games} | `{board}` | {moves} |")
    lines.append("")

    varied = [(tree.mine[k].games, tree.mine[k].fen, c) for k, c in by_key.items()
              if len(c) >= 3 and min(e.weight for e in c) / sum(e.weight for e in c) >= 0.15]
    lines += ["## Positions where I vary my move (3+ moves, each >= 15%)", ""]
    lines += [f"- {games} games: `{fen.split()[0]}` -> " + ", ".join(san_of(fen, e.uci()) for e in c)
              for games, fen, c in sorted(varied, reverse=True)[:10]] or ["(none)"]
    lines.append("")

    if sanity_dropped:
        lines += ["## Moves removed by the engine check", ""]
        lines += [f"- `{d.fen.split()[0]}`: {san_of(d.fen, d.move)} ({d.loss_cp} cp worse than the best move)"
                  for d in sorted(sanity_dropped, key=lambda d: -d.loss_cp)[:15]]
        lines.append("")
    return "\n".join(lines)
