"""Search the comments of the chess books and annotated games (the output of `chessme books-learn` / `books-nlp-label`) by text and by concept. The records are read into one
table with a full-text index; nothing is sent anywhere. Annotator and player names are never part of the records."""
import gzip
import json
import re
from collections import Counter
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from ..models import BookNote, Setting

FILES = ("books_learn/labelled/labelled.jsonl.gz", "books_learn/run/annotated/annotated_moves.jsonl.gz")
BATCH = 2000


def find_source(research_dir: Path) -> Path | None:
    for f in FILES:
        p = Path(research_dir) / f
        if p.is_file():
            return p
    return None


def _concepts(r: dict) -> list[str]:
    c = r.get("concepts")
    if isinstance(c, dict):
        return sorted(c)
    return sorted(set(c or []) | set(r.get("concepts_lexicon") or []))


def iter_records(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("comment") and r.get("fen") and r.get("uci") and r.get("san"):
                yield r


def index(session_factory, research_dir: Path, ctx) -> str:
    path = find_source(research_dir)
    if path is None:
        raise RuntimeError("the book reader's output was not found: run `chessme books-learn` (docs/language-model.md) or copy its result into your data folder")
    s = session_factory()
    try:
        s.execute(delete(BookNote))
        s.execute(text("INSERT INTO book_notes_fts(book_notes_fts) VALUES('delete-all')"))
        s.commit()
        batch, n, concepts = [], 0, Counter()
        for r in iter_records(path):
            names = _concepts(r)
            concepts.update(names)
            batch.append(BookNote(fen=r["fen"], san=r["san"], uci=r["uci"], ply=r.get("ply"), colour=r.get("color"), glyph=r.get("glyph"), judgement=r.get("judgement") or r.get("glyph"),
                                  evaluation=r.get("evaluation"), source=r.get("source"), comment=r["comment"][:2000], concepts="," + ",".join(names) + "," if names else ","))
            if len(batch) >= BATCH:
                s.add_all(batch)
                s.commit()
                n += len(batch)
                batch = []
                ctx.progress(0.0, f"{n:,} comments read")
                ctx.check()
        s.add_all(batch)
        s.commit()
        n += len(batch)
        s.execute(text("INSERT INTO book_notes_fts(rowid, comment) SELECT id, comment FROM book_notes"))
        row = s.get(Setting, "books_stats")
        value = {"concepts": concepts.most_common(60)}
        if row is None:
            s.add(Setting(key="books_stats", value=value))
        else:
            row.value = value
        s.commit()
    finally:
        s.close()
    return f"{n:,} comments indexed"


def status(session: Session, research_dir: Path) -> dict:
    n = session.scalar(select(func.count()).select_from(BookNote)) or 0
    row = session.get(Setting, "books_stats")
    return {"indexed": n, "available": find_source(research_dir) is not None, "concepts": [{"name": k, "count": c} for k, c in (row.value["concepts"] if row and row.value else [])]}


def fts_query(q: str) -> str | None:
    """A safe full-text query from what the player typed: every word, as a prefix (no operators or quotes from the input reach the database)."""
    words = re.findall(r"\w+", q or "")
    return " ".join(f'"{w}"*' for w in words[:8]) or None


def search(session: Session, q: str | None = None, concept: str | None = None, limit: int = 24, offset: int = 0) -> dict:
    query = select(BookNote)
    match = fts_query(q or "")
    if match:
        ids = [i for (i,) in session.execute(text("SELECT rowid FROM book_notes_fts WHERE book_notes_fts MATCH :m ORDER BY rank LIMIT 5000"), {"m": match})]
        query = query.where(BookNote.id.in_(ids))
    if concept and re.fullmatch(r"[\w -]{1,40}", concept):
        query = query.where(BookNote.concepts.like(f"%,{concept},%"))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(BookNote.id).limit(limit).offset(offset)).all()
    return {"total": total, "items": [{"id": r.id, "fen": r.fen, "san": r.san, "uci": r.uci, "ply": r.ply, "colour": r.colour, "glyph": r.glyph, "judgement": r.judgement, "evaluation": r.evaluation,
                                       "source": r.source, "comment": r.comment, "concepts": [c for c in r.concepts.split(",") if c]} for r in rows]}
