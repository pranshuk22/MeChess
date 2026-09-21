# Roadmap

A short, honest status. MeChess is a research prototype.

## Done and tested

- C++ engine with verified move generation, alpha-beta search, transposition table, MultiPV, UCI.
- Match runner with paired openings and SPRT; Texel tuner (tuning did not improve strength so far, so the hand-set evaluation stays).
- Data pipeline: fetch, normalise, weight, audit.
- Opening book from your games, played by the engine.
- "Me" model: encoding, training, evaluation, C++ inference; a comparison harness against Maia-2 / Maia-3 on identical positions
  (their models are stronger predictors today, mostly because of far more training data).
- MeChess controller: book, engine candidates, prior, sampling, Elo dial (starting table), UCI front end.
- Strength measurement and dial calibration tooling (adaptive ladder against limited Stockfish, monotone calibration curve); see [calibration.md](calibration.md). The measurements themselves still have to be run.
- Style analysis: features, candidate datasets, choice model, population baseline, cohort and anchor tooling; game-level features and a learned
  player embedding on 999 players ([style-analysis.md](style-analysis.md)).
- **Game analysis**: move classes, accuracy and reports from Stockfish (`analyse`); move-quality features for the cohort ([game-analysis.md](game-analysis.md)).
- **Opening explorer and theory books**: exact per-band counts from the Lichess database, a queryable SQLite explorer, playable books, checkpointing
  and resuming; a first real run covered 4.0 million games ([opening-explorer.md](opening-explorer.md)).
- **Books, annotated games and a text model**: notation, glyph and figurine readers, 103 books, seven annotated-game sources, Stack Exchange and
  Wikipedia prose, a multi-task language model trained on Kaggle ([language-model.md](language-model.md)).
- **Kaggle notebooks** as thin adapters with preflight, dry-run, time budgets and resuming ([kaggle.md](kaggle.md)).
- **Lichess bot** through `lichess-bot` ([lichess-bot.md](lichess-bot.md)).

## Findings from the style cohort and anchors

Cohort (1,000 players) and anchors (35 famous players) are analysed with Stockfish as the judge. Personal move-choice style is
small and hard to measure with the current features (see [style-analysis.md](style-analysis.md)); the reliably personal parts are the
opening repertoire, the fine-tuned move-prediction model, strength focus and castling timing. Next for style: more decisions per
player, richer features (plans, structure, clocks) and game-level statistics.

## In progress

- **Recalibrating the dial** with search depth as a knob (uniform prior for the public bot first) and putting a theory book in the bot.
- **Finishing the opening explorer scan**: the first run stopped at 4% of its plan; rerun with the fix, resuming from its checkpoint.
- **Measuring the language model** on the held-out test set, and trying the early-stopping and fewer-repeated-examples changes.

## Next

1. **Learn instead of hard-code** where there is ground truth: class boundaries from human glyphs and a rating-dependent win-probability model,
   validated against Lichess's own labels; concept detectors and a position-to-concept model from the annotated games.
2. **Run the strength measurement** of our engine against Stockfish (`chessme strength`).
3. **Run the dial calibration** (`chessme calibrate`) and validate the scale against a Lichess bot account; state the rating scale honestly.
4. **Human mistake model** and **endgame model** (play endgames as well as you do, not perfectly; tablebases only to measure and shape errors).
5. **Style term in the controller**: choose among good moves with the player's fitted preferences and check that the style statistics of generated games match yours.
6. **Better priors**: history as input, more training data, few-shot personalisation for players with few games.
7. **Win-probability windows** instead of a fixed centipawn window for "good enough".
8. **Packaging**: Docker image, a small hosted bot, "train your own" walkthrough for a second user.

## Longer term

- A **coach** layer built on the same data: reports on how your play evolved, your style, your recurring mistakes, drills from
  your own errors, sparring against a version of yourself. Claims stay modest until there is evidence that it helps players improve.
- Research questions the style work can address: whether a player's style is stable across ratings and time, whether
  per-player skill scaling can be validated on the player's own history, and how human endgame errors compare with tablebases.
