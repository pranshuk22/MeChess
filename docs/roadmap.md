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
- Style analysis: features, candidate datasets, choice model, population baseline, cohort and anchor tooling.

## In progress

- Running the cohort (hundreds of players, about 50 games each) and the anchors (famous players' peak-year games) with
  Stockfish as the judge, to find out whether style is a stable, measurable trait and how much players differ.

## Next

1. **Mistake labelling**: centipawn (or win-probability) loss per move in your games; kinds of positions where you err.
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
