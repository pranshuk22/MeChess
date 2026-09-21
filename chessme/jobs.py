"""Pause, resume and stop for long jobs.

Every long stage (fetching, feature extraction, engine analysis, training) does its work in small units and calls
`JobControl.checkpoint()` between them. Control is by plain files in one folder (default `data/control/`), so it works from any
terminal and survives restarts:

    PAUSE            every job holds (sleeps) until the file is removed
    <job>.pause      only that job holds
    STOP / <job>.stop   every / that job exits cleanly at its next checkpoint (rerun the same command to resume)

A held job keeps its state and continues where it was; a stopped job exits, and because every stage records finished units of work on
disk, the same command resumes from there. SIGINT and SIGTERM act like STOP but never interrupt a unit of work half-way."""
import contextlib
import multiprocessing
import os
import signal
import threading
import time
from pathlib import Path

DEFAULT_DIR = "data/control"


class Stopped(Exception):
    """Raised by a checkpoint when the job was asked to stop; the job should exit cleanly."""


class JobControl:
    def __init__(self, name, control_dir=DEFAULT_DIR, poll=2.0, log=print):
        self.name, self.dir, self.poll, self.log = name, Path(control_dir), poll, log
        self._signalled = None
        self._announced = False

    # -- files ---------------------------------------------------------------------------------------------
    def _flag(self, base):
        return [self.dir / base, self.dir / f"{self.name}.{base.lower()}"]

    def paused(self):
        return any(p.exists() for p in self._flag("PAUSE"))

    def stop_requested(self):
        return self._signalled is not None or any(p.exists() for p in self._flag("STOP"))

    # -- the checkpoint --------------------------------------------------------------------------------------
    def checkpoint(self):
        """Call between units of work. Returns when the job may continue; raises Stopped when it should exit."""
        if self.stop_requested():
            raise Stopped(f"{self.name}: stop requested" + (f" (signal {self._signalled})" if self._signalled else ""))
        if self.paused():
            self.log(f"{self.name}: PAUSED (remove {self.dir / 'PAUSE'} or run `chessme control resume` to continue)")
            while self.paused():
                time.sleep(self.poll)
                if self.stop_requested():
                    raise Stopped(f"{self.name}: stop requested while paused")
            self.log(f"{self.name}: resumed")

    @contextlib.contextmanager
    def signals(self):
        """SIGINT / SIGTERM request a stop at the next checkpoint (instead of killing the process mid-unit)."""
        def handler(signum, frame):
            self._signalled = signum
            self.log(f"{self.name}: signal {signum} received; finishing the current unit, then stopping")
        try:
            old = {s: signal.signal(s, handler) for s in (signal.SIGINT, signal.SIGTERM)}
        except ValueError:                       # not the main thread
            yield self
            return
        try:
            yield self
        finally:
            for s, h in old.items():
                signal.signal(s, h)


# ---- command line side ---------------------------------------------------------------------------------------------

def _path(control_dir, kind, job=None):
    d = Path(control_dir)
    return d / (kind if not job else f"{job}.{kind.lower()}")


def set_flag(kind, job=None, control_dir=DEFAULT_DIR):
    p = _path(control_dir, kind, job)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(time.strftime("%Y-%m-%d %H:%M:%S\n"))
    return p


def clear_flag(kind, job=None, control_dir=DEFAULT_DIR):
    p = _path(control_dir, kind, job)
    existed = p.exists()
    p.unlink(missing_ok=True)
    return existed


def flags(control_dir=DEFAULT_DIR):
    """Names of the control files currently present."""
    d = Path(control_dir)
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


# ---- a pool that can be paused between tasks -----------------------------------------------------------------------

def _stop_pool(pool, grace=3.0):
    """Shut a worker pool down without ever blocking. `Pool.terminate()` sends SIGTERM and then joins the workers, which waits forever for one that
    ignores it: so it runs in a helper thread, and if it has not returned after `grace` seconds the workers are killed with SIGKILL (which cannot be
    ignored or caught) and terminate() can finish."""
    t = threading.Thread(target=pool.terminate, daemon=True)
    t.start()
    t.join(grace)
    if t.is_alive():
        for p in list(getattr(pool, "_pool", None) or []):
            try:
                os.kill(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError, TypeError):
                pass
        t.join(15)


class TaskTimeout(RuntimeError):
    """A pooled task did not finish in time: its worker is stuck or died (a pool replaces a dead worker but the task it held is lost)."""


def run_pool(fn, tasks, workers, ctl, *, on_result=None, in_flight=None, task_timeout=None):
    """Run `fn(task)` in worker processes, with at most `in_flight` tasks queued (default 2 x workers), checking `ctl` before each
    submission so a pause holds the *submissions* and a stop lets the running tasks finish. Yields results as they complete.
    Stopped is raised after the in-flight tasks have been collected. With `task_timeout` (seconds), a task that has been running longer than that
    raises TaskTimeout instead of waiting forever (the pool is terminated)."""
    in_flight = in_flight or workers * 2
    tasks = list(tasks)
    results, pending, i, stopped = [], [], 0, None
    started = {}
    pool = multiprocessing.get_context("spawn").Pool(workers)
    try:
        while i < len(tasks) or pending:
            while stopped is None and i < len(tasks) and len(pending) < in_flight:
                try:
                    ctl.checkpoint()
                except Stopped as e:
                    stopped = e
                    break
                pending.append(pool.apply_async(fn, (tasks[i],)))
                started[id(pending[-1])] = (time.time(), tasks[i])
                i += 1
            if not pending:
                break
            done = [p for p in pending if p.ready()]
            if not done:
                if task_timeout:
                    now = time.time()
                    for p in pending:
                        t0, task = started[id(p)]
                        if now - t0 > task_timeout:
                            raise TaskTimeout(f"a task ran for more than {task_timeout:.0f} s without finishing (a worker is stuck or died): {str(task)[:120]}")
                time.sleep(0.05)
                continue
            for p in done:
                pending.remove(p)
                r = p.get()
                if on_result:
                    on_result(r)
                yield r
    finally:
        _stop_pool(pool)
    if stopped is not None:
        raise stopped
