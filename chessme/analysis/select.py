"""Choose the games to analyse for a personal report, from the normalised games (`data/processed/games.jsonl`) and the raw PGN files they came from.

The raw files hold the full game with clocks; the normalised rows say which games are usable, which colour the player had and under which account. The
chosen games are written as one PGN with an added header `MeChessSide` (white / black), so the analysis knows the player's side whatever the account name."""
from collections import defaultdict
from pathlib import Path

from ..model.data import iter_game_texts, quick_headers


def raw_games(paths, platform="lichess"):
    """{game id: PGN text} for every game in the raw PGN files (Lichess: the id in the Site tag, else GameId)."""
    out = {}
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            for text in iter_game_texts(f):
                tags = quick_headers(text)
                gid = tags.get("GameId") or tags.get("Site", "").rsplit("/", 1)[-1]
                if gid:
                    out[f"{platform}:{gid}"] = text
    return out


def choose(rows, *, n, platform="lichess", per_class=None, time_classes=None, since=None, min_plies=20):
    """Rows of the newest usable games (standard chess, rated, long enough): `n` overall, or `per_class` for each time class, optionally only the
    given classes and only since an ISO date. Newest first within the choice."""
    ok = [r for r in rows if r.get("platform") == platform and r.get("usable") and r.get("variant", "standard") == "standard"
          and (r.get("plies") or 0) >= min_plies and (not since or r["played_at"] >= since)
          and (not time_classes or r.get("time_class") in time_classes)]
    ok.sort(key=lambda r: r["played_at"], reverse=True)
    if per_class:
        seen, out = defaultdict(int), []
        for r in ok:
            if seen[r["time_class"]] < per_class:
                seen[r["time_class"]] += 1
                out.append(r)
        return out
    return ok[:n]


def with_side(text, color):
    """The PGN text with a `MeChessSide` header naming the player's colour."""
    lines = text.split("\n")
    at = max(i for i, ln in enumerate(lines[:40]) if ln.startswith("[")) + 1
    return "\n".join(lines[:at] + [f'[MeChessSide "{color}"]'] + lines[at:])


def write_pgn(rows, raw, out):
    """Write the chosen games (with the player's side) to `out`; returns (written, ids missing from the raw files)."""
    missing, chunks = [], []
    for r in rows:
        text = raw.get(r["game_id"])
        if text is None:
            missing.append(r["game_id"])
            continue
        chunks.append(with_side(text.rstrip("\n"), r["color"]) + "\n\n")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text("".join(chunks), encoding="utf-8")
    return len(chunks), missing
