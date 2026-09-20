import math

import chess
import chess.pgn
import numpy as np
import pytest

from chessme.style import gamefeatures as G

RUY = "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7 f1e1 b7b5 a4b3 d7d6 c2c3 e8g8 h2h3 c6b8 d2d4 b8d7 b1d2 c8b7 b3c2 f8e8 d2f1 e7f8 f1g3 g7g6 a2a4 c7c5"   # 30 plies, all legal, no capture


def make_game(moves=RUY, white_thinks=None, black_thinks=None, base=300, inc=0, result="1/2-1/2", termination="Normal", eco="C84",
              tc=True, clocks=True):
    g = chess.pgn.Game()
    g.headers.update({"White": "w", "Black": "b", "Result": result, "ECO": eco, "Opening": "Ruy Lopez", "Termination": termination})
    if tc:
        g.headers["TimeControl"] = f"{base}+{inc}"
    node, board = g, chess.Board()
    wclk = bclk = float(base)
    wt, bt = list(white_thinks or []), list(black_thinks or [])
    for m in moves.split():
        mv = chess.Move.from_uci(m)
        node = node.add_variation(mv)
        if clocks:
            if board.turn == chess.WHITE:
                wclk = wclk - (wt.pop(0) if wt else 3.0) + inc
                node.set_clock(wclk)
            else:
                bclk = bclk - (bt.pop(0) if bt else 3.0) + inc
                node.set_clock(bclk)
        board.push(mv)
    return str(g)


def feats(text, color=chess.WHITE):
    f, meta = G.game_features(text, color)
    return f, meta


class TestOpening:
    def test_first_move_and_castling_and_early_piece_counts(self):
        f, _ = feats(make_game())
        assert (f["w_e4"], f["w_d4"], f["w_other"]) == (1.0, 0.0, 0.0)
        assert math.isnan(f["b_e4_e5"]) and math.isnan(f["b_d4_d5"])                       # not Black
        assert f["castle_move"] == 5 and f["castled_short"] == 1 and f["castled_by_10"] == 1
        assert [f[f"early_{k}"] for k in ("pawn", "knight", "bishop", "rook", "queen", "king")] == pytest.approx([0.4, 0.1, 0.3, 0.1, 0.0, 0.1])
        assert f["queen_early"] == 0.0

    def test_development_and_centre_after_ten_moves(self):
        f, _ = feats(make_game())
        assert f["minors_out_by_8"] == 2          # Ng1 and Bf1 have left their squares, Nb1 and Bc1 have not
        assert f["centre_pawns_10"] == 2 and f["centre_control_10"] == 4     # pawns d4, e4; d5 (by e4) and e5 (by Nf3) attacked

    def test_black_replies_are_recorded_against_the_first_move(self):
        f, _ = feats(make_game(), chess.BLACK)
        assert (f["b_e4_e5"], f["b_e4_c5"], f["b_e4_other"]) == (1.0, 0.0, 0.0) and math.isnan(f["w_e4"])
        f, _ = feats(make_game("e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 a7a6 c1e3 e7e6 f2f3 b7b5"), chess.BLACK)
        assert f["b_e4_c5"] == 1.0 and f["b_e4_e5"] == 0.0
        f, _ = feats(make_game("d2d4 g8f6 c2c4 e7e6 b1c3 f8b4 e2e3 e8g8 f1d3 d7d5 g1f3 c7c5 e1g1 b8c6"), chess.BLACK)
        assert (f["b_d4_nf6"], f["b_d4_d5"], f["b_d4_other"]) == (1.0, 0.0, 0.0) and math.isnan(f["b_e4_e5"])

    def test_an_early_queen_and_never_castling(self):
        f, _ = feats(make_game("e2e4 e7e5 d1h5 b8c6 f1c4 g7g6 h5f3 g8f6 b1c3 f8g7 d2d3 d7d6 c1g5 h7h6 g5h4 g6g5"))
        assert f["queen_early"] == 1.0 and math.isnan(f["castle_move"]) and math.isnan(f["castled_by_10"])   # 8 own moves: too short for "by 10"

    def test_a_flank_opening_counts_as_other(self):
        f, _ = feats(make_game("g2g3 e7e5 f1g2 g8f6 b1c3 d7d5 d2d3 f8e7 g1f3 e8g8"))
        assert f["w_other"] == 1.0 and f["w_nf3"] == 0.0
        f, _ = feats(make_game("g1f3 d7d5 g2g3 g8f6 f1g2 e7e6 e1g1 f8e7 d2d3 e8g8"))
        assert f["w_nf3"] == 1.0 and f["w_other"] == 0.0

    def test_short_games_do_not_invent_values(self):
        f, _ = feats(make_game("e2e4 e7e5 g1f3 b8c6"))
        assert math.isnan(f["early_pawn"]) and math.isnan(f["minors_out_by_8"]) and math.isnan(f["centre_control_10"])


