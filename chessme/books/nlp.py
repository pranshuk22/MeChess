"""A trained language model for chess text (plan 8p, stages N1 and N4).

One shared text encoder, three heads, trained together (multi-task):
  concepts    which chess concepts a comment or paragraph talks about (outpost, prophylaxis, zugzwang, ...). The labels come from the
              keyword lexicon, but the model never sees the keywords: they are masked in the input, so it has to infer the concept from
              the *context* ("a knight on d5 that no pawn can attack") and therefore generalises past the keywords.
  judgement   the human's verdict on the move (?? ? ?! !? ! !!), learned from the comments of moves that carry that glyph.
  evaluation  who stands better and by how much (equal, White / Black slight / moderate / decisive), from evaluation glyphs.
Training text: the comments of annotated games (all three tasks), plus Stack Exchange answers, Wikipedia paragraphs and book paragraphs
(concepts only). Examples are split by game/document, so no game appears on both sides of the split.

Two encoders: `bow` (hashed word and bigram embeddings; small, fast, runs anywhere) and `transformer` (any Hugging Face encoder, e.g.
distilroberta-base; needs a GPU for real use). Training is resumable, has a wall-clock budget (`deadline_minutes`: it stops cleanly and
saves a checkpoint), and a dry-run mode that runs the same code on a few hundred examples for a few steps."""
import gzip
import hashlib
import json
import re
import time
import zlib
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from ..jobs import Stopped
from . import glyphs as GL
from . import text as T

CONCEPTS = list(T.LEXICON)
JUDGEMENT = ["!!", "!", "!?", "?!", "?", "??"]
EVAL_CLASSES = ["equal", "white slightly better", "white clearly better", "white winning", "black slightly better", "black clearly better", "black winning"]
MASK = "unk"


# ---- examples --------------------------------------------------------------------------------------------------------

def mask_keywords(text):
    """Replace every lexicon keyword by `unk`: the concept label can no longer be read off the input."""
    for rx in T._LEX.values():
        text = rx.sub(MASK, text)
    return text


def looks_english(text):
    words = re.findall(r"[A-Za-z']+", text)
    if len(words) < 4:
        return False
    common = {"the", "a", "and", "is", "to", "of", "in", "it", "white", "black", "this", "that", "for", "with", "on", "be", "not", "but"}
    return sum(w.lower() in common for w in words) / len(words) > 0.12 and sum(ord(c) < 128 for c in text) / len(text) > 0.9


def eval_class(nags):
    for n in nags:
        v = GL.EVAL_SCORE.get(n)
        if v is not None:
            return {0: 0, 1: 1, 2: 2, 3: 3, -1: 4, -2: 5, -3: 6}[v]
    return -1


def judgement_class(nags):
    for n in nags:
        if GL.info(n)[2] == "judgement" and GL.symbol(n) in JUDGEMENT:
            return JUDGEMENT.index(GL.symbol(n))
    return -1


def concept_vector(text):
    counts = T.concept_counts(text)
    return [1.0 if c in counts else 0.0 for c in CONCEPTS]


def _example(text, group, source, judgement=-1, evaluation=-1):
    return {"text": text, "concepts": concept_vector(text), "judgement": judgement, "eval": evaluation, "group": group, "source": source}


def _paragraph_examples(paras, source, group_prefix):
    for i, p in enumerate(paras):
        yield _example(p, f"{group_prefix}:{i // 20}", source)


