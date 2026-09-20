"""Integration: the C++ engine's network inference must agree with PyTorch on the same exported weights."""
import random
import re

import chess
import pytest
import torch

from chessme.model import export, infer, net
from tests.integration.uci_helper import run_uci

pytestmark = pytest.mark.integration


def lively_model(cfg, seed=1):
    """Random weights with wide logits and non-trivial BatchNorm statistics, so the parity check has teeth."""
    torch.manual_seed(seed)
    m = net.MeNet(cfg)
    with torch.no_grad():
        for mod in m.modules():
            if isinstance(mod, torch.nn.BatchNorm2d):
                mod.running_mean.normal_(0, 0.3)
                mod.running_var.uniform_(0.6, 1.8)
                mod.weight.uniform_(0.7, 1.3)
                mod.bias.normal_(0, 0.2)
            elif isinstance(mod, (torch.nn.Conv2d, torch.nn.Linear)):
                mod.weight.mul_(1.6)
        m.p_bias.normal_(0, 1.2)
        m.p_under.bias.normal_(0, 1.0)
    return m.eval()


def positions():
    rng, out = random.Random(3), []
    fens = [
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",      # castling both ways
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R b KQkq - 0 1",
        "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3",           # en passant available
        "1n2k3/P7/8/8/8/8/p7/1N2K3 w - - 0 1", "1n2k3/P7/8/8/8/8/p7/1N2K3 b - - 0 1",  # under-promotions, both colours
        "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 2",
    ]
    out += [chess.Board(f) for f in fens]
    while len(out) < 60:
        b = chess.Board()
        for _ in range(rng.randint(0, 100)):
            moves = list(b.legal_moves)
            if not moves:
                break
            b.push(rng.choice(moves))
        if not b.is_game_over():
            out.append(b)
    return out


def engine_policy(engine_path, weights, board, rating, opp, platform):
    out = run_uci(engine_path, [f"setoption name MeNetFile value {weights}", f"setoption name MeRating value {rating}",
                                f"setoption name MeOppRating value {opp}", f"setoption name MePlatform value {platform}",
                                f"position fen {board.fen(en_passant='fen')}", "menet"])
    (line,) = re.findall(r"^menet (.*)$", out, re.M)
    return {chess.Move.from_uci(t.split(":")[0]): float(t.split(":")[1]) for t in line.split()}


@pytest.mark.parametrize("cfg", [net.NetConfig(blocks=2, channels=16, policy_dim=8, value_channels=2, value_hidden=8),
                                 net.NetConfig()])
def test_cpp_policy_matches_pytorch(engine_path, tmp_path, cfg):
    model = lively_model(cfg)
    weights = tmp_path / "net.bin"
    export.export_net(model, weights)
    worst = 0.0
    for i, board in enumerate(positions()[:24 if cfg.blocks > 2 else 60]):
        rating, opp, platform = [(1500, 1500, 0), (1900, 1750, 0), (2400, 2300, 1), (1200, 1400, 1)][i % 4]
        want = infer.move_probabilities(model, board, rating, opp, platform)
        got = engine_policy(engine_path, weights, board, rating, opp, platform)
        assert set(got) == set(want), board.fen()
        diff = max(abs(got[m] - want[m]) for m in want)
        worst = max(worst, diff)
        assert diff < 2e-4, (board.fen(), diff)
        assert max(got, key=got.get) == max(want, key=want.get) or abs(max(want.values()) - sorted(want.values())[-2]) < 1e-3
    assert worst < 2e-4


def test_ratings_and_platform_change_the_engine_output_like_they_do_in_pytorch(engine_path, tmp_path):
    model = lively_model(net.NetConfig(blocks=2, channels=16, policy_dim=8, value_channels=2, value_hidden=8), seed=5)
    weights = tmp_path / "net.bin"
    export.export_net(model, weights)
    b = chess.Board("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1")
    low = engine_policy(engine_path, weights, b, 1200, 1200, 0)
    high = engine_policy(engine_path, weights, b, 2400, 2400, 0)
    other = engine_policy(engine_path, weights, b, 1200, 1200, 1)
    assert max(abs(low[m] - high[m]) for m in low) > 1e-3   # the rating input matters
    assert max(abs(low[m] - other[m]) for m in low) > 1e-4  # so does the platform flag


def test_default_opponent_rating_means_same_as_mine(engine_path, tmp_path):
    model = lively_model(net.NetConfig(blocks=2, channels=16, policy_dim=8, value_channels=2, value_hidden=8), seed=6)
    weights = tmp_path / "net.bin"
    export.export_net(model, weights)
    b = chess.Board()
    same = engine_policy(engine_path, weights, b, 1800, 1800, 0)
    default = engine_policy(engine_path, weights, b, 1800, 0, 0)  # MeOppRating 0 = use MeRating
    assert all(abs(same[m] - default[m]) < 1e-7 for m in same)


def test_a_real_checkpoint_round_trips_through_the_engine(engine_path, tmp_path):
    """Whatever the training produced (BatchNorm statistics and all) must export and load."""
    model = lively_model(net.NetConfig())
    net.save_checkpoint(tmp_path / "c.pt", model)
    loaded, _ = net.load_checkpoint(tmp_path / "c.pt")
    export.export_net(loaded, tmp_path / "net.bin")
    out = run_uci(engine_path, [f"setoption name MeNetFile value {tmp_path / 'net.bin'}", "position startpos", "menet"])
    assert "loaded me-network" in out and "6 blocks, 64 channels" in out
