# Game analysis: move classes, accuracy and reports

`chessme analyse GAMES.pgn --player NAME` runs Stockfish over every position of the games in a PGN file, labels each move the way the popular
sites do, and writes a per-game record and a Markdown report. The classification itself is plain code (`chessme/analysis/classify.py`,
`runner.py`) that works on numbers, so every rule is unit-tested without an engine.

```bash
.venv/bin/python -m chessme analyse my_games.pgn --player MyName --out data/analysis --nodes 200000
```

It is **resumable and pausable** (one JSON file per game; `chessme control pause analyse`), analyses at a **fixed node budget** (results do not
depend on the machine), asks Stockfish for two lines per position (so "only move" is known), and takes named openings from `data/opening_names`
(`chessme theory-book --download` fetches them once).

## The scale: expected points

Every score is turned into the mover's *expected points* (0 lost, 0.5 even, 1 won) with the Lichess curve
`p = 1 / (1 + exp(-0.00368208 x cp))` (mate scores are clamped). The loss of a move is the expected points of the best move minus those of the
move played.

| Class | Rule (loss in expected points) |
|---|---|
| Best | at most 0.005 |
| Excellent | up to 0.02 |
| Good | up to 0.05 |
| Inaccuracy | up to 0.10 |
| Mistake | up to 0.20 |
| Blunder | above 0.20 |
| **Book** | the move continues a named opening line (Lichess opening names, CC0) |
| **Great** | the best move, when the runner-up is at least 0.15 worse or falls to a lower tier (winning to balanced, balanced to losing); never for a forced move |
| **Brilliant** | (almost) the best move, a real sacrifice (at least 2 pawns given, measured at the end of the engine's 5-ply line so trades do not count), the player is not worse than 0.45 afterwards, and the position was not already won (below 0.85) |
| **Miss** | an inaccuracy or mistake right after the opponent's error (which lost at least 0.10) where the gain was not taken |

The bands follow the published Chess.com scale; **the special classes are our reading of their public descriptions** (their exact rules are not
public), and all thresholds are configurable (`Thresholds`). Nothing here claims to match a site move for move: validating against Lichess's own
labels on the same games is listed in the [roadmap](roadmap.md).

## Accuracy and the rest of the report

- **Accuracy** per move follows the Lichess formula `103.1668 exp(-0.04354415 x drop) - 3.1669 + 1` (drop in win probability, in percent),
  clipped to 0-100, averaged per colour and per phase.
- **Phases**: opening until move 10 (unless the position is already an endgame), endgame when the pieces (no pawns) are worth 26 points or less.
- **Opportunism / luck** (as in Lichess Insights): how often you punish the opponent's mistakes, and how often yours go unpunished.
- **Conversion / resourcefulness** (as in Lichess Tutor): games won after reaching 66.6% win chance; games not lost after falling to 33.3%.
- The report lists the class counts, the biggest mistakes and the average over the games of the chosen player.

## Move-quality features for style

`chessme style-games-quality` runs the same analysis over a sample of the cohort's games (10 games for up to 400 players, 3 workers) and stores
per-game rates (accuracy by phase, class shares, opportunism, luck, conversion, resourcefulness). `style-quality-report` gives their reliability
and gate. They feed the style work described in [style-analysis.md](style-analysis.md).

## Limits

- The special classes are judgement calls; use the numbers (loss, accuracy), not only the labels.
- Fixed nodes, not fixed depth: very sharp positions can move between runs of a different budget.
- Clock use, time trouble and the human difficulty of a move are not part of the classification yet.
- The thresholds are hand-set today. The plan is to learn them from human glyphs (`? ?? !` in annotated games) and check them against
  Lichess: see [language-model.md](language-model.md) and the plan.
