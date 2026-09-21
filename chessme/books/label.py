"""Label annotated moves with the trained chess-text model: which concepts a comment discusses, what human verdict it implies, who stands better.

The result is a set of (position, move, concepts) examples for a model that looks at positions (the position-to-concept model): the text model
reads the comment, the label is attached to the board it was written about. Both the keyword lexicon and the model contribute:

  concepts_lexicon   the concepts whose keywords appear in the comment (high precision, low recall)
  concepts_model     the concepts the model finds from context; the model was trained with the keywords hidden, so it is fed the comment
                     with the keywords hidden, and what it adds beyond the lexicon is real context reading
  concepts           their union;  model_only  the ones only the model found (the ones to check by eye)

Streaming and resumable: records are read once, labelled in chunks (sorted by length so a batch has little padding), appended to `OUT.part`
with a progress file, and the part file becomes `OUT` (gzip) when the input is finished. A stopped or interrupted run continues where it stopped."""
import gzip
import json
import os
import time
from pathlib import Path

import numpy as np

from . import nlp as N

CHUNK = 2048
KEEP = ("ply", "color", "fen", "uci", "san", "glyph", "eval", "source", "game")


def read_records(path, skip=0):
    """Records of a (gzipped) JSON-lines file; the first `skip` are passed over without parsing."""
    with (gzip.open(path, "rt", encoding="utf-8") if str(path).endswith(".gz") else open(path, encoding="utf-8")) as f:
        i = 0
        for line in f:
            if not line.strip():
                continue
            i += 1
            if i > skip:
                yield json.loads(line)


def usable(rec, min_chars=25):
    """Only comments that are text the model can read: long enough and English."""
    c = rec.get("comment") or ""
    return len(c) >= min_chars and N.looks_english(c)


def thresholds_of(cfg):
    th = cfg.get("thresholds") if cfg else None
    return np.array(th) if th else np.full(len(N.CONCEPTS), 0.5)


def _softmax(x):
    e = np.exp(x - x.max(1, keepdims=True))
    return e / e.sum(1, keepdims=True)


def label_texts(model, cfg, texts, batch=64):
    """(concept probabilities, judgement probabilities, evaluation probabilities) for `texts`, in the input order, batched by length."""
    import torch
    mask = cfg.get("mask", True) if cfg else True
    inp = [N.mask_keywords(t) if mask else t for t in texts]
    order = sorted(range(len(inp)), key=lambda i: len(inp[i]))
    C, J, E = (np.zeros((len(inp), n), dtype=np.float32) for n in (len(N.CONCEPTS), len(N.JUDGEMENT), len(N.EVAL_CLASSES)))
    device = next(model.parameters()).device
    for s in range(0, len(order), batch):
        idx = order[s:s + batch]
        with torch.autocast(device_type=device.type, enabled=device.type == "cuda"):
            c, j, e = N.predict_batches(model, [inp[i] for i in idx], batch=len(idx))
        model.eval()                                    # predict_batches puts the model back into training mode
        C[idx], J[idx], E[idx] = c, _softmax(j), _softmax(e)      # the heads return logits for judgement and evaluation
    return C, J, E


def label_chunk(model, cfg, recs, batch=64, comment_chars=400):
    """The labelled records for the usable ones among `recs` (others are dropped)."""
    recs = [r for r in recs if usable(r)]
    if not recs:
        return []
    C, J, E = label_texts(model, cfg, [r["comment"] for r in recs], batch)
    th = thresholds_of(cfg)
    out = []
    for r, c, j, e in zip(recs, C, J, E):
        model_c = [N.CONCEPTS[k] for k in np.where(c > th)[0]]
        lex = sorted((r.get("concepts") or {}).keys()) if isinstance(r.get("concepts"), dict) else sorted(r.get("concepts") or [])
        d = {k: r.get(k) for k in KEEP}
        d.update(comment=r["comment"][:comment_chars], concepts_lexicon=lex, concepts_model=model_c,
                 concepts=sorted(set(lex) | set(model_c)), model_only=sorted(set(model_c) - set(lex)),
                 concept_scores={N.CONCEPTS[k]: round(float(c[k]), 3) for k in np.argsort(-c)[:3]},
                 judgement=N.JUDGEMENT[int(j.argmax())], judgement_conf=round(float(j.max()), 3),
                 evaluation=N.EVAL_CLASSES[int(e.argmax())], evaluation_conf=round(float(e.max()), 3))
        out.append(d)
    return out


def _restore(part, prog):
    """(records already read, ) from an interrupted run; the part file is cut back to the last completed chunk (a torn last line is dropped)."""
    if not (part.exists() and prog.exists()):
        part.unlink(missing_ok=True)
        prog.unlink(missing_ok=True)
        return 0
    p = json.loads(prog.read_text())
    with open(part, "r+b") as f:
        f.truncate(p["bytes"])
    return p["read"]


