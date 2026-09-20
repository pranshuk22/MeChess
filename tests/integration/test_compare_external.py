"""Optional: verifies that our batched scoring of Maia-3 / Maia-2 reproduces their own reference code exactly.

Runs only when the external checkouts and weights are available (they are large / separately licensed):
  CHESSME_MAIA3_REPO, CHESSME_MAIA3_CKPT (5M checkpoint), CHESSME_MAIA2_REPO, CHESSME_MAIA2_CKPT, CHESSME_EXTRA_PATH
"""
import os
import random
import sys

import chess
import pytest

from chessme.model import compare as C

pytestmark = pytest.mark.integration

MAIA3_REPO, MAIA3_CKPT = os.environ.get("CHESSME_MAIA3_REPO"), os.environ.get("CHESSME_MAIA3_CKPT")
MAIA2_REPO, MAIA2_CKPT = os.environ.get("CHESSME_MAIA2_REPO"), os.environ.get("CHESSME_MAIA2_CKPT")
EXTRA = [p for p in os.environ.get("CHESSME_EXTRA_PATH", "").split(os.pathsep) if p]


def random_items(n, seed):
    rng, out = random.Random(seed), []
    while len(out) < n:
        b, played = chess.Board(), []
        for _ in range(rng.randint(10, 60)):
            moves = list(b.legal_moves)
            if not moves:
                break
            m = rng.choice(moves)
            played.append(m.uci())
            b.push(m)
        legal = list(b.legal_moves)
        if legal:
            out.append(C.EvalItem(b.fen(), rng.choice(legal).uci(), rng.choice([1200, 1500, 1800, 2200]),
                                  rng.choice([1300, 1600, 1900, 2100]), 0, len(played), tuple(played)))
    return out


@pytest.mark.skipif(not (MAIA3_REPO and MAIA3_CKPT), reason="Maia-3 checkout / weights not provided")
@pytest.mark.parametrize("history", [False, True])
def test_maia3_scorer_matches_the_reference_engine(history):
    scorer = C.Maia3Scorer(MAIA3_REPO, MAIA3_CKPT, "5m", use_history=history, extra_paths=EXTRA)
    sys.path.insert(0, MAIA3_REPO)
    from maia3 import uci as mu

    args = ["--model", "5m", "--checkpoint-path", MAIA3_CKPT, "--device", "cpu", "--temperature", "0", "--multipv", "20"]
    if history:
        args.append("--use-uci-history")
    ref = mu.Maia3UCIEngine(mu.parse_args(args))
    ref.ensure_model_loaded()
    for it in random_items(12, 4):
        ref.self_elo, ref.oppo_elo = it.mover_elo, it.opp_elo
        ref.cmd_position("position startpos moves " + " ".join(it.moves)) if history else ref.cmd_position("position fen " + it.fen)
        _, top = ref.score_moves()
        ours = scorer.probs([it])[0]
        for entry in top:
            assert ours[entry["move"].uci()] == pytest.approx(entry["policy"], abs=1e-5), (it.fen, entry["move"])


@pytest.mark.skipif(not (MAIA2_REPO and MAIA2_CKPT), reason="Maia-2 checkout / weights not provided")
def test_maia2_scorer_matches_the_reference_inference():
    scorer = C.Maia2Scorer(MAIA2_REPO, MAIA2_CKPT, extra_paths=EXTRA)
    with C._on_path(MAIA2_REPO, *EXTRA):
        from maia2 import inference as inf
    prepared = inf.prepare()
    for it in random_items(12, 5):
        ref, _ = inf.inference_each(scorer.model, prepared, it.fen, it.mover_elo, it.opp_elo)
        ours = scorer.probs([it])[0]
        assert set(ref) == set(ours)
        for m, p in ref.items():
            assert ours[m] == pytest.approx(p, abs=1e-4), (it.fen, m)  # the reference rounds to 4 decimals


@pytest.mark.skipif(not MAIA3_REPO, reason="Maia-3 checkout not provided")
def test_our_vocabulary_and_history_tokens_match_maia3s_own_functions():
    import torch

    from chessme.dataset.weights import Weighter
    from chessme.model import maia3_ft as M
    from tests.samples import make_row

    with C._on_path(MAIA3_REPO, *EXTRA):
        from maia3 import dataset as md
        from maia3 import utils as mut
    moves_dict = {m: i for i, m in enumerate(mut.get_all_possible_moves())}
    rng = random.Random(9)
    # 1) vocabulary: every legal move of many positions
    for _ in range(60):
        b = chess.Board()
        for _ in range(rng.randint(0, 80)):
            legal = list(b.legal_moves)
            if not legal:
                break
            b.push(rng.choice(legal))
        for m in b.legal_moves:
            uci = m.uci() if b.turn == chess.WHITE else mut.mirror_move(m.uci())
            assert M.vocab_index(m, b.turn) == moves_dict[uci], (b.fen(), m)
    # 2) tokens: a real game, every sampled position, compared with the reference history builder
    game = "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O h3 Nb8 d4 Nbd7 Nbd2 Bb7"
    row = make_row(game_id="x", moves=game, color="white", my_rating=1800, opp_rating=1700, platform="lichess")
    data = M.build_player_data([row], Weighter({"filters": {"time_class_weights": {"blitz": 1.0}}}, [row]), min_ply=0)
    from collections import deque

    class Cfg:
        history = 8
        include_time_info = False

    boards = torch.from_numpy(data.boards)
    for i in range(len(data)):
        replay, hist = chess.Board(), deque(maxlen=8)
        hist.append(md.tokenize_board(replay))
        for san in game.split()[: int(data.cur[i] - data.start[i])]:
            replay.push_san(san)
            hist.append(md.tokenize_board(replay))
        ref = md.get_historical_tokens(hist, Cfg, base=0.0, inc=0.0, clk_left_before=0.0, clk_ponder=0.0)[:, :96]
        ours = M.make_batch(data, [i], boards, "cpu")[0][0]
        assert torch.equal(ours, ref), i
