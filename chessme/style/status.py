"""One-screen status of the long style jobs: what is running, how far each stage is, how long it will take.

Progress is read from the files the jobs write (players.json, items/, cands/) and rates from the timestamps in their
logs, so it works while jobs run and after they stop. `chessme style-status --watch 10` refreshes every 10 seconds."""
import json
import re
import subprocess
import time
from pathlib import Path

_ETIME = re.compile(r"^[\d:.-]+$")  # ps elapsed time: 22:11, 01:50:03, 2-03:04:05
_PROGRESS = re.compile(r"\[\s*(\d+)s\]\s+(\d+)/(\d+)")
JOBS = (  # (label, substring that identifies the process on its command line)
    ("cohort fetch", "style-cohort-fetch"),
    ("cohort / anchors analysis", "style-cohort-analyze"),
    ("anchors fetch", "style-anchors-fetch"),
    ("population sampling", "style-pop-data"),
    ("style data", "style-data"),
    ("stockfish workers", "stockfish"),
)


def count(folder, pattern):
    p = Path(folder)
    return len(list(p.glob(pattern))) if p.exists() else 0


def read_json_len(path):
    try:
        return len(json.loads(Path(path).read_text()))
    except (OSError, ValueError):
        return 0


def folder_progress(folder):
    """{"fetched", "rejected", "items", "analysed"} for a cohort or anchors folder."""
    f = Path(folder)
    return {"fetched": read_json_len(f / "players.json"), "rejected": read_json_len(f / "rejected.json"),
            "items": count(f / "items", "*.jsonl"), "analysed": count(f / "cands", "*.npz")}


def rate_from_log(path, tail_lines=12):
    """Items per second from the last few 'elapsed n/total' progress lines of a log, or None."""
    try:
        lines = Path(path).read_text(errors="replace").replace("\0", "").splitlines()[-400:]
    except OSError:
        return None
    pts = [(int(m.group(1)), int(m.group(2))) for m in map(_PROGRESS.search, lines) if m]
    pts = pts[-tail_lines:]
    if len(pts) < 2 or pts[-1][0] <= pts[0][0] or pts[-1][1] <= pts[0][1]:
        return None
    return (pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0])


def eta_text(remaining, rate):
    if remaining <= 0:
        return "done"
    if not rate:
        return "unknown (no recent progress)"
    s = remaining / rate
    return f"about {s / 3600:.1f} h" if s >= 5400 else f"about {max(s / 60, 1):.0f} min"


def parse_ps(text):
    """[(pid, elapsed, rss_mb, command)] from `ps -Ao pid,etime,rss,command` output."""
    out = []
    for line in text.splitlines()[1:]:
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0].isdigit() and parts[2].isdigit() and _ETIME.match(parts[1]):
            out.append((int(parts[0]), parts[1], int(parts[2]) // 1024, parts[3]))
    return out


def running(ps_text=None):
    """{label: {"processes": n, "rss_mb": total, "elapsed": longest}} for the known jobs."""
    if ps_text is None:
        ps_text = subprocess.run(["ps", "-Ao", "pid,etime,rss,command"], capture_output=True, text=True).stdout
    found = {}
    for pid, elapsed, rss, cmd in parse_ps(ps_text):
        if "chessme.style.status" in cmd or "style-status" in cmd or "watch.sh" in cmd or "grep" in cmd:
            continue
        for label, key in JOBS:
            if key in cmd:
                d = found.setdefault(label, {"processes": 0, "rss_mb": 0, "elapsed": elapsed})
                d["processes"] += 1
                d["rss_mb"] += rss
                break
    return found


def last_lines(path, n=2):
    try:
        lines = [l for l in Path(path).read_text(errors="replace").replace("\0", "").splitlines() if l.strip()]
    except OSError:
        return ["(log not found)"]
    return lines[-n:] or ["(log is empty)"]


def render(*, cohort, anchors, target, logs, jobs, now=None):
    now = now or time.strftime("%H:%M:%S")
    c, a = folder_progress(cohort), folder_progress(anchors)
    fetch_rate = rate_from_log(Path(logs) / "cohort_fetch.log")
    an_rate = rate_from_log(Path(logs) / "cohort_analyze.log")
    lines = [f"MeChess style jobs  {now}", "", "RUNNING"]
    lines += ([f"  {label:28s} {d['processes']:2d} process(es), {d['rss_mb']:5d} MB, up {d['elapsed']}" for label, d in jobs.items()]
              or ["  nothing running"])
    lines += ["", "COHORT (individual players, ~50 games each)",
              f"  fetched   {c['fetched']:5d} / {target}   ({100 * c['fetched'] / max(target, 1):.0f}%)   rejected {c['rejected']}   "
              f"ETA {eta_text(target - c['fetched'], fetch_rate)}",
              f"  analysed  {c['analysed']:5d} / {c['fetched']}   ETA {eta_text(c['fetched'] - c['analysed'], an_rate)} "
              f"(for what is fetched so far)",
              "", "ANCHORS (famous players, peak years)",
              f"  sampled   {a['items']:5d}    analysed {a['analysed']:3d} / {a['items']}", "", "LATEST LOG LINES"]
    for name in ("cohort_fetch", "cohort_analyze", "anchors_analyze"):
        lines.append(f"  {name}:")
        lines += [f"    {l[:150]}" for l in last_lines(Path(logs) / f"{name}.log")]
    return "\n".join(lines)
