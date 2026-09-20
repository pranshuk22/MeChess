"""Verify every anchor's aliases against the PGN Mentor page and archives, so spelling mistakes cannot silently lose games.

For each anchor: the game count the page lists for the file, the games the aliases actually match inside the archive,
the page's display name against our alias tokens, and every unmatched name that resembles the surname. Archives are
downloaded one at a time and deleted straight away."""
import html
import re
import time
from pathlib import Path

from ..ingest import http
from . import anchor_sources as AS
from . import anchors as A

PAGE_URL = "https://www.pgnmentor.com/files.html"
_ROW = re.compile(r'href="players/([^"/]+)\.zip">[^<]*</a>.*?</td><td>([^<,]+),\s*([\d,]+) games', re.S)


def parse_page(page_html):
    """{file stem: (display name, games listed)} from the PGN Mentor files page."""
    out = {}
    for stem, name, n in _ROW.findall(page_html):
        out.setdefault(stem, (html.unescape(name).strip(), int(n.replace(",", ""))))
    return out


def name_tokens(display):
    return {t for t in A.normalise(display).split(" ") if t}


def display_name_problems(display, aliases):
    """Tokens of the page's display name ('Mikhail Tal') that appear in none of our aliases (a possible misspelling)."""
    alias_tokens = set()
    for a in aliases:
        alias_tokens |= name_tokens(a)
    # an alias may abbreviate a first name to a prefix ('Ju' for Judit): count a token as covered if any alias token is a prefix
    return sorted(t for t in name_tokens(display) if not any(t.startswith(x) or x.startswith(t) for x in alias_tokens))


def check_archive(texts, aliases, *, min_games=3, similarity=0.65):
    """(games matched by the aliases, [(unmatched similar name, games)]) for one archive's game texts."""
    census = A.name_census(texts, aliases)
    matched = sum(k for _, k, ok in census if ok)
    return matched, A.unmatched_variants(census, aliases, min_games=min_games, similarity=similarity)


def verify(config, page_html, tmp_dir, *, only=None, getter=None, pause=0.5, log=print):
    """One result dict per selected anchor; logs a line per anchor and a final list of the ones needing attention."""
    page = parse_page(page_html)
    results = []
    keys = [k for k, v in config["anchors"].items() if v.get("selected", True) and (not only or k in only)]
    for i, key in enumerate(keys, 1):
        spec = config["anchors"][key]
        stem = AS.file_stem(spec)
        res = {"key": key, "file": stem, "problems": []}
        if stem not in page:
            res["problems"].append(f"file '{stem}' is not listed on the PGN Mentor page")
            log(f"[{i}/{len(keys)}] {key}: NOT ON PAGE ({stem})")
            results.append(res)
            continue
        display, listed = page[stem]
        res.update(display=display, listed=listed)
        bad = display_name_problems(display, spec["aliases"])
        if bad:
            res["problems"].append(f"page name '{display}': {bad} not covered by any alias")
        raw = Path(tmp_dir) / f"{key}.zip"
        n = AS.download(AS.BASE.format(name=stem), raw, getter=getter)
        if n is None:
            res["problems"].append("download failed")
            log(f"[{i}/{len(keys)}] {key}: DOWNLOAD FAILED")
            results.append(res)
            continue
        try:
            texts = list(A.read_game_texts(raw))
        finally:
            raw.unlink(missing_ok=True)
        matched, variants = check_archive(texts, spec["aliases"])
        res.update(archive=len(texts), matched=matched, variants=variants)
        if matched < 0.9 * listed:
            res["problems"].append(f"aliases match only {matched} of the {listed} games the page lists")
        if variants:
            res["problems"].append("unmatched similar names: " + ", ".join(f"'{n}' x{k}" for n, k in variants[:6]))
        log(f"[{i}/{len(keys)}] {key}: page '{display}' lists {listed}; archive has {len(texts)}; aliases match {matched} "
            f"({100 * matched / max(listed, 1):.0f}%)" + ("   <-- CHECK" if res["problems"] else "   ok"))
        for p in res["problems"]:
            log(f"      ! {p}")
        results.append(res)
        if pause:
            time.sleep(pause)
    bad = [r for r in results if r["problems"]]
    log(f"\nverified {len(results)} anchors; {len(bad)} need attention: {[r['key'] for r in bad]}")
    return results
