"""A small adapter on top of a FROZEN move model (design C5 of the architecture research): it never changes the model, it only re-weights the model's
own top moves using information the model was not given (the clocks, and a summary of its own confidence).

From a score file (`score.py`) we know, for every position, the probabilities of the model's 16 most probable moves, the probability it gave the
human's move and that move's rank. The adapter turns the 16 log-probabilities and the remaining mass (the 'tail') into 17 logits:

    logit_i = log p_i / tau(x) + b_i(x)          (i = 1..16)        logit_tail = log tail + c(x)

where tau, b and c come from a small network of the features x (clock features, ratings, the model's confidence). With the output layer at zero
(tau = 1, b = c = 0) the adapter returns the model's own probabilities exactly, and training only moves it away where the features help. The
probability of the human's move is that of its slot; for a move outside the top 16, the slot is the tail and the move keeps its share of the tail
that the frozen model gave it. So every adapted number is a probability of a real move, comparable with the frozen model's NLL."""
import numpy as np

K = 16
FEATURES = ("log clock", "log opp clock", "clock share of base", "log clock ratio", "under 10 s", "under 30 s", "increment", "ply", "mover rating", "opponent rating",
            "legal moves", "model confidence", "model entropy")


def features(arr, scores):
    """The feature matrix (n x len(FEATURES)). `arr` is `report.position_arrays`."""
    clock = np.maximum(arr["clock"], 0.0)
    opp, bases, incs = np.maximum(arr["opp_clock"], 0.0), arr["base"], arr["inc"]
    f = np.stack([np.log1p(clock) / 5.0, np.log1p(opp) / 5.0, np.clip(clock / np.maximum(bases, 1), 0, 2), (np.log1p(clock) - np.log1p(opp)) / 2.0,
                  (clock < 10).astype(float), (clock < 30).astype(float), np.asarray(incs, float) / 10.0, np.asarray(arr["ply"], float) / 100.0,
                  (np.asarray(arr["me"], float) - 1600) / 500.0, (np.asarray(arr["opp"], float) - 1600) / 500.0, np.asarray(arr["n_legal"], float) / 40.0,
                  scores["conf"], scores["entropy"] / 3.0], axis=1)
    return f.astype(np.float32)


def slots(scores):
    """What the adapter needs from a score file: log-probabilities of the 16 slots plus the tail, the human's slot, and (when the human's move is in the
    tail) the log share of the tail that the frozen model gave that move."""
    p = scores["topk_p"][:, :K].astype(np.float64)
    tail = np.maximum(1.0 - p.sum(axis=1), 1e-9)
    logp = np.log(np.maximum(p, 1e-12))
    target = np.where(scores["rank"] <= K, scores["rank"] - 1, K).astype(np.int64)
    in_tail = target == K
    within = np.where(in_tail, np.log(np.maximum(scores["p"], 1e-12)) - np.log(tail), 0.0)
    return {"logp": logp.astype(np.float32), "log_tail": np.log(tail).astype(np.float32), "target": target, "log_within": within.astype(np.float32)}


class Adapter:
    """The network; built lazily so that importing this module does not need torch."""

    def __new__(cls, n_features=len(FEATURES), hidden=32, mode="full"):
        import torch.nn as nn

        class Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.body = nn.Sequential(nn.Linear(n_features, hidden), nn.GELU(), nn.Linear(hidden, hidden), nn.GELU())
                self.out = nn.Linear(hidden, 2 + K)                      # log tau, tail shift, 16 slot biases
                import torch
                # mode 'tau': only the temperature may change (the calibration-wrapper baseline); 'full': temperature, tail shift and slot biases
                self.register_buffer("keep", torch.tensor([1.0] + [0.0] * (1 + K)) if mode == "tau" else torch.ones(2 + K))
                nn.init.zeros_(self.out.weight)
                nn.init.zeros_(self.out.bias)

            def forward(self, x, logp, log_tail):
                import torch
                h = self.out(self.body(x)) * self.keep
                tau = torch.exp(h[:, 0:1])
                slot_logits = logp / tau + h[:, 2:]
                tail_logit = log_tail + h[:, 1]
                return torch.log_softmax(torch.cat([slot_logits, tail_logit.unsqueeze(1)], dim=1), dim=1)
        return Net()


