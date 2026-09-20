import chess
import numpy as np
import pytest
import torch

from chessme.dataset.weights import Weighter
from chessme.model import encoding as enc
from chessme.model import maia3_ft as M
from tests.samples import make_row

CFG = {"filters": {"min_rating": {"lichess": 1400}, "recency": {"half_life_days": 3650, "min_weight": 0.1},
                   "time_class_weights": {"blitz": 1.0}}}
GAME = "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O h3 Nb8 d4 Nbd7 Nbd2 Bb7"


def rows(n=4):
    return [make_row(game_id=f"g{i}", moves=GAME, color="white" if i % 2 == 0 else "black", my_rating=1800 + 10 * i,
                     opp_rating=1750, platform="lichess") for i in range(n)]


def test_mirror_and_vocabulary_index_match_maia3s_layout():
    assert M.mirror_uci("e7e5") == "e2e4" and M.mirror_uci("a2a1q") == "a7a8q"
    b = chess.Board()
    assert M.vocab_index(b.parse_san("e4"), chess.WHITE) == 12 * 64 + 28          # e2e4
    b.push_san("e4")
    assert M.vocab_index(b.parse_san("e5"), chess.BLACK) == 12 * 64 + 28          # e7e5 mirrored to e2e4
    promo = chess.Board("1n2k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    assert M.vocab_index(chess.Move.from_uci("a7a8q"), chess.WHITE) == 4096 + 0 * 4 + 0
    assert M.vocab_index(chess.Move.from_uci("a7b8n"), chess.WHITE) == 4096 + (0 * 8 + 1) * 4 + 3
    assert M.vocab_index(chess.Move.from_uci("a7a8r"), chess.WHITE) == 4096 + 1
    assert all(0 <= M.vocab_index(m, promo.turn) < M.VOCAB for m in promo.legal_moves)


def test_all_legal_moves_get_distinct_vocabulary_slots():
    for fen in [chess.STARTING_FEN, "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R b KQkq - 0 1",
                "1n2k3/P7/8/8/8/8/p7/1N2K3 b - - 0 1"]:
        b = chess.Board(fen)
        idx = [M.vocab_index(m, b.turn) for m in b.legal_moves]
        assert len(idx) == len(set(idx))


def test_player_data_selects_the_players_moves_with_history():
    r = rows(4)
    d = M.build_player_data(r, Weighter(CFG, r), min_ply=8)
    assert len(d) > 0 and d.legal_off[-1] == len(d.legal_flat) and len(d.legal_off) == len(d) + 1
    assert d.boards.shape[1] == 64 and set(np.unique(d.elos[:, 1])) == {1750}
    assert all(d.start[i] <= d.cur[i] for i in range(len(d)))
    for i in range(len(d)):  # the target is one of the legal moves and both agree on legality
        legal = set(d.legal_flat[d.legal_off[i]:d.legal_off[i + 1]].tolist())
        assert int(d.target[i]) in legal and len(legal) >= 2


def test_batch_tokens_match_the_reference_tokenisation_and_history_padding():
    r = rows(2)
    d = M.build_player_data(r, Weighter(CFG, r), min_ply=0)
    boards = torch.from_numpy(d.boards)
    i = 0  # first sample of game 0: ply 0, so its history is the start position repeated 8 times
    tokens, me, opp, mask, target, w = M.make_batch(d, [i], boards, "cpu")
    assert tokens.shape == (1, 64, 96) and mask.shape == (1, M.VOCAB) and mask.sum() == d.legal_off[1] - d.legal_off[0]
    start_tokens = torch.nn.functional.one_hot(torch.from_numpy(d.boards[d.cur[i]]).long(), 13)[:, 1:].float()
    for h in range(8):
        assert torch.equal(tokens[0, :, h * 12:(h + 1) * 12], start_tokens)
    # a later sample sees genuinely different positions, newest last
    j = 12
    t2 = M.make_batch(d, [j], boards, "cpu")[0]
    newest = torch.nn.functional.one_hot(torch.from_numpy(d.boards[d.cur[j]]).long(), 13)[:, 1:].float()
    assert torch.equal(t2[0, :, 7 * 12:], newest) and not torch.equal(t2[0, :, :12], t2[0, :, 7 * 12:])


def test_each_history_position_is_in_its_own_movers_view():
    r = rows(1)
    d = M.build_player_data(r, Weighter(CFG, r), min_ply=0)
    b = chess.Board()
    first = d.start[0]
    for ply, san in enumerate(GAME.split()[:6]):
        assert np.array_equal(d.boards[first + ply], enc.canonical_state(b)[0])
        b.push_san(san)


class Tiny(torch.nn.Module):
    """Stands in for Maia-3: (tokens, elos, elos) -> (move logits, value, ponder)."""

    def __init__(self):
        super().__init__()
        self.proj_sq_from = torch.nn.Linear(96, 32)
        self.head = torch.nn.Linear(32, M.VOCAB)
        self.last_ln = torch.nn.LayerNorm(32)

    def forward(self, tokens, me, opp):
        x = self.last_ln(torch.relu(self.proj_sq_from(tokens)).mean(1))
        return self.head(x), torch.zeros(len(tokens), 3), torch.zeros(len(tokens), 1)


def test_finetuning_reduces_loss_saves_best_and_respects_scope(tmp_path):
    r = rows(6)
    w = Weighter(CFG, r)
    tr, va = M.build_player_data(r[:5], w, 8), M.build_player_data(r[5:], w, 8)
    model = Tiny()
    before = M.evaluate(model, va, "cpu", torch.from_numpy(va.boards))
    hist = M.finetune(model, tr, va, tmp_path / "ft.pt", epochs=30, batch_size=16, lr=3e-3, warmup=5, eval_every=20,
                      log=lambda s: None)
    assert (tmp_path / "ft.pt").exists() and "model_state_dict" in torch.load(tmp_path / "ft.pt")
    assert hist[-1]["train_nll"] < 3.0 and min(h["val_nll"] for h in hist) < before["nll"]

    frozen = Tiny()
    keep = {k: v.clone() for k, v in frozen.state_dict().items()}
    M.finetune(frozen, tr, va, tmp_path / "h.pt", epochs=5, batch_size=16, lr=1e-2, warmup=2, eval_every=10, scope="heads",
               log=lambda s: None)
    after = frozen.state_dict()
    assert torch.equal(keep["head.weight"], after["head.weight"])           # not in the 'heads' scope: unchanged
    assert not torch.equal(keep["proj_sq_from.weight"], after["proj_sq_from.weight"])  # in scope: trained
