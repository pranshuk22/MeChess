"""Lichess studies through the public API (annotated games by users): one request at a time, 60 s wait on HTTP 429, no token.

Study content is user-generated; use it for research and learning and do not redistribute it. The exported files stay local; the
folder names carry no usernames."""
import hashlib
import time
import urllib.error
import urllib.request
from pathlib import Path

from .fetch import UA

BY_USER = "https://lichess.org/api/study/by/{user}/export.pgn?comments=true&variations=false&clocks=false"
BY_ID = "https://lichess.org/api/study/{sid}.pgn?comments=true&variations=false&clocks=false"


def _get(url, tries=3, sleep=time.sleep, opener=None):
    opener = opener or (lambda u: urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120).read())
    for i in range(tries):
        try:
            return opener(url).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                sleep(60)                                    # rate limited: wait a full minute, as Lichess asks
            elif e.code == 404:
                return ""                                    # no such user or no public studies: an empty result, not a failure
            else:
                sleep(5 * (i + 1))
        except Exception:
            sleep(5 * (i + 1))
    return None


def run(out_dir, users=(), study_ids=(), *, pause=2.0, sleep=time.sleep, opener=None, log=print):
    """Export every user's public studies and every listed study to `<out>/<sha8>.pgn` (finished ones are skipped).
    Returns {"done", "empty", "failed"}."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stats = {"done": 0, "empty": 0, "failed": 0}
    todo = [(u, BY_USER.format(user=u)) for u in users] + [(s, BY_ID.format(sid=s)) for s in study_ids]
    for key, url in todo:
        path = out / f"{hashlib.sha1(key.encode()).hexdigest()[:8]}.pgn"
        if path.exists():
            stats["done"] += 1
            continue
        text = _get(url, sleep=sleep, opener=opener)
        if text is None:
            stats["failed"] += 1
            log("  a request failed (kept for a rerun)")
        elif not text.strip():
            stats["empty"] += 1
        else:
            path.write_text(text)
            stats["done"] += 1
            log(f"  {path.name}: {text.count('[Event ')} chapters")
        sleep(pause)
    return stats
