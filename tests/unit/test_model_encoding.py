import random

import chess
import numpy as np
import pytest
import torch

from chessme.model import encoding as enc


def random_boards(n, seed, max_plies=120):
    rng, out = random.Random(seed), []
    while len(out) < n:
        b = chess.Board()
        for _ in range(rng.randint(0, max_plies)):
            moves = list(b.legal_moves)
            if not moves:
                break
            b.push(rng.choice(moves))
        if not b.is_game_over():
            out.append(b)
    return out


def mirrored(board):
    """The colour-swapped, vertically-flipped twin of a position (with the side to move swapped too)."""
    return board.mirror()


def test_every_legal_move_gets_a_distinct_valid_slot():
    for b in random_boards(300, 1):
        idx = enc.legal_indices(b)
        assert len(idx) == len(set(idx)) == b.legal_moves.count()
        assert all(0 <= i < enc.POLICY_SIZE for i in idx)


def test_slots_decode_back_to_the_same_move():
    for b in random_boards(80, 2):
        for m in b.legal_moves:
            assert enc.index_to_move(enc.move_index(m, b), b) == m
        assert enc.index_to_move(enc.POLICY_SIZE - 1, b) in (None, *b.legal_moves)


def test_black_to_move_is_encoded_like_the_mirrored_white_position():
    for b in random_boards(200, 3):
        m = mirrored(b)
        sa, sb = enc.canonical_state(b), enc.canonical_state(m)
        assert np.array_equal(sa[0], sb[0]) and sa[1] == sb[1] and sa[2] == sb[2]
        assert sorted(enc.legal_indices(b)) == sorted(enc.legal_indices(m))


def test_start_position_layout():
    arr, castle, ep = enc.canonical_state(chess.Board())
    assert arr[4] == 6 and arr[60] == 12  # mover's king on e1, opponent's on e8
    assert list(arr[8:16]) == [1] * 8 and list(arr[48:56]) == [7] * 8
    assert castle == 15 and ep == enc.NO_EP


def test_black_to_move_sees_its_own_pieces_at_the_bottom():
    b = chess.Board()
    b.push_san("e4")
    arr, castle, ep = enc.canonical_state(b)
    assert arr[4] == 6                    # Black's king, seen from Black's side, is on the canonical e1
    assert arr[12] == 1                   # Black's own e-pawn (e7) is the mover's pawn on the canonical e2
    assert arr[36] == 7 and arr[52] == 0  # White's advanced pawn (e4) is the opponent's pawn on the canonical e5
    assert ep == enc.NO_EP                # e3 is the ep square, but no Black pawn can capture there


def test_castling_rights_are_relative_to_the_mover():
    b = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w Kq - 0 1")
    assert enc.canonical_state(b)[1] == 1 | 8  # mover K-side, opponent Q-side
    b.turn = chess.BLACK
    assert enc.canonical_state(b)[1] == 2 | 4  # Black to move: its Q-side (bit 2), opponent's K-side (bit 4)


def test_castling_is_an_ordinary_king_move_in_the_canonical_view():
    w = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    b = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1")
    assert enc.move_index(chess.Move.from_uci("e1g1"), w) == 4 * 64 + 6
    assert enc.move_index(chess.Move.from_uci("e8g8"), b) == 4 * 64 + 6  # identical slot from Black's side
    assert enc.move_index(chess.Move.from_uci("e1c1"), w) == 4 * 64 + 2


