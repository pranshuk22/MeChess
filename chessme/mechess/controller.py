"""MeChess move selection: opening book -> engine-approved candidate moves -> a prior picks among them.

    1. Book: while inside the book (and inside the dial's book depth) play the books in priority order (my own repertoire, then theory for the
       level), sampled by their frequencies.
    2. Candidates: the alpha-beta engine (MultiPV) returns its best lines; keep those within the dial's window of the best.
    3. Prior: a policy model (mine, or a personalised Maia-3) says which of them I would play.
    4. Choice: sample with weight  prior^(1/T) * exp(-loss / cp_scale)  (loss = centipawns below the best candidate).
"""
import math
import random
from dataclasses import dataclass, field

import chess

from ..book.format import read_book
from ..book.keys import book_key
from .dial import settings_for

MATE_CP = 90000  # engine scores beyond this are forced mates
LOSS_CAP = 1000


class BookReader:
    """Reads a chessme opening book (book.bin) and samples moves from it."""

    def __init__(self, path):
        self.by_key = {}
        for e in read_book(path):
            self.by_key.setdefault(e.key, []).append(e)

    def moves(self, board, elo=None):
        """[(legal move, weight)] the book has for `board` (`elo` is accepted so every book has the same call; a single book ignores it)."""
        out = []
        for e in self.by_key.get(book_key(board), []):
            move = chess.Move(e.from_sq, e.to_sq, e.promo or None)
            if move in board.legal_moves:
                out.append((move, e.weight))
        return out


class TheoryBands:
    """A folder of theory books `theory_LO_HI.bin` (one per rating band): the band that holds the Elo being played is used, and loaded once."""

    def __init__(self, directory):
        from ..book.theory import pick_book
        self.directory, self._pick, self._readers = directory, pick_book, {}

    def moves(self, board, elo=None):
        path = self._pick(self.directory, elo or 1500)
        if path is None:
            return []
        if path not in self._readers:
            self._readers = {path: BookReader(path)}     # keep one band in memory: a game is played at one Elo
        return self._readers[path].moves(board)


class BookStack:
    """Several books in priority order: the first one that knows the position decides (your own repertoire, then theory for the level)."""

    def __init__(self, books):
        self.books = list(books)

    def moves(self, board, elo=None):
        for b in self.books:
            options = b.moves(board, elo)
            if options:
                return options
        return []


def load_books(spec):
    """A book from `spec`: paths separated by commas, in priority order; a folder means a set of rating-band theory books."""
    from pathlib import Path
    books = []
    for part in (x.strip() for x in str(spec).split(",")):
        if not part:
            continue
        if not Path(part).exists():
            raise FileNotFoundError(f"book not found: {part}")
        books.append(TheoryBands(part) if Path(part).is_dir() else BookReader(part))
    if not books:
        return None
    return books[0] if len(books) == 1 else BookStack(books)


@dataclass
class Candidate:
    move: chess.Move
    cp: int
    loss: int = 0
    prior: float = 0.0
    weight: float = 0.0
    prob: float = 0.0


@dataclass
class Choice:
    move: chess.Move
    source: str  # "book" | "search" | "blunder"
    candidates: list = field(default_factory=list)


class MeChess:
    """`engine` is a started UciEngine with the MultiPV option available; `prior(board, elo, opp_elo, platform)`
    returns {legal move: probability}."""

    def __init__(self, engine, prior, book=None, table=None, seed=None, calibration=None):
        self.engine, self.prior, self.book, self.table = engine, prior, book, table
        self.calibration = calibration
        self.rng = random.Random(seed)
        self._multipv = None

    def _set_multipv(self, k):
        if k != self._multipv:
            self.engine._send(f"setoption name MultiPV value {k}")
            self.engine.ready()
            self._multipv = k

    def choose(self, board, elo, opp_elo=None, platform=0):
        settings = settings_for(elo, self.table, self.calibration)
        opp_elo = opp_elo or elo
        if board.legal_moves.count() == 0:
            raise ValueError("no legal moves")

        # 1. opening book
        if self.book is not None and len(board.move_stack) < settings.book_plies:
            options = self.book.moves(board, elo)
            if options:
                move = self._sample([m for m, _ in options], [w for _, w in options], settings.temperature)
                return Choice(move, "book", [Candidate(m, 0, prior=w) for m, w in options])

        # 2. engine candidates
        self._set_multipv(settings.multipv)
        root = board.root()
        res = self.engine.go(root.fen(), [m.uci() for m in board.move_stack], nodes=settings.nodes, depth=settings.depth or None)
        lines = [l for l in res.lines if chess.Move.from_uci(l.move) in board.legal_moves]
        if not lines:  # engine gave no usable analysis: fall back to its best move
            return Choice(chess.Move.from_uci(res.bestmove), "search", [])
        best = lines[0].cp
        if best >= MATE_CP:
            keep = [l for l in lines if l.cp >= MATE_CP]  # a forced mate: stay on mating moves
        else:
            keep = [l for l in lines if l.cp >= best - settings.window_cp and l.cp > -MATE_CP] or lines[:1]
        cands = [Candidate(chess.Move.from_uci(l.move), l.cp, loss=min(LOSS_CAP, max(0, best - l.cp))) for l in keep]
        if len(cands) == 1:
            cands[0].prob = 1.0
            return self._with_blunder(board, Choice(cands[0].move, "search", cands), settings)

        # 3. prior over the candidates
        probs = self.prior(board, elo, opp_elo, platform)
        raw = [max(probs.get(c.move, 0.0), 1e-6) for c in cands]
        total = sum(raw)
        for c, p in zip(cands, raw):
            c.prior = p / total

        # 4. choice
        weights = [self._weight(c, settings) for c in cands]
        z = sum(weights)
        for c, w in zip(cands, weights):
            c.weight, c.prob = w, (w / z if z > 0 else 1.0 / len(cands))
        if settings.temperature <= 0:
            move = max(cands, key=lambda c: c.weight).move
        else:
            move = self.rng.choices([c.move for c in cands], weights=[c.prob for c in cands])[0]
        return self._with_blunder(board, Choice(move, "search", cands), settings)

    def _with_blunder(self, board, choice, settings):
        """With probability `blunder_rate`, replace a search move by a random other legal move (a strength knob for the weak end)."""
        if settings.blunder_rate > 0 and self.rng.random() < settings.blunder_rate:
            others = [m for m in board.legal_moves if m != choice.move]
            if others:
                return Choice(self.rng.choice(others), "blunder", choice.candidates)
        return choice

    @staticmethod
    def _weight(c, settings):
        t = max(settings.temperature, 1e-3)
        return math.exp(math.log(c.prior) / t - c.loss / settings.cp_scale)

    def _sample(self, moves, weights, temperature):
        if temperature <= 0:
            return moves[max(range(len(moves)), key=lambda i: weights[i])]
        w = [x ** (1.0 / temperature) for x in weights]  # the book uses the same temperature knob
        return self.rng.choices(moves, weights=w)[0]
