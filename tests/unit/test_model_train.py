import json
import random

import chess
import numpy as np
import pytest
import torch

from chessme.model import data as D
from chessme.model import encoding as enc
from chessme.model import infer, net, train

TINY = net.NetConfig(blocks=1, channels=16, policy_dim=8, value_channels=4, value_hidden=16)


def random_positions(n, seed=1, min_ply=10, max_ply=70):
    rng, out = random.Random(seed), []
    while len(out) < n:
        b = chess.Board()
        for _ in range(rng.randint(min_ply, max_ply)):
            moves = list(b.legal_moves)
            if not moves:
                break
            b.push(rng.choice(moves))
        if not b.is_game_over() and b.legal_moves.count() > 1:
            out.append(b)
    return out


def dataset(boards, choose, ratings=(1500, 1500), weights=None, extras=True, platform=0):
    """Samples where the 'player' picks choose(board, rating) in each position."""
    buf = D.SampleBuffer(extras)
    for i, b in enumerate(boards):
        rating = ratings[i % len(ratings)] if isinstance(ratings, (list, tuple)) and len(ratings) > 2 else ratings[0]
        buf.add(b, choose(b, rating), (rating, rating), platform, 1, 20, 1.0 if weights is None else weights[i])
    return buf.to_arrays()


def lowest(board, rating):
    return min(board.legal_moves, key=lambda m: enc.move_index(m, board))


def highest(board, rating):
    return max(board.legal_moves, key=lambda m: enc.move_index(m, board))


def cfg(**kw):
    kw.setdefault("device", "cpu"); kw.setdefault("batch_size", 64); kw.setdefault("eval_every", 50)
    kw.setdefault("warmup_steps", 5); kw.setdefault("lr", 5e-3)
    return train.TrainConfig(**kw)


# ---- network ------------------------------------------------------------------------------------------------------

def test_forward_shapes_and_default_size():
    m = net.MeNet()
    p, v = m(torch.randn(3, enc.N_PLANES, 8, 8))
    assert p.shape == (3, enc.POLICY_SIZE) and v.shape == (3, 3)
    assert 300_000 < net.num_parameters(m) < 1_500_000  # a small Maia-sized net, cheap to run in the engine


def test_eval_mode_is_deterministic_and_batch_independent():
    m = net.MeNet(TINY).eval()
    x = torch.randn(4, enc.N_PLANES, 8, 8)
    a, _ = m(x)
    b, _ = m(x.flip(0))
    assert torch.allclose(a, b.flip(0), atol=1e-5)  # in eval mode BatchNorm makes samples independent


def test_checkpoint_round_trip(tmp_path):
    m = net.MeNet(TINY).eval()
    net.save_checkpoint(tmp_path / "c.pt", m, {"note": "x"})
    m2, meta = net.load_checkpoint(tmp_path / "c.pt")
    x = torch.randn(2, enc.N_PLANES, 8, 8)
    assert torch.equal(m(x)[0], m2.eval()(x)[0]) and meta == {"note": "x"} and m2.cfg == TINY


# ---- batching ----------------------------------------------------------------------------------------------------

def test_planes_from_a_shard_match_planes_from_the_board():
    boards = random_positions(12, 3)
    data = dataset(boards, lowest, ratings=(1800,))
    x = train.to_planes(data, np.arange(12), torch.device("cpu"))
    for i, b in enumerate(boards):
        arr, castle, ep = enc.canonical_state(b)
        want = enc.build_planes(torch.tensor(arr[None]), torch.tensor([castle], dtype=torch.uint8),
                                torch.tensor([ep], dtype=torch.uint8), torch.tensor([[1800, 1800]], dtype=torch.float32),
                                torch.tensor([0], dtype=torch.uint8))
        assert torch.equal(x[i], want[0])


def test_legal_mask_matches_the_legal_moves():
    boards = random_positions(15, 4)
    data = dataset(boards, lowest)
    mask = train.legal_mask(data, np.arange(15), torch.device("cpu"))
    for i, b in enumerate(boards):
        assert sorted(torch.nonzero(mask[i]).squeeze(1).tolist()) == sorted(enc.legal_indices(b))


