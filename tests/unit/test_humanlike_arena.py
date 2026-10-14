import json
import shutil

import chess
import chess.engine
import numpy as np
import pytest

from chessme.humanlike import arena as AR
from chessme.humanlike import play as P
from chessme.model.compare import EvalItem, Scorer

VALUES = {chess.PAWN: 100, chess.KNIGHT: 300, chess.BISHOP: 300, chess.ROOK: 500, chess.QUEEN: 900}
needs_sf = pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish")


class GreedyEngine:
    """Stand-in for Stockfish with a one-move horizon (material after the best move)."""

    def __init__(self, cp=None):
        self.cp, self.calls = cp, 0

    def analyse(self, board, limit, game=None):
        self.calls += 1
        best, best_cp = None, -10 ** 6
        for m in sorted(board.legal_moves, key=lambda x: x.uci()):
            board.push(m)
            cp = -sum(VALUES.get(p.piece_type, 0) * (1 if p.color == board.turn else -1) for p in board.piece_map().values())
            board.pop()
            if cp > best_cp:
                best, best_cp = m, cp
        cp = best_cp if self.cp is None else self.cp
        return {"score": chess.engine.PovScore(chess.engine.Cp(cp), board.turn), "pv": [best]}


class UniformScorer(Scorer):
    name = "uniform"

    def probs(self, items):
        out = []
        for it in items:
            legal = [m.uci() for m in chess.Board(it.fen).legal_moves]
            out.append({u: 1 / len(legal) for u in legal})
        return out


def item(fen=chess.STARTING_FEN, rating=1500):
    return EvalItem(fen, "", rating, rating)


# white can take a free queen with Rxd5; any other move leaves it
FREE_QUEEN = "4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1"


def test_beta_zero_keeps_the_prior_and_a_large_beta_takes_the_best_move():
    pool = AR.EnginePool(engines=[GreedyEngine()])
    prior = UniformScorer().probs([item(FREE_QUEEN)])[0]
    flat = AR.ReweightedScorer(UniformScorer(), pool, beta=0.0, k=16).probs([item(FREE_QUEEN)])[0]
    assert sum(flat.values()) == pytest.approx(1.0) and len(flat) == min(16, len(prior))
    assert max(flat.values()) - min(flat.values()) < 1e-9                         # uniform stays uniform
    sharp = AR.ReweightedScorer(UniformScorer(), pool, beta=300.0, k=16).probs([item(FREE_QUEEN)])[0]
    assert max(sharp, key=sharp.get) == "d2d5" and sharp["d2d5"] > 0.99
    weak = AR.ReweightedScorer(UniformScorer(), pool, beta=-5.0, k=16).probs([item(FREE_QUEEN)])[0]
    assert weak.get("d2d5", 0) < flat.get("d2d5", 1)                                  # a negative beta makes the best move less likely


def test_the_bot_only_chooses_among_the_priors_top_k_moves_and_overrides_the_rating():
    seen = []

    class Spy(UniformScorer):
        def probs(self, items):
            seen.extend((it.mover_elo, it.opp_elo) for it in items)
            return super().probs(items)
    pool = AR.EnginePool(engines=[GreedyEngine()])
    p = AR.ReweightedScorer(Spy(), pool, beta=1.0, k=5, rating=2200).probs([item()])[0]
    assert len(p) == 5 and seen == [(2200, 2200)]


def test_the_referee_ends_games_on_a_sustained_decisive_evaluation_or_a_dead_draw():
    def game(gid):
        return P.Game(gid, chess.Board(), [], {chess.WHITE: 1500, chess.BLACK: 1500}, {chess.WHITE: 1e9, chess.BLACK: 1e9}, 0, 0, {})
    ref = AR.Referee(AR.EnginePool(engines=[GreedyEngine(cp=1500)]), win_plies=3)
    g = game("a")
    for _ in range(2):
        ref.check([g])
        assert g.result == "*"
    ref.check([g])
    assert g.result == "1-0" and g.termination == "adjudicated_win"
    ref = AR.Referee(AR.EnginePool(engines=[GreedyEngine(cp=-1500)]), win_plies=2)
    g = game("b")
    ref.check([g]); ref.check([g])
    assert g.result == "0-1"
    ref = AR.Referee(AR.EnginePool(engines=[GreedyEngine(cp=0)]), draw_after=0, draw_plies=3, win_plies=3)
    g = game("c")
    for _ in range(3):
        ref.check([g])
    assert g.result == "1/2-1/2" and g.termination == "adjudicated_draw"


