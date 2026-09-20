"""A rating-matched population baseline: sample decisions from other players' public games in a Lichess dump.

Streamed (never stored whole): games are filtered by rating band and time control, and a few random decisions per game
are kept for BOTH players when their own rating is inside the band, so the baseline reflects what players of that
strength choose among equally good moves. Items are then run through the same engine-candidate step as the user's."""
import io
import random
from dataclasses import dataclass

import chess
import chess.pgn

from ..ingest.normalize import time_class_from_tc
from ..model.data import CountingReader, iter_game_texts, open_source, quick_headers, text_lines


@dataclass
class PopItem:
    fen: str
    played: str
    mover_elo: int
    ply: int
    platform: int = 0
    player: str = ""
    game: int = 0


def game_items(text, *, lo, hi, time_classes, per_game, min_ply, rng, accept=None):
    """Up to `per_game` random decisions from one game's PGN text (both players), or [] if the game is unsuitable.

    `accept(elo)` (optional) says whether a player's rating is still wanted, so games whose players are only in
    already-full rating bins are dropped from the headers alone, before the expensive move parsing."""
    accept = accept or (lambda elo: True)
    tags = quick_headers(text)
    if tags.get("Variant", "Standard") != "Standard" or not tags.get("Event", "").lower().startswith("rated"):
        return []
    if tags.get("Termination") in ("Abandoned", "Rules infraction"):
        return []
    if time_class_from_tc(tags.get("TimeControl", "-")) not in time_classes:
        return []
    try:
        elo = {chess.WHITE: int(tags["WhiteElo"]), chess.BLACK: int(tags["BlackElo"])}
    except (KeyError, ValueError):
        return []
    if not any(lo <= e < hi and accept(e) for e in elo.values()):
        return []
    game = chess.pgn.read_game(io.StringIO(text))
    if game is None:
        return []
    names = {chess.WHITE: tags.get("White", ""), chess.BLACK: tags.get("Black", "")}
    board, pool = game.board(), []
    for ply, move in enumerate(game.mainline_moves()):
        if ply >= min_ply and lo <= elo[board.turn] < hi and accept(elo[board.turn]) and board.legal_moves.count() >= 2:
            pool.append(PopItem(board.fen(), move.uci(), elo[board.turn], ply, 0, names[board.turn]))
        board.push(move)
    return rng.sample(pool, min(per_game, len(pool)))


def population_items(source, *, lo, hi, n_positions=None, per_bin=None, bin_width=100, time_classes=("blitz", "rapid"),
                     per_game=4, min_ply=8, seed=1, budget_bytes=None, progress=None, progress_every=5000, stats=None):
    """Stream `source` and sample decisions from players rated in [lo, hi).

    With `per_bin`, every `bin_width`-wide rating bin gets that many decisions (rare high ratings are read for longer,
    so the sample is balanced instead of dominated by the crowded middle) and streaming stops when all bins are full.
    With only `n_positions`, it stops at that total. `budget_bytes` caps the compressed bytes read either way.
    Nothing is written to disk: the stream is decompressed and parsed in memory.

    `progress(stats)` is called every `progress_every` games scanned; `stats` (a dict, filled in place) holds
    games_seen, games_used, decisions, bytes_read, per_bin (bin start -> count) and stop_reason
    ("quota" | "budget" | "end_of_data")."""
    if per_bin is None and n_positions is None:
        raise ValueError("give per_bin or n_positions")
    n_bins = -(-(hi - lo) // bin_width)
    counts = [0] * n_bins
    stats = {} if stats is None else stats
    stats.update(games_seen=0, games_used=0, decisions=0, bytes_read=0, stop_reason="end_of_data",
                 per_bin={lo + i * bin_width: 0 for i in range(n_bins)})

    def refresh():
        stats.update(decisions=len(items), bytes_read=reader.count)
        stats["per_bin"] = {lo + i * bin_width: c for i, c in enumerate(counts)}

    binary, close = open_source(source)
    reader = CountingReader(binary, budget_bytes)
    items = []
    try:
        for text in iter_game_texts(text_lines(reader, str(source).endswith(".zst"))):
            stats["games_seen"] += 1
            rng = random.Random(f"{seed}:{quick_headers(text).get('Site', stats['games_seen'])}")
            got = game_items(text, lo=lo, hi=hi, time_classes=time_classes, per_game=per_game, min_ply=min_ply, rng=rng,
                             accept=(lambda e: counts[(e - lo) // bin_width] < per_bin) if per_bin is not None else None)
            if per_bin is not None:
                kept = []
                for it in got:
                    b = (it.mover_elo - lo) // bin_width
                    if counts[b] < per_bin:
                        counts[b] += 1
                        kept.append(it)
                got = kept
            if got:
                stats["games_used"] += 1
                items.extend(got)
            if progress and stats["games_seen"] % progress_every == 0:
                refresh()
                progress(stats)
            if per_bin is not None and all(c >= per_bin for c in counts):
                stats["stop_reason"] = "quota"
                break
            if per_bin is None and len(items) >= n_positions:
                stats["stop_reason"] = "quota"
                break
        else:
            if budget_bytes is not None and reader.count >= budget_bytes:
                stats["stop_reason"] = "budget"
    finally:
        close()
    refresh()
    return items if per_bin is not None else items[:n_positions]
