# Getting started

## Requirements

| Need | Version | Used for |
|---|---|---|
| Python | 3.10+ (3.12 is pinned in `.python-version`) | everything outside the engine |
| C++ compiler | C++17 (`clang++` on macOS, `g++` on Linux) | the engine, tuner, perft tool |
| `make` | any | building and testing |
| CMake | optional | alternative build (`engine/CMakeLists.txt`; less tested than `make`) |
| [Stockfish](stockfish.md) | 16+ recommended | judging which moves are "good" in the style analysis; optional otherwise |
| GPU | not needed | training runs on CPU; a GPU or Apple MPS speeds it up |

Python packages are pinned in `requirements.txt` (runtime) and `requirements-dev.txt` (tests).

## Install and build

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
make -C engine                  # -> engine/build/chessme-engine, build/perft, build/texel, build/test_unit
```

`make -C engine CXX=g++` selects another compiler. The binary is found at
`engine/build/chessme-engine` by default; every command that needs an engine has an `--engine` option.

Optionally `pip install -e .` gives you a `chessme` command; otherwise use `.venv/bin/python -m chessme`.

## Check that it works

```bash
make test        # C++ unit tests, quick perft, Python unit tests: a few seconds
make test-all    # also the verified perft suite and the Python integration tests (about 1.5 minutes)
make test-deep   # the deep perft suite (about 600 million nodes)
```

## Your profile

A *profile* is a YAML file that says which accounts are yours and how their games are weighted.

```bash
cp configs/profiles/example.yaml configs/profiles/me.yaml
$EDITOR configs/profiles/me.yaml         # put your account names in
export CHESSME_PROFILE=me                # or pass --profile me to each command
```

Files in `configs/profiles/` other than `example.yaml` are git-ignored, so your account names are
never committed. The example file explains every setting:

- `accounts`: Lichess and/or chess.com usernames (any number).
- `filters.min_rating`: ignore games played below this rating (per platform; the two rating scales are kept separate).
- `filters.recency`: newer games count more (half-life in days).
- `filters.time_class_weights`: e.g. bullet moves are trusted early in the game and down-weighted later.
- `book`: how strict the opening book is.
- `rating_range`: the Elo dial's range.

## First run

```bash
.venv/bin/python -m chessme fetch      # download games for the profile's accounts (resumable)
.venv/bin/python -m chessme ingest     # -> data/processed/games.jsonl
.venv/bin/python -m chessme audit      # games per account, ratings over time, colour split, ...
.venv/bin/python -m chessme book       # -> your opening book + a report
```

`data/` is git-ignored; everything downloaded or derived lives there.

## Environment variables

| Variable | Meaning |
|---|---|
| `CHESSME_PROFILE` | default profile name for commands with `--profile` (default `example`) |
| `LICHESS_TOKEN` | optional Lichess API token (higher rate limits). **Read only from the environment**, never from files |
| `CHESSME_MAIA3_REPO`, `CHESSME_MAIA3_CKPT`, `CHESSME_MAIA2_REPO`, `CHESSME_MAIA2_CKPT`, `CHESSME_EXTRA_PATH` | enable the optional integration test that checks our Maia scoring against their reference code (see [testing](testing.md)) |
| `OMP_NUM_THREADS` | limits CPU threads for PyTorch when training on a shared machine |

## Playing against it

Any UCI GUI (for example Arena, CuteChess, Lichess-bot) can load either program as an engine:

- `engine/build/chessme-engine`: the plain engine. Options are listed in the [command reference](cli.md#engine-uci-options).
- `python -m chessme mechess ...`: the MeChess controller (book, candidate moves, prior, Elo dial).
