"""Contrastive player embedding from game-level features (plan 8m, F6).

A set encoder maps a *bag* of a player's games (per-game feature vectors) to one unit vector; two disjoint bags of the same player
are pulled together and bags of different players pushed apart (InfoNCE). Players are split into training and held-out players; the
held-out players are only used to evaluate: identification (half A vs half B among held-out players) compared with the raw features.

Training is resumable: a checkpoint holds the weights, the optimiser, the step and the sampler's random state, so a stopped run
continues exactly where it was (same result as an uninterrupted run)."""
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from . import gamefeatures as G
from . import gamestats as S
from ..jobs import Stopped

MATCH_WINDOW = 100          # rating-matched identification: candidates within this many rating points
EXCLUDE = [G.FEATURE_NAMES.index(n) for n in S.EXCLUDED if n in G.FEATURE_NAMES]


# ---- data ------------------------------------------------------------------------------------------------------------

def prepare(players, seed=0, held_out=0.25):
    """(ids, games: list of (n_i, F) arrays, ratings, train_idx, test_idx). Columns of excluded artefact features are dropped
    later by `Normaliser`; games keep NaN for missing values."""
    ids = sorted(players)
    games = [np.asarray(players[i][1], dtype=np.float32) for i in ids]
    ratings = np.array([players[i][0] for i in ids], dtype=np.float64)
    order = np.random.default_rng(seed).permutation(len(ids))
    n_test = max(2, int(len(ids) * held_out))
    return ids, games, ratings, np.sort(order[n_test:]), np.sort(order[:n_test])


class Normaliser:
    """Standardises features with training-player statistics; a missing value becomes 0 with a 1 in the missing-indicator half."""
    def __init__(self, games=None, keep=None):
        self.keep = keep if keep is not None else [j for j in range(len(G.FEATURE_NAMES)) if j not in EXCLUDE]
        if games is not None:
            X = np.vstack(games)[:, self.keep]
            with np.errstate(all="ignore"):
                self.mean = np.nan_to_num(np.nanmean(X, axis=0))
                sd = np.nan_to_num(np.nanstd(X, axis=0))
            self.sd = np.where(sd < 1e-6, 1.0, sd)

    @property
    def dim(self):
        return 2 * len(self.keep)

    def __call__(self, g):
        X = g[:, self.keep]
        miss = ~np.isfinite(X)
        Z = np.where(miss, 0.0, (X - self.mean) / self.sd)
        return np.concatenate([np.clip(Z, -6, 6), miss.astype(np.float32)], axis=1).astype(np.float32)

    def state(self):
        return {"keep": self.keep, "mean": self.mean.tolist(), "sd": self.sd.tolist()}

    @classmethod
    def from_state(cls, s):
        n = cls(keep=s["keep"])
        n.mean, n.sd = np.array(s["mean"], dtype=np.float32), np.array(s["sd"], dtype=np.float32)
        return n


# ---- model -----------------------------------------------------------------------------------------------------------

class BagEncoder(nn.Module):
    def __init__(self, in_dim, hidden=128, dim=32):
        super().__init__()
        self.game = nn.Sequential(nn.Linear(in_dim, hidden), nn.ReLU(), nn.Linear(hidden, hidden), nn.ReLU())
        self.out = nn.Linear(hidden, dim)

    def forward(self, x, mask):
        """x: (B, k, in_dim) games of B bags; mask: (B, k) 1 for real games. Returns unit vectors (B, dim)."""
        h = self.game(x) * mask.unsqueeze(-1)
        pooled = h.sum(1) / mask.sum(1, keepdim=True).clamp(min=1)
        return F.normalize(self.out(pooled), dim=-1)


def info_nce(a, b, temperature=0.1):
    """Symmetric InfoNCE over a batch: a[i] and b[i] are the two bags of player i."""
    logits = a @ b.T / temperature
    target = torch.arange(len(a))
    return 0.5 * (F.cross_entropy(logits, target) + F.cross_entropy(logits.T, target))


