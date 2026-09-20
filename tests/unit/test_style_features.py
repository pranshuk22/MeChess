import chess
import pytest

from chessme.style.features import FEATURE_NAMES, feature_vector, move_features, see


def feats(fen, uci):
    b = chess.Board(fen)
    m = chess.Move.from_uci(uci)
    assert m in b.legal_moves, (fen, uci)
    return move_features(b, m)


def test_vector_matches_names_and_is_deterministic():
    b = chess.Board()
    m = chess.Move.from_uci("e2e4")
    assert len(feature_vector(b, m)) == len(FEATURE_NAMES) == len(set(FEATURE_NAMES))
    assert feature_vector(b, m) == feature_vector(b, m)


def test_every_legal_move_in_varied_positions_yields_finite_features():
    fens = [chess.STARTING_FEN,
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
            "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
            "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3"]
    for fen in fens:
        b = chess.Board(fen)
        for m in b.legal_moves:
            assert all(v == v and abs(v) < 1e3 for v in feature_vector(b, m)), (fen, m)


def test_quiet_opening_pawn_push():
    f = feats(chess.STARTING_FEN, "e2e4")
    assert f["pawn_push"] == 1 and f["to_center"] == 1 and f["capture"] == 0 and f["check"] == 0


def test_mobility_grows_when_a_knight_develops():
    assert feats(chess.STARTING_FEN, "g1f3")["mobility_delta"] > 0


def test_castling_side():
    fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    assert feats(fen, "e1g1")["castle_short"] == 1 and feats(fen, "e1g1")["castle_long"] == 0
    assert feats(fen, "e1c1")["castle_long"] == 1 and feats(fen, "e1g1")["king_move"] == 0


def test_check_and_promotion():
    assert feats("4k3/8/8/8/8/8/8/R3K3 w - - 0 1", "a1a8")["check"] == 1
    p = feats("8/P6k/8/8/8/8/8/4K3 w - - 0 1", "a7a8q")
    assert p["promotion"] == 1