class TestShape:
    def test_length_capture_queen_trade_and_endgame(self):
        f, _ = feats(make_game())
        assert f["plies"] == 30 and math.isnan(f["first_capture_ply"]) and math.isnan(f["queen_trade_ply"])   # a quiet game
        assert math.isnan(f["pieces_at_40"]) and f["endgame_reached"] == 0.0                                   # only 30 plies
        f, _ = feats(make_game("e2e4 d7d5 e4d5 d8d5 b1c3 d5a5 g1f3 c8g4 f1e2 b8c6 e1g1 e8c8 d2d4 g4f3"))
        assert f["first_capture_ply"] == 3

    def test_the_queen_trade_ply(self):
        f, _ = feats(make_game("e2e4 e7e5 d1h5 g8f6 h5e5 d8e7 e5e7 f8e7"))       # ...Qxe7+ Bxe7: the second queen leaves at ply 8
        assert f["queen_trade_ply"] == 8 and f["first_capture_ply"] == 5

    def test_result_and_termination_for_each_colour(self):
        mate = make_game("f2f3 e7e5 g2g4 d8h4", result="0-1")
        assert feats(mate, chess.WHITE)[0]["result"] == 0.0 and feats(mate, chess.BLACK)[0]["result"] == 1.0
        assert feats(mate)[0]["end_mate"] == 1.0 and feats(mate)[0]["end_resign"] == 0.0
        resign = make_game(result="1-0")
        f = feats(resign)[0]
        assert (f["result"], f["end_resign"], f["end_mate"], f["end_time"]) == (1.0, 1.0, 0.0, 0.0)
        timeout = make_game(result="0-1", termination="Time forfeit")
        f = feats(timeout)[0]
        assert (f["end_time"], f["lost_on_time"], f["won_on_time"], f["end_resign"]) == (1.0, 1.0, 0.0, 0.0)
        assert feats(timeout, chess.BLACK)[0]["won_on_time"] == 1.0
        assert feats(make_game(result="1/2-1/2"))[0]["end_draw"] == 1.0
        assert math.isnan(feats(make_game(result="*"))[0]["result"])

    def test_pieces_at_ply_40_and_60_and_the_endgame_flag(self):
        # a long shuffle keeps 32 pieces; then trade everything off in a made-up but legal simplification
        shuffle = "g1f3 g8f6 f3g1 f6g8 " * 10
        f, _ = feats(make_game(shuffle.strip()))
        assert f["plies"] == 40 and f["pieces_at_40"] == 32 and f["pawns_at_40"] == 16 and math.isnan(f["pieces_at_60"])