def build_examples(*, annotated=None, prose_dir=None, books_dir=None, max_per_kind=None, min_chars=25, max_chars=1200):
    """List of examples from the annotated moves file, the prose folder (Stack Exchange, Wikipedia) and the book texts; duplicates
    (same text) and non-English or very short/long text are dropped."""
    out, seen = [], set()
    counts = {}

    def add(ex):
        t = ex["text"]
        h = hashlib.md5(t.encode()).hexdigest()
        if h in seen or not (min_chars <= len(t) <= max_chars) or not looks_english(t):
            return
        k = ex["source"]
        if max_per_kind and counts.get(k, 0) >= max_per_kind:
            return
        seen.add(h)
        counts[k] = counts.get(k, 0) + 1
        out.append(ex)

    if annotated and Path(annotated).exists():
        with gzip.open(annotated, "rt", encoding="utf-8") as fh:
            for line in fh:
                m = json.loads(line)
                nags = m.get("nags") or []
                if m["comment"]:
                    add(_example(m["comment"], f"{m['source']}:{m['game']}", m["source"], judgement_class(nags), eval_class(nags)))
    prose = Path(prose_dir) / "prose" if prose_dir else None
    if prose and (prose / "stackexchange.jsonl.gz").exists():
        with gzip.open(prose / "stackexchange.jsonl.gz", "rt", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                qa = json.loads(line)
                for a in qa["answers"]:
                    add(_example(a[:max_chars], f"se:{i}", "stackexchange"))
    if prose and (prose / "wikipedia.jsonl.gz").exists():
        with gzip.open(prose / "wikipedia.jsonl.gz", "rt", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                for ex in _paragraph_examples(T.paragraphs(json.loads(line)["text"]), "wikipedia", f"wiki:{i}"):
                    add(ex)
    if books_dir:
        for txt in sorted(Path(books_dir).glob("*.txt")):
            for ex in _paragraph_examples(T.paragraphs(T.strip_gutenberg(txt.read_text(errors="replace"))), "books", f"book:{txt.stem}"):
                add(ex)
    return out


def split_of(group, val=0.1, test=0.1):
    """'train' / 'val' / 'test' from a stable hash of the group (a whole game or document stays on one side)."""
    r = (zlib.crc32(group.encode()) % 1000) / 1000.0
    return "test" if r < test else "val" if r < test + val else "train"


# ---- model -----------------------------------------------------------------------------------------------------------

def tokens(text):
    w = re.findall(r"[a-z0-9']+", text.lower())
    return w + [a + "_" + b for a, b in zip(w, w[1:])]


class BowEncoder(nn.Module):
    def __init__(self, dim=256, buckets=1 << 18):
        super().__init__()
        self.buckets, self.dim = buckets, dim
        self.emb = nn.EmbeddingBag(buckets, dim, mode="mean")
        self.norm = nn.LayerNorm(dim)

    def forward(self, texts):
        ids, offsets = [], []
        for t in texts:
            offsets.append(len(ids))
            toks = tokens(t) or ["<empty>"]
            ids.extend(zlib.crc32(w.encode()) % self.buckets for w in toks)
        dev = self.emb.weight.device
        return self.norm(self.emb(torch.tensor(ids, device=dev), torch.tensor(offsets, device=dev)))


class TransformerEncoder(nn.Module):
    def __init__(self, name, max_len=128, tokenizer=None, model=None):
        super().__init__()
        from transformers import AutoModel, AutoTokenizer
        self.tok = tokenizer or AutoTokenizer.from_pretrained(name)
        self.model = model or AutoModel.from_pretrained(name)
        self.max_len, self.dim = max_len, self.model.config.hidden_size

    def forward(self, texts):
        b = self.tok(list(texts), padding=True, truncation=True, max_length=self.max_len, return_tensors="pt")
        dev = next(self.model.parameters()).device
        b = {k: v.to(dev) for k, v in b.items()}
        h = self.model(**b).last_hidden_state
        m = b["attention_mask"].unsqueeze(-1).to(h.dtype)
        return (h * m).sum(1) / m.sum(1).clamp(min=1)


class Tagger(nn.Module):
    def __init__(self, encoder):
        super().__init__()
        self.enc = encoder
        d = encoder.dim
        self.drop = nn.Dropout(0.1)
        self.concepts = nn.Linear(d, len(CONCEPTS))
        self.judgement = nn.Linear(d, len(JUDGEMENT))
        self.evaluation = nn.Linear(d, len(EVAL_CLASSES))

    def forward(self, texts):
        h = self.drop(self.enc(texts))
        return self.concepts(h), self.judgement(h), self.evaluation(h)


def make_encoder(backend, model_name="distilroberta-base", dim=256, max_len=128):
    if backend == "bow":
        return BowEncoder(dim)
    if backend == "transformer":
        return TransformerEncoder(model_name, max_len)
    raise ValueError(f"unknown backend {backend!r}")


# ---- metrics ---------------------------------------------------------------------------------------------------------

def f1_macro(y_true, y_pred, n_classes):
    f = []
    for c in range(n_classes):
        tp = int(((y_true == c) & (y_pred == c)).sum())
        fp = int(((y_true != c) & (y_pred == c)).sum())
        fn = int(((y_true == c) & (y_pred != c)).sum())
        if tp + fn:
            f.append(2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0)
    return float(np.mean(f)) if f else float("nan")


def concept_f1(Y, P):
    """(micro F1, macro F1 over concepts that occur) for binary matrices."""
    tp, fp, fn = (Y * P).sum(), ((1 - Y) * P).sum(), (Y * (1 - P)).sum()
    micro = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else float("nan")
    per = [2 * (Y[:, c] * P[:, c]).sum() / (Y[:, c].sum() + P[:, c].sum()) for c in range(Y.shape[1]) if Y[:, c].sum() > 0]
    return float(micro), float(np.mean(per)) if per else float("nan")


def average_precision(y, score):
    """Area under the precision-recall curve for one concept (NaN when it never occurs). Threshold-free: needs no cut-off to be right."""
    if y.sum() == 0:
        return float("nan")
    order = np.argsort(-score, kind="stable")
    hit = y[order]
    precision = np.cumsum(hit) / (np.arange(len(hit)) + 1)
    return float((precision * hit).sum() / hit.sum())


def tune_thresholds(Y, S, grid=np.linspace(0.05, 0.95, 19)):
    """Per concept, the cut-off in `grid` that gives the best F1 on (validation) data; 0.5 when the concept never occurs."""
    out = np.full(Y.shape[1], 0.5)
    for c in range(Y.shape[1]):
        if Y[:, c].sum() == 0:
            continue
        f = [2 * ((S[:, c] > t) * Y[:, c]).sum() / (Y[:, c].sum() + (S[:, c] > t).sum() + 1e-9) for t in grid]
        out[c] = grid[int(np.argmax(f))]
    return out


@torch.no_grad()
def predict_batches(model, texts, batch=64):
    model.eval()
    C, J, E = [], [], []
    for i in range(0, len(texts), batch):
        c, j, e = model(texts[i:i + batch])
        C.append(torch.sigmoid(c).float().cpu().numpy())
        J.append(j.float().cpu().numpy())
        E.append(e.float().cpu().numpy())
    model.train()
    return np.vstack(C), np.vstack(J), np.vstack(E)


def evaluate(model, examples, mask=True, batch=64, thresholds=None):
    """Concept F1 (micro / macro, at 0.5 and at the tuned per-concept thresholds), concept average precision next to the base rate,
    judgement macro-F1 and accuracy, evaluation macro-F1 and accuracy, each next to the trivial baseline."""
    if not examples:
        return {}
    texts = [mask_keywords(e["text"]) if mask else e["text"] for e in examples]
    C, J, E = predict_batches(model, texts, batch)
    Y = np.array([e["concepts"] for e in examples])
    micro, macro = concept_f1(Y, (C > 0.5).astype(float))
    prior = (Y.mean(0) > 0.5).astype(float)[None].repeat(len(Y), 0)
    out = {"n": len(examples), "concept_f1_micro": micro, "concept_f1_macro": macro, "concept_f1_micro_prior": concept_f1(Y, prior)[0]}
    aps = [average_precision(Y[:, c], C[:, c]) for c in range(Y.shape[1])]
    base = [Y[:, c].mean() for c in range(Y.shape[1]) if Y[:, c].sum() > 0]                # AP of a random ranking = the concept's base rate
    out["concept_ap_macro"] = float(np.nanmean(aps)) if base else float("nan")
    out["concept_ap_baseline"] = float(np.mean(base)) if base else float("nan")
    if thresholds is not None:
        out["concept_f1_micro_tuned"], out["concept_f1_macro_tuned"] = concept_f1(Y, (C > thresholds[None]).astype(float))
    for key, logits, n_cls in (("judgement", J, len(JUDGEMENT)), ("eval", E, len(EVAL_CLASSES))):
        y = np.array([e[key] for e in examples])
        ok = y >= 0
        if ok.sum():
            pred = logits.argmax(1)
            out[f"{key}_n"] = int(ok.sum())
            out[f"{key}_acc"] = float((pred[ok] == y[ok]).mean())
            out[f"{key}_f1_macro"] = f1_macro(y[ok], pred[ok], n_cls)
            out[f"{key}_acc_majority"] = float((y[ok] == np.bincount(y[ok]).argmax()).mean())
    return out


# ---- training --------------------------------------------------------------------------------------------------------

def _device():
    if torch.cuda.is_available():
        return "cuda"
    return "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu"


def _class_weights(values, n):
    counts = np.bincount([v for v in values if v >= 0], minlength=n).astype(float) + 1.0
    w = 1.0 / np.sqrt(counts)
    return torch.tensor(w / w.mean(), dtype=torch.float32)


def train(examples, out_dir, *, backend="bow", model_name="distilroberta-base", epochs=3, batch=64, lr=None, seed=0, mask=True,
          dim=256, max_len=128, ckpt_every=500, val_every=1000, dry_run=False, deadline_minutes=None, device=None, ctl=None, log=print, encoder=None):
    """Train (or resume) the tagger on `examples` (from `build_examples`). Returns {"metrics", "stopped", "step"}.
    `dry_run` uses at most 400 training examples for 20 steps and evaluates on what there is: the same code path, a few seconds.
    `deadline_minutes` is a wall-clock budget: at the deadline a checkpoint is written and the function returns stopped=True."""
    t0 = time.time()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ckpt = out / "ckpt.pt"
    device = device or _device()
    lr = lr or (5e-4 if backend == "bow" else 3e-5)
    parts = {k: [e for e in examples if split_of(e["group"]) == k] for k in ("train", "val", "test")}
    if dry_run:                                # the model must be able to memorise a handful of examples: proves the loss, heads and step work
        parts["train"] = parts["train"][:64]
        parts["val"], parts["test"] = parts["val"][:200], parts["test"][:200]
        epochs, batch = 1, min(batch, 32)
    if not parts["train"]:
        raise ValueError("no training examples")
    cfg = {"backend": backend, "model_name": model_name, "epochs": epochs, "batch": batch, "lr": lr, "seed": seed, "mask": mask, "dim": dim,
           "max_len": max_len, "n_train": len(parts["train"])}
    torch.manual_seed(seed)
    model = Tagger(encoder or make_encoder(backend, model_name, dim, max_len)).to(device)
    heads = [p for n, p in model.named_parameters() if not n.startswith("enc.")]
    body = [p for n, p in model.named_parameters() if n.startswith("enc.")]
    # the classification heads start from random weights: they need a much larger step than a pretrained encoder
    opt = torch.optim.AdamW([{"params": body, "lr": lr}, {"params": heads, "lr": max(lr, 1e-3 if backend == "transformer" else lr)}], weight_decay=0.01)
    scaler = torch.amp.GradScaler("cuda") if device == "cuda" else None
    step, history, parts_log = 0, [], []
    if ckpt.exists() and not dry_run:
        st = torch.load(ckpt, weights_only=False, map_location=device)
        if st["cfg"] != cfg:
            raise ValueError(f"{ckpt} was made with a different configuration; use another --out or delete it")
        model.load_state_dict(st["model"])
        opt.load_state_dict(st["opt"])
        step, history = st["step"], st["history"]
        log(f"resuming from step {step}")
    train_ex = parts["train"]
    per_epoch = (len(train_ex) + batch - 1) // batch
    total = 40 if dry_run else epochs * per_epoch
    wj = _class_weights([e["judgement"] for e in train_ex], len(JUDGEMENT)).to(device)
    we = _class_weights([e["eval"] for e in train_ex], len(EVAL_CLASSES)).to(device)
    stopped = False

    def save():
        if not dry_run:
            tmp = ckpt.with_suffix(".tmp")
            torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "step": step, "cfg": cfg, "history": history}, tmp)
            tmp.replace(ckpt)

    try:
        while step < total:
            epoch, i = divmod(step, per_epoch)
            if dry_run:
                epoch, i = 0, step % per_epoch                            # the same 64 examples again and again
            order = np.random.default_rng(seed * 1000 + epoch).permutation(len(train_ex))     # deterministic per epoch: resume-safe
            idx = order[i * batch:(i + 1) * batch]
            if ctl:
                ctl.checkpoint()
            if deadline_minutes is not None and (time.time() - t0) / 60 >= deadline_minutes:
                stopped = True
                log(f"time budget of {deadline_minutes} min reached at step {step}/{total}: saving a checkpoint")
                break
            torch.manual_seed(seed * 1_000_003 + step)                 # dropout draws depend on the step only: resume gives the same run
            b = [train_ex[j] for j in idx]
            texts = [mask_keywords(e["text"]) if mask else e["text"] for e in b]
            yc = torch.tensor([e["concepts"] for e in b], device=device)
            yj = torch.tensor([e["judgement"] for e in b], device=device)
            ye = torch.tensor([e["eval"] for e in b], device=device)
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=scaler is not None):
                c, j, e = model(texts)
                l_c = F.binary_cross_entropy_with_logits(c.float(), yc)
                l_j = F.cross_entropy(j.float(), yj, weight=wj, ignore_index=-1) if (yj >= 0).any() else None
                l_e = F.cross_entropy(e.float(), ye, weight=we, ignore_index=-1) if (ye >= 0).any() else None
                loss = l_c + (l_j if l_j is not None else 0) + (l_e if l_e is not None else 0)
            opt.zero_grad()
            if scaler:
                scaler.scale(loss).backward()
                scaler.step(opt)
                scaler.update()
            else:
                loss.backward()
                opt.step()
            step += 1
            history.append(float(loss.detach()))
            parts_log.append((float(l_c.detach()), None if l_j is None else float(l_j.detach()), None if l_e is None else float(l_e.detach())))
            if step % 50 == 0 or step == total:
                w = parts_log[-50:]
                mean = lambda i: (np.mean([x[i] for x in w if x[i] is not None]) if any(x[i] is not None for x in w) else float("nan"))
                log(f"step {step}/{total} loss {np.mean(history[-50:]):.4f} = concepts {mean(0):.3f} + judgement {mean(1):.3f} + evaluation {mean(2):.3f} "
                    f"(the last two exist only in batches that contain a glyph: expect this total to wobble by +-0.2; {(time.time() - t0) / 60:.1f} min)")
            if not dry_run and val_every and step % val_every == 0 and step % per_epoch != 0 and parts["val"]:
                v = evaluate(model, parts["val"][:1500], mask=mask, batch=batch)
                log(f"  step {step} validation: concept AP {v.get('concept_ap_macro', float('nan')):.3f} (random {v.get('concept_ap_baseline', float('nan')):.3f}), "
                    f"judgement acc {v.get('judgement_acc', float('nan')):.3f} (majority {v.get('judgement_acc_majority', float('nan')):.3f}), "
                    f"evaluation acc {v.get('eval_acc', float('nan')):.3f} (majority {v.get('eval_acc_majority', float('nan')):.3f})")
            if step % ckpt_every == 0:
                save()
            if not dry_run and step % per_epoch == 0 and parts["val"]:            # a learning curve in the log, once per epoch
                v = evaluate(model, parts["val"][:2000], mask=mask, batch=batch)
                log(f"epoch {step // per_epoch} validation: concept AP {v.get('concept_ap_macro', float('nan')):.3f} (random {v.get('concept_ap_baseline', float('nan')):.3f}), "
                    f"judgement acc {v.get('judgement_acc', float('nan')):.3f} (majority {v.get('judgement_acc_majority', float('nan')):.3f}), "
                    f"evaluation acc {v.get('eval_acc', float('nan')):.3f} (majority {v.get('eval_acc_majority', float('nan')):.3f})")
                if v.get("concept_ap_macro", 1) < 1.5 * v.get("concept_ap_baseline", 0):
                    log("WARNING: concept average precision is not clearly above a random ranking yet")
    except Stopped as e:
        stopped = True
        log(f"stopped: {e}")
    save()
    metrics = {"steps": step, "total_steps": total, "stopped": stopped, "device": device, "minutes": round((time.time() - t0) / 60, 2),
               "config": cfg, "sources": {k: sum(1 for e in examples if e["source"] == k) for k in sorted({e["source"] for e in examples})}}
    if dry_run and len(history) >= 10:
        first, last = float(np.mean(history[:5])), float(np.mean(history[-5:]))
        metrics["dry_run"] = {"first_loss": first, "last_loss": last, "learned": last < 0.8 * first}
    thresholds = None
    if parts["val"]:
        texts = [mask_keywords(e["text"]) if mask else e["text"] for e in parts["val"]]
        thresholds = tune_thresholds(np.array([e["concepts"] for e in parts["val"]]), predict_batches(model, texts, batch)[0])
    for name in ("val", "test"):
        metrics[name] = evaluate(model, parts[name], mask=mask, batch=batch, thresholds=thresholds)
    if parts["test"]:
        metrics["test_unmasked"] = evaluate(model, parts["test"], mask=False, batch=batch, thresholds=thresholds)   # how much the keywords add when visible
    if thresholds is not None and not dry_run:
        (out / "thresholds.json").write_text(json.dumps([float(t) for t in thresholds]))
    if not dry_run:
        (out / "metrics.json").write_text(json.dumps(metrics, indent=1))
        (out / "config.json").write_text(json.dumps(cfg))
    return {"metrics": metrics, "stopped": stopped, "step": step, "model": model}


