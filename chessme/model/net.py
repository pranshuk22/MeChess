"""The "me" network: a small residual conv net (Maia / Leela style) with a policy head and a result head."""
from dataclasses import asdict, dataclass

import math

import torch
import torch.nn as nn
import torch.nn.functional as F

from .encoding import N_PLANES, POLICY_SIZE


@dataclass
class NetConfig:
    blocks: int = 6
    channels: int = 64
    policy_dim: int = 32  # size of the from-square / to-square embeddings in the policy head
    value_channels: int = 8
    value_hidden: int = 64


class ResBlock(nn.Module):
    def __init__(self, c):
        super().__init__()
        self.c1 = nn.Conv2d(c, c, 3, padding=1, bias=False)
        self.b1 = nn.BatchNorm2d(c)
        self.c2 = nn.Conv2d(c, c, 3, padding=1, bias=False)
        self.b2 = nn.BatchNorm2d(c)

    def forward(self, x):
        y = F.relu(self.b1(self.c1(x)))
        y = self.b2(self.c2(y))
        return F.relu(x + y)


class MeNet(nn.Module):
    """planes [B, 20, 8, 8] -> (policy logits [B, 4168], result logits [B, 3] = loss/draw/win for the mover)."""

    def __init__(self, cfg=NetConfig()):
        super().__init__()
        self.cfg = cfg
        c = cfg.channels
        self.stem = nn.Sequential(nn.Conv2d(N_PLANES, c, 3, padding=1, bias=False), nn.BatchNorm2d(c), nn.ReLU())
        self.tower = nn.Sequential(*[ResBlock(c) for _ in range(cfg.blocks)])
        # Policy: every square gets a "from" and a "to" embedding; a move's logit is their dot product plus a
        # learned per-(from,to) bias (which lets the net learn how pieces move). Under-promotions get a small
        # separate head reading the mover's 7th rank, where promoting pawns stand.
        self.p_qk = nn.Conv2d(c, 2 * cfg.policy_dim, 1)
        self.p_bias = nn.Parameter(torch.zeros(4096))
        self.p_under = nn.Linear(c * 8, POLICY_SIZE - 4096)
        self.v_conv = nn.Sequential(nn.Conv2d(c, cfg.value_channels, 1, bias=False), nn.BatchNorm2d(cfg.value_channels), nn.ReLU())
        self.v_fc1 = nn.Linear(cfg.value_channels * 64, cfg.value_hidden)
        self.v_fc2 = nn.Linear(cfg.value_hidden, 3)

    def forward(self, planes):
        x = self.tower(self.stem(planes))
        d = self.cfg.policy_dim
        q, k = self.p_qk(x).flatten(2).split(d, dim=1)  # each [B, d, 64]
        moves = torch.einsum("bdf,bdt->bft", q, k).flatten(1) / math.sqrt(d) + self.p_bias
        policy = torch.cat([moves, self.p_under(x[:, :, 6, :].flatten(1))], dim=1)
        value = self.v_fc2(F.relu(self.v_fc1(self.v_conv(x).flatten(1))))
        return policy, value


def num_parameters(model):
    return sum(p.numel() for p in model.parameters())


def save_checkpoint(path, model, meta=None):
    torch.save({"model": model.state_dict(), "net_config": asdict(model.cfg), "meta": meta or {}}, path)


def load_checkpoint(path, device="cpu"):
    ck = torch.load(path, map_location=device, weights_only=False)
    model = MeNet(NetConfig(**ck["net_config"]))
    model.load_state_dict(ck["model"])
    return model.to(device), ck.get("meta", {})
