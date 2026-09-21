"""Does the bot choose like the player? Two held-out checks, both on games the bot was not built from.

  books   the player's moves in the opening of held-out games (the newest games; the personal book is built from the older ones only): how many
          are in the personal book, in the theory book of the player's rating, or in both stacked, and what probability the book gives the move
          that was played (a sampled book move equals the player's move with that probability)
  moves   positions from held-out games: the controller is run as it plays (search candidates at the dial of the position's rating, a prior that
          weighs them) and asked what probability it gives the move that was played. The search is done once per position and shared by all
          priors, so the priors are compared on exactly the same candidates. With the uniform prior the most likely move is the engine's best
          one, which is the baseline every "plays like me" claim has to beat.

The probabilities are those of the choice rule (`Choice.candidates`); the small blunder-rate branch of the weak dial settings is not included."""
import chess

from .controller import BookStack, MeChess


def book_agreement(books, rows, *, max_ply=20, min_rating=0):
    """{name: {moves, coverage, top1, sampled, sampled_when_in_book}} for each book in `books` ({name: object with .moves(board, elo)}) over the
    player's moves in the first `max_ply` plies of `rows` (normalised games; only Lichess-scale games, since the theory books are on that scale)."""
    tot = {n: [0, 0, 0, 0.0] for n in books}            # moves, in book, top-1, probability given to the played move
    games = 0
    for row in rows:
        if row.get("platform") != "lichess" or not row.get("usable") or (row.get("my_rating") or 0) < min_rating:
            continue
        games += 1
        white = row["color"] == "white"
        elo = row.get("my_rating") or 1500
        board = chess.Board()
        for san in row["moves"].split()[:max_ply]:
            try:
                move = board.parse_san(san)
            except ValueError:
                break
            if (board.turn == chess.WHITE) == white:
                for name, book in books.items():
                    t = tot[name]
                    t[0] += 1
                    options = book.moves(board, elo)
                    if options:
                        z = sum(w for _, w in options)
                        t[1] += 1
                        t[2] += max(options, key=lambda o: o[1])[0] == move
                        t[3] += sum(w for m, w in options if m == move) / z
            board.push(move)
    out = {"games": games}
    for n, (moves, inb, top1, prob) in tot.items():
        out[n] = {"moves": moves, "coverage": inb / moves if moves else 0.0, "top1": top1 / inb if inb else 0.0,
                  "sampled": prob / moves if moves else 0.0, "sampled_when_in_book": prob / inb if inb else 0.0}
    return out


class SharedSearch:
    """Wraps an engine so that the same search is answered from memory the second time: the priors under test see identical candidates."""

    def __init__(self, engine):
        self.engine, self.cache, self.multipv = engine, {}, None

    def _send(self, cmd):
        if cmd.startswith("setoption name MultiPV value"):
            self.multipv = int(cmd.rsplit(" ", 1)[1])
        self.engine._send(cmd)

    def ready(self):
        self.engine.ready()

    def go(self, fen, moves=(), **kw):
        key = (fen, tuple(moves), self.multipv, kw.get("nodes"), kw.get("depth"))
        if key not in self.cache:
            self.cache[key] = self.engine.go(fen, moves, **kw)
        return self.cache[key]


def move_agreement(positions, engine, priors, *, table=None, calibration=None, seed=0):
    """{prior name: {positions, in_candidates, top1, expected_match}} over `positions` (objects with .fen, .played, .rating). `expected_match` is the
    average probability given to the played move (0 when it was not among the candidates); `top1` how often the most likely candidate was played."""
    shared = SharedSearch(engine)
    out = {}
    for name, prior in priors.items():
        mc = MeChess(shared, prior, None, table=table, seed=seed, calibration=calibration)
        n = inc = top1 = 0
        mass = loss = 0.0
        for p in positions:
            board = chess.Board(p.fen)
            played = chess.Move.from_uci(p.played)
            if played not in board.legal_moves:
                continue
            choice = mc.choose(board, int(p.rating))
            n += 1
            hit = [c for c in choice.candidates if c.move == played]
            inc += bool(hit)
            mass += hit[0].prob if hit else 0.0
            if choice.candidates:
                top1 += max(choice.candidates, key=lambda c: c.prob).move == played
                loss += sum(c.prob * c.loss for c in choice.candidates)
        out[name] = {"positions": n, "in_candidates": inc / n if n else 0.0, "top1": top1 / n if n else 0.0, "expected_match": mass / n if n else 0.0,
                     "expected_loss_cp": loss / n if n else 0.0}
    return out


