"""Live engine analysis: one long-lived Stockfish that analyses whatever position the browser is looking at, streaming its lines. One shared engine (the laptop is
small): the newest request wins. All engine I/O is on two threads (a reader and a command worker); a new request stops the old search cleanly (stop, isready,
readyok) before the next one starts, so late output of the old search is never shown for the new position."""
import queue
import re
import subprocess
import threading

import chess

SCORE = re.compile(r"\bscore (cp|mate) (-?\d+)")


def parse_info(line: str):
    """A UCI `info` line as {multipv, depth, kind, score (side to move), nodes, nps, pv [uci]}, or None when it carries no score and line."""
    if not line.startswith("info ") or " pv " not in line + " " or "score" not in line:
        return None
    t = line.split()

    def after(key, cast=int, default=None):
        try:
            return cast(t[t.index(key) + 1])
        except (ValueError, IndexError):
            return default
    m = SCORE.search(line)
    pv = t[t.index("pv") + 1:] if "pv" in t else []
    if not m or not pv or "lowerbound" in t or "upperbound" in t:
        return None                                                            # a bound is not a finished line
    return {"multipv": after("multipv", int, 1), "depth": after("depth", int, 0), "kind": m.group(1), "score": int(m.group(2)), "nodes": after("nodes", int, 0), "nps": after("nps", int, 0), "pv": pv}


def to_lines(fen: str, snapshot: dict, max_pv=10):
    """The lines for the browser: score from white's point of view, the pv in SAN (cut at the first illegal move), best first."""
    board = chess.Board(fen)
    white = board.turn == chess.WHITE
    out = []
    for k in sorted(snapshot):
        i = snapshot[k]
        b = board.copy(stack=False)
        san, uci = [], []
        for u in i["pv"][:max_pv]:
            try:
                mv = chess.Move.from_uci(u)
            except ValueError:
                break
            if mv not in b.legal_moves:
                break
            san.append(b.san(mv))
            uci.append(u)
            b.push(mv)
        if not san:
            continue
        score = i["score"] if white else -i["score"]
        out.append({"multipv": k, "depth": i["depth"], "kind": i["kind"], "score": score, "nodes": i["nodes"], "nps": i["nps"], "san": san, "uci": uci})
    return out


def _san_pv(board: chess.Board, ucis, max_pv=10):
    b = board.copy(stack=False)
    san, uci = [], []
    for u in ucis[:max_pv]:
        try:
            mv = chess.Move.from_uci(u)
        except ValueError:
            break
        if mv not in b.legal_moves:
            break
        san.append(b.san(mv))
        uci.append(u)
        b.push(mv)
    return san, uci


def lines_from_stored(fen: str, stored: list[dict], depth: int | None) -> list[dict]:
    """Cached lines (white's point of view, a mate stored as +-(100000 - distance)) in the shape live lines have."""
    board = chess.Board(fen)
    out = []
    for i, l in enumerate(stored, 1):
        san, uci = _san_pv(board, l["pv"])
        if not san:
            continue
        cp = l["cp"]
        mate = abs(cp) >= 90_000
        out.append({"multipv": i, "depth": depth or 0, "kind": "mate" if mate else "cp", "score": (1 if cp > 0 else -1) * (100_000 - abs(cp)) if mate else cp, "nodes": 0, "nps": 0, "san": san, "uci": uci})
    return out


def snapshot_to_stored(fen: str, snapshot: dict) -> list[dict]:
    """A live snapshot as lines for the cache (white's point of view)."""
    from ..analysis.runner import SimpleLine
    from .services import cache as CA
    board = chess.Board(fen)
    sign = 1 if board.turn == chess.WHITE else -1
    lines = []
    for k in sorted(snapshot):
        i = snapshot[k]
        cp = i["score"] if i["kind"] == "cp" else (1 if i["score"] > 0 else -1) * (100_000 - abs(i["score"]))
        lines.append(SimpleLine(i["pv"][0], cp, i["pv"]))
    return CA.to_stored(sign == 1, lines)


class LiveEngine:
    def __init__(self, path: str, threads=1, hash_mb=64):
        self.proc = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self._ready = threading.Event()
        self._lines: dict[int, dict] = {}
        self._cb = None
        self._discard = False
        self._searching = False
        self._cmds: queue.Queue = queue.Queue()
        self._closed = False
        self._send("uci")
        for line in self.proc.stdout:
            if line.strip() == "uciok":
                break
        self._send(f"setoption name Threads value {threads}")
        self._send(f"setoption name Hash value {hash_mb}")
        threading.Thread(target=self._read, daemon=True, name="live-reader").start()
        self._send("isready")
        if not self._ready.wait(15):
            self.close()
            raise RuntimeError("the engine did not answer")
        threading.Thread(target=self._work, daemon=True, name="live-worker").start()

    def _send(self, line: str):
        try:
            self.proc.stdin.write(line + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError):
            pass

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            if line == "readyok":
                self._ready.set()
            elif not self._discard:
                info = parse_info(line)
                if info and self._cb:
                    self._lines[info["multipv"]] = info
                    self._cb(dict(self._lines))

    def _work(self):
        while not self._closed:
            cmd = self._cmds.get()
            while not self._cmds.empty():                                      # only the newest request matters
                cmd = self._cmds.get_nowait()
            if cmd is None:
                return
            if self._searching:
                self._discard = True
                self._ready.clear()
                self._send("stop")
                self._send("isready")
                self._ready.wait(5)
                self._searching = False
            self._lines = {}
            self._cb = None
            if cmd == "stop":
                continue
            fen, multipv, cb = cmd
            self._cb = cb
            self._discard = False
            self._send(f"setoption name MultiPV value {multipv}")
            self._send(f"position fen {fen}")
            self._send("go infinite")
            self._searching = True

    def analyse(self, fen: str, multipv: int, callback):
        """Start analysing `fen` (stopping any search); `callback(snapshot)` is called on the reader thread with {multipv: info} whenever a line improves."""
        self._cmds.put((fen, max(1, min(int(multipv), 5)), callback))

    def stop(self):
        self._cmds.put("stop")

    def close(self):
        self._closed = True
        self._cmds.put(None)
        self._send("quit")
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class LiveManager:
    """Starts the shared engine on first use and restarts it when the settings (threads, memory, path) change."""

    def __init__(self):
        self._engine: LiveEngine | None = None
        self._key = None
        self._lock = threading.Lock()

    def get(self, path: str, threads: int, hash_mb: int) -> LiveEngine:
        with self._lock:
            key = (path, threads, hash_mb)
            if self._engine is not None and (self._key != key or self._engine.proc.poll() is not None):
                self._engine.close()
                self._engine = None
            if self._engine is None:
                self._engine, self._key = LiveEngine(path, threads, hash_mb), key
            return self._engine

    def close(self):
        with self._lock:
            if self._engine is not None:
                self._engine.close()
                self._engine = None
