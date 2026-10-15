"""Background jobs: imports, analyses, training. A job is a function that reports progress and checks for cancellation; its state lives in the database
(so the Activity page survives a restart) and every change is pushed to the browsers that listen (server-sent events)."""
import asyncio
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import select

from .models import Job


def iso(d):
    """ISO time in UTC. SQLite keeps no zone: what it returns is naive UTC, which `astimezone` would wrongly read as local time."""
    if not d:
        return None
    return (d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)).isoformat()


def to_out(j: Job) -> dict:
    return {"id": j.id, "kind": j.kind, "title": j.title, "status": j.status, "progress": round(j.progress or 0.0, 4), "message": j.message,
            "createdAt": iso(j.created_at), "startedAt": iso(j.started_at), "finishedAt": iso(j.finished_at)}


class Cancelled(Exception):
    pass


class JobContext:
    def __init__(self, manager, job_id, cancel_event):
        self._m, self.id, self._cancel = manager, job_id, cancel_event

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check(self):
        if self._cancel.is_set():
            raise Cancelled()

    def sleep(self, seconds: float):
        """Wait, but wake at once (and stop the job) when it is cancelled."""
        if self._cancel.wait(seconds):
            raise Cancelled()

    def progress(self, fraction: float, message: str | None = None):
        self.check()
        self._m._update(self.id, progress=max(0.0, min(1.0, fraction)), message=message)


class JobManager:
    def __init__(self, session_factory, workers=2):
        self._sf = session_factory
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")
        self._cancel: dict[str, threading.Event] = {}
        self._listeners: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()
        with self._sf() as s:                                                   # jobs left running by a stopped server did not finish
            for j in s.scalars(select(Job).where(Job.status.in_(("queued", "running")))):
                j.status, j.message, j.finished_at = "failed", "interrupted: the app was closed while this was running", datetime.now(timezone.utc)
            s.commit()

    # ---- listeners (server-sent events) -------------------------------------------------------------------------------------------------------
    def subscribe(self, loop):
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        with self._lock:
            self._listeners.append((loop, q))
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._listeners = [(l, x) for l, x in self._listeners if x is not q]

    def _publish(self, out: dict):
        with self._lock:
            targets = list(self._listeners)
        for loop, q in targets:
            def put(q=q):
                if q.full():
                    q.get_nowait()                                              # a slow listener loses its oldest update, never blocks a job
                q.put_nowait(out)
            try:
                loop.call_soon_threadsafe(put)
            except RuntimeError:
                pass                                                            # that listener's loop is gone

    # ---- state ---------------------------------------------------------------------------------------------------------------------------------
    def _update(self, job_id, **fields):
        with self._sf() as s:
            j = s.get(Job, job_id)
            for k, v in fields.items():
                if v is not None:
                    setattr(j, k, v)
            s.commit()
            out = to_out(j)
        self._publish(out)

    def submit(self, kind: str, title: str, fn, params: dict | None = None) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._sf() as s:
            j = Job(id=job_id, kind=kind, title=title, status="queued", params=params or {})
            s.add(j)
            s.commit()
            out = to_out(j)
        self._publish(out)
        ev = self._cancel[job_id] = threading.Event()
        self._pool.submit(self._run, job_id, fn, ev)
        return job_id

    def _run(self, job_id, fn, ev):
        if ev.is_set():
            return self._finish(job_id, "cancelled", "cancelled before it started")
        self._update(job_id, status="running", started_at=datetime.now(timezone.utc))
        try:
            msg = fn(JobContext(self, job_id, ev))
        except Cancelled:
            return self._finish(job_id, "cancelled", "cancelled")
        except Exception as e:                                                  # a failing job is reported, never raised into the server
            traceback.print_exc()
            return self._finish(job_id, "failed", f"{type(e).__name__}: {e}")
        self._finish(job_id, "done", msg if isinstance(msg, str) else "done", progress=1.0)

    def _finish(self, job_id, status, message, progress=None):
        fields = {"status": status, "message": message, "finished_at": datetime.now(timezone.utc)}
        if progress is not None:
            fields["progress"] = progress
        self._update(job_id, **fields)
        self._cancel.pop(job_id, None)

    def cancel(self, job_id) -> bool:
        ev = self._cancel.get(job_id)
        if ev is None:
            return False
        ev.set()
        return True

    def list(self, limit=50):
        with self._sf() as s:
            return [to_out(j) for j in s.scalars(select(Job).order_by(Job.created_at.desc()).limit(limit))]

    def get(self, job_id):
        with self._sf() as s:
            j = s.get(Job, job_id)
            return to_out(j) if j else None

    def shutdown(self):
        for ev in list(self._cancel.values()):                                  # (a copy: a finishing job removes its entry)
            ev.set()
        self._pool.shutdown(wait=False, cancel_futures=True)
