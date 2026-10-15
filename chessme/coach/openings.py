"""Opening practice: drill your own repertoire against the replies players of your rating really play.

* `Repertoire.from_pgn`: your prepared moves from a PGN with variations (the mainline and every variation; the moves of the chosen colour are what you must know, the
  moves of the other colour are the replies you expect).
* `OpeningDrill`: you play your colour; the opponent answers with a reply drawn from the explorer's frequencies at your rating (only replies played in at least `min_share` of
  the games), so the lines you actually meet come up as often as they occur. Your move must be one of your prepared moves in that position; when the opponent plays something your
  repertoire does not answer, the drill stops and tells you how often that happens.
* `coverage`: walks the explorer's tree along your repertoire and reports how much of the opponent's play stays inside it, and the most common unanswered replies.

The explorer is passed in as `replies(fen) -> [(uci, share), ...]` (most played first), so this runs and is tested without the database; `explorer_replies` adapts the SQLite explorer."""
import random

import chess
import chess.pgn

DEFAULT_MIN_SHARE = 0.02


def key(board):
    """Position key that ignores the move counters (transpositions meet)."""
    return " ".join(board.fen().split(" ")[:4])


class Repertoire:
    def __init__(self, color):
        self.color = chess.WHITE if color == "white" else chess.BLACK
        self.mine = {}            # position key -> {uci: san} prepared moves of the player's colour
        self.expected = {}        # position key -> {uci} replies of the other colour that the repertoire answers

    @classmethod
    def from_pgn(cls, text, color):
        rep = cls(color)
        import io
        f = io.StringIO(text)
        while (game := chess.pgn.read_game(f)) is not None:
            rep._walk(game, game.board())
        return rep

    def _walk(self, node, board):
        for child in node.variations:
            k = key(board)
            if board.turn == self.color:
                self.mine.setdefault(k, {})[child.move.uci()] = board.san(child.move)
            else:
                self.expected.setdefault(k, set()).add(child.move.uci())
            b = board.copy(stack=False)
            b.push(child.move)
            self._walk(child, b)

    def prepared(self, board):
        return self.mine.get(key(board), {})

    @property
    def size(self):
        return sum(len(v) for v in self.mine.values())


def explorer_replies(db_path, rating):
    """`replies(fen)` from the SQLite explorer at `rating`."""
    from ..book import explorer as E

    def replies(fen):
        res = E.query_position(db_path, fen, rating=rating)
        return [(m["uci"], m["share"]) for m in res["moves"]]
    return replies


