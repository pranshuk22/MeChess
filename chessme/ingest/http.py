import time

import requests

# Generic UA on purpose: no personal contact details are sent to third parties.
USER_AGENT = "chessme/0.1 (personal research project)"


RETRY_STATUS = (500, 502, 503, 504)         # server-side hiccups worth another try (a 4xx other than 429 is the caller's problem)


def get(url, *, headers=None, params=None, stream=False, retries=5):
    """GET with polite back-off on HTTP 429, transient server errors (5xx: retried, then returned for the caller to report) and network errors.
    Raises SystemExit when the network or the rate limit never lets a request through."""
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=h, params=params, stream=stream, timeout=60)
        except requests.RequestException as e:
            print(f"  network error ({e}); retry {attempt + 1}/{retries}")
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 429:
            print("  rate limited (429); waiting 65s")
            time.sleep(65)
            continue
        if r.status_code in RETRY_STATUS and attempt + 1 < retries:
            print(f"  server error ({r.status_code}); retry {attempt + 1}/{retries}")
            if hasattr(r, "close"):
                r.close()
            time.sleep(5 * (attempt + 1))
            continue
        return r
    raise SystemExit(f"Giving up on {url}")
