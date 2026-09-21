# Command reference

Everything is `python -m chessme <command>` (or `chessme <command>` after `pip install -e .`).
Run any command with `-h` for all options. Commands that take `--profile` default to
`$CHESSME_PROFILE` (or `example`).

## Data

| Command | What it does |
|---|---|
| `fetch` | Download games for the profile's accounts (Lichess API, chess.com API). Incremental: reruns fetch only new games |
| `ingest` | Normalise raw PGNs into `data/processed/games.jsonl` (one row per game: ratings, time class, moves, clocks, ...) |
| `audit` | Print a data report: games per account and time class, rating over time, colour split, openings |
| `openings` | Build a file of starting positions (from your games or random) for engine matches |

## Engine, tuning, matches

| Command | What it does |
|---|---|
| `match --a ENGINE --b ENGINE --openings FILE` | Play engine A against engine B with paired openings; optional `--sprt ELO0 ELO1` sequential test; `--nodes / --depth / --movetime`, `--concurrency`, `--pgn` output |
| `selfplay` | Generate `FEN | result` data by engine self-play |
| `texel-data` | Tuning positions from your own games (weighted by the profile filters) |
| `tune` | Fit evaluation parameters with the C++ Texel tuner (`engine/build/texel`) |

## Strength and the Elo dial

| Command | What it does |
|---|---|
| `strength` | Measure an engine's strength with an adaptive ladder against Stockfish at known `UCI_Elo` (result on that scale) |
| `calibrate-link` | Measure dial settings beyond Stockfish's UCI_Elo range by playing them against the next dial setting and fitting all settings jointly |
| `calibrate` | Measure MeChess at several dial settings and write a calibration file (`--dial 1200 1500 ...`, `--out`, `--redo`, `--offset`) |

Details, scale caveats and costs: [calibration.md](calibration.md). `mechess --calibration FILE` makes `--elo` mean the measured Elo.

## Opening book

| Command | What it does |
|---|---|
| `book` | Build `book.bin` (position graph of your repertoire) and a readable report; `--sanity-engine` checks lines with an engine |
| `theory-book --out FILE` | Build an opening book of known theory for both colours from the CC0 Lichess opening names (`--download` fetches them), weighted by what players in a rating band play (`--games COHORT --band LO HI`, or `--pgn FILES`). Popular moves beyond the names are added when played often enough. `mechess --book DIR` picks the band of the target Elo from files named `theory_LO_HI.bin` |
| `explorer-build` | Build an opening explorer (SQLite) and a theory book per rating band from a Lichess database dump, streamed (`--source URL`, `--sample-every N`, `--max-scan N`); resumable; `--check` tests the source in seconds |
| `explorer-query DB` | Look a position up in the explorer: the moves played there at a rating with games, share, average rating, engine evaluation and the White / draw / Black bar (`--fen`, `--rating`) |
| `explorer-rebuild STATE` | Rebuild `explorer.db`, the books and the report from a saved checkpoint with other thresholds (`--db-min-games`, `--book-min-games`, `--eval-margin`, `--max-ply`), without streaming again |

Use it in the engine with the UCI options `OwnBook`, `BookFile`, `BookMaxPly`, `BookTemperature`, `BookSeed`.

## The "me" model (move prediction)

| Command | What it does |
|---|---|
| `me-data` | Build training shards, either from a Lichess `.pgn.zst` dump (rating-balanced quotas) or from your own games (`user`, time-split into train / val / test) |
| `me-train` | Train or fine-tune the residual conv net |
| `me-eval` | Evaluate a checkpoint on a val / test shard (top-1, top-3, by game phase) |
| `me-baseline` | How often the engine's best move equals the human move (a reference line) |
| `me-fix-ep`, `me-merge` | Housekeeping for shards (en-passant encoding rule; merging data folders) |
| `me-compare` | Compare models on **identical positions**: ours, Maia-3, Maia-2 (`--scorer ours=PATH`, `maia3=5m+history`, `maia2=blitz`) |
| `me-maia3-ft` | Personalise a locally downloaded Maia-3 model on your games (CPU-friendly; needs the Maia-3 checkout, see [third-party](third-party.md)) |

