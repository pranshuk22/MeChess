# Testing

Policy: **every feature ships with unit tests and, where it touches the engine, an integration test; every bug gets a
regression test.** Tests describe the behaviour they protect and avoid vacuous assertions.

## Commands

| Command | What runs | Time |
|---|---|---|
| `make test` | C++ unit tests, quick perft suite, Python unit tests (not marked `slow`) | seconds |
| `make test-all` | also the perft suite with hash / make-unmake verification at every node, and the Python integration tests against the real engine binary | about 1.5 minutes |
| `make test-deep` | the deep perft suite (about 600 million nodes) | minutes |
| `.venv/bin/python -m pytest tests/unit/test_style_features.py -q` | a single file | |

## Layout

- `engine/tests/`: C++ unit tests with a small in-repo framework (`test_framework.h`), one file per module;
  `crosscheck.py` compares the C++ move generator with python-chess on hundreds of random positions.
- `tests/unit/`: Python unit tests, one file per module. Engines are replaced by scripted stand-ins so no binary is needed.
- `tests/integration/`: drive the compiled engine (built on demand by `make`): UCI conversation, book, MultiPV, "me" net parity
  with PyTorch, matches, the MeChess controller playing real games.
- `tests/fake_engine.py`: a tiny scripted UCI engine with modes (multipv, mate, crash, garbage output, ...), used to test the client.
- `tests/samples.py`: synthetic game rows for the data pipeline.

Markers (`pyproject.toml`): `integration` (drives the engine binary), `slow` (over about 5 seconds; skipped by `make test`).

## Optional tests

`tests/integration/test_compare_external.py` checks that our batched scoring reproduces the reference code of Maia-2 /
Maia-3 exactly. It runs only when you provide local checkouts and weights (large and separately licensed):

```
CHESSME_MAIA3_REPO=/path/to/maia3 CHESSME_MAIA3_CKPT=/path/to/5m.pt \
CHESSME_MAIA2_REPO=/path/to/maia2 CHESSME_MAIA2_CKPT=/path/to/blitz_model.pt \
CHESSME_EXTRA_PATH=/path/to/extra/site-packages  pytest tests/integration/test_compare_external.py
```

No test needs Stockfish, network access, your games or any personal data; a fresh clone passes `make test`.

## CI

`.github/workflows/ci.yml` builds the engine with `g++`, runs the C++ tests and the verified perft suite, then the Python
tests, on every push and pull request.