def sample_batch(games_norm, idx, rng, batch, bag):
    """Two disjoint random bags of `bag` games for each of `batch` distinct players (players with fewer than 2*bag games get smaller
    bags, padded). Returns tensors (A, maskA, B, maskB)."""
    players = rng.choice(idx, size=min(batch, len(idx)), replace=False)
    dim = games_norm[players[0]].shape[1]
    A, B = np.zeros((len(players), bag, dim), np.float32), np.zeros((len(players), bag, dim), np.float32)
    mA, mB = np.zeros((len(players), bag), np.float32), np.zeros((len(players), bag), np.float32)
    for r, p in enumerate(players):
        g = games_norm[p]
        perm = rng.permutation(len(g))
        k = min(bag, len(g) // 2)
        A[r, :k], B[r, :k] = g[perm[:k]], g[perm[k:2 * k]]
        mA[r, :k] = mB[r, :k] = 1.0
    return tuple(torch.from_numpy(x) for x in (A, mA, B, mB))


# ---- evaluation ------------------------------------------------------------------------------------------------------

def embed_bags(model, games_norm, idx, parity):
    """Embeddings of each player's games of one alternating half (parity 0 or 1)."""
    model.eval()
    out = []
    with torch.no_grad():
        for p in idx:
            g = games_norm[p][parity::2]
            out.append(model(torch.from_numpy(g)[None], torch.ones(1, len(g))).numpy()[0])
    model.train()
    return np.array(out)


def evaluate(model, norm, games, ratings, idx):
    """Held-out identification of the embedding vs the raw aggregated features, plus how much of the embedding is just rating."""
    gn = [norm(g) for g in games]
    EA, EB = embed_bags(model, gn, idx, 0), embed_bags(model, gn, idx, 1)
    emb = S.identification(EA, EB, list(range(EA.shape[1])))
    r_idx = ratings[idx]
    emb_m = S.identification(EA, EB, list(range(EA.shape[1])), ratings=r_idx, window=MATCH_WINDOW)
    XA = np.array([np.nanmean(np.where(np.isfinite(games[i][0::2]), games[i][0::2], np.nan), axis=0) for i in idx])
    XB = np.array([np.nanmean(np.where(np.isfinite(games[i][1::2]), games[i][1::2], np.nan), axis=0) for i in idx])
    keep = norm.keep
    raw = S.identification(XA[:, keep], XB[:, keep], list(range(len(keep))))
    raw_m = S.identification(XA[:, keep], XB[:, keep], list(range(len(keep))), ratings=r_idx, window=MATCH_WINDOW)
    # rating leakage: R^2 of a linear map from the embedding (half A) to rating
    r = ratings[idx]
    Xr = np.hstack([EA, np.ones((len(EA), 1))])
    coef, *_ = np.linalg.lstsq(Xr, r, rcond=None)
    ss_res, ss_tot = ((r - Xr @ coef) ** 2).sum(), ((r - r.mean()) ** 2).sum()
    return {"embedding_top1": emb["top1"], "embedding_top5": emb["topk"], "raw_top1": raw["top1"], "raw_top5": raw["topk"],
            "chance": emb["chance"],
            "matched_embedding_top1": emb_m["top1"], "matched_raw_top1": raw_m["top1"], "matched_chance": emb_m["chance"], "rating_r2": float(1 - ss_res / ss_tot) if ss_tot > 0 else float("nan"), "n_heldout": len(idx)}


# ---- training (resumable) --------------------------------------------------------------------------------------------

def _save(path, model, opt, step, rng, cfg, norm, split, history):
    tmp = Path(str(path) + ".tmp")
    torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "step": step, "rng": rng.bit_generator.state, "cfg": cfg,
                "norm": norm.state(), "split": split, "history": history}, tmp)
    tmp.replace(path)


def train(players, out_dir, *, steps=2000, batch=64, bag=20, hidden=128, dim=32, lr=2e-3, temperature=0.1, seed=0, held_out=0.25,
          ckpt_every=100, eval_every=500, ctl=None, log=print):
    """Train (or resume) in `out_dir`; returns {"step", "eval", "stopped"}. The checkpoint `out_dir/ckpt.pt` is written every
    `ckpt_every` steps and when stopped. The final evaluation is written to `out_dir/eval.json`."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "ckpt.pt"
    ids, games, ratings, train_idx, test_idx = prepare(players, seed, held_out)
    cfg = {"steps": steps, "batch": batch, "bag": bag, "hidden": hidden, "dim": dim, "lr": lr, "temperature": temperature, "seed": seed,
           "held_out": held_out}
    torch.manual_seed(seed)
    step, history = 0, []
    rng = np.random.default_rng(seed + 1)
    if ckpt.exists():
        st = torch.load(ckpt, weights_only=False)
        if st["cfg"] != cfg or st["split"] != [ids[i] for i in test_idx]:
            raise ValueError(f"{ckpt} was made with a different configuration or player set; use another --out or delete it")
        norm = Normaliser.from_state(st["norm"])
        model = BagEncoder(norm.dim, hidden, dim)
        model.load_state_dict(st["model"])
        opt = torch.optim.Adam(model.parameters(), lr=lr)
        opt.load_state_dict(st["opt"])
        rng.bit_generator.state = st["rng"]
        step, history = st["step"], st["history"]
        log(f"resuming from step {step}")
    else:
        norm = Normaliser([games[i] for i in train_idx])
        model = BagEncoder(norm.dim, hidden, dim)
        opt = torch.optim.Adam(model.parameters(), lr=lr)
    gn = [norm(g) for g in games]
    split = [ids[i] for i in test_idx]
    stopped = False
    try:
        while step < steps:
            if ctl:
                ctl.checkpoint()
            A, mA, B, mB = sample_batch(gn, train_idx, rng, batch, bag)
            loss = info_nce(model(A, mA), model(B, mB), temperature)
            opt.zero_grad()
            loss.backward()
            opt.step()
            step += 1
            history.append(float(loss.detach()))
            if step % 50 == 0:
                log(f"step {step}/{steps} loss {np.mean(history[-50:]):.4f}")
            if step % ckpt_every == 0:
                _save(ckpt, model, opt, step, rng, cfg, norm, split, history)
            if eval_every and step % eval_every == 0 and step < steps:
                log(f"  held-out: {json.dumps({k: round(v, 3) for k, v in evaluate(model, norm, games, ratings, test_idx).items()})}")
    except Stopped as e:
        stopped = True
        log(f"stopped: {e}")
    _save(ckpt, model, opt, step, rng, cfg, norm, split, history)
    result = evaluate(model, norm, games, ratings, test_idx)
    if not stopped:
        (out_dir / "eval.json").write_text(json.dumps(result, indent=1))
        log(f"final held-out: {json.dumps({k: round(v, 3) for k, v in result.items()})}")
    return {"step": step, "eval": result, "stopped": stopped, "model": model, "norm": norm}
