"""Endgame practice judged EXACTLY by Syzygy tablebases: no engine opinion is involved.

A theme fixes the material (for example king and pawn against king) and what you must achieve: win it (convert) or hold it (draw with the worse side). Start positions are random
legal placements of that material, kept only when the tablebase says the result is the one the theme needs (a win for you with you to move, or a draw for you to hold). Every move of
yours is judged by what it does to the theoretical result: a move that turns a win into a draw, or a draw into a loss, is refused and explained. The opponent plays the strongest resistance
the tablebase allows (the longest way to lose, or the quickest win when you are the defender), so you cannot be saved by its mistakes.

`tb` is any object with `probe_wdl(board)` and `probe_dtz(board)` as in `chess.syzygy.Tablebase` (win 2 ... loss -2 for the side to move); the table files are an external download
you choose (the 3 to 5 piece set is about 1 GB)."""
import random

import chess
import chess.syzygy

THEMES = {
    "kpk-win": {"title": "King and pawn against king: win it", "material": ("KP", "K"), "role": "attacker", "goal": "promote",
                "tip": "Get your king in front of the pawn, on a key square, and keep the opposition when the pawn is not yet far advanced."},
    "kpk-hold": {"title": "King against king and pawn: hold the draw", "material": ("KP", "K"), "role": "defender", "goal": "survive",
                 "tip": "Stay in front of the pawn or take the opposition; a king in the corner in front of a rook pawn draws."},
    "kqk": {"title": "Queen against king: checkmate", "material": ("KQ", "K"), "role": "attacker", "goal": "mate",
            "tip": "Shrink the box with the queen a knight's move from the king; bring your king up, and avoid stalemate."},
    "krk": {"title": "Rook against king: checkmate", "material": ("KR", "K"), "role": "attacker", "goal": "mate",
            "tip": "Cut the king off along a rank or file, bring your king up to take the opposition, and give the check on the edge."},
}
MAX_PLIES = 120


def _category(wdl):
    """+1 win, 0 draw (including cursed wins and blessed losses: the fifty-move rule makes them draws), -1 loss."""
    return 1 if wdl == 2 else -1 if wdl == -2 else 0


def available(tb, theme):
    """True when the table files for the theme's material are present (probes the first legal arrangement it finds)."""
    t = THEMES[theme]
    symbols = ["K", "k"] + [c for c in t["material"][0] if c != "K"] + [c.lower() for c in t["material"][1] if c != "K"]       # kings first: a pawn must not land on the back rank
    for squares in ((chess.A1, chess.H8, chess.C2, chess.F6), (chess.A1, chess.H8, chess.D3, chess.B6), (chess.E1, chess.E8, chess.A3, chess.H6)):
        board = chess.Board(None)
        for sym, sq in zip(symbols, squares):
            board.set_piece_at(sq, chess.Piece.from_symbol(sym))
        board.turn = chess.WHITE
        if not board.is_valid():
            continue
        try:
            tb.probe_wdl(board)
            return True
        except (KeyError, chess.syzygy.MissingTableError):
            return False
    return False


def generate(theme, tb, rng=None, tries=3000):
    """(fen, player colour) of a random start position for the theme with the player to move, or None if none was found."""
    rng = rng or random.Random()
    t = THEMES[theme]
    for _ in range(tries):
        player = rng.choice([chess.WHITE, chess.BLACK])
        strong, weak = t["material"]
        mine, theirs = (strong, weak) if t["role"] == "attacker" else (weak, strong)
        board = chess.Board(None)
        squares = rng.sample(range(64), len(mine) + len(theirs))
        it = iter(squares)
        for sym in mine:
            board.set_piece_at(next(it), chess.Piece.from_symbol(sym.upper() if player == chess.WHITE else sym.lower()))
        for sym in theirs:
            board.set_piece_at(next(it), chess.Piece.from_symbol(sym.lower() if player == chess.WHITE else sym.upper()))
        board.turn = player
        pawn_ok = all(chess.square_rank(sq) not in (0, 7) for sq, p in board.piece_map().items() if p.piece_type == chess.PAWN)
        if not pawn_ok or not board.is_valid() or board.is_game_over():
            continue
        try:
            cat = _category(tb.probe_wdl(board))
        except (KeyError, chess.syzygy.MissingTableError):
            return None
        need = 1 if t["role"] == "attacker" else 0
        if cat == need:
            return board.fen(), player
    return None


def _moves_by_value(board, tb, color):
    """[(category for `color`, dtz-like distance, move)] for every legal move, as seen by `color` after the move."""
    out = []
    for m in board.legal_moves:
        b = board.copy(stack=False)
        b.push(m)
        if b.is_checkmate():
            out.append((1 if b.turn != color else -1, 0, m))
            continue
        if b.is_stalemate() or b.is_insufficient_material():
            out.append((0, 0, m))
            continue
        try:
            wdl = tb.probe_wdl(b)
            dtz = abs(tb.probe_dtz(b))
        except (KeyError, chess.syzygy.MissingTableError):
            out.append((0, 99, m))                           # material left the table (a capture or a promotion): treat as unknown, ranked last
            continue
        cat = _category(wdl)
        out.append((cat if b.turn == color else -cat, dtz, m))
    return out


