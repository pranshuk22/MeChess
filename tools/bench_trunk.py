"""Throughput of a Chessformer-class trunk (E2 of the architecture research): 64 square tokens, a transformer encoder, a from-to policy head and a
value head, at about 2 / 5 / 10 million parameters. Measures positions per second for inference and for a training step (forward, backward, AdamW),
with and without an additive attention bias (the cost of a learned geometric bias, which disables the fused attention kernel on some devices),
in fp32 and half precision, and peak memory; then the hours needed to train on 1 billion positions.

Synthetic inputs: speed does not depend on the values. Usage: python tools/bench_trunk.py [--device mps|cuda|cpu] [--sizes 2,5,10] [--out FILE.json]"""
import argparse
import json
import time

import torch
import torch.nn as nn
import torch.nn.functional as F

SIZES = {2: (128, 10, 8), 5: (192, 11, 8), 10: (256, 12, 8)}      # d_model, layers, heads (feed-forward width 4 x d_model)


class Block(nn.Module):
    def __init__(self, d, heads, bias):
        super().__init__()
        self.h, self.qkv, self.o = heads, nn.Linear(d, 3 * d), nn.Linear(d, d)
        self.n1, self.n2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.ff = nn.Sequential(nn.Linear(d, 4 * d), nn.GELU(), nn.Linear(4 * d, d))
        self.bias = nn.Parameter(torch.zeros(heads, 64, 64)) if bias else None          # learned per-head bias over square pairs

    def forward(self, x, impl):
        b, n, d = x.shape
        q, k, v = self.qkv(self.n1(x)).view(b, n, 3, self.h, d // self.h).permute(2, 0, 3, 1, 4)
        mask = None if self.bias is None else self.bias.unsqueeze(0).to(q.dtype)
        if impl == "sdpa":
            a = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
        else:                                                                           # explicit softmax(QK^T / sqrt(d) + bias) V
            s = q @ k.transpose(-1, -2) / (q.shape[-1] ** 0.5)
            a = (s if mask is None else s + mask).softmax(-1) @ v
        x = x + self.o(a.transpose(1, 2).reshape(b, n, d))
        return x + self.ff(self.n2(x))


class Trunk(nn.Module):
    def __init__(self, d, layers, heads, bias):
        super().__init__()
        self.inp, self.pos = nn.Linear(19, d), nn.Parameter(torch.zeros(64, d))
        self.blocks = nn.ModuleList(Block(d, heads, bias) for _ in range(layers))
        self.norm = nn.LayerNorm(d)
        self.q, self.k = nn.Linear(d, 64), nn.Linear(d, 64)                              # from-to policy: bilinear over squares (64 x 64 logits)
        self.value = nn.Sequential(nn.Linear(d, 64), nn.GELU(), nn.Linear(64, 3))
        self.impl = "sdpa"

    def forward(self, x):
        h = self.inp(x) + self.pos
        for blk in self.blocks:
            h = blk(h, self.impl)
        h = self.norm(h)
        return torch.einsum("bsi,bti->bst", self.q(h), self.k(h)).flatten(1), self.value(h.mean(1))


def params(model):
    return sum(p.numel() for p in model.parameters())


def sync(device):
    if device == "cuda":
        torch.cuda.synchronize()
    elif device == "mps":
        torch.mps.synchronize()


def peak_mb(device):
    if device == "cuda":
        return torch.cuda.max_memory_allocated() / 2 ** 20
    if device == "mps":
        return torch.mps.driver_allocated_memory() / 2 ** 20
    return float("nan")


def bench(model, device, batch, dtype, train, steps=8, warmup=3):
    x = torch.randn(batch, 64, 19, device=device)
    y = torch.randint(0, 4096, (batch,), device=device)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-4) if train else None
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()

    def step():
        with torch.autocast(device_type=device, dtype=dtype, enabled=dtype != torch.float32):
            with torch.set_grad_enabled(train):
                logits, value = model(x)
                loss = F.cross_entropy(logits.float(), y) + value.float().pow(2).mean() if train else None
        if train:
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
    for _ in range(warmup):
        step()
    sync(device)
    t = time.perf_counter()
    for _ in range(steps):
        step()
    sync(device)
    dt = (time.perf_counter() - t) / steps
    return batch / dt, peak_mb(device)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--sizes", default="2,5,10")
    ap.add_argument("--batches", default="256,1024")
    ap.add_argument("--dtypes", default="fp32,fp16")
    ap.add_argument("--impls", default="sdpa,manual")
    ap.add_argument("--biases", default="0,1", help="0 = no attention bias, 1 = learned bias")
    ap.add_argument("--out")
    args = ap.parse_args()
    dev = args.device
    dtypes = {"fp32": torch.float32, "fp16": torch.float16, "bf16": torch.bfloat16}
    rows = []
    print(f"torch {torch.__version__} on {dev}" + (f" ({torch.cuda.get_device_name(0)})" if dev == "cuda" else ""), flush=True)
    for size in (int(s) for s in args.sizes.split(",")):
        for bias in (bool(int(b)) for b in args.biases.split(",")):
            for impl in args.impls.split(","):
                model = Trunk(*SIZES[size], bias).to(dev)
                model.impl = impl
                for dname in args.dtypes.split(","):
                    for train in (False, True):
                        for batch in (int(b) for b in args.batches.split(",")):
                            try:
                                pps, mem = bench(model, dev, batch, dtypes[dname], train)
                            except (RuntimeError, torch.OutOfMemoryError) as e:
                                pps, mem = float("nan"), float("nan")
                                print(f"  failed: {str(e)[:80]}", flush=True)
                            row = {"size_m": size, "params_m": round(params(model) / 1e6, 2), "bias": bias, "attention": impl, "dtype": dname,
                                   "mode": "train" if train else "infer", "batch": batch, "pos_per_s": None if pps != pps else round(pps),
                                   "peak_mb": None if mem != mem else round(mem)}
                            rows.append(row)
                            print(json.dumps(row), flush=True)
                del model
    if args.out:
        with open(args.out, "w") as f:
            json.dump({"device": dev, "torch": torch.__version__, "rows": rows}, f, indent=1)


if __name__ == "__main__":
    main()
