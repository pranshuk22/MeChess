"""Getting games in: Lichess and Chess.com by user name (public games only, no passwords), and PGN text. Everything yields PGN texts of single games; `store_pgn`
turns one into a stored game. Polite to the sites: one request at a time, back-off on 429."""
import hashlib
import io
import re
import time
from typing import Iterable, Iterator

import chess.pgn

from .services import games as G

USER = re.compile(r"[A-Za-z0-9_-]{2,30}")
UA = {"User-Agent": "MeChess (local study tool)"}


def valid_user(name: str) -> bool:
    return bool(name and USER.fullmatch(name))


def split_pgn(lines: Iterable[str]) -> Iterator[str]:
    """Single-game PGN texts from lines of a PGN stream (a new game starts at an [Event header after movetext was seen)."""
    buf, seen_moves = [], False
    for line in lines:
        line = line.rstrip("\r\n")
        if line.startswith("[Event ") and seen_moves:
            yield "\n".join(buf).strip() + "\n"
            buf, seen_moves = [], False
        buf.append(line)
        if line and not line.startswith("["):
            seen_moves = True
    if seen_moves:
        yield "\n".join(buf).strip() + "\n"


def lichess_games(user: str, max_games: int, timeout=60) -> Iterator[str]:
    """Newest first; streamed, so a stop (or a few thousand games) costs only what was read."""
    import requests
    if not valid_user(user):
        raise ValueError("that is not a Lichess user name")
    for attempt in range(3):
        r = requests.get(f"https://lichess.org/api/games/user/{user}", params={"max": max_games, "opening": "true", "clocks": "true", "evals": "false", "rated": "true"},
                         headers={**UA, "Accept": "application/x-chess-pgn"}, stream=True, timeout=timeout)
        if r.status_code == 429:
            time.sleep(65)                                                    # one request at a time per address: wait as asked
            continue
        if r.status_code == 404:
            raise ValueError(f"Lichess has no user {user}")
        r.raise_for_status()
        r.encoding = "utf-8"
        yield from split_pgn(r.iter_lines(decode_unicode=True))
        return
    raise RuntimeError("Lichess is busy: try again in a few minutes")


def chesscom_games(user: str, max_games: int, timeout=30) -> Iterator[str]:
    """Newest monthly archives first, standard chess only."""
    import requests
    if not valid_user(user):
        raise ValueError("that is not a Chess.com user name")
    base = f"https://api.chess.com/pub/player/{user.lower()}/games/archives"
    r = requests.get(base, headers=UA, timeout=timeout)
    if r.status_code == 404:
        raise ValueError(f"Chess.com has no user {user}")
    r.raise_for_status()
    n = 0
    for url in reversed(r.json().get("archives", [])):
        time.sleep(0.3)
        a = requests.get(url, headers=UA, timeout=timeout)
        a.raise_for_status()
        for g in reversed(a.json().get("games", [])):
            if g.get("pgn") and g.get("rules", "chess") == "chess":
                yield g["pgn"]
                n += 1
                if n >= max_games:
                    return


def game_key(headers: dict, pgn_text: str) -> tuple[str, str]:
    """(id, source) of a game: its Lichess or Chess.com id when the headers have one, else a hash of the text."""
    site = (headers.get("Site") or "") + " " + (headers.get("Link") or "")
    m = re.search(r"lichess\.org/(\w{8})", site)
    if m:
        return f"lichess:{m.group(1)}", "lichess"
    m = re.search(r"chess\.com/(?:game/)?(?:live|daily)/(\d+)", site)
    if m:
        return f"chesscom:{m.group(1)}", "chesscom"
    return "pgn:" + hashlib.sha1(pgn_text.encode()).hexdigest()[:16], "pgn"


def colour_for(headers: dict, players: Iterable[str]) -> str | None:
    names = {p.strip().lower() for p in players if p and p.strip()}
    if (headers.get("White") or "").lower() in names:
        return "white"
    if (headers.get("Black") or "").lower() in names:
        return "black"
    return None


def store_pgn(session, pgn_text: str, players: Iterable[str] = (), source: str | None = None) -> str:
    """Store one game from PGN text. Returns 'added', 'known', or 'skipped' (no moves, other variant, unreadable)."""
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None or game.errors:
        return "skipped"
    h = dict(game.headers)
    if h.get("Variant", "Standard") not in ("Standard", "From Position", "Chess"):
        return "skipped"
    moves = [m.uci() for m in game.mainline_moves()]
    if not moves:
        return "skipped"
    gid, src = game_key(h, pgn_text)
    new = G.store(session, id=gid, source=source or src, headers=h, user_colour=colour_for(h, players), pgn=str(game), uci_moves=moves)
    return "added" if new else "known"


def import_stream(session_factory, texts: Iterable[str], players, source: str, ctx, *, total: int | None = None, stop_after_known: int | None = None) -> str:
    """Job body: store every game of the stream, in batches; with `stop_after_known`, stop when that many games in a row were already there (newest first streams)."""
    added = known = skipped = run = seen = 0
    s = session_factory()
    try:
        for text in texts:
            ctx.check()
            seen += 1
            try:
                with s.begin_nested():
                    r = store_pgn(s, text, players, source)
            except Exception:
                r = "skipped"
            added += r == "added"
            known += r == "known"
            skipped += r == "skipped"
            run = run + 1 if r == "known" else 0
            if seen % 25 == 0:
                s.commit()
                ctx.progress(min(0.99, seen / total) if total else 0.0, f"{seen:,} games read")
            if stop_after_known and run >= stop_after_known:
                break
        s.commit()
    finally:
        s.close()
    return f"{added:,} new games" + (f", {known:,} already in the library" if known else "") + (f", {skipped:,} skipped" if skipped else "")
