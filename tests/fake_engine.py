#!/usr/bin/env python3
"""A tiny scriptable UCI engine for testing the client and match code.

usage: fake_engine.py MODE [LOGFILE]
MODE: normal | hang (never answers `go`) | crash (exits on `go`) | illegal (bestmove e2e5) | null (bestmove 0000)
      | mate (reports a mate score) | noscore (bestmove without info lines) | garbage (bestmove with no move)
Every received line is appended to LOGFILE if given.
"""
import sys

mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
log = open(sys.argv[2], "a") if len(sys.argv) > 2 else None


def out(line):
    print(line, flush=True)


for raw in sys.stdin:
    line = raw.strip()
    if log:
        log.write(line + "\n")
        log.flush()
    if line == "uci":
        out("id name fake")
        out("uciok")
    elif line == "isready":
        out("readyok")
    elif line.startswith("go"):
        if mode == "hang":
            continue
        if mode == "crash":
            sys.exit(3)
        if mode == "multipv":
            out("info depth 2 multipv 1 score cp 30 nodes 50 pv e2e4 e7e5")
            out("info depth 2 multipv 2 score cp 10 nodes 50 pv d2d4 d7d5")
            out("info depth 3 multipv 1 score cp 35 nodes 90 pv e2e4 e7e5 g1f3")
            out("info depth 3 multipv 2 score cp -20 nodes 90 pv d2d4 d7d5 c2c4")
            out("info depth 3 multipv 3 score mate 4 nodes 90 pv g1f3")
        elif mode == "multipv_cut":  # what Stockfish prints when a node limit stops it mid-iteration
            out("info depth 6 multipv 1 score cp 22 nodes 13000 pv e2e4 c7c5")
            out("info depth 6 multipv 2 score cp 17 nodes 13000 pv d2d4 d7d5")
            out("info depth 6 multipv 3 score cp 15 nodes 13000 pv g1f3 d7d5")
            out("info depth 7 multipv 1 score cp 24 nodes 18000 pv e2e4 e7e5")
            out("info depth 7 multipv 2 score cp 16 nodes 18000 pv d2d4 d7d5")
            out("info depth 7 multipv 3 score cp 15 nodes 18000 pv g1f3 d7d5")
            out("info depth 7 multipv 2 score cp 99 lowerbound nodes 19000 pv c2c4")  # a bound is not a score
            out("info depth 7 multipv 3 score cp 16 nodes 20005 pv d2d4 d7d5")  # partial re-sorted block (no line 1)
        elif mode == "mate":
            out("info depth 4 score mate 3 nodes 321 pv e2e4 e7e5 d1h5")
        elif mode != "noscore":
            out("info depth 2 score cp 10 nodes 50 pv d2d4")
            out("info depth 3 score cp 25 nodes 100 time 4 pv e2e4 e7e5")
        out({"illegal": "bestmove e2e5", "null": "bestmove 0000", "garbage": "bestmove"}.get(mode, "bestmove e2e4"))
    elif line == "quit":
        break
