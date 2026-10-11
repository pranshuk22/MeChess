"""The shell helpers the long jobs are chained with: their exit status is what lets a chain stop at the first failed step."""
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def watch(limit_mb, *cmd, tmp_path):
    env = {**os.environ, "WATCH_OUT": str(tmp_path / "out.log")}
    return subprocess.run(["bash", str(TOOLS / "watch.sh"), str(limit_mb), *cmd], capture_output=True, text=True, timeout=60, env=env)


def test_watch_passes_the_commands_exit_status_on(tmp_path):
    """Regression: watch.sh always exited 0, so a chain script could not tell a failed or killed step from a good one."""
    assert watch(4000, "true", tmp_path=tmp_path).returncode == 0
    assert watch(4000, "bash", "-c", "exit 3", tmp_path=tmp_path).returncode == 3


def test_watch_kills_a_job_over_the_memory_limit_and_says_so(tmp_path):
    import sys

    t0 = time.time()
    hog = "x = bytearray(150 * 1024 * 1024); import time; time.sleep(60)"            # holds ~150 MB for a minute
    r = watch(60, sys.executable, "-c", hog, tmp_path=tmp_path)
    assert r.returncode == 137 and "KILLED" in r.stdout and time.time() - t0 < 40


def test_every_script_parses():
    for script in TOOLS.glob("*.sh"):
        r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert r.returncode == 0, f"{script.name}: {r.stderr}"


def test_await_log_reads_the_modification_time_with_either_stat(tmp_path):
    """Regression: the stall detector used only BSD `stat -f %m`, which on Linux prints something else, so the check never worked there."""
    log = tmp_path / "x.log"
    log.write_text("started\n")
    script = (TOOLS / "await_log.sh").read_text()
    assert "stat -c %Y" in script and "stat -f %m" in script
    probe = subprocess.run(["bash", "-c", f'stat -c %Y "{log}" 2>/dev/null || stat -f %m "{log}" 2>/dev/null'], capture_output=True, text=True)
    assert probe.stdout.strip().isdigit() and int(probe.stdout.strip()) > 1_000_000_000


def test_await_log_returns_when_the_marker_appears(tmp_path):
    log = tmp_path / "x.log"
    log.write_text("working\nall done\n")
    r = subprocess.run(["bash", str(TOOLS / "await_log.sh"), str(log), "all done"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "DONE" in r.stdout