class EndgameDrill:
    def __init__(self, theme, tb, fen, player, seed=0):
        self.theme, self.tb, self.player = theme, tb, player
        self.cfg = THEMES[theme]
        self.board = chess.Board(fen)
        self.rng = random.Random(seed)
        self.start_category = _category(tb.probe_wdl(self.board))
        self.errors, self.over, self.report, self.line = 0, False, None, []

    def view(self):
        return {"fen": self.board.fen(), "color": "white" if self.player == chess.WHITE else "black", "over": self.over, "report": self.report, "line": self.line,
                "legal": [] if self.over else [m.uci() for m in self.board.legal_moves], "errors": self.errors, "goal": self.cfg["title"], "tip": self.cfg["tip"]}

    def good_moves(self):
        """Moves that keep the result of the position (the best category for the player)."""
        vals = _moves_by_value(self.board, self.tb, self.player)
        best = max(v[0] for v in vals)
        return [(d, m) for c, d, m in vals if c == best], best

    def hint(self, level=1):
        good, best = self.good_moves()
        keep = {1: "win", 0: "draw", -1: "loss"}[best]
        if level <= 1:
            return f"{len(good)} of the {self.board.legal_moves.count()} legal moves keep the {keep}. {self.cfg['tip']}"
        move = min(good, key=lambda t: t[0])[1]
        return f"Move the piece on {chess.square_name(move.from_square)}." if level == 2 else f"The move is {self.board.san(move)}."

    def _finish(self, success, message):
        self.over, self.report = True, {"success": success, "message": message, "errors": self.errors}

    def _check_end(self):
        b = self.board
        goal = self.cfg["goal"]
        if b.is_checkmate():
            winner = not b.turn
            return self._finish(winner == self.player, "Checkmate. " + ("You converted the win." if winner == self.player else "You lost the game."))
        if b.is_stalemate() or b.is_insufficient_material():
            return self._finish(self.cfg["role"] == "defender", "A draw." + (" You held it." if self.cfg["role"] == "defender" else " The win slipped away."))
        if goal == "promote" and any(p.piece_type == chess.QUEEN and p.color == self.player for p in b.piece_map().values()):
            return self._finish(True, "The pawn promoted and the win is intact. Well done.")
        if goal == "survive" and len(self.board.move_stack) >= 2 * 20:
            return self._finish(True, "You held the draw for 20 moves.")
        if len(self.board.move_stack) >= MAX_PLIES or b.halfmove_clock >= 100:
            return self._finish(self.cfg["role"] == "defender", "The game ran past the move limit.")

    def move(self, uci):
        if self.over:
            return {"error": "this game is finished", "view": self.view()}
        if self.board.turn != self.player:
            return {"error": "not your turn", "view": self.view()}
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return {"error": "that is not a move", "view": self.view()}
        if move not in self.board.legal_moves:
            return {"error": "that move is not legal here", "view": self.view()}
        vals = {m: (c, d) for c, d, m in _moves_by_value(self.board, self.tb, self.player)}
        best = max(c for c, _ in vals.values())
        cat, _ = vals[move]
        if cat < best:
            self.errors += 1
            word = {1: "the win", 0: "the draw", -1: "the position"}[best]
            lost = {0: "only a draw", -1: "a loss"}[cat]
            return {"verdict": "throws it away", "message": f"{self.board.san(move)} gives away {word}: with correct play it is now {lost}. Try another move.", "view": self.view()}
        good, _ = self.good_moves()
        fastest = min(d for d, _ in good)
        slow = best == 1 and vals[move][1] > fastest + 12
        san = self.board.san(move)
        self.board.push(move)
        self.line.append(san)
        self._check_end()
        out = {"verdict": "ok", "slow": slow}
        if slow:
            out["message"] = "That keeps the win, but not the quickest way: watch the fifty-move rule."
        if not self.over:
            reply = self._opponent_move()
            out["reply_san"] = reply
            self._check_end()
        out["view"] = self.view()
        return out

    def _opponent_move(self):
        """The strongest resistance: the best result for the opponent, then the longest (when losing) or the shortest (when winning) distance, with a coin flip among near ties."""
        opp = self.board.turn
        vals = _moves_by_value(self.board, self.tb, opp)
        best = max(c for c, _, _ in vals)
        pool = [(d, m) for c, d, m in vals if c == best]
        pool.sort(key=lambda t: t[0], reverse=(best < 1))
        pick = pool[0] if len(pool) < 2 or self.rng.random() < 0.7 else pool[1]
        san = self.board.san(pick[1])
        self.board.push(pick[1])
        self.line.append(san)
        return san
