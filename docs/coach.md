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

My weaknesses: each reviewed game is kept (one small JSON in `~/.mechess-coach/games`; the same game twice counts once). From them the start page shows where your own rate of mistakes (moves that give away at least 10 points of expected score) is clearly higher than elsewhere in your games: by phase and by situation (ahead, level, behind), and the kind of mistake (allowed a mate in one, did not deal with a threat, put a piece where it can be captured, a deeper loss), each with the practice that fits. A category needs at least 30 moves and a one-sided 95% test, so one bad game does not make a weakness. This compares you with yourself, not with other players of your rating (planned).

Opening practice: paste your repertoire as a PGN with variations, say which colour you play and the rating of the players you face. The drill lets you play your side; the opponent answers with replies drawn from the opening explorer at that rating (replies chosen by at least 2% of the games), so the lines you really meet come up as often as they occur. A move that is not in your repertoire is refused with the move you prepared. The line ends when you reach the end of your prepared line, when the opponent plays something you have no answer to (with how often that happens), or when theory ends. *Check coverage* walks the explorer's tree along your repertoire and lists the most common replies you have no answer to. Needs the explorer database (`--explorer`, default `data/explorer/explorer.db`; see [opening-explorer.md](opening-explorer.md)).

Endgame practice: pick a theme (king and pawn against king, to win it or to hold the draw; queen against king; rook against king) and play it out. The position is generated at random and kept only when the tablebase says the result is the one the theme needs. Every move you make is judged exactly by the Syzygy tablebase: a move that turns a win into a draw, or a draw into a loss, is refused and explained, and the opponent always plays the strongest resistance the tablebase allows. A three-step hint and a note when a win is kept but slowly (the fifty-move rule) are included. Needs the table files (`--syzygy DIR`, default `data/syzygy`; the 3 to 5 piece set is about 1 GB, from tablebase.lichess.ovh; they are an external download and are not part of this repository). More themes (Lucena, Philidor, queen against pawn on the seventh, bishop and knight mate) need the 4 and 5 piece files and are planned.

Privacy: the server listens on 127.0.0.1 only; your games and attempts stay in memory on this machine; the only network use is the optional Lichess fetch. The page loads no outside
scripts, fonts or images.

Planned (see the research notes): a weakness profile, opening and variation practice, a steered game that trains chosen weaknesses, endgame practice checked with tablebases, drills
from your own mistakes with spaced repetition, and an optional language-model chat whose claims are checked against the engine.
