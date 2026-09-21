import os
import signal
import threading
import time

import pytest

from chessme import jobs as J


def square(x):          # top level so worker processes can import it
    return x * x


def slow_square(x):
    time.sleep(0.05)
    return x * x


@pytest.fixture
def ctl(tmp_path):
    return J.JobControl("fetch", tmp_path / "control", poll=0.02, log=lambda *_: None)


class TestFlags:
    def test_no_files_means_go(self, ctl):
        ctl.checkpoint()
        assert not ctl.paused() and not ctl.stop_requested()

    def test_the_global_and_the_per_job_pause_files_both_hold_the_job(self, ctl, tmp_path):
        d = tmp_path / "control"
        J.set_flag("PAUSE", control_dir=d)
        assert ctl.paused()
        J.clear_flag("PAUSE", control_dir=d)
        J.set_flag("PAUSE", "fetch", control_dir=d)
        assert ctl.paused()
        other = J.JobControl("train", d, log=lambda *_: None)
        assert not other.paused()                            # a pause aimed at "fetch" does not hold "train"

    def test_stop_files_and_flags_listing(self, ctl, tmp_path):
        d = tmp_path / "control"
        J.set_flag("STOP", "fetch", control_dir=d)
        assert ctl.stop_requested() and J.flags(d) == ["fetch.stop"]
        with pytest.raises(J.Stopped):
            ctl.checkpoint()
        assert J.clear_flag("STOP", "fetch", control_dir=d) and not J.clear_flag("STOP", "fetch", control_dir=d)
        assert J.flags(d) == []


class TestCheckpoint:
    def test_a_paused_job_waits_and_continues_when_resumed(self, ctl, tmp_path):
        d = tmp_path / "control"
        J.set_flag("PAUSE", control_dir=d)
        t0 = time.time()
        threading.Timer(0.3, lambda: J.clear_flag("PAUSE", control_dir=d)).start()
        ctl.checkpoint()
        assert 0.25 < time.time() - t0 < 2.0

    def test_a_stop_while_paused_ends_the_wait(self, ctl, tmp_path):
        d = tmp_path / "control"
        J.set_flag("PAUSE", control_dir=d)
        threading.Timer(0.2, lambda: J.set_flag("STOP", control_dir=d)).start()
        with pytest.raises(J.Stopped):
            ctl.checkpoint()

    def test_pause_and_resume_are_logged_once(self, tmp_path):
        d, lines = tmp_path / "c", []
        c = J.JobControl("x", d, poll=0.02, log=lines.append)
        J.set_flag("PAUSE", control_dir=d)
        threading.Timer(0.2, lambda: J.clear_flag("PAUSE", control_dir=d)).start()
        c.checkpoint()
        assert sum("PAUSED" in l for l in lines) == 1 and sum("resumed" in l for l in lines) == 1


class TestSignals:
    def test_sigterm_requests_a_stop_at_the_next_checkpoint_without_killing_the_process(self, ctl):
        with ctl.signals():
            os.kill(os.getpid(), signal.SIGTERM)             # would normally kill the process instantly
            assert ctl.stop_requested()
            with pytest.raises(J.Stopped, match="signal"):
                ctl.checkpoint()

    def test_handlers_are_restored(self, ctl):
        before = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
        with ctl.signals():
            assert signal.getsignal(signal.SIGTERM) != before[0]
        assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)) == before


class TestRunPool:
    def test_results_arrive_for_every_task(self, ctl):
        assert sorted(J.run_pool(square, range(10), 2, ctl)) == [i * i for i in range(10)]

    def test_a_pause_holds_submissions_and_resumes_the_rest(self, ctl, tmp_path):
        d, got = tmp_path / "control", []
        J.set_flag("PAUSE", control_dir=d)
        threading.Timer(0.6, lambda: J.clear_flag("PAUSE", control_dir=d)).start()
        t0 = time.time()
        for r in J.run_pool(slow_square, range(6), 2, ctl):
            got.append(r)
        assert sorted(got) == [i * i for i in range(6)] and time.time() - t0 > 0.55

    def test_a_stop_collects_what_is_in_flight_then_raises(self, ctl, tmp_path):
        d, got = tmp_path / "control", []
        gen = J.run_pool(slow_square, range(40), 2, ctl, in_flight=2)
        with pytest.raises(J.Stopped):
            for r in gen:
                got.append(r)
                if len(got) == 3:
                    J.set_flag("STOP", control_dir=d)
        assert 3 <= len(got) < 40 and all(r in {i * i for i in range(40)} for r in got)

    def test_on_result_callback_sees_every_result(self, ctl):
        seen = []
        list(J.run_pool(square, range(5), 2, ctl, on_result=seen.append))
        assert sorted(seen) == [0, 1, 4, 9, 16]


def _sleep_forever(x):
    import time
    time.sleep(3600)


def _die(x):
    import os
    os._exit(1)                        # a worker that dies without an answer: its task is lost


def test_a_stuck_task_raises_instead_of_hanging():
    from chessme.jobs import JobControl, TaskTimeout, run_pool
    import time
    t0 = time.time()
    with pytest.raises(TaskTimeout, match="stuck or died"):
        list(run_pool(_sleep_forever, [1], 1, JobControl("t", control_dir="/nonexistent-control"), task_timeout=3))
    assert time.time() - t0 < 30


def test_a_worker_that_dies_is_detected_by_the_timeout():
    from chessme.jobs import JobControl, TaskTimeout, run_pool
    with pytest.raises(TaskTimeout):
        list(run_pool(_die, [1], 1, JobControl("t", control_dir="/nonexistent-control"), task_timeout=5))


def _ignore_sigterm_and_sleep(x):
    import signal as _s, time as _t
    _s.signal(_s.SIGTERM, _s.SIG_IGN)     # a worker that cannot be terminated politely: Pool.terminate() alone waits for it forever
    _t.sleep(3600)


def test_a_worker_that_ignores_sigterm_cannot_hang_the_shutdown():
    from chessme.jobs import JobControl, TaskTimeout, run_pool
    t0 = time.time()
    with pytest.raises(TaskTimeout):
        list(run_pool(_ignore_sigterm_and_sleep, [1], 1, JobControl("t", control_dir="/nonexistent-control"), task_timeout=3))
    assert time.time() - t0 < 40


def test_finished_pools_leave_no_worker_processes_behind():
    import multiprocessing
    from chessme.jobs import JobControl, run_pool
    assert sorted(run_pool(square, [1, 2, 3, 4], 2, JobControl("t", control_dir="/nonexistent-control"))) == [1, 4, 9, 16]
    time.sleep(0.5)
    assert not multiprocessing.active_children()
