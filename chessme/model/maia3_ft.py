"""Personalise a Maia-3 model on one player's games (same recipe as our own fine-tuning).

The Maia-3 network itself is loaded from its public checkout (AGPL-3.0, kept outside this project); everything here
(data, loss, loop) is ours. Facts about Maia-3's interface that this relies on (verified by tests against its code):
  * input tokens: for each of the last 8 positions, a 64 x 12 one-hot board in the *mover's* canonical view of that
    position (own pieces channels 0-5, opponent's 6-11), oldest first; positions before the game start repeat the first;
  * move vocabulary: from*64+to for ordinary moves (mirrored when Black moves), then 4096 + (from_file*8+to_file)*4 +
    [q, r, b, n] for promotions; 4352 logits;
  * both players' ratings are integers.
"""
import math
import time
from dataclasses import dataclass

import chess
import numpy as np
import torch
import torch.nn.functional as F

from . import encoding as enc

HISTORY = 8
VOCAB = 4096 + 256
PROMO_ORDER = {"q": 0, "r": 1, "b": 2, "n": 3}


def mirror_uci(uci):
    """Flip a UCI move vertically (Black's moves are expressed in the mirrored board)."""
    f = lambda sq: sq[0] + str(9 - int(sq[1]))
    return f(uci[:2]) + f(uci[2:4]) + uci[4:]


def vocab_index(move, turn):
    """Index of `move` in Maia-3's move vocabulary for the side to move."""
    uci = move.uci() if turn == chess.WHITE else mirror_uci(move.uci())
    if len(uci) == 5:  # promotion (rank 7 -> 8 in the mover's view)
        return 4096 + ((ord(uci[0]) - 97) * 8 + (ord(uci[2]) - 97)) * 4 + PROMO_ORDER[uci[4]]
    return chess.parse_square(uci[:2]) * 64 + chess.parse_square(uci[2:4])


@dataclass
class PlayerData:
    boards: np.ndarray  # [P, 64] uint8: every position of every game, each in its own mover's canonical view
    cur: np.ndarray  # [N] index (into boards) of the position before the sampled move
    start: np.ndarray  # [N] index of the first position of that game
    target: np.ndarray  # [N] vocabulary index of the move played
    elos: np.ndarray  # [N, 2] mover, opponent
    weight: np.ndarray  # [N]
    legal_flat: np.ndarray  # concatenated vocabulary indices of legal moves
    legal_off: np.ndarray  # [N+1] offsets into legal_flat

    def __len__(self):
        return len(self.cur)


def build_player_data(rows, weighter, min_ply=8):
    """Sampled moves of the player's games (same selection rule as the other shards) with everything needed to
    rebuild the 8-position history on the fly."""
    boards, cur, start, target, elos, weight, legal_flat, legal_off = [], [], [], [], [], [], [], [0]
    for row in rows:
        if weighter.game_weight(row) <= 0 or row.get("result") not in ("1-0", "0-1", "1/2-1/2"):
            continue
        if row.get("my_rating") is None or row.get("opp_rating") is None:
            continue
        mine_white = row["color"] == "white"
        board, first = chess.Board(), len(boards)
        try:
            for ply, san in enumerate(row["moves"].split()):
                move = board.parse_san(san)
                boards.append(enc.canonical_state(board)[0])
                if ply >= min_ply and (board.turn == chess.WHITE) == mine_white and board.legal_moves.count() >= 2:
                    w = weighter.move_weight(row, ply)
                    if w > 0:
                        cur.append(len(boards) - 1)
                        start.append(first)
                        target.append(vocab_index(move, board.turn))
                        elos.append((row["my_rating"], row["opp_rating"]))
                        weight.append(w)
                        idx = [vocab_index(m, board.turn) for m in board.legal_moves]
                        legal_flat.extend(idx)
                        legal_off.append(len(legal_flat))
                board.push(move)
        except ValueError:
            # a game that stops replaying: drop the samples we took from it (their positions stay harmlessly)
            continue
    return PlayerData(np.array(boards, np.uint8).reshape(-1, 64), np.array(cur, np.int64), np.array(start, np.int64),
                      np.array(target, np.int64), np.array(elos, np.int64).reshape(-1, 2), np.array(weight, np.float32),
                      np.array(legal_flat, np.int64), np.array(legal_off, np.int64))


