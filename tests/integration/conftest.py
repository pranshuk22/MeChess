import shutil
import subprocess
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[2] / "engine"
ENGINE = ENGINE_DIR / "build" / "chessme-engine"
TEXEL = ENGINE_DIR / "build" / "texel"

# An evaluation in which the queen is worth nothing: an engine using it gives its queen away.
CRIPPLED_PARAMS = "mat_mg 100 320 330 500 0 0\nmat_eg 100 320 330 500 0 0\n"


def _build(target):
    if not (shutil.which("clang++") or shutil.which("g++") or shutil.which("c++")):
        pytest.skip("no C++ compiler available")
    r = subprocess.run(["make", "-C", str(ENGINE_DIR), target], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.fixture(scope="session")
def engine_path():
    """Builds the engine on demand (make) and returns the binary path."""
    _build("build/chessme-engine")
    return ENGINE


@pytest.fixture(scope="session")
def texel_path():
    _build("build/texel")
    return TEXEL


@pytest.fixture()
def crippled_params(tmp_path):
    p = tmp_path / "crippled.txt"
    p.write_text(CRIPPLED_PARAMS)
    return p
