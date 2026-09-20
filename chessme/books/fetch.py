"""Download the public-domain books listed in sources.json (Project Gutenberg plain text, Internet Archive OCR text) and analyse
them with `text.analyse_book`. Polite by design: one request at a time, a pause between books, retries with backoff (the Internet
Archive answers with transient 500s), and a finished book is never fetched again."""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import text as T

SOURCES = Path(__file__).with_name("sources.json")
UA = {"User-Agent": "MeChess-book-reader (research; public-domain texts only)"}


def load_sources(path=SOURCES):
    return json.loads(Path(path).read_text())["books"]


def urls(book):
    """Candidate text URLs of a book, best first."""
    out = []
    if book.get("gutenberg"):
        out.append(f"https://www.gutenberg.org/cache/epub/{book['gutenberg']}/pg{book['gutenberg']}.txt")
    if book.get("archive"):
        name = book.get("archive_file") or f"{book['archive']}_djvu.txt"
        out.append(f"https://archive.org/download/{book['archive']}/{urllib.parse.quote(name)}")
    return out


def get(url, tries=4, pause=5.0, opener=None, sleep=time.sleep):
    """The text at `url`, or None after `tries` attempts (linear backoff)."""
    opener = opener or (lambda u: urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read())
    for i in range(tries):
        try:
            data = opener(url)
            text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
            if len(text) > 5000 and "<title>500" not in text[:400]:
                return text
        except Exception:
            pass
        sleep(pause * (i + 1))
    return None


def run(out_dir, books=None, *, pause=3.0, opener=None, sleep=time.sleep, log=print):
    """Fetch and analyse every book: writes `<id>.txt` (kept for re-analysis) and `<id>.json` (lines, notation counts, concepts).
    Returns {"done", "failed"}."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    done, failed = [], []
    for b in books or load_sources():
        js = out / f"{b['id']}.json"
        if js.exists():
            done.append(b["id"])
            continue
        txt = out / f"{b['id']}.txt"
        text = txt.read_text(errors="replace") if txt.exists() else None
        for u in ([] if text else urls(b)):
            text = get(u, opener=opener, sleep=sleep)
            if text:
                break
        if not text:
            log(f"  {b['id']}: could not download")
            failed.append(b["id"])
            continue
        txt.write_text(text)
        res = T.analyse_book(T.strip_gutenberg(text))
        js.write_text(json.dumps({"id": b["id"], "author": b["author"], "title": b["title"], "declared_notation": b["notation"], **res}))
        log(f"  {b['id']}: {res['paragraphs']} paragraphs, {len(res['lines'])} lines, {res['notation']}")
        done.append(b["id"])
        sleep(pause)
    return {"done": done, "failed": failed}