def test_promotions_queen_uses_the_normal_slot_and_underpromotions_get_their_own():
    b = chess.Board("1n2k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    slots = {m.uci(): enc.move_index(m, b) for m in b.legal_moves if m.from_square == chess.A7}
    assert slots["a7a8q"] == chess.A7 * 64 + chess.A8
    assert slots["a7b8q"] == chess.A7 * 64 + chess.B8
    under = [slots[k] for k in ("a7a8n", "a7a8b", "a7a8r", "a7b8n", "a7b8b", "a7b8r")]
    assert all(s >= 4096 for s in under) and len(set(under)) == 6
    assert len(set(slots.values())) == len(slots)


def test_underpromotion_slots_are_the_same_for_both_colours():
    w = chess.Board("1n2k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    bl = w.mirror()
    sw = sorted(enc.move_index(m, w) for m in w.legal_moves)
    sb = sorted(enc.move_index(m, bl) for m in bl.legal_moves)
    assert sw == sb


def test_en_passant_square_is_canonical():
    b = chess.Board("rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3")
    assert enc.canonical_state(b)[2] == chess.F6
    bb = chess.Board("rnbqkbnr/pppp1ppp/8/8/3Pp3/8/PPP1PPPP/RNBQKBNR b KQkq d3 0 3")
    assert enc.canonical_state(bb)[2] == chess.D3 ^ 56


def test_en_passant_is_marked_only_when_a_capture_is_possible():
    capturable = chess.Board("rnbqkbnr/pppp1ppp/8/8/3Pp3/8/PPP1PPPP/RNBQKBNR b KQkq d3 0 3")
    assert enc.canonical_state(capturable)[2] == chess.D3 ^ 56
    not_capturable = chess.Board("rnbqkbnr/pppp1ppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
    assert not_capturable.ep_square == chess.E3 and enc.canonical_state(not_capturable)[2] == enc.NO_EP


def test_stored_arrays_can_be_normalised_to_the_same_rule():
    """Shards built before the rule was pinned down are fixed from their own arrays; must equal the direct rule."""
    boards = random_boards(600, 21, max_plies=60)
    boards += [chess.Board("rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3"),
               chess.Board("rnbqkbnr/pppp1ppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"),
               chess.Board("rnbqkbnr/pppp1ppp/8/8/3Pp3/8/PPP1PPPP/RNBQKBNR b KQkq d3 0 3")]
    old_ep, arrs, want = [], [], []
    for b in boards:
        arr, _, ep = enc.canonical_state(b)
        arrs.append(arr)
        want.append(ep)
        # the old rule: mark the square after every double push
        old_ep.append(enc.NO_EP if b.ep_square is None else (b.ep_square if b.turn == chess.WHITE else b.ep_square ^ 56))
    fixed = enc.normalise_ep(np.stack(arrs), np.array(old_ep, np.uint8))
    assert fixed.tolist() == want and any(o != w for o, w in zip(old_ep, want))


def planes_for(b, ratings=(1700, 1700), platform=0):
    arr, castle, ep = enc.canonical_state(b)
    return enc.build_planes(torch.tensor(arr[None]), torch.tensor([castle], dtype=torch.uint8),
                            torch.tensor([ep], dtype=torch.uint8), torch.tensor([ratings], dtype=torch.float32),
                            torch.tensor([platform], dtype=torch.uint8))[0]


def test_plane_shapes_and_piece_planes():
    p = planes_for(chess.Board())
    assert p.shape == (20, 8, 8)
    assert p[0].sum() == 8 and p[0][1].sum() == 8       # mover's pawns on rank index 1
    assert p[6].sum() == 8 and p[6][6].sum() == 8       # opponent's pawns on rank index 6
    assert p[5][0][4] == 1 and p[11][7][4] == 1          # kings on e1 / e8
    assert p[:12].sum() == 32


def test_constant_planes_carry_rating_platform_and_castling():
    p = planes_for(chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w Kq - 0 1"), ratings=(2200, 1200), platform=1)
    assert p[12].min() == p[12].max() == 1 and p[13].max() == 0 and p[14].max() == 0 and p[15].min() == 1
    assert p[17].mean() == pytest.approx(1.0) and p[18].mean() == pytest.approx(-1.0) and p[19].min() == 1
    p0 = planes_for(chess.Board(), ratings=(1700, 1700), platform=0)
    assert p0[17].abs().max() == 0 and p0[19].max() == 0


def test_en_passant_plane_has_a_single_marked_square():
    b = chess.Board("rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3")
    p = planes_for(b)
    assert p[16].sum() == 1 and p[16][5][5] == 1
    assert planes_for(chess.Board())[16].sum() == 0


def test_batch_building_matches_single_building():
    boards = random_boards(20, 9)
    parts = [enc.canonical_state(b) for b in boards]
    batch = enc.build_planes(torch.tensor(np.stack([a for a, _, _ in parts])),
                             torch.tensor([c for _, c, _ in parts], dtype=torch.uint8),
                             torch.tensor([e for _, _, e in parts], dtype=torch.uint8),
                             torch.tensor([[1500, 1600]] * 20, dtype=torch.float32), torch.zeros(20, dtype=torch.uint8))
    for i, b in enumerate(boards):
        assert torch.equal(batch[i], planes_for(b, (1500, 1600)))


def test_normalise_rating():
    assert enc.normalise_rating(1700) == 0 and enc.normalise_rating(2200) == pytest.approx(1.0)
