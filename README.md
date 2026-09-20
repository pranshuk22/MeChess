# MeChess

**A chess engine that plays like *you*, at a rating you choose, trained on your own games.**

MeChess is a source-available, config-driven research project (free for research, learning and other non-commercial use): a C++ alpha-beta engine, a Python
toolkit that learns a player's openings, move preferences and style from their public games, and
a controller that combines them into one UCI engine with an Elo dial. Anyone can point it at their
own Lichess / chess.com accounts and train a personal model; nothing about a person is built into
the code.

> **Status: research prototype.** The engine, data pipeline, opening book, move-prediction model,
> controller and style analysis work and are tested. The Elo dial is *not calibrated yet* and there
> is no packaged release. See the [roadmap](docs/roadmap.md) for what is done and what is next.

## What it does

| Part | What it is | State |
|---|---|---|
| **Engine** (`engine/`, C++17) | Bitboards + magic move generation, negamax / PVS alpha-beta, transposition table, quiescence, null-move, LMR, futility, aspiration, time management, MultiPV, UCI. Move generation is verified against published perft suites | working, well tested |
| **Data pipeline** (`chessme/ingest`, `dataset`) | Downloads your games (Lichess API, chess.com API), normalises them, weights them by recency and time control, audits them | working |
| **Opening book** (`chessme/book`) | A position graph of *your* repertoire with frequencies; the engine can play it (`OwnBook`) | working |
| **"Me" model** (`chessme/model`) | A small residual conv net that predicts the move you would play at a given rating; C++ inference; comparison harness against Maia-2 / Maia-3 | working |
| **Controller** (`chessme/mechess`) | A UCI engine: opening book, then engine candidate moves, then a prior picks among them; Elo dial | working, dial uncalibrated |
| **Style analysis** (`chessme/style`) | Measures *which of several equally good moves* a player tends to choose (28 theory-based features), compares with a rating-matched population, a cohort of players, and famous "anchor" players | experimental |
| **Tuning / matches** | Texel tuner, match runner with SPRT, self-play data | working (tuning gave no gain so far) |

## Quick start

Requirements: Python 3.10+ (3.12 pinned), a C++17 compiler (`clang++` or `g++`), and optionally
[Stockfish](docs/stockfish.md) (strongly recommended as the judge of "good moves").

```bash
git clone https://github.com/<you>/MeChess.git && cd MeChess
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
make -C engine                # builds engine/build/chessme-engine (+ perft, texel, unit tests)
make test                     # C++ unit tests + quick perft + Python unit tests (seconds)
```

Then make your own profile (your copy is git-ignored, so account names stay on your machine):

```bash
cp configs/profiles/example.yaml configs/profiles/me.yaml     # edit the accounts
export CHESSME_PROFILE=me
.venv/bin/python -m chessme fetch          # download your games
.venv/bin/python -m chessme ingest         # normalise them
.venv/bin/python -m chessme audit          # see what you have
.venv/bin/python -m chessme book           # build your opening book
```

Run the engine directly (UCI) or the MeChess controller:

```bash
engine/build/chessme-engine                                   # plain engine, speaks UCI
.venv/bin/python -m chessme mechess --elo 1600 --prior uniform  # controller, speaks UCI
```

More: [getting started](docs/getting-started.md), [every command](docs/cli.md).

## How it fits together

```
your games (Lichess / chess.com)      Lichess open database
        |                                   |
   fetch -> ingest -> weighted games        +--> pretraining shards
        |                                            |
        +--> opening book                            v
        +--> "me" model  <-------- fine-tune on your games
        +--> style analysis (engine judge: Stockfish)
                     |
   opening book -> engine candidate moves (MultiPV) -> prior picks -> Elo dial  ==>  UCI engine
```

Details in [docs/architecture.md](docs/architecture.md).

## Documentation

- [Getting started](docs/getting-started.md): install, build, first run, environment variables
- [Command reference](docs/cli.md): every `chessme` command and the engine's UCI options
- [Using Stockfish](docs/stockfish.md): why and how we use it, its command line, how our client reads it
- [Lichess bot](docs/lichess-bot.md): running MeChess as a bot account, token handling, comparing the dial with Lichess ratings
- [Strength and the Elo dial](docs/calibration.md): measuring strength against Stockfish, calibrating the dial
- [Style analysis](docs/style-analysis.md): the method, the datasets, the tests, the limits
- [Data sources and privacy](docs/data-sources.md): where games come from, terms, what is stored
- [Running long jobs](docs/operations.md): memory guard, logs, resuming, laptops that sleep
- [Architecture](docs/architecture.md), [Testing](docs/testing.md), [Third-party software](docs/third-party.md), [Roadmap](docs/roadmap.md)

## Privacy

Your account names live only in your own profile file (git-ignored). Tokens are read from the
environment (`LICHESS_TOKEN`), never from files. Only public games are used. See
[data sources and privacy](docs/data-sources.md).

## Contributing

Issues and pull requests are welcome; contributions are accepted under the same licence. Every feature comes with unit tests and, where it touches the
engine, an integration test; every bug fix comes with a regression test. Run `make test` before
sending a change, and keep commits small.

## License

[PolyForm Noncommercial License 1.0.0](LICENSE): free to use, copy, modify and share for research, learning, personal
projects, education and other **non-commercial** purposes. **Commercial use (selling it, or building a product or
business on it) is not permitted.** Stockfish (GPL), Maia-2 / Maia-3 (AGPL / research releases) and the game archives you
may download have their own terms; MeChess uses them only as external programs or data you obtain yourself and never
bundles or copies them. See [third-party software](docs/third-party.md).
