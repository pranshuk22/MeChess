"""Fetch the anchors' game files (PGN Mentor player archives) and turn them into sampled decisions, one anchor at a time.

Disk and privacy discipline: each archive (0.4-2.5 MB) is downloaded, sampled and DELETED straight away (unless
`keep_raw`); only the derived decisions (position, move, rating, game number) are kept. The archives carry a copyright
notice of their publisher, so they are used for local analysis only and never redistributed. A file you place in the
`files_dir` folder (e.g. dubov.pgn) is used instead of a download."""
import json
import re
import time
from pathlib import Path

from ..ingest import http
from . import anchors as A

BASE = "https://www.pgnmentor.com/players/{name}.zip"
MAX_BYTES = 40_000_000  # refuse anything larger than this (the biggest player file is a few MB)


def file_stem(spec):
    """PGN Mentor names its files by surname ('Tal, Mikhail' -> 'Tal'); a `file:` entry in the config overrides that
    (e.g. the Polgar sisters are PolgarJ / PolgarS / PolgarZ)."""
    if spec.get("file"):
        return spec["file"]
    return re.sub(r"[^A-Za-z]", "", spec["aliases"][0].split(",")[0]).capitalize()


def download(url, dest, *, getter=None, max_bytes=MAX_BYTES):
    """Stream `url` to `dest`; returns the byte count, or None on a missing file / error / oversize download."""
    getter = getter or http.get
    try:
        r = getter(url, stream=True)
    except (SystemExit, Exception):
        return None
    if r.status_code != 200:
        return None
    n = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 16):
            n += len(chunk)
            if n > max_bytes:
                f.close()
                dest.unlink()
                return None
            f.write(chunk)
    return n


def describe(key, e, requested):
    """Multi-line log text for one finished anchor (what was found, dropped and used)."""
    f = e["filter_counts"]
    lines = [f"  {key}: peak window asked {e['peak_years']}, used {e['window']}"
             + (f" (widened after {len(e['attempts'])} tries)" if len(e["attempts"]) > 1 else ""),
             f"      archive: {f['seen']:,} games, {f['anchor_games']:,} by this player; dropped: {f['not_serious']} not classical "
             f"(blitz / rapid / simul / online), {f['variant']} variant, {f['no_date']} undated, {f['outside_window']} outside the window",
             f"      kept {f['kept']} serious games in the window; used {e['games_used']} of the {requested} requested"
             + ("  ** FEWER THAN REQUESTED **" if e["games_used"] < requested else "")
             + f"; {e['decisions']} decisions (about {e['decisions'] / max(e['games_used'], 1):.1f} per game)",
             f"      used games: years {e['used_years']}, {e['used_white']} as White / {e['used_black']} as Black, "
             f"mean rating {e['mean_elo'] if e['mean_elo'] else 'not given in the PGN'}"]
    for w, n, _ in e["attempts"][:-1]:
        lines.append(f"      window {w}: only {n} games, widened")
    lines.append("      names in archive: " + ", ".join(f"'{n}' x{k} ({'matched' if ok else 'NOT matched'})"
                                                     for n, k, ok in e["census"][:4]))
    for n, k in e["unmatched_variants"]:
        lines.append(f"      ** WARNING: '{n}' ({k} games) has this player's surname but is not matched: probably a spelling "
                     f"variant, add it to the aliases in configs/anchors.yaml **")
    return "\n".join(lines)


def summary_table(index, sources):
    rows = ["", "SUMMARY", f"  {'anchor':16s}{'status':10s}{'window':14s}{'games':>6s}{'decisions':>10s}"]
    for key, src in sources.items():
        e = index.get(f"anchor_{key}")
        if e:
            rows.append(f"  {key:16s}{'ok':10s}{str(e['window']):14s}{e['games_used']:6d}{e['decisions']:10d}")
        else:
            rows.append(f"  {key:16s}{'MISSING':10s}{src['status']}")
    ok = sum(1 for k in sources if f"anchor_{k}" in index)
    rows.append(f"  {ok} of {len(sources)} anchors have data; {sum(index[k]['decisions'] for k in index):,} decisions in total")
    return "\n".join(rows)


def fetch_anchors(config, out_dir, tmp_dir, *, files_dir=None, only=None, max_games=100, per_game=10, keep_raw=False,
                  redo=False, pause=1.0, getter=None, log=print):
    """Sample decisions from every selected anchor's peak years. Resumable: anchors with an items file are skipped
    unless `redo`. Writes items/anchor_<key>.jsonl, players.json (index for the analysis step) and sources.json.
    Everything that happens is reported through `log` (one line per fact)."""
    out, tmp = Path(out_dir), Path(tmp_dir)
    (out / "items").mkdir(parents=True, exist_ok=True)
    idx_path, src_path = out / "players.json", out / "sources.json"
    index = json.loads(idx_path.read_text()) if idx_path.exists() else {}
    sources = json.loads(src_path.read_text()) if src_path.exists() else {}
    keys = [k for k, v in config["anchors"].items() if v.get("selected", True) and (not only or k in only)]
    log(f"anchors to process: {len(keys)}; {max_games} games each, {per_game} decisions per game; raw archives "
        f"{'kept' if keep_raw else 'deleted after sampling'} in {tmp}")
    t_all = time.time()
    for n_done, key in enumerate(keys, 1):
        spec = config["anchors"][key]
        log(f"[{n_done}/{len(keys)}] {key}")
        if f"anchor_{key}" in index and not redo:
            log(f"  already done ({index[f'anchor_{key}']['decisions']} decisions); use --redo to rebuild")
            sources.setdefault(key, {"source": "earlier run", "status": "ok"})
            continue
        t0 = time.time()
        local = [p for p in Path(files_dir).glob("*") if p.suffix.lower() in (".pgn", ".zip") and key in p.stem.lower()] \
            if files_dir else []
        raw, source = None, None
        if local:
            paths, source = local, "local file"
            log(f"  using your local file(s): {[p.name for p in local]}")
        else:
            url = BASE.format(name=file_stem(spec))
            raw = tmp / f"{key}.zip"
            log(f"  downloading {url}")
            n = download(url, raw, getter=getter)
            if n is None:
                sources[key] = {"source": None, "status": "no file (not on PGN Mentor, or download failed)"}
                log("  NO FILE: not available from PGN Mentor (or the download failed); put a <key>.pgn in the files folder "
                    "to include this anchor")
                src_path.write_text(json.dumps(sources, indent=1))
                continue
            paths, source = [raw], url
            log(f"  downloaded {n / 1024:.0f} KB in {time.time() - t0:.1f}s")
        try:
            entry = A.build_one(key, spec, paths, out, max_games=max_games, per_game=per_game)
        finally:
            if raw is not None and raw.exists() and not keep_raw:
                raw.unlink()  # derived decisions only
                log("  raw archive deleted (only derived decisions kept)")
        index[f"anchor_{key}"] = entry
        sources[key] = {"source": source, "status": "ok", "games_available": entry["games_available"], "window": entry["window"]}
        log(describe(key, entry, max_games) + f"\n      took {time.time() - t0:.1f}s")
        idx_path.write_text(json.dumps(index, indent=1))
        src_path.write_text(json.dumps(sources, indent=1))
        if pause and raw is not None:
            time.sleep(pause)
    log(summary_table(index, sources))
    log(f"finished in {time.time() - t_all:.0f}s")
    return index
