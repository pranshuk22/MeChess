"""MeChess as a UCI engine (a Python program that drives the C++ engine), usable in any chess GUI or Lichess bot."""
import sys
import time

import chess
import numpy as np

from .controller import MeChess

OPTIONS = {"Elo": (1800, 0, 4000), "OppElo": (0, 0, 3000), "Platform": (0, 0, 1), "Seed": (0, 0, 2**31 - 1)}


class MechessUci:
    def __init__(self, controller, inp=None, out=None, elo=1800, clock=None, clock_strength=1.0, sleep=time.sleep, clock_seed=None):
        """`clock`: a `ClockModel`; when given and the GUI sends its clocks with `go`, the bot waits the way the player would have thought."""
        self.mc, self.inp, self.out = controller, inp or sys.stdin, out or sys.stdout
        self.clock, self.clock_strength, self.sleep = clock, clock_strength, sleep
        self.clock_rng = np.random.default_rng(clock_seed)
        self.base = None                     # the game's starting time, learnt from the first clock seen
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
            self.base = None
        elif cmd == "setoption":
            self.setoption(rest)
        elif cmd == "position":
            self.position(rest)
        elif cmd == "go":
            self.go(rest)
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

    def clocks(self, rest):
        """{'wtime': ms, ...} from the arguments of `go`."""
        t = rest.split()
        return {k: int(t[i + 1]) for i, k in enumerate(t[:-1]) if k in ("wtime", "btime", "winc", "binc") and t[i + 1].lstrip("-").isdigit()}

    def wait(self, rest, started):
        """Sleep the rest of the player's think time (what the clock model draws minus what the search already took)."""
        c = self.clocks(rest)
        me = "wtime" if self.board.turn == chess.WHITE else "btime"
        if self.clock is None or me not in c:
            return
        remaining = c[me] / 1000.0
        inc = c.get("winc" if self.board.turn == chess.WHITE else "binc", 0) / 1000.0
        if self.base is None or len(self.board.move_stack) < 2:
            self.base = remaining
        delay = self.clock.delay(self.board, remaining, self.base, inc, self.clock_rng, strength=self.clock_strength)
        left = delay - (time.time() - started)
        if left > 0:
            self.sleep(left)
        self.send(f"info string clock: thought {max(delay, 0):.1f}s of {remaining:.0f}s")

    def go(self, rest=""):
        started = time.time()
        if self.board.legal_moves.count() == 0:
            self.send("bestmove 0000")
            return
        c = self.mc.choose(self.board, self.opts["Elo"], self.opts["OppElo"] or None, self.opts["Platform"])
        shown = ", ".join(f"{self.board.san(x.move)} {100 * x.prob:.0f}%" for x in sorted(c.candidates, key=lambda x: -x.prob)[:5])
        self.send(f"info string {c.source}: {shown}")
        self.wait(rest, started)
        self.send(f"bestmove {c.move.uci()}")
