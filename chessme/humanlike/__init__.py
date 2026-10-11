"""Measuring how human-like a chess move model is, beyond top-1 move matching.

  metrics.py   pure functions: top-1 / NLL / calibration, strata, paired cluster bootstrap
  testset.py   builds a fixed test set of positions (with clocks, history and rating) from Lichess games
  score.py     runs any `compare.Scorer` over a test set and writes one record per position

The Maia models are loaded from separate checkouts the caller provides (AGPL: never copied into this project)."""
