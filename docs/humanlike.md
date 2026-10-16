# Human-likeness suite

A set of commands (`chessme humanlike-*`, all listed in [cli.md](cli.md)) that measure **how human a move model plays**, not only how often it
guesses the human's move. The models under test are external (Maia-2, Maia-3, our own checkpoints); the suite scores them on a fixed test
set built from public Lichess games, and the heavy parts run on Kaggle ([kaggle.md](kaggle.md)).

## What it measures

| Question | Commands | Answer looks like |
|---|---|---|
| Does the model predict the human's move? | `humanlike-testset`, `humanlike-score`, `humanlike-report` | top-1, sampled match, NLL, calibration, by rating, phase and the mover's clock; game-level intervals |
| How much room is left? | `humanlike-ceiling` | the opening explorer's exact counts as an oracle |
| Does it make the *errors* humans make? | `humanlike-judge`, `humanlike-errors`, `humanlike-scaling` | blunder rate of the model against the humans' on the same positions, per clock regime; slope per doubling of the parameters |
| Which kind of blunder? | `humanlike-diagnose` | mate in 1 / ignores a threat / walks into a capture / deeper, for humans and model; whether the blunder probability the model implies per position is informative and calibrated |
| Can a clock-aware correction close the gap? | `humanlike-adapter`, `humanlike-confirm` | a small adapter (clock, ratings, the model's confidence) on a frozen model; evaluated on games it never saw and on a second, untouched test set |
| Can a classifier tell generated games from human ones? | `humanlike-selfplay`, `humanlike-humangames`, `humanlike-c2st` | AUC of a two-sample test on moves only, with dose-response and human-against-human controls |
| Can people tell them apart? | `humanlike-stimuli` | stimuli and answer key for a forced-choice study (the study itself is not run yet) |
| Strength against human-likeness | `humanlike-frontier`, `humanlike-arena` | the trade-off for policies built from the human prior and engine losses; Elo against a Stockfish node ladder |

## Rules the suite keeps

* The test sets are fixed by a hash of the game, with a manifest; a second set shares no game with the first and is used only to confirm what the
  first suggested. Hypotheses and the criteria to judge them are written down before the data is looked at.
* Every number carries an interval that resamples whole games, not positions.
* "Blunder" is the engine's verdict (Stockfish, pinned node budget, expected points given away); the blunder *types* are rules on the board
  and the move alone.
* Generated games and human games start from the same positions, with the same clocks and ratings.

## What it found so far (preliminary, one speed and one month of games)

Reported with the numbers and the intervals in the accompanying paper when it is out; the short version, checked on the confirmation set:

* Maia-3 (23M and 79M parameters) makes fewer blunders than humans do when the human has under 10 seconds left; the gap is smaller for the 5M
  model and not shown there. With ample time the models are close to the humans.
* Larger models blunder less in every clock regime (about 0.2 points per doubling of the parameters).
* The missing blunders are mostly the one-move kind (putting a piece where it can be taken, ignoring a threat).
* A small clock-aware adapter brings the under-10-second gap to within noise on the second test set, without costing likelihood at long clocks (the gap stays uncertain: the interval includes small differences either way).
* These are measurements of one model family on one source of games. They do not say a model is "indistinguishable" from people; the
  classifier and human-study parts exist to test that, and the classifier still separates generated games from human ones.

## Not included

Maia, Allie, Stockfish and tablebase files are downloaded by the user and never bundled ([third-party.md](third-party.md)).


## MeChess in the app: choosing like a person from your own games

MeChess (the opponent in Play) takes the engine's sound candidate moves and chooses among them with a **prior**. With the uniform prior that choice is almost random, which does not feel human. In the app the prior is a move-choice model (`chessme.style`: a conditional logit over move features such as captures, checks, castling, king attacks, pawn breaks) learned from your own library: the app samples a few thousand decisions from your games (from move 10), asks Stockfish for the sound candidates at each, and fits the model; held-out decisions say how much better than a random choice it predicts (a pilot on 300 games: the human's move was picked 49% of the time, a random choice 26%). Two models: the typical players of your library, and you. Its slips (the weak levels' blunder knob) are drawn mostly with the same weights, so they are moves a person would be tempted by. The strength dial was calibrated with the uniform prior; with a learned prior the rating is a rough guide until it is measured again. The computer's thinking time (`app/pacing.py`) follows a person's pace: quick for the first moves and a recapture, longer in tense positions, scaled by strength and by the clock.