class OpeningDrill:
    def __init__(self, repertoire, replies, *, min_share=DEFAULT_MIN_SHARE, max_plies=24, seed=0):
        self.rep, self.replies, self.min_share, self.max_plies = repertoire, replies, min_share, max_plies
        self.rng = random.Random(seed)
        self.board = chess.Board()
        self.over, self.report = False, None
        self.line = []                     # SAN of the moves played so far
        self.mistakes = 0
        self._opponent_if_needed()

    def _sans(self, moves):
        b = self.board.copy(stack=False)
        out = []
        for m in moves:
            out.append(b.san(m))
            b.push(m)
        return out

    def view(self):
        return {"fen": self.board.fen(), "color": "white" if self.rep.color == chess.WHITE else "black", "over": self.over, "report": self.report, "line": self.line,
                "legal": [] if self.over else [m.uci() for m in self.board.legal_moves], "mistakes": self.mistakes}

    def _finish(self, reason, **extra):
        self.over, self.report = True, {"reason": reason, **extra}

    def _opponent_if_needed(self):
        """Let the opponent move while it is their turn. The line ends when the repertoire ends (no reply is expected any more), when the opponent plays a reply the repertoire does
        not answer, when theory ends, or at the depth limit."""
        while not self.over and self.board.turn != self.rep.color:
            expected = self.rep.expected.get(key(self.board))
            if expected is None:
                return self._finish("repertoire-ends", message="You reached the end of your prepared line. Well done.")
            if len(self.board.move_stack) >= self.max_plies:
                return self._finish("depth", message=f"You reached move {self.max_plies // 2} inside your repertoire.")
            rows = [(u, s) for u, s in self.replies(self.board.fen()) if s >= self.min_share]
            if not rows:
                return self._finish("theory-ends", message="Players of this rating rarely reach this position: your repertoire is as deep as it needs to be here.")
            total = sum(s for _, s in rows)
            uci = self.rng.choices([u for u, _ in rows], weights=[s / total for _, s in rows])[0]
            share = dict(rows)[uci]
            move = chess.Move.from_uci(uci)
            san = self.board.san(move)
            self.board.push(move)
            self.line.append(san)
            if uci not in expected:
                return self._finish("unanswered", message=f"The opponent played {san}, which about {100 * share:.0f}% of players at this rating choose here, and your repertoire has no answer to it. "
                                                           "Prepare a move here.", reply=san, share=share)
            if not self.rep.prepared(self.board):
                return self._finish("repertoire-ends", message="You reached the end of your prepared line. Well done.")
        if not self.over and len(self.board.move_stack) >= self.max_plies:
            self._finish("depth", message=f"You reached move {self.max_plies // 2} inside your repertoire.")

    def move(self, uci):
        if self.over:
            return {"error": "this line is finished", "view": self.view()}
        if self.board.turn != self.rep.color:
            return {"error": "not your turn", "view": self.view()}
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return {"error": "that is not a move", "view": self.view()}
        if move not in self.board.legal_moves:
            return {"error": "that move is not legal here", "view": self.view()}
        prepared = self.rep.prepared(self.board)
        if uci not in prepared:
            self.mistakes += 1
            return {"verdict": "not in your repertoire", "expected": sorted(prepared.values()),
                    "message": "Your repertoire plays " + " or ".join(sorted(prepared.values())) + " here.", "view": self.view()}
        self.line.append(prepared[uci])
        self.board.push(move)
        self._opponent_if_needed()
        return {"verdict": "ok", "view": self.view()}


def coverage(repertoire, replies, *, min_share=DEFAULT_MIN_SHARE, max_plies=16, top=5):
    """Walk the opponent's likely replies along the repertoire: {"covered": share of games that stay inside it until a prepared line ends, theory ends or the depth limit,
    "gaps": [{"line", "share"}] the most common replies the repertoire has no answer to}. Probabilities multiply along a line; a reply is unanswered when the repertoire expects
    other replies in that position but not this one."""
    gaps, covered = [], 0.0

    def walk(board, prob, line):
        nonlocal covered
        if len(board.move_stack) >= max_plies:
            covered += prob
            return
        if board.turn == repertoire.color:
            prepared = repertoire.prepared(board)
            if not prepared:                                                # a prepared line that ends here
                covered += prob
                return
            move = chess.Move.from_uci(sorted(prepared)[0])                 # the first prepared move (a repertoire with several answers is followed along one of them)
            san = board.san(move)
            board.push(move)
            walk(board, prob, line + [san])
            board.pop()
            return
        expected = repertoire.expected.get(key(board))
        if expected is None:                                                # the repertoire has nothing more to say here: the end of the prepared line
            covered += prob
            return
        rows = [(u, s) for u, s in replies(board.fen()) if s >= min_share]
        if not rows:
            covered += prob
            return
        total = sum(s for _, s in rows)
        for u, s in rows:
            move = chess.Move.from_uci(u)
            san = board.san(move)
            if u not in expected:                                           # a reply the repertoire does not answer
                gaps.append({"line": " ".join(line + [san]), "share": prob * s / total})
                continue
            board.push(move)
            walk(board, prob * s / total, line + [san])
            board.pop()
    walk(chess.Board(), 1.0, [])
    return {"covered": covered, "gaps": sorted(gaps, key=lambda g: -g["share"])[:top]}
