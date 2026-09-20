"""One command for everything that learns from books and annotated games (plan 8n): runs the same on a laptop and in a Kaggle
notebook.

  1. books      download the public-domain books, extract game lines and concept counts        -> <out>/books/
  2. pairs      game lines paired with the concepts mentioned around them                       -> <out>/concept_line_pairs.jsonl
  3. annotated  the annotated-game archive, read as a stream                                    -> <out>/annotated/annotated_moves.jsonl.gz
  4. report     one Markdown summary                                                            -> <out>/report.md

Every step skips work already done (`redo` repeats it) and the job can be paused or stopped (`chessme control ... books`)."""
import json
from pathlib import Path

from ..jobs import JobControl, Stopped
from . import annotated as A
from . import fetch as F
from . import glyphs as GL
from . import text as T

STEPS = ("books", "pairs", "annotated", "report")


def build_pairs(books_dir, out_path, window=2):
    """Concept-line pairs of every downloaded book; returns the number of pairs."""
    n = 0
    with open(out_path, "w") as fh:
        for txt in sorted(Path(books_dir).glob("*.txt")):
            paras = T.paragraphs(T.strip_gutenberg(txt.read_text(errors="replace")))
            for r in T.concept_line_pairs(paras, window, book=txt.stem):
                fh.write(json.dumps(r) + "\n")
                n += 1
    return n


def render_report(out):
    out = Path(out)
    L = ["# What the books and annotated games gave", ""]
    books = sorted((out / "books").glob("*.json"))
    if books:
        L += ["## Books", "", "| book | declared | paragraphs | game lines | plies | notation found | concepts (top) |", "|---|---|---|---|---|---|---|"]
        tot_l = tot_p = 0
        for f in books:
            d = json.loads(f.read_text())
            plies = sum(len(l["moves"]) for l in d["lines"])
            tot_l += len(d["lines"]); tot_p += plies
            top = ", ".join(f"{k} {v}" for k, v in sorted(d["concepts"].items(), key=lambda kv: -kv[1])[:3])
            n = d["notation"]
            L.append(f"| {d['id']} | {d.get('declared_notation', '')} | {d['paragraphs']} | {len(d['lines'])} | {plies} | "
                     f"{n['algebraic']} alg / {n['descriptive']} desc | {top} |")
        L += ["", f"Total: {tot_l} game lines, {tot_p} plies, from {len(books)} books. Only lines from the initial position are read; "
                  "most other examples start from a diagram and need diagram recognition first.", ""]
    pairs = out / "concept_line_pairs.jsonl"
    if pairs.exists():
        L += [f"Concept-line pairs: {sum(1 for _ in open(pairs))} (`concept_line_pairs.jsonl`).", ""]
    st = out / "annotated" / "stats.json"
    if st.exists():
        s = json.loads(st.read_text())
        L += ["## Annotated games", "", "| source | games | annotated moves |", "|---|---|---|"]
        L += [f"| {k} | {v} | {s['annotated_moves'].get(k, 0)} |" for k, v in sorted(s["games"].items())]
        L += ["", "### Annotation glyphs (NAG numbers found in the games)", "", "| glyph | meaning | kind | in the games | written in comments |", "|---|---|---|---|---|"]
        for n, c in sorted(s.get("nags", {}).items(), key=lambda kv: -kv[1])[:20]:
            sym, meaning, kind, _ = GL.info(int(n))
            L.append(f"| {sym or '$' + n} | {meaning} | {kind} | {c} | {s.get('text_nags', {}).get(n, 0)} |")
        L += ["", "Human move glyphs found: " + (", ".join(f"`{g}` {n}" for g, n in sorted(s["glyphs"].items(), key=lambda kv: -kv[1])) or "none"),
              f"Annotated moves with a comment: {s['with_comment']}; with a glyph: {s['with_glyph']}.",
              "Concepts mentioned in comments: " + ", ".join(f"{k} {v}" for k, v in sorted(s["concepts"].items(), key=lambda kv: -kv[1])[:12]), ""]
    return "\n".join(L) + "\n"


def run(out_dir, *, steps=STEPS, limit_per_source=None, extra_pgn_dir=None, redo=False, archive=None, control_dir="data/control",
        job="books", opener=None, log=print):
    """Run the chosen steps. Returns {"steps": [...], "stopped": bool}."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ctl = JobControl(job, control_dir, log=log)
    done = []
    with ctl.signals():
        try:
            if "books" in steps:
                ctl.checkpoint()
                log("== books")
                F.run(out / "books", opener=opener, log=log)
                done.append("books")
            if "pairs" in steps:
                ctl.checkpoint()
                pairs = out / "concept_line_pairs.jsonl"
                if redo or not pairs.exists():
                    log(f"== pairs: {build_pairs(out / 'books', pairs)} concept-line pairs")
                done.append("pairs")
            if "annotated" in steps:
                ctl.checkpoint()
                ann = out / "annotated"
                if redo or not (ann / "stats.json").exists():
                    log("== annotated games")
                    path = archive or A.download(ann, opener=opener)
                    stats = A.extract(path, ann, limit_per_source=limit_per_source, extra_pgn_dir=extra_pgn_dir, ctl=ctl, log=log)
                    (ann / "stats.json").write_text(json.dumps(stats))
                done.append("annotated")
            if "report" in steps:
                (out / "report.md").write_text(render_report(out))
                log(f"== report -> {out / 'report.md'}")
                done.append("report")
        except Stopped as e:
            log(f"stopped: {e} (rerun the same command to resume)")
            return {"steps": done, "stopped": True}
    return {"steps": done, "stopped": False}
