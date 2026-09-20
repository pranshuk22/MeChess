"""Training and evaluation of the "me" network."""
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from . import encoding as enc
from .net import MeNet, NetConfig, load_checkpoint, num_parameters, save_checkpoint


@dataclass
class TrainConfig:
    batch_size: int = 1024
    lr: float = 2e-3
    weight_decay: float = 1e-4
    epochs: float = 1.0
    warmup_steps: int = 200
    value_weight: float = 0.25
    grad_clip: float = 1.0
    eval_every: int = 1000
    eval_samples: int = 50000
    patience: int = 0  # stop after this many evaluations without improvement (0 = never)
    seed: int = 1
    device: str = "auto"
    init_from: str = ""  # checkpoint to start from (fine-tuning)
    freeze_body: bool = False  # fine-tune only the heads
    max_steps: int = 0  # 0 = derive from epochs


def pick_device(name="auto"):
    if name != "auto":
        return torch.device(name)
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def to_planes(data, idx, device):
    """Planes for the samples `idx` of a shard dict (torch tensors are created on `device`)."""
    t = lambda k, dt=None: torch.from_numpy(data[k][idx]).to(device) if dt is None else torch.from_numpy(data[k][idx]).to(device, dt)
    return enc.build_planes(t("board"), t("castle"), t("ep"), t("ratings", torch.float32), t("platform"))


def legal_mask(data, idx, device):
    """Boolean mask [B, POLICY_SIZE] of legal moves (requires the shard to carry `legal`)."""
    legal = torch.from_numpy(data["legal"][idx].astype(np.int64)).to(device)
    m = torch.zeros(len(idx), enc.POLICY_SIZE + 1, dtype=torch.bool, device=device)
    m.scatter_(1, torch.where(legal < 0, torch.full_like(legal, enc.POLICY_SIZE), legal), True)
    return m[:, :-1]


def phase_of(data, idx):
    """Per-sample phase labels: early (<20 plies), middle, late (>=40 plies); 'endgame' = <= 6 minor/major pieces."""
    ply = data["ply"][idx].astype(np.int32)
    board = data["board"][idx]
    heavy = ((board >= 2) & (board <= 5)) | ((board >= 8) & (board <= 11))
    return ply, heavy.sum(axis=1)


@torch.no_grad()
def evaluate(model, data, device, batch_size=2048, limit=None):
    """Legal-masked accuracy of the policy on a shard that carries `legal` arrays.

    Returns overall and per-phase top-1 / top-3, the mean probability given to the played move, and the
    cross-entropy over legal moves. Also the accuracy of picking a uniformly random legal move, for reference.
    """
    if "legal" not in data:
        raise ValueError("evaluation needs a shard with legal-move arrays (val/test shards have them)")
    model.eval()
    n = len(data["move"]) if not limit else min(limit, len(data["move"]))
    if n == 0:
        return {}
    acc = {"top1": [], "top3": [], "prob": [], "nll": [], "uniform": [], "weight": []}
    for start in range(0, n, batch_size):
        idx = np.arange(start, min(start + batch_size, n))
        x = to_planes(data, idx, device)
        logits, _ = model(x)
        mask = legal_mask(data, idx, device)
        logits = logits.masked_fill(~mask, float("-inf"))
        target = torch.from_numpy(data["move"][idx].astype(np.int64)).to(device)
        logp = F.log_softmax(logits, dim=1)
        top3 = logits.topk(3, dim=1).indices
        acc["top1"].append((top3[:, 0] == target).cpu().numpy())
        acc["top3"].append((top3 == target[:, None]).any(1).cpu().numpy())
        played = logp.gather(1, target[:, None]).squeeze(1)
        acc["nll"].append((-played).cpu().numpy())
        acc["prob"].append(played.exp().cpu().numpy())
        acc["uniform"].append((1.0 / mask.sum(1)).cpu().numpy())
        acc["weight"].append(data["weight"][idx])
    a = {k: np.concatenate(v) for k, v in acc.items()}
    ply, heavy = phase_of(data, np.arange(n))
    groups = {"all": np.ones(n, bool), "early (10-19)": ply < 20, "middle (20-39)": (ply >= 20) & (ply < 40),
              "late (40+)": ply >= 40, "endgame (<=6 pieces)": heavy <= 6}
    out = {}
    for name, sel in groups.items():
        if sel.sum():
            out[name] = {"n": int(sel.sum()), "top1": float(a["top1"][sel].mean()), "top3": float(a["top3"][sel].mean()),
                         "prob": float(a["prob"][sel].mean()), "nll": float(a["nll"][sel].mean()),
                         "uniform_top1": float(a["uniform"][sel].mean())}
    return out


