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
| `calibrate` | Measure MeChess at several dial settings and write a calibration file (`--dial 1200 1500 ...`, `--out`, `--redo`, `--offset`) |

Details, scale caveats and costs: [calibration.md](calibration.md). `mechess --calibration FILE` makes `--elo` mean the measured Elo.

## Opening book

| Command | What it does |
|---|---|
| `book` | Build `book.bin` (position graph of your repertoire) and a readable report; `--sanity-engine` checks lines with an engine |

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
       --prior uniform|ours=CHECKPOINT|maia3=CHECKPOINT --elo 1600 --seed 1
```

UCI options: `Elo`, `OppElo`, `Platform`, `Seed` (with `--calibration FILE`, `Elo` is the *measured* Elo, see [calibration.md](calibration.md)). The controller plays your book while it lasts, then asks the
engine for its best lines (MultiPV), keeps those within the dial's centipawn window, lets the prior weigh them and
samples with the dial's temperature. The dial table (`chessme/mechess/dial.py`) is a set of starting values; run `calibrate` to measure them.

## Style analysis

See [style-analysis.md](style-analysis.md) for the method. Commands:

| Command | What it does |
|---|---|
| `style-data` | Build the choice-level dataset from your games: engine candidates + move features (`--engine stockfish`) |
| `style-pop-data SOURCE` | Sample a rating-matched **population** from a Lichess dump (streamed, nothing stored) |
| `style-report` | Fit the style model, evaluate on held-out games, compare with the population, write a readable report (`--baseline`, `--label`, `--out`) |
| `style-judge-compare A B` | How much does the judge engine change the data? (two dataset folders) |
| `style-cohort-fetch SOURCE` | Fetch ~50 recent games for hundreds of players (the **cohort**) via the Lichess API |
| `style-cohort-analyze` | Run the engine over the cohort (parallel, resumable) |
| `style-cohort-report` | Split-half reliability and the personal-versus-population test |
| `style-anchors-fetch` | Download famous players' archives, sample decisions from their peak years, delete the archives |
| `style-anchors-build` | Same, from game files you supply |
| `style-anchors-verify` | Check every anchor's name aliases against the archives, so spelling variants do not lose games |
| `style-summary --player DIR` | One player against everything: the cohort (what is reliably personal, in between-player SD units), the five axes (with their own reliability), the anchors at the level of style poles, the rating-matched population, and the shrunk personal-signal test. Writes a markdown summary |
| `style-status` | One-screen status of the long jobs: running processes, progress, ETA, latest log lines (`--watch N` to refresh) |
| `style-anchors-report` | Can the features tell the anchors apart? Which anchor is closest to you? |

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
