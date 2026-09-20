# Style analysis

**Question:** among moves that are about equally good, which one does this player tend to choose?
Style is measured *at the choice level*, so it is not confounded by the opening, the rating or the opponent.

## The pieces

1. **Judge** ([Stockfish](stockfish.md)): for each decision, the engine's best lines (MultiPV 8, 20,000 nodes) give the
   *candidate set*: moves within a window (default 60 cp) of the best. Positions with a single good move carry no
   style information and are skipped. If the played move is not a candidate, the player made a mistake; that position is
   counted but not used for the style fit.
2. **Move features** (`chessme/style/features.py`): 28 numbers per move, from chess theory and computed from the board only:
   forcing (capture, check, promotion, castling side); material (sacrifice, exchange sacrifice, trade, queen trade, via a
   static-exchange evaluator); king (pressure on the enemy king zone, pawn storm, weakening your own king); pawn
   structure (pawn break, doubled / isolated / passed pawn changes for both sides, bishop pair); files (rook on open /
   semi-open file, seventh rank); activity (mobility change, central squares, pushes, retreats, king moves).
3. **Choice model** (`chessme/style/model.py`): a conditional logit. The probability of choosing move *m* among the
   candidates is a softmax of `w . z(features) - c * loss(m)`, where `z` standardises each feature and `c` measures how much
   the player cares about strength. The fitted weights `w` are the player's preferences. On held-out games we report
   accuracy against picking at random and against a strength-only model.
4. **Population baseline** (`style-pop-data`): the same data from thousands of other players (Lichess dump, streamed,
   balanced per 100-point rating bin over a wide range). The player's weights are compared with the population's
   expected weights at the player's rating; a z-score says how many standard errors apart they are. The
   readable report (`style-report --baseline ... --out report.md`) puts this in words.
5. **Cohort** (`style-cohort-*`): hundreds of individual players with about 50 games each. Two tests decide whether style
   is a measurable trait at all:
   - *split-half reliability*: fit each player on alternating halves of their games; the covariance of the two halves
     across players is the true between-player variance of each preference and the correlation is its reliability;
   - *trait test*: does a player's fitted style predict their other half better than the population's style does?
   A *fair* version shrinks each preference towards the population by its own reliability (estimated on other players), the
   standard estimator when individual fits are noisy. The cohort also gives the honest yardstick for "unusual": z-scores against
   the between-player spread, not just sampling noise.
6. **Anchors** (`style-anchors-*`, `configs/anchors.yaml`): famous players (attackers, defenders, positional players,
   universal players) sampled from their peak years, about 100 classical games each. They give the report its
   vocabulary. Two checks: can the features tell the anchors apart (a confusion matrix on held-out chunks), and whose
   preferences predict your choices best. Anchors are landmarks; the wide cohort, not the anchors, is the
   yardstick for "how unusual are you".
7. **Judge comparison** (`style-judge-compare`): how much the choice of judge changes candidate sets and results.

## Findings so far

From a cohort of 1,000 Lichess players (rated 1500 to 2600, blitz and rapid, 50 games each, about 128 usable decisions per half,
Stockfish as the judge) and 35 famous anchor players (100 classical peak-year games each). These are aggregates; the numbers
depend on the feature set and the amount of data and will change with either.

- **Most of "style" is shared.** Choosing among near-equal moves is predicted about 5 points better by the 28 features
  (which every player shares to a similar degree) than by move strength alone.
- **The personal part is small.** Trusting a player's own fitted preferences fully predicts their other games *worse* than the
  population's preferences (about 128 decisions cannot support 28 personal weights). Shrinking each preference towards the
  population by its own reliability does give a small but real gain (about +0.002 log-loss per decision, roughly 5 standard
  errors over 500 players). Style differences between players exist, but these features barely see them.
- **What is reliably personal:** how much a player cares about move strength (reliability about 0.4) and castling timing
  (about 0.3); then mobility, pawn pushes and pawn breaks (0.14 to 0.19). Most other preferences have reliability under 0.1.
- **Anchors cannot be told apart.** A 35-way classification of held-out chunks from the famous anchor players is at chance
  (3%), so claims such as "closest to player X" are not supported by these features at this data volume.
- **Consequence.** Do not describe a player as "aggressive" or "positional" from these features alone. The parts of "plays like
  me" that are clearly personal are the opening repertoire, the move-prediction model fine-tuned on the player's games, time use, and
  how much the player cares about strength.

Ideas that could raise the signal: many more decisions per player, features that see plans and structure over several moves,
clock-based features (time use is likely a strong personal trait), and game-level statistics (opening choice, castling ply,
length of games) in addition to move-level choices.

## Order of a full run

```
style-data       -> your dataset            style-pop-data -> population baseline
style-report --baseline ...   -> readable report

style-cohort-fetch -> style-cohort-analyze -> style-cohort-report        (is style a stable trait?)
style-anchors-fetch -> style-cohort-analyze --out data/style/anchors -> style-anchors-report
```

## Things to know

- **Judge matters.** With a weak judge, differences between a player and the population were exaggerated. Use Stockfish.
- **Multiple comparisons.** With 28 features some z-scores above 2 are expected by chance. Read the report's list of
  differences with that in mind.
- **Approximate peak years.** The anchor windows in `configs/anchors.yaml` are approximate and should be checked
  against rating histories.
- **Name spellings.** Game archives spell the same player differently (`Jobava,Ba`, `Kortschnoj, Viktor`). The anchor fetch logs
  the names it finds and warns about unmatched ones; `style-anchors-verify` checks every anchor against the archive page.
- **Limits.** The feature set cannot see plans, prophylaxis or move-order ideas. Online blitz and over-the-board classical
  games differ. Style is only measured among near-equal moves; mistakes are a different topic.
