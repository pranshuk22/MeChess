"""Position and move encoding for the "me" model. This file is the SPECIFICATION the C++ inference must match.

Everything is expressed from the point of view of the side to move ("canonical" view): when Black is to move the
board is mirrored vertically (square s -> s ^ 56) and the colours are swapped, so the network only ever sees a
position in which the mover plays up the board. Castling is a king move (e1g1 / e1c1 in the canonical view).

Board array (64 x uint8), square = rank * 8 + file, canonical view:
    0 empty; 1..6 = mover's pawn, knight, bishop, rook, queen, king; 7..12 = the opponent's, same order.
Castle bits (uint8): 1 mover king-side, 2 mover queen-side, 4 opponent king-side, 8 opponent queen-side.
En passant: canonical target square 0..63, or 255. It is set ONLY when a pawn of the mover attacks that square
(a pseudo-legal en-passant capture exists), so it does not depend on whether a FEN records the square.

Input planes (20 x 8 x 8, plane[c][rank][file]):
    0-5   mover's P N B R Q K            6-11  opponent's P N B R Q K
    12-15 castling rights (constant 0/1 planes): mover K-side, mover Q-side, opponent K-side, opponent Q-side
    16    en-passant target square (a single 1)
    17    mover's rating   (rating - 1700) / 500, constant plane
    18    opponent's rating, same scaling
    19    rating scale: 0 = Lichess, 1 = chess.com, constant plane

Policy (4168 logits), in canonical squares:
    from * 64 + to                                             for every move except under-promotions
    4096 + kind * 24 + from_file * 3 + (to_file - from_file + 1)   for under-promotions, kind: N=0, B=1, R=2
(queen promotions use the ordinary from*64+to slot).
"""
import chess
import numpy as np

N_PLANES = 20
POLICY_SIZE = 4096 + 3 * 24
UNDERPROMO_KIND = {chess.KNIGHT: 0, chess.BISHOP: 1, chess.ROOK: 2}
RATING_CENTER, RATING_SCALE = 1700.0, 500.0
PLATFORM_ID = {"lichess": 0, "chesscom": 1}
NO_EP = 255


def canonical_state(board):
    """(board64 uint8[64], castle bits, ep square) in the mover's point of view."""
    white = board.turn == chess.WHITE
    arr = np.zeros(64, np.uint8)
    for sq, piece in board.piece_map().items():
        arr[sq if white else sq ^ 56] = piece.piece_type + (0 if piece.color == board.turn else 6)
    us, them = board.turn, not board.turn
    castle = (int(board.has_kingside_castling_rights(us)) | int(board.has_queenside_castling_rights(us)) << 1
              | int(board.has_kingside_castling_rights(them)) << 2 | int(board.has_queenside_castling_rights(them)) << 3)
    ep = NO_EP
    if board.ep_square is not None and board.has_pseudo_legal_en_passant():
        ep = board.ep_square if white else board.ep_square ^ 56
    return arr, castle, ep


def move_index(move, board):
    """Policy slot of `move` for the side to move on `board`."""
    f, t = move.from_square, move.to_square
    if board.turn == chess.BLACK:
        f, t = f ^ 56, t ^ 56
    kind = UNDERPROMO_KIND.get(move.promotion)
    if kind is not None:
        return 4096 + kind * 24 + (f & 7) * 3 + ((t & 7) - (f & 7) + 1)
    return f * 64 + t


def legal_indices(board):
    """Policy slots of all legal moves (all distinct)."""
    return [move_index(m, board) for m in board.legal_moves]


def index_to_move(idx, board):
    """The legal move with policy slot `idx`, or None."""
    for m in board.legal_moves:
        if move_index(m, board) == idx:
            return m
    return None


def normalise_rating(r):
    return (np.asarray(r, np.float32) - RATING_CENTER) / RATING_SCALE


def build_planes(board64, castle, ep, ratings, platform):
    """Vectorised planes for a batch of torch tensors -> float tensor [B, 20, 8, 8].

    board64 [B,64] uint8, castle [B] uint8, ep [B] uint8, ratings [B,2] (mover, opponent; raw Elo), platform [B] uint8.
    """
    import torch
    import torch.nn.functional as F

    B = board64.shape[0]
    dev = board64.device
    x = torch.zeros(B, N_PLANES, 64, device=dev)
    onehot = F.one_hot(board64.long(), 13)[..., 1:].to(x.dtype)  # [B,64,12]
    x[:, :12, :] = onehot.permute(0, 2, 1)
    c = castle.long()
    for bit in range(4):
        x[:, 12 + bit, :] = ((c >> bit) & 1).to(x.dtype).unsqueeze(1)
    has_ep = ep.long() < 64
    if has_ep.any():
        rows = torch.nonzero(has_ep).squeeze(1)
        x[rows, 16, ep.long()[rows]] = 1.0
    r = (ratings.to(x.dtype) - RATING_CENTER) / RATING_SCALE
    x[:, 17, :] = r[:, 0:1]
    x[:, 18, :] = r[:, 1:2]
    x[:, 19, :] = platform.to(x.dtype).unsqueeze(1)
    return x.view(B, N_PLANES, 8, 8)


def normalise_ep(board, ep):
    """Apply the en-passant rule to stored arrays (vectorised): keep `ep` only where a mover pawn attacks it.

    `board` [N,64] canonical piece codes, `ep` [N]. Used to fix shards built before the rule was pinned down.
    In the canonical view the target is on rank index 5 and the capturing pawn (code 1) stands on rank index 4,
    one file to the side (squares 32 + file -/+ 1).
    """
    ep = ep.copy()
    has = ep < 64
    file = (ep & 7).astype(np.int64)
    idx = np.arange(len(ep))
    left = np.where(file > 0, board[idx, 32 + np.clip(file - 1, 0, 7)] == 1, False)
    right = np.where(file < 7, board[idx, 32 + np.clip(file + 1, 0, 7)] == 1, False)
    ep[has & ~(left | right)] = NO_EP
    return ep