def format_eval(res, title=""):
    if not res:
        return (title + "\n" if title else "") + "(no positions)"
    lines = [title] if title else []
    lines += ["| subset | positions | top-1 | top-3 | avg prob of my move | NLL | random-legal top-1 |", "|---|---|---|---|---|---|---|"]
    for k, r in res.items():
        lines.append(f"| {k} | {r['n']} | {100 * r['top1']:.1f}% | {100 * r['top3']:.1f}% | {100 * r['prob']:.1f}% | "
                     f"{r['nll']:.3f} | {100 * r['uniform_top1']:.1f}% |")
    return "\n".join(lines)


def lr_at(step, total, cfg):
    if step < cfg.warmup_steps:
        return cfg.lr * (step + 1) / cfg.warmup_steps
    progress = (step - cfg.warmup_steps) / max(1, total - cfg.warmup_steps)
    return cfg.lr * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1.0, progress))))


def train(train_data, val_data, net_cfg, cfg, out_dir, log=print):
    """Train (or fine-tune when cfg.init_from is set). Returns the history list; writes best.pt / last.pt / history.jsonl."""
    torch.manual_seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed)
    device = pick_device(cfg.device)
    if cfg.init_from:
        model, _ = load_checkpoint(cfg.init_from, device)
    else:
        model = MeNet(net_cfg).to(device)
    if cfg.freeze_body:
        for name, p in model.named_parameters():
            p.requires_grad = name.startswith(("p_", "v_"))
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=cfg.lr, weight_decay=cfg.weight_decay)

    n = len(train_data["move"])
    steps_per_epoch = max(1, n // cfg.batch_size)
    total = cfg.max_steps or max(1, int(cfg.epochs * steps_per_epoch))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log(f"{num_parameters(model):,} parameters | {n:,} training samples | {total} steps of {cfg.batch_size} on {device}")

    history, best, since_best, step, t0 = [], float("inf"), 0, 0, time.time()
    weights = train_data["weight"].astype(np.float32)
    run_loss = run_acc = torch.zeros((), device=device)
    run_cnt = 0
    order = rng.permutation(n)
    pos = 0
    while step < total:
        if pos + cfg.batch_size > n:
            order, pos = rng.permutation(n), 0
        idx = np.sort(order[pos:pos + cfg.batch_size])  # sorted: contiguous-ish memory access
        pos += cfg.batch_size
        for g in opt.param_groups:
            g["lr"] = lr_at(step, total, cfg)
        model.train()
        x = to_planes(train_data, idx, device)
        target = torch.from_numpy(train_data["move"][idx].astype(np.int64)).to(device)
        result = torch.from_numpy(train_data["result"][idx].astype(np.int64)).to(device)
        w = torch.from_numpy(weights[idx]).to(device)
        logits, value = model(x)
        ce = F.cross_entropy(logits, target, reduction="none")
        vce = F.cross_entropy(value, result, reduction="none")
        loss = ((ce + cfg.value_weight * vce) * w).sum() / w.sum().clamp_min(1e-8)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        if cfg.grad_clip:
            torch.nn.utils.clip_grad_norm_(params, cfg.grad_clip)
        opt.step()
        step += 1
        run_loss = run_loss + ce.detach().mean()  # stays on the device: no per-step sync
        run_acc = run_acc + (logits.detach().argmax(1) == target).float().mean()
        run_cnt += 1

        if step % cfg.eval_every == 0 or step == total:
            rec = {"step": step, "train_ce": float(run_loss) / run_cnt, "train_top1_unmasked": float(run_acc) / run_cnt,
                   "lr": opt.param_groups[0]["lr"], "seconds": round(time.time() - t0, 1)}
            run_loss = run_acc = torch.zeros((), device=device)
            run_cnt = 0
            if val_data is not None:
                v = evaluate(model, val_data, device, limit=cfg.eval_samples)["all"]
                rec.update(val_nll=v["nll"], val_top1=v["top1"], val_top3=v["top3"])
                improved = v["nll"] < best
            else:
                improved = True
            if improved:
                best, since_best = rec.get("val_nll", 0.0), 0
                save_checkpoint(out / "best.pt", model, {"step": step, **rec})
            else:
                since_best += 1
            history.append(rec)
            log(json.dumps(rec))
            with open(out / "history.jsonl", "a") as f:
                f.write(json.dumps(rec) + "\n")
            if cfg.patience and since_best >= cfg.patience:
                log(f"early stop after {since_best} evaluations without improvement")
                break
    save_checkpoint(out / "last.pt", model, {"step": step})
    (out / "train_config.json").write_text(json.dumps({"train": asdict(cfg), "net": asdict(model.cfg)}, indent=2))
    return history