class TestStaticExchange:
    def test_queen_takes_pawn_defended_by_pawn_loses_material(self):
        b = chess.Board("4k3/8/4p3/3p4/8/8/8/3QK3 w - - 0 1")
        assert see(b, chess.Move.from_uci("d1d5")) == -8
        assert feats(b.fen(), "d1d5")["sacrifice"] == 1

    def test_free_piece_is_not_a_sacrifice(self):
        b = chess.Board("4k3/8/8/3n4/8/8/8/3QK3 w - - 0 1")
        assert see(b, chess.Move.from_uci("d1d5")) == 3
        assert feats(b.fen(), "d1d5")["sacrifice"] == 0

    def test_rook_takes_defended_knight_is_an_exchange_sacrifice(self):
        f = feats("3rk3/8/8/3n4/8/8/8/3RK3 w - - 0 1", "d1d5")
        assert f["exchange_sacrifice"] == 1 and f["sacrifice"] == 1

    def test_xray_battery_behind_the_mover_is_counted(self):
        b = chess.Board("3rk3/8/8/3n4/8/8/3R4/3RK3 w - - 0 1")
        assert see(b, chess.Move.from_uci("d2d5")) == 3

    def test_equal_knight_trade(self):
        f = feats("4k3/8/5n2/3n4/8/2N5/8/4K3 w - - 0 1", "c3d5")
        assert f["trade"] == 1 and f["sacrifice"] == 0

    def test_winning_a_piece_for_free_is_not_a_trade(self):
        assert feats("4k3/8/8/3n4/8/2N5/8/4K3 w - - 0 1", "c3d5")["trade"] == 0

    def test_queen_trade(self):
        assert feats("3qk3/8/8/8/8/8/8/3QK3 w - - 0 1", "d1d8")["queen_trade"] == 1

    def test_en_passant_counts_as_a_pawn_capture(self):
        b = chess.Board("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        assert see(b, chess.Move.from_uci("e5d6")) == 1


class TestKingSafety:
    def test_pawn_storm_towards_the_enemy_king(self):
        fen = "6k1/5ppp/8/8/8/8/5PPP/6K1 w - - 0 1"
        assert feats(fen, "h2h4")["pawn_storm"] == 1
        assert feats(chess.STARTING_FEN, "e2e4")["pawn_storm"] == 0

    def test_advancing_the_own_shield_pawn_weakens_the_king(self):
        fen = "6k1/5ppp/8/8/8/8/5PPP/6K1 w - - 0 1"
        assert feats(fen, "g2g4")["weakens_own_king"] == 1
        assert feats("4k3/pppppppp/8/8/8/8/PPPPPPPP/6K1 w - - 0 1", "a2a4")["weakens_own_king"] == 0

    def test_attackers_at_the_enemy_king_raise_the_zone_count(self):
        fen = "6k1/5ppp/8/8/8/5N2/8/3Q2K1 w - - 0 1"
        assert feats(fen, "d1d5")["king_zone_delta"] >= 0
        assert feats(fen, "f3g5")["king_zone_delta"] > 0


class TestStructure:
    def test_capture_toward_the_centre_creates_doubled_and_isolated_pawns(self):
        f = feats("4k3/8/8/8/8/2p5/1PP5/4K3 w - - 0 1", "b2c3")
        assert f["own_doubled_delta"] == 1 and f["own_isolated_delta"] == 2 and f["pawn_break"] == 1

    def test_capture_can_create_a_passed_pawn(self):
        f = feats("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1", "e4d5")
        assert f["own_passed_delta"] == 1

    def test_capturing_a_doubled_pawn_repairs_the_opponent_structure(self):
        f = feats("4k3/2p5/2p5/3P4/8/8/8/4K3 w - - 0 1", "d5c6")
        assert f["opp_doubled_delta"] == -1 and f["pawn_break"] == 1
        assert feats("4k3/2p5/2p5/3P4/8/8/8/4K3 w - - 0 1", "e1e2")["opp_doubled_delta"] == 0

    def test_taking_a_bishop_removes_the_pair_only_when_there_is_a_pair(self):
        f = feats("4k3/8/2b5/3b4/8/2N2N2/8/4K3 w - - 0 1", "c3d5")
        assert f["capture"] == 1 and f["takes_bishop_pair"] == 1
        assert feats("4k3/8/2n5/3b4/8/2N2N2/8/4K3 w - - 0 1", "c3d5")["takes_bishop_pair"] == 0

    def test_trading_a_bishop_for_a_knight_gives_up_the_pair(self):
        fen = "4k3/1p6/2n5/8/8/8/6B1/2B1K3 w - - 0 1"
        assert feats(fen, "g2c6")["concedes_bishop_pair"] == 1
        assert feats("4k3/1p6/2n5/8/8/8/6B1/4K3 w - - 0 1", "g2c6")["concedes_bishop_pair"] == 0


class TestFiles:
    def test_rook_to_open_and_semi_open_files(self):
        assert feats("4k3/pp6/8/8/8/8/PP6/R3K3 w - - 0 1", "a1d1")["rook_open_file"] == 1
        assert feats("4k3/pp6/8/8/8/8/PP6/R3K3 w - - 0 1", "a1c1")["rook_open_file"] == 1
        assert feats("4k3/1p6/8/8/8/8/P7/R3K3 w - - 0 1", "a1b1")["rook_semi_open_file"] == 1
        assert feats("4k3/1p6/8/8/8/8/1P6/R3K3 w - - 0 1", "a1b1")["rook_open_file"] == 0

    def test_rook_to_the_seventh_is_colour_relative(self):
        assert feats("4k3/8/8/8/8/8/8/R3K3 w - - 0 1", "a1a7")["rook_seventh"] == 1
        assert feats("r3k3/8/8/8/8/8/8/4K3 b - - 0 1", "a8a2")["rook_seventh"] == 1
        assert feats("4k3/8/8/8/8/8/8/R3K3 w - - 0 1", "a1a6")["rook_seventh"] == 0


class TestActivity:
    def test_retreat_and_centralisation(self):
        fen = "4k3/8/8/8/8/5N2/8/4K3 w - - 0 1"
        assert feats(fen, "f3g1")["retreat"] == 1
        assert feats(fen, "f3e5")["retreat"] == 0 and feats(fen, "f3e5")["to_center"] == 1

    def test_black_moves_use_black_relative_directions(self):
        b = chess.Board("4k3/8/5n2/8/8/8/8/4K3 b - - 0 1")
        assert move_features(b, chess.Move.from_uci("f6g8"))["retreat"] == 1
        assert move_features(b, chess.Move.from_uci("f6e4"))["retreat"] == 0

    def test_king_walk(self):
        assert feats("4k3/8/8/8/8/8/8/4K3 w - - 0 1", "e1e2")["king_move"] == 1
