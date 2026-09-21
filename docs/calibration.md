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

### The weak end of the dial

Below the search floor, fewer nodes or a wider candidate window stop weakening the play measurably (the two lowest of the original settings
played equally). The built-in table now has a smooth path for the weak end (`chessme/mechess/design.py`, `chessme dial-design`): the node
budget rises geometrically from a very weak row towards the 1800 row while a **blunder rate** (the probability of playing a random legal
move instead of the chosen one), the candidate window, the temperature and the cp scale ease towards the 1800 values. Measured with
direct games between adjacent settings (200 games per link, uniform prior), every step is distinguishable:

| Dial setting | 1000 | 1200 | 1300 | 1400 | 1500 | 1600 | 1700 | 1800 |
|---|---|---|---|---|---|---|---|---|
| Measured (Stockfish scale) | ~370 | ~430 | ~520 | ~600 | ~720 | ~990 | ~1090 | ~1240 |

The uncertainty grows down the chain (about +/-150 at the bottom, 95%). Two pitfalls this exposed: the UCI `Elo` option used to clamp at 800,
so labels below it silently played as 800; and steps smaller than about 100 Elo are invisible at 80 games (a 0.06 change in blunder rate is
about 40 Elo), so use larger steps or more games per link.

### Calibrate with the prior you will play with

The strength of a dial setting depends on the prior. With the same search settings, MeChess using a personalised Maia-3 model and an opening
book measured about 400 Elo stronger at settings 1800 and 2100 than with the uniform prior (which lets the wide window pick weak moves).
Calibrate with the exact prior, book and table you will use, for example:

```bash
python -m chessme calibrate --table my_table.json --prior maia3=CHECKPOINT --maia3-repo PATH --extra-path LIBS \
       --book book.bin --dial 1000 1200 1300 1400 1500 1600 1700 1800 2100 2400 2600 --concurrency 3 --out dial_mine.json
python -m chessme calibrate-link --calibration dial_mine.json --table my_table.json --prior maia3=CHECKPOINT ... --link-pairs 100
python -m chessme mechess --calibration dial_mine.json --prior maia3=CHECKPOINT ... --elo 1500
```

With a personalised prior and an opening book the measured strengths of the same dial settings were (Stockfish scale): 1000 about 830, 1200 about 940,
1300 about 960, 1400 about 1030, 1500 about 1140, 1600 about 1390, 1700 about 1430, 1800 about 1630, 2100 about 1960, 2400 about 2340, 2600 about 2500
(the lowest five linked by direct games, the rest measured against Stockfish; 100 to 200 games each, no engine faults).

Neural priors are started with one CPU thread per game (`OMP_NUM_THREADS=1`) so that parallel games do not fight over cores; memory use
is around 1.8 GB for three parallel games. A calibration file records the dial table it was measured with, and `mechess --calibration`
uses that table automatically.

### Example dial calibration

MeChess with the uniform prior, 100 ms per move, against Stockfish 19 (one laptop; 110 to 120 games per measured point, no engine
faults). Your numbers will differ with the machine, the prior, the book and the time control.

| Dial setting | Measured (Stockfish `UCI_Elo` scale) | How |
|---|---|---|
| 1200 | about 700 +/- 210 | linked to dial 1500 (below Stockfish's lowest setting) |
| 1500 | about 700 +/- 200 | linked to dial 1800 (below Stockfish's lowest setting) |
| 1800 | 1236 +/- 69 | against Stockfish |
| 2100 | 1531 +/- 68 | against Stockfish |
| 2400 | 2048 +/- 66 | against Stockfish |
| 2600 | 2344 +/- 66 | against Stockfish |

What it showed: the starting table's labels were far too high (setting 1800 plays about 1240 on this scale); the two lowest settings play
equally strongly (they scored 50% against each other), so the dial has no resolution down there; the top setting approaches, but stays
below, the plain engine (about 2460). With the calibration file, a target of 1500 maps to setting 2069 (about 13,000 search nodes), 2000
to setting 2372. Relating this scale to the Lichess rating scale still needs an outside check.

## Settings that cannot be measured

Stockfish's `UCI_Elo` has a floor (about 1320) and a ceiling (about 3190). A dial setting that loses almost every game even to the
weakest Stockfish (or wins almost every game against the strongest) is *beyond the measurable range*: the ladder stops with
"weaker than the weakest opponent available" and the number it prints is an extrapolation from a handful of games, not a
measurement. Such points are kept in the calibration file (with their stop reason) but **never used to map dial settings**; targets
outside the measured range are clamped to its edge, and `Calibration.in_range(target)` says whether a target is covered. To extend the
range downward you need weaker reference opponents, for example measuring a low dial setting against a higher one and linking that
to an absolute measurement above the floor.

### Linking them (`calibrate-link`)

```bash
python -m chessme calibrate-link --calibration data/calibration/dial.json --prior uniform --link-pairs 40 --concurrency 3
```

For every dial setting that could not be measured, MeChess plays that setting against the next dial setting up (direct games, same
openings scheme) and all settings are then fitted jointly (`strength.joint_fit`): the settings measured against Stockfish are
*anchors* (each acts as a Gaussian prior with its own standard error) and the linked ones get the rating their games imply. Chains
work (1200 linked to 1500, 1500 linked to 1800); the standard error grows along the chain and is stored with each point. The
extrapolated number is kept as `raw_measured`, and the file records the games under `links`, so a rerun replays nothing (`--redo` plays
them again). Lopsided links (under 10% or over 90%) are flagged in the log: play more games. A linked rating is only as good as the
absolute measurement it hangs on, so run it after `calibrate` has measured the higher settings, and never at the same time (both are
wall-clock measurements).

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


## Search depth as a knob (redesign of the weak end)

Measuring the first dial showed that node budgets with MultiPV 5 reach only depth 2 to 3, so at the weak end fewer nodes or a wider window no
longer weakened the play measurably, and the bot gave games away. The dial table therefore has an eighth column, `depth` (0 = none), sent to the
engine as `go depth D nodes N` (whichever limit is reached first). A depth-limited search is cheap (MultiPV 5: depth 3 about 38k nodes and 36 ms,
depth 6 about 219k nodes and 196 ms) and already sees a simple fork at depth 3.

A new table (`data/calibration/table_v3.json`, weak levels depth 2 to 3 with a small random-move rate, mid levels depth 4 to 5, top levels
node-capped) is defined **but has not been measured yet**: a first 10-game probe put the depth-4 row near 1,620 on the Stockfish scale against
about 1,240 for the old 1,800 row, which only shows that the knob changes strength a lot. The full calibration (uniform prior first, for the public
bot; then the personalised prior) is the next measurement.
