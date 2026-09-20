"""Compare our model with public human-move models (Maia-3, Maia-2) on identical positions.

Every scorer is given the same items and returns a probability for each *legal* move; the metrics are computed in
one place, so no model gets a different masking or averaging rule. The Maia code and weights are loaded from
separate checkouts / files that the caller provides (they are AGPL / research releases: never copied into this
project, only imported at run time).
"""
import contextlib
import sys
from collections import deque
from dataclasses import dataclass

import chess
import numpy as np
import torch

from . import encoding as enc

GROUPS = ("all", "early (10-19)", "middle (20-39)", "late (40+)", "endgame (<=6 pieces)")


@dataclass(frozen=True)
class EvalItem:
    fen: str  # the position before the move
    played: str  # the move actually played, UCI
    mover_elo: int
    opp_elo: int
    platform: int = 0
    ply: int = 0
    moves: tuple = ()  # UCI moves from the standard start position that lead to `fen` (empty = unknown)

    @property
    def has_history(self):
        return len(self.moves) == self.ply and self.ply > 0


def heavy_pieces(fen):
    """Number of knights, bishops, rooks and queens on the board (both colours)."""
    return sum(fen.split()[0].count(c) for c in "NBRQnbrq")


# ---- building items -----------------------------------------------------------------------------------------------

def items_from_shard(data, limit=None, seed=1):
    """Items from a val / test shard (needs FENs). No history is available."""
    if "fen" not in data:
        raise ValueError("needs a shard with FENs (val/test shards have them)")
    n = len(data["move"])
    idx = np.arange(n) if not limit or limit >= n else np.sort(np.random.default_rng(seed).permutation(n)[:limit])
    out = []
    for i in idx:
        fen = str(data["fen"][i])
        move = enc.index_to_move(int(data["move"][i]), chess.Board(fen))
        if move is None:
            continue
        out.append(EvalItem(fen, move.uci(), int(data["ratings"][i][0]), int(data["ratings"][i][1]),
                            int(data["platform"][i]), int(data["ply"][i])))
    return out


def items_from_games(rows, weighter, min_ply=8):
    """Items from normalised game rows: the player's own moves (same selection rule as the training shards), each
    with the full move history so history-using models can be given it."""
    out = []
    for row in rows:
        if weighter.game_weight(row) <= 0 or row.get("result") not in ("1-0", "0-1", "1/2-1/2"):
            continue
        if row.get("my_rating") is None or row.get("opp_rating") is None:
            continue
        mine_white = row["color"] == "white"
        board, played = chess.Board(), []
        try:
            for ply, san in enumerate(row["moves"].split()):
                move = board.parse_san(san)
                if ply >= min_ply and (board.turn == chess.WHITE) == mine_white and board.legal_moves.count() >= 2 \
                        and weighter.move_weight(row, ply) > 0:
                    out.append(EvalItem(board.fen(), move.uci(), int(row["my_rating"]), int(row["opp_rating"]),
                                        enc.PLATFORM_ID[row["platform"]], ply, tuple(played)))
                board.push(move)
                played.append(move.uci())
        except ValueError:
            continue
    return out


# ---- scorers ------------------------------------------------------------------------------------------------------

class Scorer:
    name = "scorer"

    def probs(self, items):
        """One {legal move uci: probability} dict per item (probabilities over the legal moves sum to 1)."""
        raise NotImplementedError


def _softmax(scores):
    s = np.asarray(scores, dtype=np.float64)
    e = np.exp(s - s.max())
    return e / e.sum()


class OursScorer(Scorer):
    def __init__(self, checkpoint, name=None, device="cpu", batch_size=256):
        from .net import load_checkpoint

        self.model, _ = load_checkpoint(checkpoint, device)
        self.model.eval()
        self.device, self.batch_size, self.name = device, batch_size, name or str(checkpoint)

    @torch.no_grad()
    def probs(self, items):
        out = []
        for start in range(0, len(items), self.batch_size):
            chunk = items[start:start + self.batch_size]
            boards = [chess.Board(it.fen) for it in chunk]
            states = [enc.canonical_state(b) for b in boards]
            planes = enc.build_planes(
                torch.from_numpy(np.stack([s[0] for s in states])),
                torch.tensor([s[1] for s in states], dtype=torch.uint8),
                torch.tensor([s[2] for s in states], dtype=torch.uint8),
                torch.tensor([[it.mover_elo, it.opp_elo] for it in chunk], dtype=torch.float32),
                torch.tensor([it.platform for it in chunk], dtype=torch.uint8)).to(self.device)
            logits = self.model(planes)[0].cpu().numpy()
            for b, row in zip(boards, logits):
                moves = list(b.legal_moves)
                p = _softmax([row[enc.move_index(m, b)] for m in moves])
                out.append({m.uci(): float(x) for m, x in zip(moves, p)})
        return out


