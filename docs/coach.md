# The coach

The coach is part of the app ([app.md](app.md), the **Coach** page and the review's **Retry your mistakes**) and also exists as the older stand-alone page described below (`chessme coach`). In the app:

* **Graded feedback.** Every move you try is judged by the engine and graded: *best* (the engine's first choice), *great* (as good, within 3 points of win chance), *good* (sound, not the best, up to 6 points: it counts and you may try for the best), *inaccuracy*, *mistake* and *blunder*. Each grade comes with reasons built from the board and the engine only: what the move does, what it allows (a checkmate, a lost piece, the engine's line), what was better, and for the best move why it is better than the alternatives. A move that is not good does not give the answer away. (`chessme/coach/feedback.py`; used by drills, the review retry and opening practice.)
* **Practice** from your own mistakes on a spaced schedule (boxes of 1 day to 5 weeks).
* **Openings.** An *opening library* (about 150 named openings from the opening database, as repertoires pruned by what players of your rating really play), *your own repertoire from your games* (the moves you played in at least two games with their results; practise it and find its gaps), saved repertoires and your own PGN. All are practised against the replies players of a rating you choose (needs the explorer database).
* **Endgames** against the Syzygy tablebases, **steered games**, and **Weaknesses** (where you give away points, compared with yourself and, with the reference counts shipped in `chessme/coach/reference_rates.json`, with players of your rating).
* **Prepare against an opponent** is in [app.md](app.md#prepare-against-an-opponent).

The stand-alone page:

A local web page that takes you back over the game you just played, finds the moments where you gave away the most, asks you to find a better move, tells you in plain
sentences what went wrong and why the better move is better, and lets you play on from the corrected position against the engine. Everything runs on your computer.

```bash
.venv/bin/python -m chessme coach            # opens http://127.0.0.1:8766 ; needs Stockfish on the PATH (or --engine PATH)
.venv/bin/python -m chessme coach --nodes 300000 --port 9000 --no-browser
```

1. **Get a game**: type a Lichess or Chess.com user name (fetches the latest public games) or paste a PGN. When the name is one of the players, your side is preselected.
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

My weaknesses: each reviewed game is kept (one small JSON in `~/.mechess-coach/games`; the same game twice counts once). From them the start page shows where your own rate of mistakes (moves that give away at least 10 points of expected score) is clearly higher than elsewhere in your games: by phase and by situation (ahead, level, behind), and the kind of mistake (allowed a mate in one, did not deal with a threat, put a piece where it can be captured, a deeper loss), each with the practice that fits. A category needs at least 30 moves and a one-sided 95% test, so one bad game does not make a weakness. This compares you with yourself first. When a **reference** exists (`--reference`, default `chessme/coach/reference_rates.json` if that file is there), the profile also says where you give away points more or less often than **players of your rating**: public Lichess games, in 200-point bands and by speed (blitz, rapid), analysed with the same engine, node budget and number of lines as your reviews (the reference states them; if yours differ the comparison is flagged as rough). It uses the median rating and the speed of your most-played kind of reviewed game (games imported without ratings are skipped), and reports a difference only when it is clear after allowing for the ten or so categories looked at. Build the reference yourself with notebook 15 (`coach-reference-games`, `analyse --nodes 100000 --multipv 5`, `coach-reference-build`; see [kaggle.md](kaggle.md)); only counts of moves are kept, no games and no names.

Opening practice: paste your repertoire as a PGN with variations, say which colour you play and the rating of the players you face. The drill lets you play your side; the opponent answers with replies drawn from the opening explorer at that rating (replies chosen by at least 2% of the games), so the lines you really meet come up as often as they occur. A move that is not in your repertoire is refused with the move you prepared. The line ends when you reach the end of your prepared line, when the opponent plays something you have no answer to (with how often that happens), or when theory ends. *Check coverage* walks the explorer's tree along your repertoire and lists the most common replies you have no answer to. Needs the explorer database (`--explorer`, default `data/explorer/explorer.db`; see [opening-explorer.md](opening-explorer.md)).

Endgame practice: pick a theme (king and pawn against king, to win it or to hold the draw; queen against king; rook against king) and play it out. The position is generated at random and kept only when the tablebase says the result is the one the theme needs. Every move you make is judged exactly by the Syzygy tablebase: a move that turns a win into a draw, or a draw into a loss, is refused and explained, and the opponent always plays the strongest resistance the tablebase allows. A three-step hint and a note when a win is kept but slowly (the fifty-move rule) are included. Needs the table files (`--syzygy DIR`, default `data/syzygy`; the 3 to 5 piece set is about 1 GB, from tablebase.lichess.ovh; they are an external download and are not part of this repository). More themes (Lucena, Philidor, queen against pawn on the seventh, bishop and knight mate) need the 4 and 5 piece files and are planned.

Play a game I steer: choose what to practise (notice threats, play the endgame, convert an advantage, defend under pressure, calculate in sharp positions; one or several) and play a normal game. The opponent only plays moves the engine considers good enough (a small budget of expected score, larger for "convert") and, among those, prefers the ones that create the situation you chose. At the end the game is analysed, you get a plain report of how you did in the situations that arose (how often, and how many points you gave away there compared with the rest of the game), and then the usual replay of your biggest mistakes. In a check on 398 opponent decisions, steering raised the chance of a threat-creating move from 22% to 37% at an extra cost of under a point of expected score per move; it takes the target move whenever one is available inside the budget, so the limit is availability, not strength. This steers by simple rules on the board; whether it helps you improve has not been tested.

Privacy: the server listens on 127.0.0.1 only; your games and attempts stay in memory on this machine; the only network use is the optional Lichess fetch. The page loads no outside
scripts, fonts or images.

Built since: the weakness profile, opening practice, steered games, endgame practice with tablebases and drills with spaced repetition are all in the app. Still planned: endgame practice without the tablebase download, theme tags on drills, and an optional language-model chat whose claims are checked against the engine.
