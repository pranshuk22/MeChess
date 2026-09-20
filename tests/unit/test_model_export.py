import numpy as np
import torch

from chessme.model import export, net
from chessme.model.encoding import N_PLANES

TINY = net.NetConfig(blocks=2, channels=8, policy_dim=4, value_channels=2, value_hidden=8)


def randomised(cfg=TINY, seed=1):
    """A model with non-trivial BatchNorm statistics, so folding is really exercised."""
    torch.manual_seed(seed)
    m = net.MeNet(cfg)
    for mod in m.modules():
        if isinstance(mod, torch.nn.BatchNorm2d):
            mod.running_mean.normal_(0, 0.5)
            mod.running_var.uniform_(0.5, 2.0)
            mod.weight.data.uniform_(0.5, 1.5)
            mod.bias.data.normal_(0, 0.3)
    return m.eval()


def test_fold_bn_matches_conv_followed_by_bn():
    m = randomised()
    conv, bn = m.stem[0], m.stem[1]
    x = torch.randn(3, N_PLANES, 8, 8)
    want = bn(conv(x))
    w, b = export.fold_bn(conv.weight, bn)
    got = torch.nn.functional.conv2d(x, w, b, padding=1)
    assert torch.allclose(want, got, atol=1e-5)


def test_exported_size_matches_the_specification(tmp_path):
    m = randomised()
    n = export.export_net(m, tmp_path / "n.bin")
    assert n == export.expected_floats(2, 8, 4)
    header, flat = export.read_export(tmp_path / "n.bin")
    assert header == {"version": 1, "blocks": 2, "channels": 8, "policy_dim": 4} and flat.size == n


def test_exported_tensor_order_and_values(tmp_path):
    m = randomised()
    export.export_net(m, tmp_path / "n.bin")
    _, flat = export.read_export(tmp_path / "n.bin")
    w, b = export.fold_bn(m.stem[0].weight, m.stem[1])
    c = 8
    assert np.allclose(flat[: c * N_PLANES * 9], w.detach().numpy().ravel(), atol=1e-6)
    assert np.allclose(flat[c * N_PLANES * 9: c * N_PLANES * 9 + c], b.detach().numpy(), atol=1e-6)
    # the last tensors are p_under's weights and bias
    under_b = m.p_under.bias.detach().numpy()
    assert np.allclose(flat[-len(under_b):], under_b)


def test_export_is_deterministic(tmp_path):
    m = randomised()
    export.export_net(m, tmp_path / "a.bin")
    export.export_net(m, tmp_path / "b.bin")
    assert (tmp_path / "a.bin").read_bytes() == (tmp_path / "b.bin").read_bytes()
