# Architecture

```
engine/                         C++17
  src/board/                    bitboards, magic bitboards, position, make/unmake, Zobrist hashing
  src/movegen/                  legal move generation (verified by perft against published suites)
  src/eval/                     hand-crafted evaluation, linear in a flat parameter vector; params file IO
  src/search/                   negamax / PVS, TT, killers / history, quiescence, null-move, LMR, futility,
                                aspiration windows, MultiPV, time management
  src/tune/                     Texel tuner (Adam over sparse feature traces)
  src/book/                     opening-book reader (book.bin)
  src/net/                      inference for the exported "me" network
  src/uci/                      UCI front end
  tools/                        perft, texel
  tests/                        unit tests (own small framework) + a cross-check against python-chess
  params/                       tuned evaluation parameter files

chessme/                        Python
  cli.py                        every command (see docs/cli.md)
  config.py, audit.py           profiles, data audit
  ingest/                       Lichess / chess.com download, normalisation
  dataset/                      recency and time-control weights; tuning data
  book/                         opening-book graph: keys, tree, format, reports, hold-out evaluation
  model/                        the "me" model: board encoding, network, training, export, comparison harness
  mechess/                      the controller: dial, priors, UCI front end
  style/                        style analysis: features, candidates, model, population, cohort, anchors
  uci_client.py                 talks UCI to any engine (ours or Stockfish)
  match.py, sprt.py, selfplay.py, openings.py    engine matches and data generation

configs/                        example profile; anchor players
tests/                          Python unit and integration tests (fake engine included)
tools/                          long-job helpers (memory guard, pipelines)
docs/                           this documentation
```

## Data flow

1. **Games** are downloaded (`fetch`), normalised (`ingest`) into one JSON line per game, and weighted (recency, time
   class, early-versus-late plies for fast games).
2. **Opening book**: every position reached in your games becomes a node with its outgoing moves, frequencies and
   results; habit filters (`book:` in the profile) keep what you repeat. Positions are keyed by a 64-bit FNV-1a hash of
   "board, side, castling"; Python and C++ agree on the key (pinned by test constants).
3. **"Me" model**: positions are encoded from the mover's point of view (20 planes: pieces, castling, en passant, mover
   rating, opponent rating, platform), the policy is 4,168 moves (from x to squares + under-promotions) with a factorised
   from/to head. It is pretrained on rating-balanced Lichess data and fine-tuned on your games. The C++ engine can load
   the exported weights; outputs match PyTorch to about 2e-4.
4. **Controller** (`mechess`): book, then the engine's MultiPV lines within the dial's window, a prior weighs them, sampling
   with the dial's temperature. Prior options: uniform, our model, or a personalised Maia-3 (external).
5. **Style analysis** ([details](style-analysis.md)): judge engine candidates, move features, conditional-logit choice
   model, population / cohort / anchors.

## Design choices worth knowing

- **Config-driven, per profile.** No account, path or rating is hard-coded; a profile file says who you are.
- **Separate rating scales.** Lichess and chess.com ratings are kept apart everywhere (chess.com runs lower).
- **Deterministic and reproducible.** Pinned requirements, seeded sampling, node-limited engine searches, dataset files
  that record their judge.
- **External models are optional.** Maia-2 / Maia-3 and Stockfish are used only as external programs or data you
  obtain yourself ([third-party](third-party.md)).
