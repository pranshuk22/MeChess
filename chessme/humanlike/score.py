"""Run a move model over a test set once and keep per-position results, so every metric (and any metric invented later) can be computed
without running the model again.

Per position we store: the probability the model gave the move the human played, its rank, the model's top probability and entropy,
the sum of squared probabilities (the chance that two independent samples from the model agree) and the 16 most probable moves with
their probabilities (enough to study sampled play: the rest of the mass is `1 - sum(topk_p)`)."""
import hashlib
import json
import multiprocessing
from pathlib import Path

import numpy as np

TOPK = 16


def score_items(scorer, items, chunk=256, progress=None):
    """Score `items` (compare.EvalItem) with `scorer` (compare.Scorer). Returns a dict of arrays, one row per item."""
    n = len(items)
    out = {"p": np.zeros(n), "rank": np.zeros(n, dtype=np.int32), "conf": np.zeros(n), "entropy": np.zeros(n), "sq_sum": np.zeros(n),
           "n_legal": np.zeros(n, dtype=np.int32), "topk_move": np.full((n, TOPK), "", dtype="<U5"),
           "topk_p": np.zeros((n, TOPK), dtype=np.float32)}
    for start in range(0, n, chunk):
        part = items[start:start + chunk]
        for k, (it, probs) in enumerate(zip(part, scorer.probs(part))):
            i = start + k
            if it.played not in probs:
                raise ValueError(f"the played move {it.played} is not legal in {it.fen}")
            ranked = sorted(probs, key=probs.get, reverse=True)
            ps = np.array([probs[m] for m in ranked], dtype=np.float64)
            out["p"][i] = probs[it.played]
            out["rank"][i] = ranked.index(it.played) + 1
            out["conf"][i] = ps[0]
            out["entropy"][i] = float(-(ps * np.log(np.maximum(ps, 1e-12))).sum())
            out["sq_sum"][i] = float((ps ** 2).sum())
            out["n_legal"][i] = len(ps)
            m = min(TOPK, len(ps))
            out["topk_move"][i, :m] = ranked[:m]
            out["topk_p"][i, :m] = ps[:m]
        if progress:
            progress(min(start + chunk, n), n)
    out["top1"] = out["rank"] == 1
    return out


_WORKER = {}


def _init_worker(kwargs):
    import torch
    if kwargs.get("device", "cpu") == "cpu":
        torch.set_num_threads(1)                      # one process per core: do not let each of them start a thread per core
    from .models import make_scorer
    _WORKER["scorer"] = make_scorer(**kwargs)


def _score_chunk(items):
    scorer = _WORKER["scorer"]
    return score_items(scorer, items), scorer.name


def score_items_parallel(scorer_kwargs, items, workers=1, chunk_items=4000, progress=None):
    """`score_items` split over `workers` processes (each loads its own copy of the model). `scorer_kwargs` are the arguments of
    `models.make_scorer`. Returns (scores, scorer name); the rows are in the order of `items`, identical for any number of workers."""
    from .models import make_scorer
    if workers <= 1:
        scorer = make_scorer(**scorer_kwargs)
        return score_items(scorer, items, progress=progress), scorer.name
    chunks = [items[i:i + chunk_items] for i in range(0, len(items), chunk_items)]
    parts, name, done = [], None, 0
    with multiprocessing.get_context("spawn").Pool(workers, initializer=_init_worker, initargs=(scorer_kwargs,)) as pool:
        for scores, name in pool.imap(_score_chunk, chunks):
            parts.append(scores)
            done += len(scores["p"])
            if progress:
                progress(done, len(items))
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}, name


def positions_hash(positions):
    """SHA-256 of the (fen, played) pairs: ties a score file to the exact positions it was computed on."""
    h = hashlib.sha256()
    for p in positions:
        h.update(f"{p.fen}|{p.played}\n".encode())
    return h.hexdigest()


def save_scores(path, scores, model, testset_sha, extra=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = json.dumps({"model": model, "testset_sha256": testset_sha, **(extra or {})})
    np.savez_compressed(path, meta=np.array(meta), **scores)


def load_scores(path):
    with np.load(path, allow_pickle=False) as z:
        scores = {k: z[k] for k in z.files if k != "meta"}
        meta = json.loads(str(z["meta"]))
    return scores, meta
