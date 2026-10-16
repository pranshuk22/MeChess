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
  book/                         opening-book graph: keys, tree, format, reports, hold-out evaluation; theory.py (theory books from opening
                                names) and explorer.py (the opening explorer built from the Lichess database)
  model/                        the "me" model: board encoding, network, training, export, comparison harness
  mechess/                      the controller: dial, priors, UCI front end
  style/                        style analysis: features, candidates, model, population, cohort, anchors; game-level features,
                                the player embedding, move-quality features
  analysis/                     move classification (win-probability scale, classes), the game runner behind `analyse`, game accuracy (accuracy.py),
                                performance rating (performance.py), plain-language reasons for a move (explain.py), tactical motifs (motifs.py)
  coach/                        feedback on a move (feedback.py), drills, exercises, openings and the opening library (library.py), endgames,
                                steering, the weakness profile and the reference counts (reference.py, reference_rates.json)
  prep/                         preparing against an opponent: their games, position graph, traps and the expected-result planner, weaknesses, report
  mechess/humanprior.py         learns a human move-choice model from the player's own games (used as MeChess's prior)
  openings_db.py                the name of an opening from its moves (packed Lichess chess-openings data, CC0)
  app/                          the web app's server: FastAPI routers, SQLite (SQLAlchemy, Alembic migrations), background jobs, live analysis
                                (WebSocket), play (clocks, human pacing), preparation job, profile service, security; `chessme app`
  books/                        chess books and annotated games: notation and glyph readers, sources, corpora, the language model, preflight
  jobs.py                       pause / resume / stop for long jobs; a worker pool that cannot hang on a dead worker
  kaggle.py                     the Kaggle glue used by the notebooks (linking inputs, restoring checkpoints, slimming outputs)
  uci_client.py                 talks UCI to any engine (ours or Stockfish)
  match.py, sprt.py, selfplay.py, openings.py    engine matches and data generation

frontend/                       the app's pages: React, TypeScript, Tailwind; src/board is our own board component; e2e/ holds the browser tests
configs/                        example profile; anchor players
notebooks/                      three thin Kaggle adapters (collect data, train the language model, opening explorer)
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

6. **Game analysis** ([details](game-analysis.md)): Stockfish evaluates every position of your games; expected points give the class of each
   move, accuracy and the report.
7. **Opening explorer** ([details](opening-explorer.md)): the Lichess database is streamed and counted per rating band; the result is a
   queryable database and a playable book per band.
8. **Books, annotated games and the language model** ([details](language-model.md)): text and glyphs are read, a small model learns concepts,
   move judgements and evaluations from comments.

9. **The app** ([details](app.md)): the server keeps games, analyses (with the engine's lines for every move), practice positions and an opening
   evaluation cache in one SQLite file; analysis, imports, preparations and style training are background jobs with progress; the pages talk to it over
   a typed API (TypeScript types generated from the OpenAPI description) and a WebSocket for live engine lines. The review's reasons, performance and
   the profile are computed from the stored analyses, not from a second engine run.
10. **Preparing against an opponent**: their public games are analysed with the same cache; a position graph of what they play gives the traps (their usual
    move gives away points) and a planner that picks, at each of your turns, the move with the best *expected* result against their observed replies,
    within a tolerance of the engine's best (or a little more when they have often fallen for the line).

## Design choices worth knowing

- **One CLI, isolated features.** Every command is in one CLI, and the bot starts the engine through it, so feature modules are imported only when
  their command runs; a test breaks every feature module in turn and requires the CLI to still start.
- **Exact counts and honest labels.** The explorer counts every qualifying game (no sampling), reports what it dropped, and states each band's
  window; statistics carry the number of games they rest on.
- **Long jobs are resumable by construction**: units of work are small, results are written atomically, and a stopped run continues from where
  it was (and gives the same result as an uninterrupted one).

- **Config-driven, per profile.** No account, path or rating is hard-coded; a profile file says who you are.
- **Separate rating scales.** Lichess and chess.com ratings are kept apart everywhere (chess.com runs lower).
- **Deterministic and reproducible.** Pinned requirements, seeded sampling, node-limited engine searches, dataset files
  that record their judge.
- **The app is local and private.** It listens on 127.0.0.1, needs a per-run access key, makes requests only to the public game APIs when you ask, and keeps
  everything in one folder you can delete; the frontend loads no outside script, font or image (a test fails otherwise).
- **Honest numbers.** A figure says how many games or moves it rests on (intervals for performance, a minimum of games for habits and openings); the
  accuracy method was checked against Lichess's own figures on games they analysed.
- **External models are optional.** Maia-2 / Maia-3 and Stockfish are used only as external programs or data you
  obtain yourself ([third-party](third-party.md)).
