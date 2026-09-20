# Using Stockfish

[Stockfish](https://stockfishchess.org/) is the strongest open-source chess engine. MeChess uses it as an
**external program** in three places. It is never bundled, linked or copied (Stockfish is GPL-licensed;
running it as a separate process is fine, see [third-party](third-party.md)).

## What we use it for

1. **The judge in style analysis** (main use). To ask *which of several equally good moves did this player
   choose?* we first need to know which moves are "equally good". Stockfish's MultiPV lines at a fixed node
   budget define the candidate set (moves within a centipawn window of the best) and the centipawn loss of each
   move. Our own engine is far weaker and disagrees with Stockfish about which move is best in about two out of
   three positions, which distorted the first results; Stockfish is therefore the default judge. Every dataset stores
   the judge that made it (for example `stockfish@20000n`) and results from different judges must not be mixed.
2. **A reference opponent** for measuring our engine's strength and calibrating the Elo dial: limited with `UCI_LimitStrength` and
   `UCI_Elo` and played in an adaptive ladder ([calibration.md](calibration.md)).
3. **A labelling tool** (planned): centipawn loss per move in your games, for the mistake model and reports.

Anything that speaks UCI can be the judge: pass it with `--engine /path/to/engine` (the default is our own
engine at `engine/build/chessme-engine`).

## Installing

| System | Command |
|---|---|
| macOS (Homebrew) | `brew install stockfish` |
| Debian / Ubuntu | `sudo apt install stockfish` |
| Anything else | download a binary from <https://stockfishchess.org/download/> and put it on your `PATH` |

Check: `stockfish` starts a prompt; type `uci`, expect a list of options and `uciok`, then `quit`.

## The Stockfish command line, briefly

Stockfish is a UCI engine: it reads commands on standard input and writes to standard output. A session looks like:

```
$ stockfish
uci                                       # engine lists its options, ends with "uciok"
setoption name Threads value 1            # one search thread (predictable, small)
setoption name Hash value 64              # transposition table in MB
setoption name MultiPV value 8            # report the 8 best moves, not just one
isready                                   # engine answers "readyok"
position fen r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3
go nodes 20000                            # search a fixed number of nodes (reproducible, machine independent)
...
info depth 9 seldepth 12 multipv 1 score cp 32 nodes 18000 pv f1b5 g8f6 ...
info depth 9 seldepth 11 multipv 2 score cp 24 nodes 18000 pv d2d4 e5d4 ...
bestmove f1b5 ponder g8f6
quit
```

Useful facts:

- `go nodes N` (used everywhere here) gives the same answer on any machine; `go movetime MS` and `go depth D` do not.
- `info ... multipv k score cp X` is line *k* of the current search iteration; `score mate M` is a forced mate in M.
- With MultiPV > 1 and a node limit, Stockfish can stop **in the middle of an iteration** and print a partial block
  (for example only lines 3 to 8, re-sorted). It also prints `lowerbound` / `upperbound` lines during aspiration
  windows. Neither is a real score. See below for how the client copes.
- Scores are from the side to move's point of view. In recent versions centipawns are normalised so that about
  100 cp corresponds to roughly a 50% win chance (check the documentation of your version); this is why we
  are considering win-probability loss instead of a fixed centipawn window (see the [roadmap](roadmap.md)).
- `UCI_LimitStrength` and `UCI_Elo` make Stockfish play weaker on purpose; their scale is *not* the Lichess or
  chess.com scale.
- `stockfish bench` prints a speed test; not used by MeChess.

## How MeChess talks to it

`chessme/uci_client.py` (class `UciEngine`) starts the process, sends the options, and for each `go`:

- reads `info` lines and builds MultiPV lines **per iteration block** (a block starts at `multipv 1`); it keeps the last
  block that is complete (no gaps), ignoring partial final blocks and any `lowerbound` / `upperbound` line;
- converts scores to centipawns; a forced mate counts as `+-(100000 - |mate|)`;
- returns the best move, the score, the depth, and the list of lines.

`chessme/style/candidates.py` then keeps the lines within the window (default 60 cp) of the best line and computes the
features of each candidate. Options sent to a Stockfish-named binary: `MultiPV`, `Threads 1`, `Hash 64` (small and
predictable on a laptop; several worker processes share the CPU).

Typical cost: about 0.05 to 0.1 seconds per position at 20,000 nodes with MultiPV 8 on one laptop core.

## Commands that take a judge

```bash
python -m chessme style-data      --engine stockfish --out data/style/me_sf
python -m chessme style-pop-data  SOURCE --engine stockfish --out data/style/pop_sf
python -m chessme style-cohort-analyze --engine stockfish --out data/style/cohort --workers 4
python -m chessme style-judge-compare data/style/me data/style/me_sf     # how much does the judge matter?
```

## Tips

- Keep `Threads 1` and use several worker processes instead (`--workers`); it is easier on memory and scales evenly.
- Do not compare numbers made with different node budgets or different engines; the judge label is stored in the file.
- Stockfish uses tens of MB per process; when running many workers, use the [memory guard](operations.md).