def log_prob_of_played(log_slots, target, log_within):
    import torch
    return log_slots.gather(1, target.unsqueeze(1)).squeeze(1) + log_within


def fit(x, sl, train, val, epochs=30, batch=4096, lr=3e-3, hidden=32, seed=0, weight_decay=1e-4, mode="full", log=print):
    """Train on the positions `train` (boolean mask), keep the epoch with the best validation NLL (`val` mask). Returns (network, mean, std)."""
    import torch
    torch.manual_seed(seed)
    mean, std = x[train].mean(0), x[train].std(0) + 1e-6
    t = lambda a, m: torch.from_numpy(np.ascontiguousarray(a[m]))
    xs = torch.from_numpy(((x - mean) / std).astype(np.float32))
    lp, lt, tg, lw = (torch.from_numpy(np.ascontiguousarray(sl[k])) for k in ("logp", "log_tail", "target", "log_within"))
    tr, va = torch.from_numpy(np.flatnonzero(train)), torch.from_numpy(np.flatnonzero(val))
    net = Adapter(x.shape[1], hidden, mode)
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=weight_decay)
    best, best_state = float("inf"), None

    def nll(idx):
        return -log_prob_of_played(net(xs[idx], lp[idx], lt[idx]), tg[idx], lw[idx]).mean()
    for epoch in range(epochs):
        perm = tr[torch.randperm(len(tr))]
        net.train()
        for i in range(0, len(perm), batch):
            idx = perm[i:i + batch]
            opt.zero_grad()
            nll(idx).backward()
            opt.step()
        net.eval()
        with torch.no_grad():
            v = float(nll(va))
        if v < best:
            best, best_state = v, {k: p.clone() for k, p in net.state_dict().items()}
        log(f"  epoch {epoch + 1}: validation NLL {v:.4f} (best {best:.4f})")
    net.load_state_dict(best_state)
    return net, mean, std


def apply(net, mean, std, x, sl):
    """Adapted scores in the layout of `score.py` for the metrics: p (probability of the human's move), top1, conf, rank, and the slot probabilities."""
    import torch
    net.eval()
    with torch.no_grad():
        xs = torch.from_numpy(((x - mean) / std).astype(np.float32))
        log_slots = torch.cat([net(xs[i:i + 65536], torch.from_numpy(sl["logp"][i:i + 65536]), torch.from_numpy(sl["log_tail"][i:i + 65536]))
                               for i in range(0, len(x), 65536)]).numpy()
    target = sl["target"]
    p = np.exp(log_slots[np.arange(len(target)), target] + sl["log_within"])
    top_slot = log_slots[:, :K].argmax(axis=1)
    rank = np.where(target < K, 1 + (log_slots[:, :K] > log_slots[np.arange(len(target)), np.minimum(target, K - 1)][:, None]).sum(axis=1), K + 1)
    probs = np.exp(log_slots[:, :K])
    return {"p": p, "top1": (top_slot == target), "conf": probs.max(axis=1), "rank": rank.astype(np.int32), "entropy": -(probs * log_slots[:, :K]).sum(axis=1),
            "sq_sum": (probs ** 2).sum(axis=1), "tail": np.exp(log_slots[:, K]), "probs": probs.astype(np.float32)}


def game_split(gids, seed=0, val=0.1, test=0.2):
    """Train / validation / test masks by a hash of the game id (positions of one game never straddle the split)."""
    import hashlib
    h = np.array([int.from_bytes(hashlib.sha256(f"{seed}:split:{g}".encode()).digest()[:4], "big") / 2.0 ** 32 for g in gids])
    test_m, val_m = h >= 1 - test, (h >= 1 - test - val) & (h < 1 - test)
    return ~(test_m | val_m), val_m, test_m
