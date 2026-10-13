import json
from dataclasses import replace

import chess
import numpy as np
import pytest
import torch

from chessme.humanlike import adapter as A
from chessme.humanlike import play as P
from chessme.humanlike import testset as T
from chessme.model.compare import Scorer
from tests.unit.test_humanlike_testset import LINE, make_game


class UniformScorer(Scorer):
    name = "uniform"

    def probs(self, items):
        return [{m.uci(): 1.0 / chess.Board(it.fen).legal_moves.count() for m in chess.Board(it.fen).legal_moves} for it in items]


class FirstMoveScorer(Scorer):
    """Always plays the alphabetically first legal move (so games are deterministic and often short or repetitive)."""
    name = "first"

    def probs(self, items):
        out = []
        for it in items:
            ucis = sorted(m.uci() for m in chess.Board(it.fen).legal_moves)
            out.append({u: 1.0 if u == ucis[0] else 0.0 for u in ucis})
        return out


class RecordingScorer(UniformScorer):
    def __init__(self):
        self.items = []

    def probs(self, items):
        self.items += list(items)
        return super().probs(items)


def start_positions(n=6, clocks=None):
    out = []
    for i in range(n):
        g = make_game(site=f"p{i:07d}", clocks=clocks or [170 - 5 * (j // 2) if j % 2 == 0 else 170 for j in range(len(LINE))])
        out += [p for p in T.game_positions(g, per_game=100) if p.ply == 8]
    return out


def flat_time_model(share=0.02):
    tm = P.TimeModel()
    for a in range(len(P.CLOCK_SHARE_EDGES) + 1):
        for b in range(len(P.PLY_EDGES) + 1):
            tm.shares[(a, b)] = [share]
    return tm


def test_a_game_continues_from_the_real_position_with_its_clocks_and_ratings():
    p = start_positions(1)[0]
    g = P.game_from_position(p, {chess.WHITE: UniformScorer(), chess.BLACK: UniformScorer()})
    assert g.board.fen().split()[:4] == p.fen.split()[:4] and g.ply == 8 and g.base == 180
    assert g.ratings[g.board.turn] == p.me and g.ratings[not g.board.turn] == p.opp
    assert g.clocks[g.board.turn] == p.clock and g.clocks[not g.board.turn] == p.opp_clock
    with pytest.raises(ValueError, match="history"):
        P.game_from_position(replace(p, moves=" ".join(LINE[:6])), {})


def test_games_are_played_to_a_result_and_are_legal():
    ps = start_positions(8)
    games = [P.game_from_position(p, {chess.WHITE: UniformScorer(), chess.BLACK: UniformScorer()}) for p in ps]
    P.play_games(games, flat_time_model(), seed=1, max_plies=120)
    for g in games:
        assert g.result in ("1-0", "0-1", "1/2-1/2") and g.termination
        b = chess.Board()
        for u in g.start_moves + g.moves:
            assert chess.Move.from_uci(u) in b.legal_moves
            b.push_uci(u)
        assert len(g.spent) == len(g.moves) == len(g.clock_after)
    rec = P.game_record(games[0])
    assert rec["plies"] == 8 + len(games[0].moves) and rec["models"]["white"] == "uniform" and json.dumps(rec)


def test_the_games_do_not_depend_on_how_many_are_played_at_once():
    ps = start_positions(8)
    def play(batch):
        gs = [P.game_from_position(p, {chess.WHITE: UniformScorer(), chess.BLACK: UniformScorer()}) for p in ps]
        P.play_games(gs, flat_time_model(), seed=7, max_plies=80, batch=batch)
        return [g.moves for g in gs]
    assert play(1) == play(256) == play(3)
    gs = [P.game_from_position(p, {chess.WHITE: UniformScorer(), chess.BLACK: UniformScorer()}) for p in ps[:4]]
    P.play_games(gs, flat_time_model(), seed=8, max_plies=80)
    assert [g.moves for g in gs] != play(256)[:4]                                   # another seed, another games


def test_each_model_is_called_for_its_own_side_with_clocks_and_history():
    p = start_positions(1)[0]
    a, b = RecordingScorer(), RecordingScorer()
    g = P.game_from_position(p, {chess.WHITE: a, chess.BLACK: b})
    P.play_games([g], flat_time_model(), seed=2, max_plies=14)
    assert a.items and b.items and len(a.items) + len(b.items) == len(g.moves)
    first = (a.items + b.items)[0]
    assert first.ply == 8 and first.has_history and first.clock == p.clock and first.opp_clock == p.opp_clock and first.base == 180
    assert all(it.clock > 0 for it in a.items + b.items)


def test_running_out_of_time_loses_unless_the_opponent_cannot_mate():
    p = start_positions(1)[0]
    p = replace(p, clock=1.0, opp_clock=100.0)
    g = P.game_from_position(p, {chess.WHITE: UniformScorer(), chess.BLACK: UniformScorer()})
    mover = g.board.turn
    P.play_games([g], flat_time_model(share=1.0), seed=3, max_plies=200)                # every move takes all the time there is: the first move flags
    assert g.termination == "time_forfeit" and g.result == ("0-1" if mover == chess.WHITE else "1-0")
    # a bare king against a king and a knight: the side with the clock left cannot win on time
    bare = P.Game("x", chess.Board("8/8/8/8/8/8/3Nk3/K7 b - - 0 1"), [], {chess.WHITE: 1500, chess.BLACK: 1500}, {chess.WHITE: 50.0, chess.BLACK: 0.5}, 180, 0,
                  {chess.WHITE: UniformScorer(), chess.BLACK: UniformScorer()})
    P.play_games([bare], flat_time_model(share=1.0), seed=3)
    assert bare.result == "1/2-1/2"                                                    # a knight cannot mate a bare king: the flag only draws


def test_the_ply_limit_ends_endless_games():
    p = start_positions(1)[0]
    g = P.game_from_position(p, {chess.WHITE: FirstMoveScorer(), chess.BLACK: FirstMoveScorer()})
    P.play_games([g], flat_time_model(share=0.0001), seed=4, max_plies=40)
    assert g.result != "*" and g.ply <= 40 and g.termination


def test_the_time_model_follows_what_humans_spent():
    ps = start_positions(40)
    # humans in these fake games spent 5 s of the 155 s they had at ply 8: a share of 1/31, applied to the clock of the situation being simulated
    ps = [replace(p, spent=5.0) for p in ps]
    tm = P.TimeModel.fit(ps, per_bin=50)
    rng = np.random.default_rng(0)
    draws = [tm.sample(rng, 170.0, 180, 0, 10) for _ in range(20)]
    assert all(d == pytest.approx(170.0 * 5.0 / 155.0, rel=1e-6) for d in draws)
    far = tm.sample(rng, 3.0, 180, 0, 100)                                              # a situation with no data: the nearest bin is used, scaled to the clock
    assert 0 < far < 3.0
    back = P.TimeModel.from_json(tm.to_json())
    assert back.shares == tm.shares
    assert len(P.TimeModel.fit(ps, per_bin=3).shares[next(iter(tm.shares))]) <= 3


def test_an_untrained_adapter_leaves_the_models_probabilities_alone(tmp_path):
    net = A.Adapter(len(A.FEATURES))
    path = tmp_path / "a.pt"
    A.save_adapter(path, net, np.zeros(len(A.FEATURES), np.float32), np.ones(len(A.FEATURES), np.float32), hidden=32, meta={"name": "x"})
    bundle = A.load_adapter(path)
    assert bundle[3] == {"name": "x"}
    items = [__import__("chessme.model.compare", fromlist=["EvalItem"]).EvalItem(chess.Board().fen(), "", 1500, 1500, 0, 0, (), clock=120.0, opp_clock=150.0, base=180, inc=0)]
    base = UniformScorer()
    wrapped = P.AdaptedScorer(base, bundle)
    p0, p1 = base.probs(items)[0], wrapped.probs(items)[0]
    assert set(p0) == set(p1) and sum(p1.values()) == pytest.approx(1.0)
    assert all(abs(p0[u] - p1[u]) < 1e-5 for u in p0)
    assert wrapped.name == "uniform + adapter"


def test_a_trained_adapter_changes_the_probabilities_and_a_mismatching_file_is_refused(tmp_path):
    net = A.Adapter(len(A.FEATURES))
    torch.nn.init.normal_(net.out.weight, std=0.3)
    path = tmp_path / "b.pt"
    A.save_adapter(path, net, np.zeros(len(A.FEATURES), np.float32), np.ones(len(A.FEATURES), np.float32), hidden=32)
    from chessme.model.compare import EvalItem

    class Skewed(Scorer):
        name = "skewed"

        def probs(self, items):
            out = []
            for it in items:
                ucis = sorted(m.uci() for m in chess.Board(it.fen).legal_moves)
                w = np.array([2.0 ** -i for i in range(len(ucis))])
                out.append(dict(zip(ucis, (w / w.sum()).tolist())))
            return out
    items = [EvalItem(chess.Board().fen(), "", 1500, 1500, 0, 0, (), clock=5.0, opp_clock=150.0, base=180, inc=0)]
    p0, p1 = Skewed().probs(items)[0], P.AdaptedScorer(Skewed(), A.load_adapter(path)).probs(items)[0]
    assert sum(p1.values()) == pytest.approx(1.0) and any(abs(p0[u] - p1[u]) > 1e-3 for u in p0) and set(p0) == set(p1)
    d = torch.load(path, weights_only=False)
    d["features"] = d["features"][:-1]
    torch.save(d, path)
    with pytest.raises(ValueError, match="other features"):
        A.load_adapter(path)