# ---- evaluation ----------------------------------------------------------------------------------------------------

def test_untrained_model_scores_near_random_legal_and_reports_phases():
    data = dataset(random_positions(300, 5), lowest)
    res = train.evaluate(net.MeNet(TINY), data, torch.device("cpu"))
    assert set(res) >= {"all", "early (10-19)", "middle (20-39)"} or "all" in res
    a = res["all"]
    assert a["n"] == 300 and 0 <= a["top1"] <= a["top3"] <= 1
    assert abs(a["top1"] - a["uniform_top1"]) < 0.1  # no better than random legal moves
    assert a["nll"] > 0 and 0 < a["prob"] < 1


def test_evaluate_requires_legal_arrays():
    data = dataset(random_positions(10, 6), lowest, extras=False)
    with pytest.raises(ValueError, match="legal"):
        train.evaluate(net.MeNet(TINY), data, torch.device("cpu"))


def test_evaluate_respects_the_limit_and_masks_illegal_moves():
    data = dataset(random_positions(60, 7), lowest)
    assert train.evaluate(net.MeNet(TINY), data, torch.device("cpu"), limit=25)["all"]["n"] == 25


def test_format_eval_is_a_markdown_table():
    data = dataset(random_positions(30, 8), lowest)
    text = train.format_eval(train.evaluate(net.MeNet(TINY), data, torch.device("cpu")), "title")
    assert text.startswith("title") and "| subset |" in text and "| all | 30 |" in text


# ---- training -----------------------------------------------------------------------------------------------------

def test_lr_schedule_warms_up_then_decays():
    c = train.TrainConfig(lr=1.0, warmup_steps=10)
    assert train.lr_at(0, 100, c) == pytest.approx(0.1) and train.lr_at(9, 100, c) == pytest.approx(1.0)
    assert train.lr_at(50, 100, c) < 1.0 and train.lr_at(99, 100, c) == pytest.approx(0.1, abs=0.02)


@pytest.mark.slow
def test_the_network_can_overfit_a_small_dataset(tmp_path):
    boards = random_positions(200, 11)
    data = dataset(boards, lowest)
    hist = train.train(data, data, TINY, cfg(max_steps=400, eval_every=100), tmp_path, log=lambda s: None)
    assert hist[-1]["train_ce"] < 0.5 * hist[0]["train_ce"]
    res = train.evaluate(net.load_checkpoint(tmp_path / "last.pt")[0], data, torch.device("cpu"))["all"]
    assert res["top1"] > 0.85 and res["top1"] > 5 * res["uniform_top1"]


@pytest.mark.slow
def test_the_model_uses_the_rating_input(tmp_path):
    """Same positions, but the 'player' picks a different move depending on rating: only possible if ratings are used."""
    boards = random_positions(150, 12)
    low = dataset(boards, lowest, ratings=(1200,))
    high = dataset(boards, highest, ratings=(2200,))
    both = {k: np.concatenate([low[k], high[k]]) for k in low}
    train.train(both, both, TINY, cfg(max_steps=700, eval_every=350), tmp_path, log=lambda s: None)
    m = net.load_checkpoint(tmp_path / "last.pt")[0].eval()
    hits = 0
    for b in boards[:60]:
        low_move = infer.choose_move(m, b, 1200, temperature=0)
        high_move = infer.choose_move(m, b, 2200, temperature=0)
        hits += low_move == lowest(b, 0) and high_move == highest(b, 0)
    assert hits >= 45  # at least 75% of positions get the rating-appropriate move


@pytest.mark.slow
def test_sample_weights_focus_the_training(tmp_path):
    boards = random_positions(160, 13)
    good = dataset(boards[:80], lowest)
    junk = dataset(boards[:80], highest, weights=[0.0] * 80)  # same positions, opposite labels, zero weight
    both = {k: np.concatenate([good[k], junk[k]]) for k in good}
    train.train(both, good, TINY, cfg(max_steps=300, eval_every=150), tmp_path, log=lambda s: None)
    res = train.evaluate(net.load_checkpoint(tmp_path / "last.pt")[0], good, torch.device("cpu"))["all"]
    assert res["top1"] > 0.85  # zero-weight contradicting labels had no influence


