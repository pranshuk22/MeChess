"""The Kaggle notebooks are adapters: every step is a `chessme` command that exists, with options that exist (checked against `--help`)."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

NOTEBOOKS = sorted(Path("notebooks").glob("*.ipynb"))
CALL = re.compile(r'\*CLI,\s*"([a-z0-9-]+)"(.*?)(?:\)\s*(?:\n|$))', re.S)


def code(nb):
    return "\n".join("".join(c["source"]) for c in json.load(open(nb))["cells"] if c["cell_type"] == "code")


def help_text(cmd, cache={}):
    if cmd not in cache:
        r = subprocess.run([sys.executable, "-m", "chessme", cmd, "-h"], capture_output=True, text=True)
        assert r.returncode == 0, f"`chessme {cmd}` does not exist: {r.stderr[-300:]}"
        cache[cmd] = r.stdout
    return cache[cmd]


def test_there_are_four_notebooks_numbered_in_order():
    assert [n.name[0] for n in NOTEBOOKS] == ["1", "2", "3", "4"]


@pytest.mark.parametrize("nb", NOTEBOOKS, ids=lambda p: p.name)
def test_every_command_and_option_used_exists(nb):
    calls = CALL.findall(code(nb))
    assert calls, "a notebook without a chessme command is not an adapter"
    for cmd, rest in calls:
        text = help_text(cmd)
        for flag in re.findall(r'"(--[a-z0-9-]+)"', rest):
            assert flag in text, f"{nb.name}: `chessme {cmd}` has no option {flag}"


@pytest.mark.parametrize("nb", NOTEBOOKS, ids=lambda p: p.name)
def test_no_personal_names_and_no_logic_beyond_running_commands(nb):
    src = code(nb)
    assert "<you>" in src                                            # the repository URL is filled in by the person running it
    assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", src)                 # no e-mail address; the person's own folder names stay placeholders (<your-username>)
    assert "/kaggle/input/notebooks/<" in src or "DATA_DIR" not in src
    assert "import torch" not in src and "import chess" not in src   # the work is done by the commands, not in the notebook
