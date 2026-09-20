"""MeChess as a UCI engine (a Python program that drives the C++ engine), usable in any chess GUI or Lichess bot."""
import sys

import chess

from .controller import MeChess

OPTIONS = {"Elo": (1800, 800, 2800), "OppElo": (0, 0, 3000), "Platform": (0, 0, 1), "Seed": (0, 0, 2**31 - 1)}


class MechessUci:
    def __init__(self, controller, inp=None, out=None, elo=1800):
        self.mc, self.inp, self.out = controller, inp or sys.stdin, out or sys.stdout
        self.opts = {k: v[0] for k, v in OPTIONS.items()}
        self.opts["Elo"] = elo
        self.board = chess.Board()

    def send(self, line):
        print(line, file=self.out, flush=True)

    def run(self):
        for raw in self.inp:
            if not self.handle(raw.strip()):
                return

    def handle(self, line):
        cmd, _, rest = line.partition(" ")
        if cmd == "uci":
            self.send("id name MeChess")
            self.send("id author chessme")
            for name, (default, lo, hi) in OPTIONS.items():
                self.send(f"option name {name} type spin default {default if name != 'Elo' else self.opts['Elo']} min {lo} max {hi}")
            self.send("uciok")
        elif cmd == "isready":
            self.send("readyok")
        elif cmd == "ucinewgame":
            self.board = chess.Board()
        elif cmd == "setoption":
            self.setoption(rest)
        elif cmd == "position":
            self.position(rest)
        elif cmd == "go":
            self.go()
        elif cmd == "quit":
            return False
        return True

    def setoption(self, rest):
        tokens = rest.split()
        if "name" not in tokens:
            return
        i = tokens.index("value") if "value" in tokens else len(tokens)
        name = " ".join(tokens[1:i])
        value = " ".join(tokens[i + 1:])
        if name in OPTIONS and value.lstrip("-").isdigit():
            lo, hi = OPTIONS[name][1:]
            self.opts[name] = min(max(int(value), lo), hi)
            if name == "Seed" and self.opts[name]:
                import random

                self.mc.rng = random.Random(self.opts[name])

    def position(self, rest):
        tokens = rest.split()
        if not tokens:
            return
        if tokens[0] == "startpos":
            board, i = chess.Board(), 1
        elif tokens[0] == "fen":
            j = tokens.index("moves") if "moves" in tokens else len(tokens)
            try:
                board = chess.Board(" ".join(tokens[1:j]))
            except ValueError:
                return
            i = j
        else:
            return
        if i < len(tokens) and tokens[i] == "moves":
            for uci in tokens[i + 1:]:
                try:
                    move = chess.Move.from_uci(uci)
                except ValueError:
                    return
                if move not in board.legal_moves:
                    return
                board.push(move)
        self.board = board

    def go(self):
        if self.board.legal_moves.count() == 0:
            self.send("bestmove 0000")
            return
        c = self.mc.choose(self.board, self.opts["Elo"], self.opts["OppElo"] or None, self.opts["Platform"])
        shown = ", ".join(f"{self.board.san(x.move)} {100 * x.prob:.0f}%" for x in sorted(c.candidates, key=lambda x: -x.prob)[:5])
        self.send(f"info string {c.source}: {shown}")
        self.send(f"bestmove {c.move.uci()}")
