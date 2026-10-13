"""Sanity statistics of generated games (`play.game_record` lines): are they chess-like? Results, how games end, length, how much material
changes hands, and how the time is spent. The same numbers can be computed for the real continuations of the same starting positions, but
two things are not comparable: humans resign (generated games are played out) and the time model is crude, so these numbers check that the
harness plays sensible games; whether the games look human is a question for the classifier and the forced-choice study."""
import json
from collections import Counter

import chess
import numpy as np


def read_games(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def replay_counts(record):
    """Counts over the moves PLAYED BY THE MODELS (not the start): captures, checks, promotions, castlings, and the number of moves."""
    board = chess.Board()
    for u in record["start"].split():
        board.push_uci(u)
    c = Counter()
    for u in record["moves"].split():
        move = chess.Move.from_uci(u)
        c["captures"] += board.is_capture(move)
        c["castlings"] += board.is_castling(move)
        c["promotions"] += move.promotion is not None
        board.push(move)
        c["checks"] += board.is_check()
        c["moves"] += 1
    return c


def summarize(records):
    n = len(records)
    if n == 0:
        raise ValueError("no games")
    ends = Counter(r["termination"] for r in records)
    plies = np.array([r["plies"] for r in records])
    played = np.array([len(r["moves"].split()) for r in records])
    counts = Counter()
    for r in records:
        counts.update(replay_counts(r))
    spent = np.concatenate([np.asarray(r["spent"], dtype=float) for r in records if r["spent"]])
    after = np.concatenate([np.asarray(r["clock_after"], dtype=float) for r in records if r["clock_after"]])
    moves = max(counts["moves"], 1)
    return {"games": n,
            "white_wins": sum(r["result"] == "1-0" for r in records) / n, "black_wins": sum(r["result"] == "0-1" for r in records) / n,
            "draws": sum(r["result"] == "1/2-1/2" for r in records) / n,
            "endings": {k: v / n for k, v in sorted(ends.items(), key=lambda kv: -kv[1])},
            "plies_mean": float(plies.mean()), "plies_quartiles": [float(q) for q in np.percentile(plies, [25, 50, 75])],
            "moves_played": int(played.sum()),
            "captures_per_move": counts["captures"] / moves, "checks_per_move": counts["checks"] / moves,
            "promotions_per_game": counts["promotions"] / n, "castlings_per_game": counts["castlings"] / n,
            "spent_median": float(np.median(spent)), "spent_mean": float(spent.mean()), "share_under_1s": float((spent < 1).mean()),
            "share_moves_with_under_10s_left": float((after < 10).mean())}


WHOLE_GAME_ROWS = ("white wins / draws / black wins (%)", "checkmate (% of games)", "time forfeit (%)", "stalemate (%)",
                    "threefold repetition + fifty moves (%)", "plies, quartiles")


def table(summaries, per_move_only=False):
    """Markdown table: one column per named summary. `per_move_only` leaves out how the games ended and their length: after `truncate` those
    describe the whole game, not the stretch that was kept."""
    names = list(summaries)
    rows = [("games", lambda s: f"{s['games']:,}"),
            ("white wins / draws / black wins (%)", lambda s: f"{100 * s['white_wins']:.1f} / {100 * s['draws']:.1f} / {100 * s['black_wins']:.1f}"),
            ("checkmate (% of games)", lambda s: f"{100 * s['endings'].get('checkmate', 0):.1f}"),
            ("time forfeit (%)", lambda s: f"{100 * s['endings'].get('time_forfeit', 0):.1f}"),
            ("stalemate (%)", lambda s: f"{100 * s['endings'].get('stalemate', 0):.1f}"),
            ("threefold repetition + fifty moves (%)", lambda s: f"{100 * (s['endings'].get('threefold_repetition', 0) + s['endings'].get('fifty_moves', 0)):.1f}"),
            ("plies, quartiles", lambda s: " / ".join(f"{q:.0f}" for q in s["plies_quartiles"])),
            ("captures per move (%)", lambda s: f"{100 * s['captures_per_move']:.1f}"),
            ("checks per move (%)", lambda s: f"{100 * s['checks_per_move']:.1f}"),
            ("promotions per game", lambda s: f"{s['promotions_per_game']:.2f}"),
            ("castlings per game", lambda s: f"{s['castlings_per_game']:.2f}"),
            ("seconds per move, median / mean", lambda s: f"{s['spent_median']:.1f} / {s['spent_mean']:.1f}"),
            ("moves made with under 10 s left (%)", lambda s: f"{100 * s['share_moves_with_under_10s_left']:.1f}")]
    if per_move_only:
        rows = [r for r in rows if r[0] not in WHOLE_GAME_ROWS]
    out = ["| statistic | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    out += [f"| {label} | " + " | ".join(fmt(summaries[nm]) for nm in names) + " |" for label, fmt in rows]
    return "\n".join(out)


_STATUS = {"mate": "checkmate", "resign": "resign", "outoftime": "time_forfeit", "timeout": "abandoned", "stalemate": "stalemate", "draw": "draw",
           "insufficientMaterialClaim": "insufficient_material"}


def real_continuation(game, start_ply, gid=None):
    """A Lichess game (the JSON of the games export, with clocks) as a record from ply `start_ply` on, in the format of `play.game_record`, so
    the real continuation of a starting position can be summarised like a generated one. Only derived numbers are kept (no account names)."""
    sans = game["moves"].split()
    clocks = [c / 100.0 for c in game.get("clocks", [])][:len(sans)]            # an extra final clock is listed when a side resigned or ran out of time
    if len(clocks) != len(sans):
        raise ValueError("a clock for every move is needed")
    inc, base = game["clock"]["increment"], game["clock"]["initial"]
    board, ucis, before = chess.Board(), [], [float(base), float(base)]
    spent, after = [], []
    for i, san in enumerate(sans):
        side = i % 2
        ucis.append(board.push_san(san).uci())
        spent.append(max(0.0, before[side] + inc - clocks[i]) if i >= 2 else 0.0)        # the first move of each side is free
        before[side] = clocks[i]
        after.append(clocks[i])
    win = {"white": "1-0", "black": "0-1"}.get(game.get("winner"), "1/2-1/2")
    return {"gid": gid or f"{game['id']}@{start_ply}", "white": game["players"]["white"]["rating"], "black": game["players"]["black"]["rating"],
            "base": base, "inc": inc, "start": " ".join(ucis[:start_ply]), "moves": " ".join(ucis[start_ply:]),
            "spent": [round(s, 2) for s in spent[start_ply:]], "clock_after": [round(c, 2) for c in after[start_ply:]], "result": win,
            "termination": _STATUS.get(game["status"], game["status"]), "plies": len(ucis)}


def truncate(record, plies):
    """The record cut after `plies` half-moves in total (start included): compares per-move statistics over the same stretch of the game when
    one side's games end earlier (humans resign, generated games are played out)."""
    k = max(0, plies - len(record["start"].split()))
    return {**record, "moves": " ".join(record["moves"].split()[:k]), "spent": record["spent"][:k], "clock_after": record["clock_after"][:k],
            "plies": min(record["plies"], plies)}