@contextlib.contextmanager
def _on_path(*paths):
    added = [str(p) for p in paths if str(p) not in sys.path]
    sys.path[:0] = added
    try:
        yield
    finally:
        for p in added:
            if p in sys.path:
                sys.path.remove(p)


class Maia3Scorer(Scorer):
    """Maia-3 (Chessformer), loaded from a local checkout of github.com/CSSLab/maia3 and a downloaded checkpoint.

    use_history=False reproduces the engine's default (the current position only); use_history=True feeds the
    last 8 positions, as the model was designed to receive them, whenever the item carries its move history.
    """

    def __init__(self, repo, checkpoint, model="5m", use_history=False, name=None, device="cpu", batch_size=64,
                 extra_paths=()):
        with _on_path(repo, *extra_paths):
            from maia3 import dataset as md
            from maia3 import uci as mu
            from maia3 import utils as mut
        self._md, self._mut = md, mut
        self.cfg = mu.parse_args(["--model", model, "--checkpoint-path", str(checkpoint), "--device", device,
                                  "--temperature", "0"])
        self.model = mu.load_model(self.cfg)
        self.all_moves = mut.get_all_possible_moves()
        self.moves_dict = {m: i for i, m in enumerate(self.all_moves)}
        self.use_history, self.device, self.batch_size = use_history, device, batch_size
        self.name = name or f"Maia-3 {model}" + (" +history" if use_history else "")

    def _tokens(self, item, board):
        md = self._md
        if self.use_history and item.has_history:
            replay, hist = chess.Board(), deque(maxlen=self.cfg.history)
            hist.append(md.tokenize_board(replay))
            for uci in item.moves:
                replay.push_uci(uci)
                hist.append(md.tokenize_board(replay))
            assert replay.fen().split()[:4] == board.fen().split()[:4], "history does not lead to the position"
        else:
            hist = deque([md.tokenize_board(board)], maxlen=self.cfg.history)
        return md.get_historical_tokens(hist, self.cfg, base=0.0, inc=0.0, clk_left_before=0.0, clk_ponder=0.0)

    @torch.no_grad()
    def probs(self, items):
        out = []
        for start in range(0, len(items), self.batch_size):
            chunk = items[start:start + self.batch_size]
            boards = [chess.Board(it.fen) for it in chunk]
            tokens = torch.stack([self._tokens(it, b) for it, b in zip(chunk, boards)]).to(self.device)
            me = torch.tensor([it.mover_elo for it in chunk], dtype=torch.long, device=self.device)
            opp = torch.tensor([it.opp_elo for it in chunk], dtype=torch.long, device=self.device)
            logits = self.model(tokens, me, opp)[0].float().cpu().numpy()
            for b, row in zip(boards, logits):
                moves = list(b.legal_moves)
                scores = []
                for m in moves:
                    uci = m.uci() if b.turn == chess.WHITE else self._mut.mirror_move(m.uci())
                    scores.append(row[self.moves_dict[uci]])
                p = _softmax(scores)
                out.append({m.uci(): float(x) for m, x in zip(moves, p)})
        return out


