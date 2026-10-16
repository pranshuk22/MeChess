"""A human move-choice model learned from the games in the player's own library, so that MeChess chooses like a person.

The analysed games hold, for every move, the engine's best lines in the position and the move a human really played (both sides: the player's and their opponents'). Among the moves the
engine finds sound, a person does not choose at random: they like captures and checks, they develop and castle, they avoid retreats and quiet pawn moves; and when they go wrong it is with
a move that looks natural. `chessme.style` models this choice with a conditional logit over move features (`style.features`). Fitted on all the moves of the library it is a *typical
player* of the pool the player meets ("population"); fitted on the player's own moves it is *you* ("me"). `mechess.priors.StylePrior` plugs either into the controller, which then picks among
the engine's candidates (and makes its slips) with these preferences instead of at random."""
import chess
import numpy as np

from ..style.candidates import Position
from ..style.features import FEATURE_NAMES, move_features

WINDOW_CP = 150               # candidates: engine lines within this many centipawns of the best
MIN_PLY = 10                  # the opening is the book's business
MAX_POSITIONS = 60_000
MIN_POSITIONS = 1_500
MIN_USABLE = 400              # decisions among good moves a model needs


def _mover_cp(cp_white: float, white_to_move: bool) -> float:
    return cp_white if white_to_move else -cp_white


def positions_from_game(moves, white_elo=None, black_elo=None, *, only=None, game=0):
    """`Position`s for the decisions of one stored game. `moves`: rows in the API's shape (uci, lines = the engine's lines before the move with cp for White). `only`: "white" or "black"
    to keep that side's moves only. Decisions without two or more candidate lines, and the first `MIN_PLY` half-moves, are skipped."""
    board = chess.Board()
    out = []
    for i, m in enumerate(moves):
        white = board.turn == chess.WHITE
        lines = m.get("lines") or []
        try:
            mv = chess.Move.from_uci(m["uci"])
        except ValueError:
            break
        if i >= MIN_PLY and len(lines) >= 2 and (only is None or (only == "white") == white):
            best = max(_mover_cp(l["cp"], white) for l in lines)
            kept = [l for l in lines if best - _mover_cp(l["cp"], white) <= WINDOW_CP]
            cands = [l["uci"] for l in kept if chess.Move.from_uci(l["uci"]) in board.legal_moves]
            if len(cands) >= 2:
                chosen = cands.index(m["uci"]) if m["uci"] in cands else -1
                feats = np.array([[move_features(board, chess.Move.from_uci(c))[n] for n in FEATURE_NAMES] for c in cands], dtype=np.float32)
                loss = np.array([min(1000.0, best - _mover_cp(next(l for l in kept if l["uci"] == c)["cp"], white)) for c in cands], dtype=np.float32)
                elo = white_elo if white else black_elo
                out.append(Position(board.fen(), m["uci"], int(elo or 1500), i, cands, feats, loss, chosen, float("nan"), 0, game))
        if mv not in board.legal_moves:
            break
        board.push(mv)
    return out


def fit_from_games(games, *, only_user=False, progress=None):
    """(model, report) from stored games: `games` yields (moves rows, white_elo, black_elo, user_colour). The report has the number of positions and how well the model predicts held-out choices
    against a uniform choice."""
    from ..style import model as SM
    positions = []
    for n, (moves, we, be, user) in enumerate(games):
        positions += positions_from_game(moves, we, be, only=user if only_user else None, game=n)
        if progress and n % 20 == 0:
            progress(n)
        if len(positions) >= MAX_POSITIONS:
            break
    usable = [p for p in positions if p.chosen >= 0]
    if len(usable) < MIN_POSITIONS:
        raise ValueError(f"only {len(usable):,} decisions among good moves were found: analyse more of your games (about {MIN_POSITIONS:,} are needed)")
    held = [p for p in positions if p.game % 10 == 0]
    train = [p for p in positions if p.game % 10 != 0]
    model = SM.fit(train)
    ev = SM.evaluate(model, held) if held else {"n": 0}
    top = [(n, round(w, 2)) for n, w in SM.profile(model, 6)]
    return model, {"positions": len(usable), "games": len({p.game for p in positions}), "held_out": ev, "top": top}


class Decision:
    """One human decision to search: the position, the move played, who played it (the shape `style.candidates.candidates_for` reads)."""

    def __init__(self, fen, played, mover_elo, ply, game, platform=0):
        self.fen, self.played, self.mover_elo, self.ply, self.game, self.platform = fen, played, mover_elo, ply, game, platform


def sample_decisions(games, n, *, only=None, seed=1):
    """About `n` decisions spread over `games` (an iterable of (uci moves, white_elo, black_elo, user_colour)): positions from move `MIN_PLY` on, chosen at random but evenly over the games.
    `only`: "user" keeps the player's own moves only."""
    import random
    rng = random.Random(seed)
    games = [g for g in games if len(g[0]) > MIN_PLY + 2]
    if not games:
        return []
    per = max(1, round(n / len(games)))
    out = []
    for gi, (ucis, we, be, user) in enumerate(games):
        board = chess.Board()
        boards = []
        for i, u in enumerate(ucis):
            try:
                mv = chess.Move.from_uci(u)
            except ValueError:
                break
            if i >= MIN_PLY and board.legal_moves.count() > 1 and (only != "user" or user is None or (user == "white") == (board.turn == chess.WHITE)):
                boards.append((board.fen(), u, we if board.turn == chess.WHITE else be, i))
            if mv not in board.legal_moves:
                break
            board.push(mv)
        for fen, u, elo, i in rng.sample(boards, min(per, len(boards))):
            out.append(Decision(fen, u, int(elo or 1500), i, gi))
    rng.shuffle(out)
    return out[: int(n * 1.2)]


def fit_from_decisions(engine, decisions, *, nodes=20_000, multipv=5, window=WINDOW_CP, progress=None, cancel=None, target=None):
    """(model, report): search every decision with `engine` (MultiPV, `nodes`) to get its candidates, then fit the style model; held-out games measure it against a uniform choice."""
    from ..style import candidates as SC
    from ..style import model as SM
    positions = []
    engine._send(f"setoption name MultiPV value {multipv}")
    engine.ready()
    for k, d in enumerate(decisions):
        if cancel:
            cancel()
        p = SC.candidates_for(engine, d, nodes=nodes, multipv=multipv, window=window)
        if p is not None:
            positions.append(p)
        if progress and k % 20 == 0:
            progress(k, len(decisions))
        if target and sum(1 for q in positions if q.chosen >= 0) >= target:
            break
    usable = [p for p in positions if p.chosen >= 0]
    if len(usable) < MIN_USABLE:
        raise ValueError(f"only {len(usable):,} decisions among good moves were found: import and use more games (a few hundred are needed)")
    held = [p for p in positions if p.game % 5 == 0]
    train = [p for p in positions if p.game % 5 != 0]
    model = SM.fit(train)
    ev = SM.evaluate(model, held) if held else {"n": 0}
    mistakes = sum(1 for p in positions if p.chosen < 0)
    return model, {"positions": len(usable), "outside": mistakes, "held_out": ev, "top": [(n, round(w, 2)) for n, w in SM.profile(model, 6)], "nodes": nodes, "window": window}
