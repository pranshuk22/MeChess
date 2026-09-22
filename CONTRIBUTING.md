# Contributing to MeChess

Issues and pull requests are welcome. This project is config-driven: nobody's account or personal
data is hard-coded, so contributions should keep it that way.

## Getting set up

See [docs/getting-started.md](docs/getting-started.md) for the full install and build steps. In short:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
make -C engine
make test
```

## Before you send a change

1. **Write tests.** Every feature ships with unit tests, and an integration test where it touches
   the engine; every bug fix ships with a regression test that fails before the fix and passes
   after it. See [docs/testing.md](docs/testing.md) for the test layout and markers.
2. **Run the suite.** `make test` (seconds) covers the common case; `make test-all` (about 1.5
   minutes) also runs the verified perft suite and the Python integration tests against the real
   engine binary. CI runs `make test test-verify` plus the full Python suite on every push and
   pull request.
3. **Keep commits small** and focused on one change.
4. **No personal data.** Never commit account names, tokens, or anything under `data/` or
   `configs/profiles/` other than `example.yaml`; these are git-ignored on purpose. See
   [docs/data-sources.md](docs/data-sources.md) for the privacy rules the code follows.

## Reporting bugs

Open an issue with a minimal reproduction (a short PGN, a FEN, or a command and its output).
For anything engine-related, note your platform and compiler.

## Proposing a feature

Open an issue first if the change is more than a small fix, so the design can be discussed before
the implementation. [docs/architecture.md](docs/architecture.md) explains how the codebase is laid
out; [docs/cli.md](docs/cli.md) lists every existing command, so new functionality lands as a
consistent CLI command rather than a one-off script.

## Licensing

MeChess is [MIT-licensed](LICENSE). By submitting a pull request, you agree that your contribution
is licensed under the same terms.