def make_batch(data, idx, boards_dev, device):
    """(tokens [B,64,96], mover elos, opponent elos, legal mask [B,4352], target, weight) for samples `idx`."""
    idx = np.asarray(idx)
    window = np.maximum(data.cur[idx][:, None] - (HISTORY - 1) + np.arange(HISTORY)[None, :], data.start[idx][:, None])
    pos = boards_dev[torch.from_numpy(window).to(device)]  # [B, 8, 64] uint8
    tokens = F.one_hot(pos.long(), 13)[..., 1:].to(torch.float32)  # [B, 8, 64, 12]
    tokens = tokens.permute(0, 2, 1, 3).reshape(len(idx), 64, HISTORY * 12)
    mask = torch.zeros(len(idx), VOCAB, dtype=torch.bool)
    for r, i in enumerate(idx):
        mask[r, torch.from_numpy(data.legal_flat[data.legal_off[i]:data.legal_off[i + 1]])] = True
    elos = torch.from_numpy(data.elos[idx]).to(device)
    return (tokens, elos[:, 0], elos[:, 1], mask.to(device), torch.from_numpy(data.target[idx]).to(device),
            torch.from_numpy(data.weight[idx]).to(device))


def masked_logits(model, tokens, me, opp, mask):
    logits = model(tokens, me, opp)[0].float()
    return logits.masked_fill(~mask, float("-inf"))


@torch.no_grad()
def evaluate(model, data, device, boards_dev, batch_size=256, limit=None):
    model.eval()
    n = len(data) if not limit else min(limit, len(data))
    t1 = t3 = nll = 0.0
    for start in range(0, n, batch_size):
        idx = np.arange(start, min(start + batch_size, n))
        tokens, me, opp, mask, target, _ = make_batch(data, idx, boards_dev, device)
        lg = masked_logits(model, tokens, me, opp, mask)
        top3 = lg.topk(3, dim=1).indices
        t1 += (top3[:, 0] == target).sum().item()
        t3 += (top3 == target[:, None]).any(1).sum().item()
        nll += -F.log_softmax(lg, dim=1).gather(1, target[:, None]).sum().item()
    return {"n": n, "top1": t1 / n, "top3": t3 / n, "nll": nll / n}


def trainable_parameters(model, scope):
    """scope 'all', or 'heads' (the move head, final norm and rating embeddings only)."""
    if scope == "all":
        return list(model.parameters())
    keep = ("proj_sq_from", "proj_sq_to", "promo_bias_proj", "last_ln", "elo_embedding")
    params = []
    for name, p in model.named_parameters():
        p.requires_grad = name.startswith(keep)
        if p.requires_grad:
            params.append(p)
    return params


def finetune(model, train, val, out_path, *, device="cpu", epochs=3, batch_size=256, lr=1e-4, warmup=50, scope="all",
             eval_every=250, seed=1, log=print, log_every=25):
    """Weighted, legal-masked cross-entropy fine-tuning. Saves the best checkpoint (by validation NLL) to `out_path`
    in the format Maia-3's loader reads ({"model_state_dict": ...}). Returns the history."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    params = trainable_parameters(model, scope)
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.0)
    boards_tr = torch.from_numpy(train.boards).to(device)
    boards_va = torch.from_numpy(val.boards).to(device)
    total = max(1, int(epochs * len(train) / batch_size))
    log(f"{sum(p.numel() for p in params):,} trainable parameters | {len(train):,} samples | {total} steps on {device}")
    hist, best, step, t0 = [], float("inf"), 0, time.time()
    order, pos = rng.permutation(len(train)), 0
    while step < total:
        if pos + batch_size > len(train):
            order, pos = rng.permutation(len(train)), 0
        idx = order[pos:pos + batch_size]
        pos += batch_size
        lr_now = lr * ((step + 1) / warmup if step < warmup else 0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * (step - warmup) / max(1, total - warmup))))
        for g in opt.param_groups:
            g["lr"] = lr_now
        model.train()
        tokens, me, opp, mask, target, w = make_batch(train, idx, boards_tr, device)
        lg = masked_logits(model, tokens, me, opp, mask)
        ce = -F.log_softmax(lg, dim=1).gather(1, target[:, None]).squeeze(1)
        loss = (ce * w).sum() / w.sum().clamp_min(1e-8)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        opt.step()
        step += 1
        if log_every and step % log_every == 0:
            log(f"  step {step}/{total}  train nll {float(ce.detach().mean()):.3f}  {(time.time() - t0) / step:.2f} s/step")
        if step % eval_every == 0 or step == total:
            v = evaluate(model, val, device, boards_va)
            rec = {"step": step, "train_nll": float(ce.detach().mean()), "val_top1": v["top1"], "val_top3": v["top3"], "val_nll": v["nll"],
                   "seconds": round(time.time() - t0, 1)}
            hist.append(rec)
            log(str(rec))
            if v["nll"] < best:
                best = v["nll"]
                torch.save({"model_state_dict": model.state_dict()}, out_path)
    return hist
