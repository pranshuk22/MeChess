"""Fetch a user's games from the Lichess export API as PGN (incremental)."""
import json
import os
import re
from datetime import datetime, timezone

from .http import get

API = "https://lichess.org/api/games/user/{user}"
_DATE = re.compile(r'\[UTCDate "(\d{4})\.(\d\d)\.(\d\d)"\]')
_TIME = re.compile(r'\[UTCTime "(\d\d):(\d\d):(\d\d)"\]')


def _latest_ms(pgn_path):
    """Newest game start time (ms epoch) in an existing PGN file, or None."""
    best = None
    date = None
    with open(pgn_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = _DATE.match(line)
            if m:
                date = tuple(map(int, m.groups()))
                continue
            m = _TIME.match(line)
            if m and date:
                dt = datetime(*date, *map(int, m.groups()), tzinfo=timezone.utc)
                ms = int(dt.timestamp() * 1000)
                best = ms if best is None or ms > best else best
                date = None
    return best


def fetch(user, raw_dir):
    out_dir = raw_dir / "lichess" / user
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}

    params = {"clocks": "true", "opening": "true", "evals": "true", "moves": "true"}
    if state.get("since_ms"):
        params["since"] = state["since_ms"] + 1
    headers = {"Accept": "application/x-chess-pgn"}
    token = os.environ.get("LICHESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    r = get(API.format(user=user), headers=headers, params=params, stream=True)
    if r.status_code == 404:
        print(f"  lichess: user {user} not found")
        return 0
    if r.status_code != 200:
        print(f"  lichess: HTTP {r.status_code} for {user}")
        return 0

    # Download to a temp file and only keep it if it holds games, so an empty (or failed) run can
    # never clobber or leave behind a file, and two runs in the same second never collide.
    tmp = out_dir / "download.part"
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 16):
            f.write(chunk)

    n = sum(1 for line in open(tmp, encoding="utf-8", errors="replace") if line.startswith("[Event "))
    if n == 0:
        tmp.unlink()
        print(f"  lichess/{user}: no new games")
        return 0
    stamp = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"
    part = out_dir / f"games_{stamp}.pgn"
    i = 1
    while part.exists():
        part = out_dir / f"games_{stamp}_{i}.pgn"
        i += 1
    tmp.rename(part)
    latest = _latest_ms(part)
    if latest:
        state["since_ms"] = max(latest, state.get("since_ms", 0))
    state_path.write_text(json.dumps(state))
    print(f"  lichess/{user}: {n} new games -> {part.name}")
    return n
