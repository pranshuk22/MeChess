"""Fetch a user's games from the chess.com public API (monthly archives, cached)."""
import json
import time
from datetime import datetime, timezone

from .http import get

BASE = "https://api.chess.com/pub/player/{user}/games/archives"


def fetch(user, raw_dir):
    out_dir = raw_dir / "chesscom" / user
    out_dir.mkdir(parents=True, exist_ok=True)
    r = get(BASE.format(user=user.lower()))
    if r.status_code == 404:
        print(f"  chesscom: user {user} not found")
        return 0
    if r.status_code != 200:
        print(f"  chesscom: HTTP {r.status_code} for {user}")
        return 0

    archives = r.json().get("archives", [])
    now = datetime.now(timezone.utc)
    recent = {f"{now.year}-{now.month:02d}"}
    prev = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    recent.add(f"{prev[0]}-{prev[1]:02d}")

    total = 0
    for url in archives:
        year, month = url.rstrip("/").split("/")[-2:]
        key = f"{year}-{month}"
        path = out_dir / f"{key}.json"
        if path.exists() and key not in recent:
            total += len(json.loads(path.read_text()).get("games", []))
            continue
        rr = get(url)
        if rr.status_code != 200:
            print(f"  chesscom/{user}: HTTP {rr.status_code} for {key}")
            continue
        path.write_text(rr.text)
        total += len(rr.json().get("games", []))
        time.sleep(0.5)
    print(f"  chesscom/{user}: {total} games across {len(archives)} monthly archives")
    return total