def test_a_streak_is_broken_by_a_move_back_to_equality():
    class Flip(GreedyEngine):
        def analyse(self, board, limit, game=None):
            self.calls += 1
            cp = 1500 if self.calls % 3 else 0
            return {"score": chess.engine.PovScore(chess.engine.Cp(cp), chess.WHITE), "pv": [next(iter(board.legal_moves))]}
    g = P.Game("x", chess.Board(), [], {chess.WHITE: 1500, chess.BLACK: 1500}, {chess.WHITE: 1e9, chess.BLACK: 1e9}, 0, 0, {})
    ref = AR.Referee(AR.EnginePool(engines=[Flip()]), win_plies=3, draw_cp=-1)
    for _ in range(12):
        ref.check([g])
    assert g.result == "*"


def test_pairings_schedule_and_scores():
    groups = {"a": "ladder", "b": "ladder", "x": "bot", "y": "bot"}
    pairs = AR.pairings(list(groups), groups)
    assert ("x", "y") not in pairs and ("a", "x") in pairs and len(pairs) == 5
    assert ("x", "y") in AR.pairings(list(groups), groups, bot_vs_bot=True)
    games = AR.schedule({}, [("a", "b")], ["e2e4", "d2d4"])
    assert len(games) == 4 and {g[1] for g in games} == {"a", "b"} and len({g[0] for g in games}) == 4
    assert AR.result_for("a", "b", "1-0", "a", "b") == 1.0 and AR.result_for("a", "b", "1-0", "b", "a") == 0.0
    assert AR.result_for("a", "b", "1/2-1/2", "a", "b") == 0.5


@needs_sf
def test_stockfish_scorer_is_deterministic_and_plays_the_free_queen():
    pool = AR.EnginePool(shutil.which("stockfish"), workers=2)
    try:
        sc = AR.StockfishScorer(pool, 2000)
        first = sc.probs([item(FREE_QUEEN), item()])
        second = sc.probs([item(FREE_QUEEN), item()])
        assert first == second and first[0] == {"d2d5": 1.0}
        assert chess.Move.from_uci(next(iter(first[1]))) in chess.Board().legal_moves
    finally:
        pool.close()


@needs_sf
def test_a_game_between_two_ladder_players_finishes_and_the_stronger_one_scores():
    pool = AR.EnginePool(shutil.which("stockfish"), workers=2)
    ref_pool = AR.EnginePool(shutil.which("stockfish"), workers=1)
    try:
        strong, weak = AR.StockfishScorer(pool, 3000, name="strong"), AR.StockfishScorer(pool, 1, name="weak")
        games = []
        for k, start in enumerate(["e2e4 e7e5", "d2d4 d7d5", "c2c4 e7e6", "g1f3 d7d5"]):
            games.append(AR.game_from_start(start, {chess.WHITE: strong, chess.BLACK: weak}, f"s{k}w"))
            games.append(AR.game_from_start(start, {chess.WHITE: weak, chess.BLACK: strong}, f"s{k}b"))
        P.play_games(games, AR.NoTime(), max_plies=200, referee=AR.Referee(ref_pool, nodes=300))
        assert all(g.result in ("1-0", "0-1", "1/2-1/2") for g in games)
        pts = sum(AR.result_for(g.models[chess.WHITE].name, g.models[chess.BLACK].name, g.result, "strong", "weak") for g in games)
        assert pts >= 5.0                                                          # of 8
    finally:
        pool.close()
        ref_pool.close()
