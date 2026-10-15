# The coach

A local web page that takes you back over the game you just played, finds the moments where you gave away the most, asks you to find a better move, tells you in plain
sentences what went wrong and why the better move is better, and lets you play on from the corrected position against the engine. Everything runs on your computer.

```bash
.venv/bin/python -m chessme coach            # opens http://127.0.0.1:8765 ; needs Stockfish on the PATH (or --engine PATH)
.venv/bin/python -m chessme coach --nodes 300000 --port 9000 --no-browser
```

1. **Get a game**: type a Lichess user name (fetches the latest public games, one request) or paste a PGN.
2. **Choose the game and your side**; the engine analyses it once (a few seconds to a minute, more nodes is slower and stronger).
3. For each of up to five mistakes: the board shows the position **before** your move. Click a piece, then its square.
   * *Hint* gives three steps: the theme, the piece, the move.
   * A wrong try tells you roughly how much it still gives away; a different but good move is accepted with a note.
   * When you find it, the coach explains what your game move allowed and what the better move does, shows the engine's lines, and the opponent answers so you can play on.
   * *Show the answer* and *Try again* are always available. Positions that were already lost, or mistakes smaller than 10 points of expected score, are not used.

How it says things: every sentence is built from the board (python-chess) and the engine's numbers: what a move captures, whether it gives check, which piece was attacked, whether a
capture wins material by static exchange, whether the opponent can mate in one. There is no free-running text generation, so nothing is invented. The kinds of mistake
(allowed a mate in one, did not deal with a threat, put a piece where it can be captured, or a deeper loss) use the same rules as the human-likeness benchmark
(`chessme/humanlike/blunders.py`).

Drills: the positions you try are saved in `~/.mechess-coach/drills.json` (`--data-dir` to change). A position you find on the first try without a hint comes back later (1, 3, 7, 16, 35 days); anything else brings it back in ten minutes. "Practice my mistakes" on the start page replays what is due.

Privacy: the server listens on 127.0.0.1 only; your games and attempts stay in memory on this machine; the only network use is the optional Lichess fetch. The page loads no outside
scripts, fonts or images.

Planned (see the research notes): a weakness profile, opening and variation practice, a steered game that trains chosen weaknesses, endgame practice checked with tablebases, drills
from your own mistakes with spaced repetition, and an optional language-model chat whose claims are checked against the engine.
