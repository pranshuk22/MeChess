"""Use a trained network to score / choose moves for a python-chess board (reference implementation of inference)."""
import chess
import numpy as np
import torch

from . import encoding as enc


@torch.no_grad()
def move_probabilities(model, board, mover_rating, opp_rating=None, platform=0, device="cpu"):
    """{legal move: probability}, the network's policy restricted to legal moves and renormalised."""
    model.eval()
    arr, castle, ep = enc.canonical_state(board)
    ratings = torch.tensor([[mover_rating, opp_rating if opp_rating is not None else mover_rating]], dtype=torch.float32)
    x = enc.build_planes(torch.from_numpy(arr[None]), torch.tensor([castle], dtype=torch.uint8),
                         torch.tensor([ep], dtype=torch.uint8), ratings, torch.tensor([platform], dtype=torch.uint8)).to(device)
    logits = model(x)[0][0].cpu().numpy()
    moves = list(board.legal_moves)
    scores = np.array([logits[enc.move_index(m, board)] for m in moves], dtype=np.float64)
    p = np.exp(scores - scores.max())
    p /= p.sum()
    return dict(zip(moves, p))


def choose_move(model, board, mover_rating, opp_rating=None, platform=0, temperature=1.0, rng=None, device="cpu"):
    """Sample a move (temperature 0 = the most probable move)."""
    probs = move_probabilities(model, board, mover_rating, opp_rating, platform, device)
    moves, p = list(probs), np.array(list(probs.values()))
    if temperature <= 0:
        return moves[int(p.argmax())]
    p = p ** (1.0 / temperature)
    p /= p.sum()
    rng = rng or np.random.default_rng()
    return moves[int(rng.choice(len(moves), p=p))]