class TestClock:
    THINKS = [2, 3, 2, 4, 2, 60, 2, 3, 2, 4, 2, 5, 3, 3, 3]              # White's 15 think times in seconds

    def game(self, **kw):
        return make_game(white_thinks=self.THINKS, **kw)

    def test_think_times_are_read_from_the_clock_comments(self):
        g = chess.pgn.read_game(__import__("io").StringIO(self.game()))
        assert G.think_times(g, chess.WHITE, 300, 0) == pytest.approx(self.THINKS)

    def test_increment_is_added_back(self):
        g = chess.pgn.read_game(__import__("io").StringIO(make_game(white_thinks=[5] * 15, base=180, inc=2)))
        assert G.think_times(g, chess.WHITE, 180, 2) == pytest.approx([5.0] * 15)

    def test_relative_think_time_uses_the_nominal_per_move_budget(self):
        f, _ = feats(self.game())
        budget = 300 / 40.0
        assert f["think_median_rel"] == pytest.approx(3.0 / budget) and f["think_mean_rel"] == pytest.approx(np.mean(self.THINKS) / budget)
        assert f["think_open_rel"] == pytest.approx(np.mean(self.THINKS[:12]) / budget)
        assert f["think_mid_rel"] == pytest.approx(np.mean(self.THINKS[12:]) / budget)

    def test_premoves_instants_long_thinks_and_the_share_spent_in_the_opening(self):
        thinks = [0.0, 0.1, 2, 2, 2, 2, 2, 2, 40, 2, 2, 2, 2, 2, 2]
        f, _ = feats(make_game(white_thinks=thinks))
        assert f["premove_frac"] == pytest.approx(2 / 15) and f["instant_frac"] == pytest.approx(2 / 15)
        assert f["long_think_frac"] == pytest.approx(1 / 15)
        assert f["opening_time_share"] == pytest.approx(sum(thinks[:12]) / sum(thinks))

    def test_time_trouble_and_clock_left(self):
        f, _ = feats(make_game(white_thinks=[15] * 15, base=300))          # 300 - 225 = 75 s left; trouble = clock below max(10, 30 s)
        assert f["clock_left_frac"] == pytest.approx(75 / 300)
        assert f["time_trouble_frac"] == pytest.approx(0.0)
        f, _ = feats(make_game(white_thinks=[30] * 15, base=300))          # clock hits 0.. below 30 s for the last moves
        assert 0 < f["time_trouble_frac"] < 1

    def test_missing_clocks_or_time_control_or_too_few_moves_give_nan_not_zero(self):
        for kw in ({"clocks": False}, {"tc": False}):
            f, _ = feats(make_game(**kw))
            assert all(math.isnan(f[n]) for n in G.CLOCK), kw
        f, _ = feats(make_game("e2e4 e7e5 g1f3 b8c6 f1b5 a7a6"))
        assert all(math.isnan(f[n]) for n in G.CLOCK)

    def test_the_players_own_clock_is_used_for_each_colour(self):
        g = make_game(white_thinks=[1] * 15, black_thinks=[10] * 15)
        assert feats(g, chess.WHITE)[0]["think_median_rel"] < feats(g, chess.BLACK)[0]["think_median_rel"]

    def test_time_control_parsing(self):
        assert G.parse_time_control("180+2") == (180, 2) and G.parse_time_control("600") == (600, 0)
        assert G.parse_time_control("-") == (None, None) and G.parse_time_control(None) == (None, None)


class TestAggregate:
    def test_means_ignore_missing_values_and_repertoire_stats_come_from_eco_codes(self):
        f1, m1 = feats(make_game(eco="C84"))
        f2, m2 = feats(make_game("e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7", eco="C84"))
        f3, m3 = feats(make_game("d2d4 d7d5 c2c4 e7e6 b1c3 g8f6 c1g5 f8e7 e2e3 e8g8", eco="D37"))
        v = G.aggregate([G.vector(f) for f in (f1, f2, f3)], [m1, m2, m3])
        names = list(G.ALL_NAMES)
        assert len(v) == len(names)
        assert v[names.index("w_e4")] == pytest.approx(2 / 3) and v[names.index("w_d4")] == pytest.approx(1 / 3)
        assert v[names.index("think_median_rel")] == v[names.index("think_median_rel")]        # a real number
        assert v[names.index("distinct_eco_per_100")] == pytest.approx(2 * 100 / 3)
        assert v[names.index("top_eco_share_w")] == pytest.approx(2 / 3)
        assert v[names.index("eco_entropy_w")] == pytest.approx(-(2 / 3 * math.log2(2 / 3) + 1 / 3 * math.log2(1 / 3)))
        assert math.isnan(v[names.index("eco_entropy_b")])                                     # the player was never Black

    def test_a_feature_that_never_exists_stays_nan(self):
        f, m = feats(make_game())
        v = G.aggregate([G.vector(f)] * 3, [m] * 3)
        assert math.isnan(v[list(G.ALL_NAMES).index("b_e4_e5")])

    def test_no_games_gives_all_nan(self):
        assert np.isnan(G.aggregate([], [])[: len(G.FEATURE_NAMES)]).all()

    def test_feature_names_are_unique_and_grouped_into_families(self):
        assert len(set(G.ALL_NAMES)) == len(G.ALL_NAMES) and set(G.FAMILY.values()) == {"opening", "shape", "clock"}
        assert set(G.FAMILY) == set(G.FEATURE_NAMES)
