import numpy as np
import pytest

from chessme.dataset.weights import Weighter
from chessme.model import compare as C
from chessme.model import data as D
from chessme.model import encoding as enc
from tests.samples import make_row

import chess

CFG = {"filters": {"min_rating": {"lichess": 1400}, "recency": {"half_life_days": 3650, "min_weight": 0.1},
                   "time_class_weights": {"blitz": 1.0, "bullet": {"full_until_ply": 20, "late_weight": 0.1}}}}
GAME = "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O h3 Nb8 d4 Nbd7 Nbd2 Bb7"


class Oracle(C.Scorer):
    name = "oracle"

    def probs(self, items):
        out = []
        for it in items:
            moves = [m.uci() for m in chess.Board(it.fen).legal_moves]
            out.append({m: (0.9 if m == it.played else 0.1 / (len(moves) - 1)) for m in moves})
        return out


class Uniform(C.Scorer):
    name = "uniform"

    def probs(self, items):
        return [{m.uci(): 1 / chess.Board(it.fen).legal_moves.count() for m in chess.Board(it.fen).legal_moves} for it in items]


class Anti(C.Scorer):
    name = "anti"

    def probs(self, items):
        out = []
        for it in items:
            moves = [m.uci() for m in chess.Board(it.fen).legal_moves]
            out.append({m: (0.001 if m == it.played else 0.999 / (len(moves) - 1)) for m in moves})
        return out


def rows(n=3, **kw):
    return [make_row(game_id=f"g{i}", moves=GAME, color="white" if i % 2 == 0 else "black", my_rating=1800, opp_rating=1750,
                     platform="lichess", **kw) for i in range(n)]


def items(**kw):
    r = rows(**kw)
    return C.items_from_games(r, Weighter(CFG, r), min_ply=8)


def test_items_carry_history_that_leads_to_the_position():
    its = items()
    assert its and all(it.has_history for it in its)
    for it in its:
        b = chess.Board()
        for m in it.moves:
            b.push_uci(m)
        assert b.fen().split()[:4] == it.fen.split()[:4]
        assert chess.Move.from_uci(it.played) in b.legal_moves and it.ply >= 8


def test_only_the_players_own_moves_are_used():
    for it in items():
        white_to_move = it.fen.split()[1] == "w"
        assert it.ply % 2 == (0 if white_to_move else 1)
    white_items = [it for it in C.items_from_games(rows(1), Weighter(CFG, rows(1)), 8)]
    assert all(it.ply % 2 == 0 for it in white_items)  # game 0: the player is White


def test_ratings_and_platform_come_from_the_players_view():
    it = items()[0]
    assert (it.mover_elo, it.opp_elo, it.platform) == (1800, 1750, 0)


def test_filtered_games_and_min_ply_are_respected():
    r = rows(2)
    r[0]["my_rating"] = 1000  # below the rating floor
    its = C.items_from_games(r, Weighter(CFG, r), min_ply=8)
    assert its and all(it.ply >= 8 for it in its) and len(its) == len(C.items_from_games(r[1:], Weighter(CFG, r), 8))


def test_items_from_a_shard_decode_the_played_move():
    buf = D.SampleBuffer(with_extras=True)
    board = chess.Board()
    for san in GAME.split()[:14]:
        m = board.parse_san(san)
        if board.fullmove_number >= 4:
            buf.add(board, m, (1700, 1650), 0, 1, board.ply(), 1.0)
        board.push(m)
    data = buf.to_arrays()
    its = C.items_from_shard(data)
    assert len(its) == len(data["move"]) and all(not it.has_history for it in its)
    b = chess.Board(its[0].fen)
    assert chess.Move.from_uci(its[0].played) in b.legal_moves and its[0].mover_elo == 1700
    assert len(C.items_from_shard(data, limit=2)) == 2
    with pytest.raises(ValueError):
        C.items_from_shard({k: v for k, v in data.items() if k != "fen"})


def test_metrics_oracle_uniform_and_anti_scorers():
    its = items()
    o, u, a = (C.evaluate_scorer(s, its)["all"] for s in (Oracle(), Uniform(), Anti()))
    assert o["top1"] == 1.0 and o["top3"] == 1.0 and o["prob"] == pytest.approx(0.9) and o["nll"] == pytest.approx(-np.log(0.9))
    assert u["top1"] < 0.3 and u["top1"] == pytest.approx(u["uniform_top1"], abs=0.25)
    assert a["top1"] == 0.0 and a["nll"] == pytest.approx(-np.log(0.001), rel=1e-6)
    assert o["n"] == len(its) and 0 < o["top1_ci95"] + 1  # CI is defined


def test_groups_split_by_phase():
    res = C.evaluate_scorer(Oracle(), items())
    assert set(res) <= set(C.GROUPS) and "all" in res
    assert res["all"]["n"] == sum(res[g]["n"] for g in ("early (10-19)", "middle (20-39)", "late (40+)") if g in res)


def test_an_illegal_played_move_is_an_error():
    it = items()[0]
    bad = C.EvalItem(it.fen, "a1a8", it.mover_elo, it.opp_elo, it.platform, it.ply, it.moves)
    with pytest.raises(ValueError, match="not legal"):
        C.evaluate_scorer(Uniform(), [bad])


def test_heavy_piece_count():
    assert C.heavy_pieces(chess.STARTING_FEN) == 14
    assert C.heavy_pieces("8/8/8/4k3/8/8/4P3/4K3 w - - 0 1") == 0
    assert C.heavy_pieces("4k3/8/8/8/8/8/8/R3KB1R w - - 0 1") == 3


def test_format_comparison_table():
    its = items()
    text = C.format_comparison({"oracle": C.evaluate_scorer(Oracle(), its), "uniform": C.evaluate_scorer(Uniform(), its)}, "T")
    assert text.startswith("T") and "| oracle | 100.0% +/- 0.0" in text and "random legal move" in text


def test_our_scorer_matches_the_training_side_evaluation(tmp_path):
    """The comparison harness and train.evaluate must agree for our own model (same masking, same numbers)."""
    import torch

    from chessme.model import net, train
    model = net.MeNet(net.NetConfig(blocks=1, channels=16, policy_dim=8, value_channels=4, value_hidden=16))
    net.save_checkpoint(tmp_path / "m.pt", model)
    r = rows(4)
    its = C.items_from_games(r, Weighter(CFG, r), 8)
    buf = D.SampleBuffer(with_extras=True)
    for row in r:
        rec = D.record_from_row(row, Weighter(CFG, r))
        buf.extend(D.extract_samples(rec, min_ply=8, extras=True))
    data = buf.to_arrays()
    assert len(its) == len(data["move"])
    mine = C.evaluate_scorer(C.OursScorer(tmp_path / "m.pt"), its)["all"]
    ref = train.evaluate(net.load_checkpoint(tmp_path / "m.pt")[0], data, torch.device("cpu"))["all"]
    assert mine["n"] == ref["n"] and mine["top1"] == pytest.approx(ref["top1"]) and mine["top3"] == pytest.approx(ref["top3"])
    assert mine["nll"] == pytest.approx(ref["nll"], rel=1e-4)
