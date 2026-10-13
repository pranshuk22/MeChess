"""Games by id from the public Lichess games export (clocks and moves), for the real continuations of the starting positions of a self-play run.
One request at a time, with a pause between requests and a long wait after a rate-limit answer (Lichess asks for a minute)."""
import json
import time
import urllib.error
import urllib.request

URL = "https://lichess.org/api/games/export/_ids?clocks=true&moves=true&opening=false&pgnInJson=false"
BATCH = 300                                     # the most ids one request takes


def _post(ids, timeout=120):
    req = urllib.request.Request(URL, data=",".join(ids).encode(), headers={"Accept": "application/x-ndjson", "Content-Type": "text/plain",
                                                                           "User-Agent": "humanlike-research"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def fetch_games(ids, *, post=_post, batch=BATCH, pause=5.0, rate_limit_wait=65.0, retries=6, sleep=time.sleep, log=print):
    """The games (dicts of the export) of the given ids, in the order Lichess returns them; ids that do not exist are simply missing.
    `post(ids)` returns the ndjson text of one request (replaceable for tests)."""
    ids = list(ids)
    for i in range(0, len(ids), batch):
        chunk = ids[i:i + batch]
        for attempt in range(retries):
            try:
                body = post(chunk)
                break
            except urllib.error.HTTPError as e:
                wait = rate_limit_wait if e.code == 429 else pause * 2 ** attempt
                log(f"  request for ids {i}-{i + len(chunk)} failed ({e.code}); waiting {wait:.0f}s")
                sleep(wait)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                log(f"  request for ids {i}-{i + len(chunk)} failed ({e}); waiting {pause * 2 ** attempt:.0f}s")
                sleep(pause * 2 ** attempt)
        else:
            raise RuntimeError(f"the games export kept failing for ids {i}-{i + len(chunk)}")
        for line in body.splitlines():
            if line.strip():
                yield json.loads(line)
        log(f"  {min(i + batch, len(ids)):,}/{len(ids):,} ids requested")
        if i + batch < len(ids):
            sleep(pause)