## MeChess controller

`mechess` runs the controller as a UCI engine:

```
python -m chessme mechess --engine engine/build/chessme-engine --book book.bin \
       --prior uniform|ours=CHECKPOINT|maia3=CHECKPOINT|style=MODEL.json --elo 1600 --seed 1
```

`--book` takes several books in priority order, separated by commas, and a folder means one theory book per rating band (`theory_LO_HI.bin`; the
band of the Elo being played is used). `--book my/book.bin,data/explorer` plays your own repertoire where it knows the position and otherwise the
theory of the level. `--prior style=MODEL.json` (from `style-model-fit`) weighs the engine's good moves by your fitted move-choice taste
(seeks/avoids captures, trades, king attacks, pawn breaks ...); `--style-strength` scales it (0 = off, 1 = as fitted).

UCI options: `Elo`, `OppElo`, `Platform`, `Seed` (with `--calibration FILE`, `Elo` is the *measured* Elo, see [calibration.md](calibration.md)). The controller plays your book while it lasts, then asks the
engine for its best lines (MultiPV), keeps those within the dial's centipawn window, lets the prior weigh them and
samples with the dial's temperature. The dial table (`chessme/mechess/dial.py`) is a set of starting values; run `calibrate` to measure them.

## Style analysis

See [style-analysis.md](style-analysis.md) for the method. Commands:

| Command | What it does |
|---|---|
| `style-data` | Build the choice-level dataset from your games: engine candidates + move features (`--engine stockfish`) |
| `style-pop-data SOURCE` | Sample a rating-matched **population** from a Lichess dump (streamed, nothing stored) |
| `style-model-fit` | Fit your style model on a `style-data` folder, print how much better than a strength-only model it predicts your held-out choices, and save it for the bot (`--data`, `--out`, `--l2`) |
| `style-anchors-games` | Game-level features (openings, game shape) of each anchor's peak-year games from PGN Mentor, one anchor at a time, archives deleted, resumable (`--only`, `--max-games`, `--files`) |
| `style-anchors-games-report` | Can the game-level features and the trained embedding tell the anchors apart, does the embedding see era rather than style, and how far are the anchors from the online cohort (`--data`, `--embed`, `--cohort`, `--out`) |
| `style-report` | Fit the style model, evaluate on held-out games, compare with the population, write a readable report (`--baseline`, `--label`, `--out`) |
| `style-judge-compare A B` | How much does the judge engine change the data? (two dataset folders) |
| `style-cohort-fetch SOURCE` | Fetch ~50 recent games for hundreds of players (the **cohort**) via the Lichess API |
| `style-cohort-analyze` | Run the engine over the cohort (parallel, resumable) |
| `style-cohort-report` | Split-half reliability and the personal-versus-population test |
| `style-anchors-fetch` | Download famous players' archives, sample decisions from their peak years, delete the archives |
| `style-anchors-build` | Same, from game files you supply |
| `style-anchors-verify` | Check every anchor's name aliases against the archives, so spelling variants do not lose games |
| `style-summary --player DIR` | One player against everything: the cohort (what is reliably personal, in between-player SD units), the five axes (with their own reliability), the anchors at the level of style poles, the rating-matched population, and the shrunk personal-signal test. Writes a markdown summary |
| `style-rates` | Reliability across the cohort of plain habit rates (no engine); with `--anchors` whether they separate the anchors, with `--player` a player's habit profile |
| `style-status` | One-screen status of the long jobs: running processes, progress, ETA, latest log lines (`--watch N` to refresh) |
| `style-anchors-report` | Can the features tell the anchors apart? Which anchor is closest to you? |
| `style-games-fetch` | Refetch each cohort player's games with clocks and openings and compute the game-level features (resumable; `chessme control pause fetch2`) |
| `style-games-report` | Reliability of the game-level features, the pre-fixed keep rule, identification of players (with the time-control-only baseline) and held-out factors |
| `style-embed-train` | Train the contrastive player embedding on the game-level features (resumable, pausable); reports held-out identification, also among rating-matched players, and how much of the embedding is rating |
| `analyse PGN` | Analyse the games of a PGN file with Stockfish: every move classed (book, brilliant, great, best, excellent, good, inaccuracy, mistake, miss, blunder), accuracy by phase, opportunism / luck, conversion / resourcefulness, biggest mistakes; one file per game, so a stopped run resumes (`--player NAME` picks a side, `--nodes N` fixes the budget) |

