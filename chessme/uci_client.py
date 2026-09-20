"""Minimal UCI client: drive any UCI engine (ours, Stockfish, ...) from Python with hard timeouts."""
import os
import re
import select
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

STARTPOS_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class EngineError(RuntimeError):
    """The engine crashed, timed out or spoke nonsense."""


@dataclass
class Line:
    """One analysed root move (a MultiPV line)."""
    move: str
    score_kind: str  # "cp" | "mate"
    score: int  # from the side to move's point of view
    depth: int = 0
    pv: list = field(default_factory=list)

    @property
    def cp(self):
        """Score as centipawns; a forced mate counts as +-(100000 - distance)."""
        return self.score if self.score_kind == "cp" else (100000 - abs(self.score)) * (1 if self.score > 0 else -1)


@dataclass
class GoResult:
    bestmove: str
    score_kind: Optional[str] = None  # "cp" | "mate" | None if the engine reported no score
    score: Optional[int] = None  # from the side to move's point of view
    depth: int = 0
    nodes: int = 0
    pv: list = field(default_factory=list)
    lines: list = field(default_factory=list)  # MultiPV lines of the deepest finished depth, best first


_SCORE = re.compile(r"\bscore (cp|mate) (-?\d+)")
_DEPTH = re.compile(r"\bdepth (\d+)")
_NODES = re.compile(r"\bnodes (\d+)")
_PV = re.compile(r"\bpv (.*)$")
_MULTIPV = re.compile(r"\bmultipv (\d+)")


class UciEngine:
    def __init__(self, command, options=None, name=None, startup_timeout=15):
        self.command = [command] if isinstance(command, str) else list(command)
        self.options = dict(options or {})
        self.name = name or os.path.basename(self.command[-1])
        self.startup_timeout = startup_timeout
        self.proc = None
        self._buf = b""

    # -- lifecycle ---------------------------------------------------------------------------------------
    def start(self):
        try:
            self.proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, bufsize=0)
        except OSError as e:
            raise EngineError(f"cannot start {self.command}: {e}") from e
        self._send("uci")
        self._expect("uciok", self.startup_timeout)
        for k, v in self.options.items():
            self._send(f"setoption name {k} value {v}")
        self.ready()
        return self

    def ready(self, timeout=None):
        self._send("isready")
        self._expect("readyok", timeout or self.startup_timeout)

    def new_game(self):
        self._send("ucinewgame")
        self.ready()

    def close(self):
        if self.proc is None:
            return
        try:
            if self.proc.poll() is None:
                self._send("quit")
                self.proc.wait(timeout=2)
        except Exception:
            pass
        finally:
            if self.proc.poll() is None:
                self.proc.kill()
                self.proc.wait()
            self.proc.stdout.close()
            self.proc.stdin.close()
            self.proc = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()

    # -- searching ---------------------------------------------------------------------------------------
    def go(self, fen=STARTPOS_FEN, moves=(), *, nodes=None, depth=None, movetime=None, timeout=60):
        """Search a position (given as start FEN + UCI moves). One of nodes / depth / movetime must be set; nodes and depth may be
        combined (`go depth D nodes N`: stop at whichever limit is reached first)."""
        pos = "position startpos" if fen == STARTPOS_FEN else f"position fen {fen}"
        if moves:
            pos += " moves " + " ".join(moves)
        self._send(pos)
        if nodes and depth:
            self._send(f"go depth {int(depth)} nodes {int(nodes)}")
        elif nodes:
            self._send(f"go nodes {int(nodes)}")
        elif depth:
            self._send(f"go depth {int(depth)}")
        elif movetime:
            self._send(f"go movetime {int(movetime)}")
        else:
            raise ValueError("need one of nodes, depth or movetime")
        result = GoResult(bestmove="")
        blocks, cur, last_idx = [], {}, 0  # one block = the lines of one search iteration (multipv 1, 2, 3, ...)
        deadline = time.monotonic() + timeout
        while True:
            line = self._readline(deadline)
            if line.startswith("bestmove"):
                parts = line.split()
                if len(parts) < 2:
                    raise EngineError(f"{self.name}: malformed bestmove line: {line!r}")
                result.bestmove = parts[1]
                blocks.append(cur)
                # A node limit can stop the engine part-way through an iteration; it then prints a partial block
                # (e.g. only multipv 3..8), so keep the last block that starts at multipv 1 and has no gaps.
                whole = [b for b in blocks if b and sorted(b) == list(range(1, len(b) + 1))]
                if whole:
                    full = max(len(b) for b in whole)
                    result.lines = next([b[k] for k in sorted(b)] for b in reversed(whole) if len(b) == full)
                return result
            if line.startswith("info") and " score " in line:
                m = _SCORE.search(line)
                if m:
                    result.score_kind, result.score = m.group(1), int(m.group(2))
                if m := _DEPTH.search(line):
                    result.depth = int(m.group(1))
                if m := _NODES.search(line):
                    result.nodes = int(m.group(1))
                if m := _PV.search(line):
                    result.pv = m.group(1).split()
                mp = _MULTIPV.search(line)
                if m := _SCORE.search(line):
                    pv = _PV.search(line).group(1).split() if _PV.search(line) else []
                    if pv and " lowerbound" not in line and " upperbound" not in line:  # bounds are not real scores
                        idx = int(mp.group(1)) if mp else 1
                        if idx <= last_idx:  # index went back: a new iteration starts
                            blocks.append(cur)
                            cur = {}
                        cur[idx], last_idx = Line(pv[0], m.group(1), int(m.group(2)), result.depth, pv), idx

    # -- plumbing ----------------------------------------------------------------------------------------
    def _send(self, line):
        if self.proc is None or self.proc.poll() is not None:
            raise EngineError(f"{self.name}: engine is not running")
        try:
            self.proc.stdin.write((line + "\n").encode())
        except (BrokenPipeError, OSError) as e:
            raise EngineError(f"{self.name}: engine closed its input ({e})") from e

    def _readline(self, deadline):
        fd = self.proc.stdout.fileno()
        while b"\n" not in self._buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._kill()
                raise EngineError(f"{self.name}: timed out waiting for the engine")
            ready, _, _ = select.select([fd], [], [], min(remaining, 0.5))
            if not ready:
                if self.proc.poll() is not None:
                    raise EngineError(f"{self.name}: engine exited unexpectedly (code {self.proc.returncode})")
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                raise EngineError(f"{self.name}: engine closed its output")
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return line.decode(errors="replace").strip()

    def _expect(self, token, timeout):
        deadline = time.monotonic() + timeout
        while True:
            if self._readline(deadline).split(" ")[0] == token:
                return

    def _kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()  # reap it now so no zombie / orphan is left behind
