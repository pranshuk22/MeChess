"""How well does a book predict the player's moves in games it was NOT built from?"""
from collections import defaultdict

import chess

from .keys import book_key


def split_by_time(rows, holdout=0.1):
    """(train, test): the newest `holdout` share of usable games form the test set."""
    usable = sorted((r for r in rows if r.get("usable") and r.get("played_at")), key=lambda r: r["played_at"])
    cut = int(len(usable) * (1 - holdout))
    return usable[:cut], usable[cut:]


def evaluate(entries, test_rows, weighter, max_ply=30, buckets=(1, 2, 3, 4, 5, 6, 8, 10, 12, 15)):
    """Score the book on the player's own moves in `test_rows` (only games that pass the profile's filters).

    - coverage:   share of the player's moves (within max_ply) whose position is in the book
    - top1:       among in-book moves, how often the book's most-weighted move is what the player played
    - top3:       same for any of the book's three heaviest moves
    - sampled:    average probability the book would have assigned to the move actually played (i.e. how often
                  a sampled book move equals the player's move), over in-book positions
    """
    by_key = defaultdict(list)
    for e in entries:
        by_key[e.key].append(e)
    tot = defaultdict(lambda: [0, 0, 0, 0, 0.0])  # bucket -> [moves, in_book, top1, top3, prob]
    games = 0
    for row in test_rows:
        if weighter.game_weight(row) <= 0:
            continue
        games += 1
        my_white = row["color"] == "white"
        board, my_move_no = chess.Board(), 0
        for san in row["moves"].split()[:max_ply]:
            try:
                move = board.parse_san(san)
            except ValueError:
                break
            if (board.turn == chess.WHITE) == my_white:
                my_move_no += 1
                cands = sorted(by_key.get(book_key(board), []), key=lambda e: -e.weight)
                for label in ("all", next((b for b in buckets if my_move_no <= b), buckets[-1] + 1)):
                    row_stats = tot[label]
                    row_stats[0] += 1
                    if cands:
                        row_stats[1] += 1
                        played = (move.from_square, move.to_square, move.promotion or 0)
                        ids = [(c.from_sq, c.to_sq, c.promo) for c in cands]
                        row_stats[2] += ids[0] == played
                        row_stats[3] += played in ids[:3]
                        total = sum(c.weight for c in cands)
                        row_stats[4] += sum(c.weight for c in cands if (c.from_sq, c.to_sq, c.promo) == played) / total
            board.push(move)

    def summarize(s):
        moves, inb, t1, t3, prob = s
        return {"moves": moves, "coverage": inb / moves if moves else 0.0,
                "top1": t1 / inb if inb else 0.0, "top3": t3 / inb if inb else 0.0,
                "sampled": prob / inb if inb else 0.0}

    result = {"games": games, "overall": summarize(tot["all"]), "by_move": {}}
    for b in buckets + (buckets[-1] + 1,):
        if tot[b][0]:
            result["by_move"][b] = summarize(tot[b])
    return result


def format_evaluation(res, buckets=(1, 2, 3, 4, 5, 6, 8, 10, 12, 15)):
    o = res["overall"]
    lines = [f"Hold-out evaluation on {res['games']} newest games ({o['moves']} of my opening moves):",
             f"- in the book: **{100 * o['coverage']:.0f}%** of my moves",
             f"- when in the book: top-1 **{100 * o['top1']:.0f}%**, top-3 {100 * o['top3']:.0f}%, "
             f"sampling the book would match my move **{100 * o['sampled']:.0f}%** of the time", "",
             "| my move # | moves | in book | top-1 (when in book) |", "|---|---|---|---|"]
    prev = 0
    for b, s in sorted(res["by_move"].items()):
        label = f"{prev + 1}" if b == prev + 1 else f"{prev + 1}-{b}" if b <= buckets[-1] else f"{prev + 1}+"
        lines.append(f"| {label} | {s['moves']} | {100 * s['coverage']:.0f}% | {100 * s['top1']:.0f}% |")
        prev = b
    return "\n".join(lines)