## Engine UCI options

`engine/build/chessme-engine` speaks UCI. Options:

| Option | Default | Meaning |
|---|---|---|
| `Hash` | 16 | transposition table size in MB |
| `Clear Hash` | button | clear the table |
| `MultiPV` | 1 | report this many best root lines (needed for candidate moves) |
| `EvalFile` | empty | load evaluation parameters from a file (e.g. `engine/params/tuned_selfplay.txt`) |
| `OwnBook`, `BookFile`, `BookMaxPly`, `BookTemperature`, `BookSeed` | | play a `book.bin` built by `chessme book` |
| `MeNetFile`, `MeRating`, `MeOppRating`, `MePlatform` | | use an exported "me" network as the move prior (C++ inference) |

Search limits: `go nodes N`, `go depth D`, `go movetime MS`, plus the usual clock arguments.


## Language model, books and annotated games

See [language-model.md](language-model.md). Every step is resumable and can be paused or stopped with `chessme control`.

| Command | What it does |
|---|---|
| `books-preflight` | Check dependencies, disk, every download URL and the GPU before a long run (exit code 1 on failure); `--need-gpu`, `--backend transformer --model NAME` |
| `books-learn` | Everything in one command: the public-domain books, concept-line pairs, the annotated-game sources, Stack Exchange and Wikipedia prose, a report (`--steps`, `--limit-per-source` for a trial, `--slim` to drop the raw downloads) |
| `books-fetch` | Only the books: download the texts listed in `chessme/books/sources.json` and extract game lines and concept counts |
| `books-studies` | Export public Lichess studies by author or study id (one request at a time, waits a minute after HTTP 429) |
| `books-pdf` | Read PDFs you own (text layer) with the book reader; a scan is reported as needing OCR |
| `books-topics` | Cluster the paragraphs of the books into topics (needs `sentence-transformers`) |
| `books-nlp-train` | Train the chess-text language model (concepts, move judgement, evaluation): `--backend bow|transformer`, `--dry-run`, `--deadline-minutes`, `--patience`, `--lab-per-batch`, `--dropout`, `--data-dir` / `--input-root` (Kaggle) |
| `books-nlp-report` | Print the held-out metrics of a trained model, which model was kept and whether it stopped early |
| `books-nlp-label` | Label every annotated move's comment with a trained model (concepts, verdict, evaluation) into `labelled.jsonl.gz`, with a report; resumable, `--limit`, `--deadline-minutes`, `--variant concepts`; on Kaggle `--input-root` finds the data and the model ([details](language-model.md)) |
| `books-nlp-predict` | Read comments with a trained model (`--variant concepts` for the best concept-only model) |

## Move-quality features and jobs

| Command | What it does |
|---|---|
| `style-games-quality` | Engine move-quality features (accuracy by phase, class rates, opportunism, luck, conversion, resourcefulness) for a sample of the cohort; resumable, pausable |
| `style-quality-report` | Reliability and quality gate of those features |
| `dial-design` | Design the weak end of the dial: a table of settings and a calibration skeleton to link (see [calibration.md](calibration.md)) |
| `control pause|resume|stop|clear|status [job]` | Pause, resume or stop long jobs; they check a control folder between units of work ([operations.md](operations.md)) |