def run(data, out, model, cfg, *, batch=64, limit=None, deadline_minutes=None, chunk=CHUNK, log=print, fresh=False):
    """Label `data` (annotated_moves.jsonl.gz) into `out` (a .jsonl.gz). Returns {"read", "labelled", "finished"}; `finished` is False when the
    time budget ended the run (call again to continue)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    part, prog = Path(str(out) + ".part"), Path(str(out) + ".progress")
    if fresh:
        part.unlink(missing_ok=True)
        prog.unlink(missing_ok=True)
    done = _restore(part, prog)
    if done:
        log(f"continuing after {done} records already read")
    t0, read, labelled = time.time(), done, 0
    stopped = False
    buf = []
    with open(part, "ab") as f:
        def flush():
            nonlocal read, labelled, buf
            lab = label_chunk(model, cfg, buf, batch)
            for d in lab:
                f.write((json.dumps(d, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
            read += len(buf)
            labelled += len(lab)
            buf = []
            prog.write_text(json.dumps({"read": read, "bytes": f.tell()}))
            log(f"{read} records read, {labelled} labelled this session, {(time.time() - t0) / 60:.1f} min")

        for i, rec in enumerate(read_records(data, skip=done), start=done):
            if limit is not None and i >= limit:
                break
            buf.append(rec)
            if len(buf) >= chunk:
                flush()
                if deadline_minutes is not None and (time.time() - t0) / 60 >= deadline_minutes:
                    stopped = True
                    break
        if buf and not stopped:
            flush()
    if stopped:
        log(f"time budget reached after {read} records: rerun to continue")
        return {"read": read, "labelled": labelled, "finished": False}
    with open(part, "rb") as src, gzip.open(out, "wb") as dst:
        for block in iter(lambda: src.read(1 << 20), b""):
            dst.write(block)
    part.unlink()
    prog.unlink(missing_ok=True)
    log(f"wrote {out}")
    return {"read": read, "labelled": labelled, "finished": True}


# ---- report ----------------------------------------------------------------------------------------------------------

def summarise(path, sample=0, seed=0):
    """Statistics of a labelled file (dict) and up to `sample` records whose concepts only the model found, for checking by eye."""
    n = with_lex = with_model = with_any = 0
    per = {c: [0, 0, 0] for c in N.CONCEPTS}                   # lexicon, model, both
    glyph = [0, 0]
    ev = [0, 0]
    conf = []
    pool = []
    for r in read_records(path):
        n += 1
        lex, mod = set(r["concepts_lexicon"]), set(r["concepts_model"])
        with_lex += bool(lex)
        with_model += bool(mod)
        with_any += bool(lex | mod)
        for c in lex | mod:
            per[c][0] += c in lex
            per[c][1] += c in mod
            per[c][2] += c in lex and c in mod
        if r.get("glyph") in N.JUDGEMENT:
            glyph[1] += 1
            glyph[0] += r["judgement"] == r["glyph"]
        if r.get("eval"):
            ev[1] += 1
        conf.append(r["judgement_conf"])
        if r["model_only"]:
            pool.append(r)
    rng = np.random.default_rng(seed)
    pick = [pool[i] for i in rng.permutation(len(pool))[:sample]] if sample else []
    agree = {c: {"lexicon": v[0], "model": v[1], "both": v[2],
                 "model_recall_of_lexicon": round(v[2] / v[0], 3) if v[0] else None,
                 "model_precision_vs_lexicon": round(v[2] / v[1], 3) if v[1] else None} for c, v in per.items() if v[0] or v[1]}
    return ({"records": n, "with_lexicon_concept": with_lex, "with_model_concept": with_model, "with_any_concept": with_any,
             "model_only_records": len(pool), "glyph_labelled": glyph[1], "judgement_matches_glyph": round(glyph[0] / glyph[1], 3) if glyph[1] else None,
             "per_concept": agree}, pick)


def render(stats, pick):
    lines = ["# Labelled annotated moves", "",
             f"{stats['records']} moves with a readable comment; concepts from the lexicon in {stats['with_lexicon_concept']}, from the model in "
             f"{stats['with_model_concept']}, union in {stats['with_any_concept']}; {stats['model_only_records']} have a concept only the model found.", ""]
    if stats["judgement_matches_glyph"] is not None:
        lines += [f"Judgement head against the human glyph on the {stats['glyph_labelled']} glyph-labelled moves: {100 * stats['judgement_matches_glyph']:.1f}% "
                  "(the glyph was not an input: the comment was).", ""]
    lines += ["| concept | lexicon | model | both | model finds the lexicon's | model agrees with lexicon |", "|---|---|---|---|---|---|"]
    for c, v in sorted(stats["per_concept"].items(), key=lambda t: -(t[1]["lexicon"] + t[1]["model"])):
        f = lambda x: "-" if x is None else f"{100 * x:.0f}%"
        lines.append(f"| {c} | {v['lexicon']} | {v['model']} | {v['both']} | {f(v['model_recall_of_lexicon'])} | {f(v['model_precision_vs_lexicon'])} |")
    if pick:
        lines += ["", "## Concepts only the model found (check these by eye)", ""]
        for r in pick:
            lines += [f"- **{', '.join(r['model_only'])}** ({r['source']}, {r['san']}): {r['comment'][:220]!r}"]
    return "\n".join(lines) + "\n"
