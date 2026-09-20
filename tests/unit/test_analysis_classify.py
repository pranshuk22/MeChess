import pytest

from chessme.analysis import classify as C
from chessme.analysis.classify import MoveEval, classify, move_accuracy, win_prob


def cp_for(p):
    """centipawns giving win probability p (inverse of the sigmoid)"""
    import math
    return -math.log(1 / p - 1) / C.LICHESS_K


def test_win_prob_is_a_symmetric_sigmoid_with_lichess_constants():
    assert win_prob(0) == 0.5
    assert win_prob(100) + win_prob(-100) == pytest.approx(1.0)
    assert win_prob(100) == pytest.approx(1 / (1 + 2.71828 ** (-0.368208)), abs=1e-4)     # 50 + 50 * (2/(1+e^-x) - 1) == 100/(1+e^-x)
    assert win_prob(10 ** 7) == win_prob(C.MATE_CP) <= 1.0        # mate scores are clamped (saturates to 1.0)
    assert 0.0 < win_prob(-30000) == win_prob(-C.MATE_CP)


def test_loss_bands_follow_the_published_scale():
    best = 0                                               # an even position, best move keeps 0.5
    def cls(loss, **kw):
        return classify(MoveEval(best_cp=best, played_cp=cp_for(0.5 - loss), **kw))
    assert cls(0.0) == "best" and cls(0.004) == "best"
    assert cls(0.015) == "excellent"
    assert cls(0.04) == "good"
    assert cls(0.08) == "inaccuracy"
    assert cls(0.15) == "mistake"
    assert cls(0.30) == "blunder"


def test_moves_that_beat_the_engine_are_best_not_negative_loss():
    assert classify(MoveEval(best_cp=0, played_cp=50)) == "best"


def test_book_wins_over_everything():
    assert classify(MoveEval(best_cp=0, played_cp=-900, book=True)) == "book"


def test_great_needs_a_critical_only_move_and_never_a_forced_one():
    only = MoveEval(best_cp=0, played_cp=0, second_cp=-400)
    assert classify(only) == "great"
    assert classify(MoveEval(best_cp=0, played_cp=0, second_cp=-10)) == "best"          # many good moves
    assert classify(MoveEval(best_cp=0, played_cp=0, second_cp=-400, only_legal=True)) == "best"
    # tier change without a huge gap: winning (0.70) vs balanced (0.60)
    tier = MoveEval(best_cp=cp_for(0.70), played_cp=cp_for(0.70), second_cp=cp_for(0.60))
    assert classify(tier) == "great"
    same_tier = MoveEval(best_cp=cp_for(0.70), played_cp=cp_for(0.70), second_cp=cp_for(0.66))
    assert classify(same_tier) == "best"


def test_brilliant_needs_sacrifice_soundness_and_a_not_yet_won_position():
    base = dict(best_cp=cp_for(0.6), played_cp=cp_for(0.6), material_given=3.0)
    assert classify(MoveEval(**base)) == "brilliant"
    assert classify(MoveEval(**{**base, "material_given": 0.5})) == "best"                     # no real sacrifice
    assert classify(MoveEval(**{**base, "best_cp": cp_for(0.9), "played_cp": cp_for(0.9)})) == "best"   # already winning
    unsound = MoveEval(best_cp=cp_for(0.6), played_cp=cp_for(0.4), material_given=3.0)
    assert classify(unsound) != "brilliant"                                                    # loses ground / bad position
    assert classify(MoveEval(**{**base, "played_cp": cp_for(0.55)})) != "brilliant"            # not the best move


def test_miss_only_after_an_opponent_error_and_not_for_blunders():
    played = cp_for(0.5 - 0.15)
    assert classify(MoveEval(best_cp=0, played_cp=played)) == "mistake"
    assert classify(MoveEval(best_cp=0, played_cp=played, opp_loss=0.2)) == "miss"
    assert classify(MoveEval(best_cp=0, played_cp=cp_for(0.1), opp_loss=0.2)) == "blunder"
    assert classify(MoveEval(best_cp=0, played_cp=cp_for(0.5 - 0.015), opp_loss=0.2)) == "excellent"   # took most of the gain


def test_thresholds_are_configurable():
    strict = C.Thresholds(good=0.01, inaccuracy=0.02, mistake=0.04)
    assert classify(MoveEval(best_cp=0, played_cp=cp_for(0.44)), strict) == "blunder"


def test_classification_is_monotone_in_loss():
    order = ["book", "brilliant", "great", "best", "excellent", "good", "inaccuracy", "mistake", "blunder"]
    ranks = [order.index(classify(MoveEval(best_cp=0, played_cp=cp_for(0.5 - l / 100)))) for l in range(0, 50)]
    assert ranks == sorted(ranks)


def test_move_accuracy_matches_lichess_endpoints():
    assert move_accuracy(0.5, 0.5) == 100.0
    assert move_accuracy(0.5, 0.6) == 100.0                       # gaining points is not penalised
    assert move_accuracy(0.5, 0.4) == pytest.approx(103.1668 * 2.71828 ** (-0.4354415) - 3.1669 + 1, abs=0.01)
    assert move_accuracy(1.0, 0.0) == pytest.approx(0.0, abs=2.0) or move_accuracy(1.0, 0.0) < 3