class Maia2Scorer(Scorer):
    """Maia-2 (blitz or rapid checkpoint), from a local checkout of github.com/CSSLab/maia2."""

    def __init__(self, repo, checkpoint, name=None, device="cpu", batch_size=64, extra_paths=()):
        with _on_path(repo, *extra_paths):
            from importlib.resources import as_file, files

            from maia2 import inference as inf
            from maia2 import utils as mu
            from maia2.main import MAIA2Model
            from maia2.train import load_model_state_dict
            with as_file(files("maia2.configs").joinpath("maia2-training.yaml")) as cfg_path:
                cfg = mu.parse_args(cfg_path)
        self._inf, self._mu = inf, mu
        self.all_moves = mu.get_all_possible_moves()
        self.moves_dict = {m: i for i, m in enumerate(self.all_moves)}
        self.elo_dict = mu.create_elo_dict()
        model = MAIA2Model(len(self.all_moves), self.elo_dict, cfg)
        ck = torch.load(str(checkpoint), map_location="cpu", weights_only=True)
        load_model_state_dict(model, ck["model_state_dict"])
        del ck
        self.model = model.to(device).eval()
        self.device, self.batch_size = device, batch_size
        self.name = name or "Maia-2"

    @torch.no_grad()
    def probs(self, items):
        out = []
        for start in range(0, len(items), self.batch_size):
            chunk = items[start:start + self.batch_size]
            prep = [self._inf.preprocessing(it.fen, it.mover_elo, it.opp_elo, self.elo_dict, self.moves_dict) for it in chunk]
            boards = torch.stack([p[0] for p in prep]).to(self.device)
            me = torch.tensor([p[1] for p in prep]).to(self.device)
            opp = torch.tensor([p[2] for p in prep]).to(self.device)
            logits = self.model(boards, me, opp)[0].float().cpu().numpy()
            for it, row in zip(chunk, logits):
                b = chess.Board(it.fen)
                moves = list(b.legal_moves)
                scores = []
                for m in moves:
                    uci = m.uci() if b.turn == chess.WHITE else self._mu.mirror_move(m.uci())
                    scores.append(row[self.moves_dict[uci]])
                p = _softmax(scores)
                out.append({m.uci(): float(x) for m, x in zip(moves, p)})
        return out


# ---- metrics ------------------------------------------------------------------------------------------------------

def evaluate_scorer(scorer, items, chunk=512, progress=None):
    """Legal-masked accuracy of `scorer` on `items`: overall and by phase (same groups as train.evaluate)."""
    rows = []  # (top1, top3, prob, nll, uniform, ply, heavy)
    for start in range(0, len(items), chunk):
        part = items[start:start + chunk]
        for it, probs in zip(part, scorer.probs(part)):
            ranked = sorted(probs, key=probs.get, reverse=True)
            p = probs.get(it.played)
            if p is None:
                raise ValueError(f"played move {it.played} is not legal in {it.fen}")
            rows.append((ranked[0] == it.played, it.played in ranked[:3], p, -np.log(max(p, 1e-12)), 1.0 / len(probs),
                         it.ply, heavy_pieces(it.fen)))
        if progress:
            progress(min(start + chunk, len(items)), len(items))
    a = np.array(rows, dtype=np.float64)
    ply, heavy = a[:, 5], a[:, 6]
    sel = {"all": np.ones(len(a), bool), "early (10-19)": ply < 20, "middle (20-39)": (ply >= 20) & (ply < 40),
           "late (40+)": ply >= 40, "endgame (<=6 pieces)": heavy <= 6}
    out = {}
    for name in GROUPS:
        s = sel[name]
        if s.sum():
            n = int(s.sum())
            t1 = float(a[s, 0].mean())
            out[name] = {"n": n, "top1": t1, "top3": float(a[s, 1].mean()), "prob": float(a[s, 2].mean()),
                         "nll": float(a[s, 3].mean()), "uniform_top1": float(a[s, 4].mean()),
                         "top1_ci95": float(1.96 * np.sqrt(t1 * (1 - t1) / n))}
    return out


def format_comparison(results, title=""):
    """Markdown table: one row per model, columns for the overall numbers and each phase's top-1."""
    lines = [title] if title else []
    lines += ["| model | top-1 (95% CI) | top-3 | NLL | early | middle | late | endgame |", "|---|---|---|---|---|---|---|---|"]
    for name, r in results.items():
        a = r["all"]
        g = lambda k: f"{100 * r[k]['top1']:.1f}%" if k in r else "-"
        lines.append(f"| {name} | {100 * a['top1']:.1f}% +/- {100 * a['top1_ci95']:.1f} | {100 * a['top3']:.1f}% | "
                     f"{a['nll']:.3f} | {g('early (10-19)')} | {g('middle (20-39)')} | {g('late (40+)')} | {g('endgame (<=6 pieces)')} |")
    n = next(iter(results.values()))["all"]
    lines.append(f"\n{n['n']} positions; random legal move: {100 * n['uniform_top1']:.1f}% top-1. "
                 "The CI treats positions as independent, so it understates uncertainty (moves within a game are correlated).")
    return "\n".join(lines)