def render(book, move):
    lines = ["# Does the bot choose like the player? (held-out games)", ""]
    if book:
        lines += [f"## Opening books ({book['games']} newest games, the player's first moves; the personal book was built from the older games)", "",
                  "| Book | moves | in the book | top-1 when in book | probability of the played move, over all moves | ... when in book |", "|---|---|---|---|---|---|"]
        for n, s in book.items():
            if n == "games":
                continue
            lines.append(f"| {n} | {s['moves']} | {100 * s['coverage']:.0f}% | {100 * s['top1']:.0f}% | {100 * s['sampled']:.1f}% | {100 * s['sampled_when_in_book']:.0f}% |")
        lines.append("")
    if move:
        lines += ["## Move choice by search and prior (positions from held-out games; candidates from the engine at the dial of the player's rating)", "",
                  "| Prior | positions | played move among the candidates | most likely candidate is the played move | probability of the played move |", "|---|---|---|---|---|"]
        for n, s in move.items():
            lines.append(f"| {n} | {s['positions']} | {100 * s['in_candidates']:.0f}% | {100 * s['top1']:.1f}% | {100 * s['expected_match']:.1f}% |")
        lines += ["", "With the uniform prior the most likely candidate is the engine's best move: that row is the baseline. A style prior only counts as 'plays like me' where it beats it."]
    return "\n".join(lines) + "\n"


# ---- clock -----------------------------------------------------------------------------------------------------------

def _ks(a, b):
    """Kolmogorov-Smirnov distance between two samples (0 = the same distribution, 1 = disjoint)."""
    import numpy as np
    a, b = np.sort(a), np.sort(b)
    xs = np.concatenate([a, b])
    return float(np.max(np.abs(np.searchsorted(a, xs, side="right") / len(a) - np.searchsorted(b, xs, side="right") / len(b))))


def clock_agreement(model, rows, *, instant=1.0, seed=0, max_moves=40000):
    """How the clock model's waiting compares with the player's real thinking on held-out games. For every move of the player, the model draws
    a delay from the real state (time left, stage, simple move); the two sets of seconds are compared per time class: medians, and the KS distance
    (0 = the same distribution) against a bot that always answers in `instant` seconds, which is what the bot did without the model."""
    import chess
    import numpy as np

    from .clock import simple, think_times, time_class
    rng = np.random.default_rng(seed)
    real, sim = {}, {}
    n = 0
    for row in rows:
        if row.get("platform") != "lichess" or not row.get("usable") or not row.get("moves"):
            continue
        by_ply, board = {}, chess.Board()
        try:
            for i, san in enumerate(row["moves"].split()):
                by_ply[i] = simple(board)
                board.push_san(san)
        except ValueError:
            pass
        for ply, prev, think, base, inc in think_times(row):
            if ply not in by_ply or n >= max_moves:
                continue
            tc = time_class(base, inc)
            f = model.fraction(tc, ply, by_ply[ply], rng)
            d = max(0.0, min(f * prev, 0.25 * max(prev - 1.0, 0.0)))
            real.setdefault(tc, []).append(think)
            sim.setdefault(tc, []).append(float(round(d)))                       # the recorded clocks are whole seconds
            n += 1
    out = {}
    for tc in real:
        if len(real[tc]) < 200:
            continue
        r, s_ = np.array(real[tc]), np.array(sim[tc])
        out[tc] = {"moves": len(r), "real_median": float(np.median(r)), "model_median": float(np.median(s_)),
                   "real_mean": float(r.mean()), "model_mean": float(s_.mean()), "ks_model": _ks(r, s_), "ks_instant": _ks(r, np.full(len(r), float(round(instant))))}
    return out


def render_clock(res):
    lines = ["| Time control | your moves | thinking per move: yours (median / mean) | model (median / mean) | distance to yours: model / answering at once |", "|---|---|---|---|---|"]
    for tc, s in sorted(res.items()):
        lines.append(f"| {tc} | {s['moves']} | {s['real_median']:.1f}s / {s['real_mean']:.1f}s | {s['model_median']:.1f}s / {s['model_mean']:.1f}s | "
                     f"{s['ks_model']:.2f} / {s['ks_instant']:.2f} |")
    lines.append("\nDistance is the Kolmogorov-Smirnov statistic between the two sets of think times (0 = identical); lower is better. Lichess clocks are whole seconds, so "
                 "many short thoughts are recorded as 0.")
    return "\n".join(lines)


def sweep(positions, engine, priors, variants, *, table, calibration=None):
    """[(window scale, extra lines, results)] for each variant of the dial table: how much of the player's play the candidates reach and match, and
    what it costs in expected centipawn loss (a cheap proxy for strength; measure the real Elo with a calibration before adopting a variant)."""
    from .dial import widen
    return [(w, k, move_agreement(positions, engine, priors, table=widen(table, w, k), calibration=calibration)) for w, k in variants]


def render_sweep(rows):
    lines = ["## Wider candidate windows", "",
             "| window x | extra lines | prior | played move among candidates | probability of the played move | expected loss per move (cp) |", "|---|---|---|---|---|---|"]
    for w, k, res in rows:
        for name, s in res.items():
            lines.append(f"| {w:g} | +{k} | {name} | {100 * s['in_candidates']:.0f}% | {100 * s['expected_match']:.1f}% | {s['expected_loss_cp']:.0f} |")
    return "\n".join(lines) + "\n"
