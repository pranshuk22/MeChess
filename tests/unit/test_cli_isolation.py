"""The bot starts the engine through `python -m chessme mechess ...`. Every command lives in one CLI, so a broken feature module (books,
explorer, analysis, style ...) must never stop the CLI from starting: feature modules are imported only when their command runs."""
import subprocess
import sys

import pytest

FEATURE_MODULES = [
    "chessme.book.explorer", "chessme.book.theory", "chessme.books.nlp", "chessme.books.learn", "chessme.books.corpora", "chessme.books.annotated",
    "chessme.books.preflight", "chessme.books.fetch", "chessme.analysis.runner", "chessme.analysis.classify", "chessme.style.embed",
    "chessme.style.quality", "chessme.style.gamestats", "chessme.kaggle",
]

SCRIPT = """
import sys
sys.modules[{module!r}] = None            # None in sys.modules makes `import module` raise ImportError
sys.argv = ['chessme', 'mechess', '-h']
from chessme import cli
try:
    cli.main()
except SystemExit as e:
    sys.exit(e.code)
"""


@pytest.mark.parametrize("module", FEATURE_MODULES)
def test_the_cli_starts_even_if_a_feature_module_is_broken(module):
    r = subprocess.run([sys.executable, "-c", SCRIPT.format(module=module)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"{module}: {r.stderr[-500:]}"


def test_the_full_help_builds_every_parser():
    r = subprocess.run([sys.executable, "-m", "chessme", "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "explorer-build" in r.stdout and "mechess" in r.stdout


@pytest.mark.parametrize("command", ["fetch", "ingest", "audit", "book", "texel-data --out x.txt", "openings --out x.txt", "me-data user --out x"])
def test_commands_with_a_profile_take_it_from_the_environment(command):
    """Regression: `fetch`, `ingest`, `audit`, `book` ... required `--profile` although the README (and docs/cli.md) say `CHESSME_PROFILE` is the
    default, so the documented quick start failed in argparse before doing anything."""
    import os

    env = {**os.environ, "CHESSME_PROFILE": "no_such_profile_for_the_test"}
    r = subprocess.run([sys.executable, "-m", "chessme", *command.split()], capture_output=True, text=True, timeout=60, env=env)
    assert "required" not in r.stderr, r.stderr[-400:]
    assert "No such profile" in r.stderr + r.stdout, r.stderr[-400:]