def load(out_dir, device=None):
    """A trained `Tagger` (bow backend, or transformer whose weights are in the checkpoint) ready for `predict`."""
    out = Path(out_dir)
    cfg = json.loads((out / "config.json").read_text())
    device = device or _device()
    model = Tagger(make_encoder(cfg["backend"], cfg["model_name"], cfg["dim"], cfg["max_len"])).to(device)
    model.load_state_dict(torch.load(out / "ckpt.pt", map_location=device, weights_only=False)["model"])
    model.eval()
    th = out / "thresholds.json"
    cfg["thresholds"] = json.loads(th.read_text()) if th.exists() else None
    return model, cfg


def predict(model, texts, cfg=None, threshold=0.5):
    """[{"concepts": [...], "judgement": "?!", "evaluation": "white slightly better"}] for each text."""
    mask = cfg.get("mask", True) if cfg else True
    C, J, E = predict_batches(model, [mask_keywords(t) if mask else t for t in texts])
    out = []
    th = np.array(cfg["thresholds"]) if cfg and cfg.get("thresholds") else np.full(len(CONCEPTS), threshold)
    for c, j, e in zip(C, J, E):
        out.append({"concepts": [CONCEPTS[k] for k in np.where(c > th)[0]], "concept_scores": {CONCEPTS[k]: round(float(c[k]), 3) for k in np.argsort(-c)[:3]},
                    "judgement": JUDGEMENT[int(j.argmax())], "evaluation": EVAL_CLASSES[int(e.argmax())]})
    return out
