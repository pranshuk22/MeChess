import random

import chess
import pytest

from chessme import selfplay
from chessme.dataset import texel_data
from chessme.dataset.weights import Weighter
from chessme.match import GameResult
from chessme.uci_client import STARTPOS_FEN
from tests.samples import make_row


def scripted_game(san_moves, result="1-0", evals=None, error=None, start=STARTPOS_FEN):
    board = chess.Board(start)
    ucis = []
    for san in san_moves:
        m = board.parse_san(san)
        ucis.append(m.uci())
        board.push(m)
    return GameResult(start, ucis, evals if evals is not None else [20] * len(ucis), result, "x", error=error)


ITALIAN = "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 d6 O-O O-O Bb3 a6 Re1 Ba7".split()


def test_positions_are_labelled_with_the_game_result_from_whites_view():
    for result, value in (("1-0", 1.0), ("0-1", 0.0), ("1/2-1/2", 0.5)):
        rows = selfplay.positions_from_game(scripted_game(ITALIAN, result), random.Random(1), min_ply=4, keep_prob=1.0)
        assert rows and {v for _, v in rows} == {value}


def test_min_ply_skips_the_opening():
    rows = selfplay.positions_from_game(scripted_game(ITALIAN), random.Random(1), min_ply=10, keep_prob=1.0)
    assert len(rows) == len(ITALIAN) - 10
    early = selfplay.positions_from_game(scripted_game(ITALIAN), random.Random(1), min_ply=0, keep_prob=1.0)
    assert len(early) == len(ITALIAN)


def test_captures_checks_and_promotions_are_not_sampled():
    game = scripted_game("e4 d5 exd5 Qxd5 Nc3 Qa5 d4 c6 Bd2 Bf5 Qe2+ e6".split())
    fens = [f for f, _ in selfplay.positions_from_game(game, random.Random(1), min_ply=0, keep_prob=1.0)]
    board = chess.Board()
    quiet_expected = []
    for uci in game.moves:
        m = chess.Move.from_uci(uci)
        if not board.is_capture(m) and not board.is_check():
            quiet_expected.append(board.fen())
        board.push(m)
    assert fens == quiet_expected
    assert len(fens) < len(game.moves)  # some were filtered out


def test_extreme_scores_and_missing_scores_are_dropped():
    evals = [20] * 8 + [2000, -2000, None] + [20] * 5
    rows = selfplay.positions_from_game(scripted_game(ITALIAN, evals=evals), random.Random(1), min_ply=0, keep_prob=1.0)
    assert len(rows) == len(ITALIAN) - 3


def test_games_with_engine_errors_yield_nothing():
    assert selfplay.positions_from_game(scripted_game(ITALIAN, error="boom"), random.Random(1)) == []


def test_keep_probability_thins_the_sample_deterministically():
    g = scripted_game(ITALIAN * 1)
    a = selfplay.positions_from_game(g, random.Random(3), min_ply=0, keep_prob=0.5)
    assert a == selfplay.positions_from_game(g, random.Random(3), min_ply=0, keep_prob=0.5)
    assert 0 < len(a) < len(ITALIAN)
    assert selfplay.positions_from_game(g, random.Random(3), min_ply=0, keep_prob=0.0) == []


def test_randomise_plays_the_requested_number_of_legal_plies():
    fen = selfplay.randomise(STARTPOS_FEN, 4, random.Random(9))
    b = chess.Board(fen)
    assert b.is_valid() and b.fullmove_number == 3
    assert selfplay.randomise(STARTPOS_FEN, 4, random.Random(9)) == fen
    assert selfplay.randomise(STARTPOS_FEN, 4, random.Random(10)) != fen
    assert selfplay.randomise(STARTPOS_FEN, 0, random.Random(1)) == STARTPOS_FEN


def test_randomise_never_returns_a_finished_game():
    fen = "7k/6Q1/6K1/8/8/8/8/8 w - - 0 1"  # any move leaves black checkmated or stalemated soon
    out = selfplay.randomise(fen, 6, random.Random(1))
    assert not chess.Board(out).is_game_over()


# ---- tuning data from the player's own games -----------------------------------------------------------------

CFG = {"filters": {"min_rating": {"lichess": 1400}, "recency": {"half_life_days": 365, "min_weight": 0.1},
                   "time_class_weights": {"blitz": 1.0, "bullet": {"full_until_ply": 20, "late_weight": 0.1}}}}
LONG = " ".join(ITALIAN)


def rows_for_texel(**over):
    return [make_row(game_id="g1", moves=LONG, result="1-0", **over)]


def test_texel_positions_carry_result_and_weight():
    rows = rows_for_texel()
    out = list(texel_data.from_games(rows, Weighter(CFG, rows), min_ply=4, keep_prob=1.0, weight_scale=0.5))
    assert out
    for fen, value, weight in out:
        assert chess.Board(fen).is_valid() and value == 1.0
        assert weight == pytest.approx(0.5)  # newest game, blitz, scale 0.5


def long_game_san(plies=44, seed=4):
    """A long legal game from seeded random play (retries other seeds if it ends early)."""
    while True:
        rng, board, sans = random.Random(seed), chess.Board(), []
        while len(sans) < plies and not board.is_game_over():
            move = rng.choice(list(board.legal_moves))
            sans.append(board.san(move))
            board.push(move)
        if len(sans) == plies:
            return " ".join(sans)
        seed += 1


def test_texel_weights_follow_time_control_and_ply():
    rows = [make_row(game_id="long", moves=long_game_san(), result="1-0", time_class="bullet")]
    out = list(texel_data.from_games(rows, Weighter(CFG, rows), min_ply=4, keep_prob=1.0, weight_scale=1.0))
    weights = sorted({round(w, 3) for _, _, w in out})
    assert weights == [0.1, 1.0]  # plies < 20 full weight, later plies down-weighted


def test_texel_skips_filtered_games_and_bad_results():
    rows = [make_row(game_id="low", moves=LONG, result="1-0", my_rating=1000),
            make_row(game_id="star", moves=LONG, result="*"),
            make_row(game_id="unusable", moves=LONG, result="1-0", usable=False)]
    assert list(texel_data.from_games(rows, Weighter(CFG, rows), min_ply=0, keep_prob=1.0)) == []


def test_texel_keeps_positions_before_an_unreplayable_move_and_nothing_after():
    bad = make_row(game_id="bad", moves="e4 e5 Qh9 Nc6 Nf3", result="1-0")  # Qh9 is not a move
    out = list(texel_data.from_games([bad], Weighter(CFG, [bad]), min_ply=0, keep_prob=1.0))
    assert len(out) == 2  # the start position and the position after 1.e4; then the game is abandoned
    good = make_row(game_id="ok", moves=LONG, result="0-1")
    rows = [bad, good]
    out = list(texel_data.from_games(rows, Weighter(CFG, rows), min_ply=4, keep_prob=1.0))
    assert out and all(v == 0.0 for _, v, _ in out)  # the good game is still processed
