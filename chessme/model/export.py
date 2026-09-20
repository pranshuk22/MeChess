"""Export a trained MeNet to the flat binary format read by the C++ engine (engine/src/net/menet.h).

BatchNorm layers are folded into the preceding convolutions, so the engine only needs plain convolutions.

File (little-endian): "CMNN" | u32 version=1 | u32 blocks | u32 channels | u32 policy_dim | then float32 tensors:
    stem conv   w[C,20,3,3] b[C]
    per block   conv1 w[C,C,3,3] b[C], conv2 w[C,C,3,3] b[C]
    p_qk        w[2D,C] b[2D]      (1x1 conv)
    p_bias      [4096]
    p_under     w[72, C*8] b[72]   (rows read the mover's 7th rank: index = channel * 8 + file)
The result head is not exported: the engine only needs the policy.
"""
import struct

import numpy as np
import torch

from .encoding import N_PLANES, POLICY_SIZE
from .net import MeNet

MAGIC = b"CMNN"
VERSION = 1


def fold_bn(conv_w, bn):
    """Fold an eval-mode BatchNorm2d into a bias-free convolution: returns (weight, bias)."""
    scale = bn.weight / torch.sqrt(bn.running_var + bn.eps)
    return conv_w * scale[:, None, None, None], bn.bias - bn.running_mean * scale


def tensors_of(model):
    """The exported tensors, in file order, as float32 numpy arrays."""
    model = model.eval()
    out = []

    def add(*ts):
        out.extend(t.detach().cpu().numpy().astype(np.float32).ravel() for t in ts)

    with torch.no_grad():
        add(*fold_bn(model.stem[0].weight, model.stem[1]))
        for blk in model.tower:
            add(*fold_bn(blk.c1.weight, blk.b1))
            add(*fold_bn(blk.c2.weight, blk.b2))
        add(model.p_qk.weight.squeeze(-1).squeeze(-1), model.p_qk.bias, model.p_bias, model.p_under.weight, model.p_under.bias)
    return out


def export_net(model, path):
    cfg = model.cfg
    parts = tensors_of(model)
    with open(path, "wb") as f:
        f.write(MAGIC + struct.pack("<IIII", VERSION, cfg.blocks, cfg.channels, cfg.policy_dim))
        for p in parts:
            f.write(p.astype("<f4").tobytes())
    return sum(p.size for p in parts)


def expected_floats(blocks, channels, policy_dim):
    c, d = channels, policy_dim
    return (c * N_PLANES * 9 + c) + blocks * 2 * (c * c * 9 + c) + (2 * d * c + 2 * d) + 4096 + ((POLICY_SIZE - 4096) * c * 8 + (POLICY_SIZE - 4096))


def read_export(path):
    """(header dict, flat float32 array): used by tests and tools."""
    raw = open(path, "rb").read()
    if raw[:4] != MAGIC:
        raise ValueError("bad magic")
    version, blocks, channels, dim = struct.unpack("<IIII", raw[4:20])
    return {"version": version, "blocks": blocks, "channels": channels, "policy_dim": dim}, np.frombuffer(raw[20:], "<f4")
