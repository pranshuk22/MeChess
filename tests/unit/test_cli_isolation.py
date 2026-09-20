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