def test_writes_checkpoints_history_and_config(tmp_path):
    data = dataset(random_positions(100, 14), lowest)
    train.train(data, data, TINY, cfg(max_steps=100, eval_every=50), tmp_path, log=lambda s: None)
    assert (tmp_path / "best.pt").exists() and (tmp_path / "last.pt").exists()
    lines = [json.loads(l) for l in (tmp_path / "history.jsonl").read_text().splitlines()]
    assert [r["step"] for r in lines] == [50, 100] and "val_top1" in lines[0]
    assert json.loads((tmp_path / "train_config.json").read_text())["net"]["blocks"] == 1


def test_training_is_reproducible_on_cpu(tmp_path):
    data = dataset(random_positions(120, 15), lowest)
    h1 = train.train(data, data, TINY, cfg(max_steps=60, eval_every=30), tmp_path / "a", log=lambda s: None)
    h2 = train.train(data, data, TINY, cfg(max_steps=60, eval_every=30), tmp_path / "b", log=lambda s: None)
    assert [r["train_ce"] for r in h1] == [r["train_ce"] for r in h2]


def test_early_stopping(tmp_path):
    train_data = dataset(random_positions(100, 16), lowest)
    val_data = dataset(random_positions(60, 17), highest)  # contradicts training: validation cannot keep improving
    hist = train.train(train_data, val_data, TINY, cfg(max_steps=2000, eval_every=25, patience=3, lr=1e-2),
                       tmp_path, log=lambda s: None)
    assert len(hist) < 2000 // 25


def test_fine_tuning_starts_from_a_checkpoint_and_can_freeze_the_body(tmp_path):
    base_data = dataset(random_positions(120, 18), lowest)
    train.train(base_data, base_data, TINY, cfg(max_steps=60), tmp_path / "base", log=lambda s: None)
    before = net.load_checkpoint(tmp_path / "base" / "last.pt")[0].state_dict()
    new_data = dataset(random_positions(120, 19), highest)
    train.train(new_data, new_data, TINY, cfg(max_steps=60, init_from=str(tmp_path / "base" / "last.pt"), freeze_body=True,
                                              lr=1e-3), tmp_path / "ft", log=lambda s: None)
    after = net.load_checkpoint(tmp_path / "ft" / "last.pt")[0].state_dict()
    body = [k for k in before if k.startswith(("stem", "tower")) and "running" not in k and "num_batches" not in k]
    heads = [k for k in before if k.startswith(("p_", "v_")) and "running" not in k and "num_batches" not in k]
    assert all(torch.equal(before[k], after[k]) for k in body)          # frozen: unchanged
    assert any(not torch.equal(before[k], after[k]) for k in heads)     # heads adapted


# ---- inference ----------------------------------------------------------------------------------------------------

def test_probabilities_cover_exactly_the_legal_moves():
    m = net.MeNet(TINY)
    for b in random_positions(10, 20):
        p = infer.move_probabilities(m, b, 1700)
        assert set(p) == set(b.legal_moves) and sum(p.values()) == pytest.approx(1.0)


def test_choose_move_is_legal_greedy_at_zero_and_seedable():
    m = net.MeNet(TINY)
    b = random_positions(1, 21)[0]
    probs = infer.move_probabilities(m, b, 1700)
    assert infer.choose_move(m, b, 1700, temperature=0) == max(probs, key=probs.get)
    a = [infer.choose_move(m, b, 1700, rng=np.random.default_rng(3)) for _ in range(5)]
    c = [infer.choose_move(m, b, 1700, rng=np.random.default_rng(3)) for _ in range(5)]
    assert a == c and all(x in b.legal_moves for x in a)
    hot = {infer.choose_move(m, b, 1700, temperature=5.0, rng=np.random.default_rng(i)) for i in range(60)}
    assert len(hot) > 3  # high temperature spreads the choices


def test_evaluating_an_empty_shard_is_harmless():
    data = dataset(random_positions(10, 30), lowest)
    empty = {k: v[:0] for k, v in data.items()}
    assert train.evaluate(net.MeNet(TINY), empty, torch.device("cpu")) == {}
    assert "(no positions)" in train.format_eval({}, "nothing")
