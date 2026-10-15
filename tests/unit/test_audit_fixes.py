"""Regression tests for audit findings outside the web app (AUDIT-2026-10-15.md): NaN in the error profile, the pooled-row note, packaging, workflows."""
import re
import tomllib
from pathlib import Path

import numpy as np

from chessme.humanlike import blunders as B
from chessme.humanlike import calibration as CAL
from chessme.humanlike import errors as E

ROOT = Path(__file__).resolve().parents[2]


def test_missing_tail_stand_ins_stay_visible_as_nan_not_silently_uncorrected():
    # Audit #17 asked for the model's own values instead of NaN; kept as designed: NaN, visibly, so an uncorrected number is never reported as corrected.
    prep = {"p": np.array([[0.7, 0.3]] * 2), "cand_loss": np.array([[0.0, 0.3]] * 2), "tail": np.array([0.2, 0.2])}
    tail = {name: np.array([np.nan, 0.05]) for name in ["mean loss", *E.THRESHOLDS]}
    out = E.model_values(prep, tail=tail)
    assert np.isnan(out["mean loss"][0]) and not np.isnan(out["mean loss"][1])


def test_reports_that_pool_clock_regimes_say_what_the_pooled_row_is():
    note = E.POOLED_NOTE
    assert "all judged positions" in note and "not rates of the whole population" in note
    one = {"n": 1, "mean loss": {"human": (1, 0, 2), "model": (1, 0, 2), "diff": (0, -1, 1)}}
    assert note in E.render({"all judged positions": one})
    assert note not in E.render({"clock <10s": one})


def test_the_package_lists_the_dependencies_the_web_app_imports():
    # Regression (#6): `pip install .` gave a `chessme app` that could not start.
    deps = {re.split(r"[<>=!~ ]", d)[0].lower() for d in tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]}
    assert {"fastapi", "uvicorn", "websockets", "sqlalchemy", "alembic"} <= deps
    pinned = {re.split(r"[=<> ]", l)[0].lower() for l in (ROOT / "requirements.txt").read_text().splitlines() if l and not l.startswith("#")}
    assert {"fastapi", "uvicorn", "websockets", "sqlalchemy", "alembic"} <= pinned


def test_the_coach_and_the_web_app_do_not_share_a_default_port():
    # Regression (#19): both defaulted to 8765, so the second one failed with "address in use".
    from chessme import cli
    src = Path(cli.__file__).read_text()
    ports = re.findall(r'add_argument\("--port", type=int, default=(\d+)', src)
    assert len(ports) >= 2 and len(set(ports)) == len(ports)


def test_the_chain_scripts_give_up_when_the_job_they_wait_for_is_gone():
    # Regression (#22): they looped forever, printing a heartbeat, after a crash.
    for script, proc in (("dial_after_strength.sh", "chessme strength"), ("after_analysis.sh", "chessme style-cohort-analyze")):
        text = (ROOT / "tools" / script).read_text()
        assert f'pgrep -f "{proc}' in text and "exit 1" in text, script


def test_checkpoints_are_loaded_without_running_code_but_numpy_arrays_still_load(tmp_path):
    # Regression (#21): `torch.load(weights_only=False)` on files that travel through Kaggle would run code from a tampered file.
    import os
    import torch
    from chessme.model import safe_load
    ok = tmp_path / "ok.pt"
    torch.save({"state": {"w": torch.ones(2)}, "mean": np.arange(3.0), "std": np.ones(3, dtype=np.float32), "hidden": 8, "meta": {"a": 1}}, ok)
    d = safe_load.load(ok)
    assert d["state"]["w"].tolist() == [1.0, 1.0] and d["mean"].tolist() == [0.0, 1.0, 2.0] and d["std"].dtype == np.float32

    marker = tmp_path / "pwned"

    class Evil:
        def __reduce__(self):
            return (os.system, (f"touch {marker}",))
    bad = tmp_path / "bad.pt"
    torch.save({"state": Evil()}, bad)
    import pickle
    with __import__("pytest").raises((pickle.UnpicklingError, RuntimeError)):
        safe_load.load(bad)
    assert not marker.exists()


def test_the_dockerfile_starts_the_app_with_options_that_exist_and_the_compose_file_publishes_to_localhost_only():
    import json
    import subprocess
    import sys
    docker = (ROOT / "Dockerfile").read_text()
    cmd = json.loads(re.search(r"^CMD (\[.*\])$", docker, re.M).group(1))
    assert cmd[:4] == ["python", "-m", "chessme", "app"]
    help_text = subprocess.run([sys.executable, "-m", "chessme", "app", "-h"], capture_output=True, text=True, cwd=ROOT).stdout
    for flag in (a for a in cmd if a.startswith("--")):
        assert flag in help_text, flag
    assert "0.0.0.0" in cmd and "--no-browser" in cmd
    compose = (ROOT / "docker-compose.yml").read_text()
    assert '"127.0.0.1:8765:8765"' in compose and "0.0.0.0:" not in compose
    assert "torch" not in docker.split("RUN pip install")[1].split("COPY")[0]                    # the app image does not carry PyTorch
