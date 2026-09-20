# Measuring strength and calibrating the Elo dial

MeChess has an **Elo dial**: you ask for a rating and it plays at about that level. Out of the box the dial is a table of
guesses (search nodes, candidate window, sampling temperature per rating). This page describes how to *measure* what a
setting really plays at, and how to turn those measurements into a calibrated dial.

## The idea

Play games against an opponent whose strength you can set. Stockfish can be limited to a chosen Elo
(`UCI_LimitStrength` and `UCI_Elo`, see [stockfish.md](stockfish.md)). If your engine scores 64% against Stockfish at 1800,
it is about 100 Elo stronger than that opponent. Repeating this at several opponent strengths and fitting the results gives
a rating with an error bar.

## What is measured, and on which scale

- The result is an **Elo on Stockfish's `UCI_Elo` scale at the time control you used** (default 100 ms per move). It is
  **not** the Lichess or chess.com scale, and changing the time control changes it. Treat the numbers as "this
  strong relative to limited Stockfish".
- To relate it to a real platform you need an outside anchor, for example playing the engine as a bot account on Lichess
  and comparing its rating with the measured one. If you find a constant difference, put it in `--offset` (or the calibration
  file's `offset`); the offset is *not* applied unless you set it.
- MeChess chooses its own search budget from the dial (it ignores the per-move time limit given by the match runner),
  so at high dial settings it can spend more time per move than its opponent.

## The ladder (`chessme/strength.py`)

1. Guess a start rating. Play a few opening pairs (both colours) against Stockfish set to that Elo.
2. Fit the rating whose expected total score equals the actual score (logistic Elo model, maximum likelihood). Every level gets
   half a pseudo-game scored as a draw so all-win and all-loss results stay finite.
3. Play the next round against Stockfish at the *current estimate*, so games are as informative as possible.
4. Stop when the standard error is small enough (after a minimum number of games), when the game budget is used up, or when the
   engine is beyond the strongest or weakest opponent available (then it reports that instead of a number).

The 95% interval is 1.96 x the standard error. It uses the logistic Fisher information and ignores that draws carry less
variance, so it is slightly conservative; it also treats games as independent, so with few openings it can be optimistic.
Use many different openings (the default draws random 6-ply openings) and read intervals as approximate.

## Commands

Measure one engine (for example the plain alpha-beta engine):

```bash
python -m chessme strength --engine engine/build/chessme-engine \
       --movetime 100 --se 35 --max-games 400 --concurrency 4 --out data/calibration/engine_strength.json
```

Calibrate the dial (MeChess at several dial settings):

```bash
python -m chessme calibrate --engine engine/build/chessme-engine --prior uniform \
       --dial 1200 1500 1800 2100 2400 --concurrency 4 --out data/calibration/dial.json
```

Options shared by both: `--opponent` (a UCI engine with `UCI_Elo`, default `stockfish`), `--openings FILE` (default: random
openings), `--movetime`, `--pairs` (opening pairs per round), `--se`, `--min-games`, `--max-games`, `--concurrency`.
`calibrate` also takes `--book`, `--prior` (`uniform`, `ours=CHECKPOINT`, `maia3=CHECKPOINT`), `--offset`, `--redo`.
It writes the file after every dial point and skips points already measured, so it can be stopped and resumed.

Use the result:

```bash
python -m chessme mechess --calibration data/calibration/dial.json --elo 1650
```

With a calibration file, `--elo` (and the UCI option `Elo`) mean the **measured** Elo: MeChess looks up which dial
setting measured closest to 1650 and uses its knobs. Targets outside the measured range are clamped to its ends.

## From measurements to a dial

Measured points are noisy, so a higher dial could measure lower than a lower one by chance. The calibration fits a monotone
curve (isotonic regression weighted by precision) and inverts it: `Calibration.dial_for(target)` returns the dial setting
whose calibrated strength is closest to the target. Flat stretches map to their middle.

## Example result

Measured with `chessme strength --movetime 100` on a laptop (two independent runs, pooled): the plain alpha-beta engine scored
**about 2460 +/- 30 Elo on Stockfish 19's `UCI_Elo` scale** (520 games, no engine faults; the tighter run alone gave 2483 +/- 33).
The earlier, shorter run gave 2382 +/- 68, consistent within its wider interval. Your numbers depend on your machine and the time control.

## Settings that cannot be measured

Stockfish's `UCI_Elo` has a floor (about 1320) and a ceiling (about 3190). A dial setting that loses almost every game even to the
weakest Stockfish (or wins almost every game against the strongest) is *beyond the measurable range*: the ladder stops with
"weaker than the weakest opponent available" and the number it prints is an extrapolation from a handful of games, not a
measurement. Such points are kept in the calibration file (with their stop reason) but **never used to map dial settings**; targets
outside the measured range are clamped to its edge, and `Calibration.in_range(target)` says whether a target is covered. To extend the
range downward you need weaker reference opponents, for example measuring a low dial setting against a higher one and linking that
to an absolute measurement above the floor.

## Cost and practical advice

- A reliable estimate needs a few hundred games per measured engine. At 100 ms per move a game takes roughly 10 to 30 seconds,
  so one measurement is on the order of an hour on one core; `--concurrency` divides that.
- Calibrating five dial points is five measurements. Run it when the machine is otherwise idle: heavy background jobs slow the
  engines and change the results (the time control is wall-clock).
- Check `faults` in the result: an engine crash or illegal move is scored as a loss for the faulty side and would bias the estimate.
- Stockfish's `UCI_Elo` has a limited range (about 1320 to 3190 in recent versions; the code reads it from the engine). An engine
  weaker than the lowest setting cannot be measured with it.
- Re-measure after changing the engine, the prior, the book or the machine.

## Files

- `chessme/strength.py`: Elo estimation, the adaptive ladder, reading an engine's `UCI_Elo` range.
- `chessme/calibrate.py`: plays the matches (`measure`, `calibrate_dial`), builds the MeChess command.
- `chessme/mechess/calibration.py`: the monotone curve, inversion, save / load.
- `chessme/mechess/dial.py`: `settings_for(elo, table, calibration)`.
