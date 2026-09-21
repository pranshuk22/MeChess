"""Priors: models that say which legal moves the player would choose. Each is a callable
`prior(board, elo, opp_elo, platform) -> {legal move: probability}`."""
import chess


class UniformPrior:
    """No opinion: every legal move equally likely (the candidate window and search then decide everything)."""

    def __call__(self, board, elo, opp_elo, platform):
        n = board.legal_moves.count()
        return {m: 1.0 / n for m in board.legal_moves}


class OursPrior:
    """Our own me-network (track B). Sees the current position and both ratings."""

    def __init__(self, checkpoint, device="cpu"):
        from ..model.net import load_checkpoint

        self.model, _ = load_checkpoint(checkpoint, device)
        self.device = device

    def __call__(self, board, elo, opp_elo, platform):
        from ..model.infer import move_probabilities

        return move_probabilities(self.model, board, elo, opp_elo, platform, self.device)


class Maia3Prior:
    """Maia-3, optionally personalised (track A). Loaded from a separate checkout (AGPL, never bundled)."""

    def __init__(self, repo, checkpoint, size="5m", use_history=True, extra_paths=(), device="cpu"):
        from ..model.compare import Maia3Scorer

        self.scorer = Maia3Scorer(repo, checkpoint, size, use_history=use_history, device=device, extra_paths=extra_paths)

    def __call__(self, board, elo, opp_elo, platform):
        from ..model.compare import EvalItem

        moves = tuple(m.uci() for m in board.move_stack)
        item = EvalItem(board.fen(), "", int(elo), int(opp_elo), platform, len(moves), moves if board.root() == chess.Board() else ())
        return {chess.Move.from_uci(u): p for u, p in self.scorer.probs([item])[0].items()}


class StylePrior:
    """Your move-choice taste (the fitted style model, see chessme.style.model): among legal moves, a move is the more likely the more it has
    what you seek (forcing moves, trades, king attacks, pawn breaks ...) and the less it has what you avoid. The strength of play is the
    controller's job (the search window and the dial), so the model's own strength term is not used here. `strength` scales the weights."""

    def __init__(self, path, strength=1.0):
        from ..style.model import load_model
        self.model, self.strength = load_model(path), float(strength)

    def __call__(self, board, elo, opp_elo, platform):
        import numpy as np

        from ..style.features import feature_vector
        moves = list(board.legal_moves)
        z = (np.array([feature_vector(board, m) for m in moves], dtype=float) - self.model.mean) / self.model.std
        s = self.strength * (z @ self.model.w)
        p = np.exp(s - s.max())
        p /= p.sum()
        return dict(zip(moves, p.tolist()))
