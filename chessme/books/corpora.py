"""The larger text corpora of the ChessGPT data (Hugging Face `Waterhorse/chess_data`, `chessgpt_data/`), read as streams:

  annotated_pgn  two JSONL shards (about 175 MB) of annotated PGN, variations included  -> extra annotated games
  stackexchange  the chess Stack Exchange questions with their answers (about 30 MB)      -> human "why" explanations with moves
  wikipedia      chess-related Wikipedia articles (about 40 MB)                           -> concept definitions

Terms: Stack Exchange and Wikipedia text is CC BY-SA (attribution and share-alike): use it for training, keep the outputs local and do not
redistribute the text; Wikipedia titles and URLs are kept in an attribution file. Annotated PGNs keep the terms of their sources."""
import gzip
import io
import json
import re
import urllib.request
from pathlib import Path

import chess.pgn

from . import glyphs as GL
from . import text as T
from .fetch import UA

BASE = "https://huggingface.co/datasets/Waterhorse/chess_data/resolve/main/chessgpt_data/"
FILES = {
    "annotated_pgn": ["annotated_pgn/annotated_pgn-data.jsonl-00000-of-00002", "annotated_pgn/annotated_pgn-data.jsonl-00001-of-00002"],
    "stackexchange": ["stackexchange/data.jsonl"],
    "wikipedia": ["wikipedia/wikipedia-data.jsonl-00000-of-00001"],
}
FEN_RX = re.compile(r'\[FEN\s+"([^"]*)"\]')


def download(kind, out_dir, opener=None, min_bytes=1_000_000):
    """Fetch the files of one corpus (skipped when present); returns their paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    opener = opener or (lambda u: urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300))
    paths = []
    for rel in FILES[kind]:
        path = out / rel.split("/")[-1]
        if not (path.exists() and path.stat().st_size >= min_bytes):
            tmp = path.with_suffix(path.suffix + ".part")
            with opener(BASE + rel) as r, open(tmp, "wb") as f:
                while chunk := r.read(1 << 22):
                    f.write(chunk)
            tmp.replace(path)
        paths.append(path)
    return paths


def iter_jsonl(paths):
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue


def iter_annotated_pgn(paths, limit=None, source="chessgpt_annotated"):
    """Yield (source, game) for every PGN in the JSONL `text` fields."""
    n = 0
    for rec in iter_jsonl(paths):
        if limit and n >= limit:
            return
        try:
            game = chess.pgn.read_game(io.StringIO(rec.get("text", "")))
        except Exception:
            continue
        if game is not None:
            n += 1
            yield source, game


def parse_qa(text):
    """One Stack Exchange thread `Q: ... A: ... A: ...` -> {"question", "answers", "fens"}; None when it has no question."""
    if not text.startswith("Q:"):
        return None
    parts = re.split(r"\n\s*\n\s*A:", text[2:])
    q, answers = parts[0].strip(), [a.strip() for a in parts[1:] if a.strip()]
    fens = [f for f in FEN_RX.findall(text) if f]
    clean = lambda s: GL.normalise_figurines(" ".join(FEN_RX.sub("", s).split()))
    return {"question": clean(q), "answers": [clean(a) for a in answers], "fens": fens}


def iter_qa(paths, limit=None):
    n = 0
    for rec in iter_jsonl(paths):
        qa = parse_qa(rec.get("text", ""))
        if qa and qa["answers"]:
            yield qa
            n += 1
            if limit and n >= limit:
                return


def iter_wikipedia(paths, limit=None):
    """Yield {"title", "url", "text"} for articles that mention chess."""
    n = 0
    for rec in iter_jsonl(paths):
        text = rec.get("text", "")
        meta = rec.get("metadata") or {}
        if re.search(r"chess", text, re.I) and len(text) > 300:
            yield {"title": meta.get("title", ""), "url": meta.get("url", ""), "text": text}
            n += 1
            if limit and n >= limit:
                return


def write_prose(out_dir, se_paths=None, wiki_paths=None, *, limit=None, max_chars=6000):
    """Write `prose/stackexchange.jsonl.gz`, `prose/wikipedia.jsonl.gz` (text cut at `max_chars`) and the Wikipedia attribution list;
    returns statistics with the concept mentions of each corpus."""
    out = Path(out_dir) / "prose"
    out.mkdir(parents=True, exist_ok=True)
    stats = {"stackexchange": {"threads": 0, "answers": 0, "with_fen": 0, "concepts": {}}, "wikipedia": {"articles": 0, "concepts": {}}}
    if se_paths:
        with gzip.open(out / "stackexchange.jsonl.gz", "wt", encoding="utf-8") as fh:
            for qa in iter_qa(se_paths, limit):
                s = stats["stackexchange"]
                s["threads"] += 1
                s["answers"] += len(qa["answers"])
                s["with_fen"] += bool(qa["fens"])
                for k in T.concept_counts(" ".join(qa["answers"])):
                    s["concepts"][k] = s["concepts"].get(k, 0) + 1
                qa["answers"] = [a[:max_chars] for a in qa["answers"]]
                qa["question"] = qa["question"][:max_chars]
                fh.write(json.dumps(qa) + "\n")
    if wiki_paths:
        with gzip.open(out / "wikipedia.jsonl.gz", "wt", encoding="utf-8") as fh, open(out / "wikipedia_attribution.tsv", "w", encoding="utf-8") as at:
            at.write("title\turl\tlicence\n")
            for art in iter_wikipedia(wiki_paths, limit):
                s = stats["wikipedia"]
                s["articles"] += 1
                for k in T.concept_counts(art["text"]):
                    s["concepts"][k] = s["concepts"].get(k, 0) + 1
                at.write(f"{art['title']}\t{art['url']}\tCC BY-SA\n")
                art["text"] = art["text"][:max_chars]
                fh.write(json.dumps(art) + "\n")
    return stats
