# Running long jobs

Several stages take hours (engine analysis of a cohort, fetching hundreds of players). This page collects what we
learned about running them safely on a laptop.

## Memory guard: `tools/watch.sh`

```bash
WATCH_OUT=data/style/logs/my_job.log tools/watch.sh 2000 .venv/bin/python -u -m chessme style-cohort-analyze ...
```

Runs the command in the background, writes its output to `WATCH_OUT` (default `/tmp/watch.out`), prints the peak
memory when it ends, and **kills the whole process tree if its total resident memory exceeds the limit in MB**.
It counts child processes too (engine workers), which a plain `ulimit` or a look at the parent process would miss.
Give every job its own `WATCH_OUT`, otherwise jobs overwrite each other's logs.

## Pipeline scripts

| Script | What it does |
|---|---|
| `tools/cohort_analyze_loop.sh <fetch-pid>` | analyses cohort players with Stockfish while the fetch (that process id) is still running, then once more at the end |
| `tools/anchors_pipeline.sh` | anchors end to end: fetch archives, sample peak-year decisions, Stockfish analysis |

## Status at a glance

```bash
python -m chessme style-status              # one screen: running jobs, progress, ETA, latest log lines
python -m chessme style-status --watch 10   # refresh every 10 seconds
```

It reads the files the jobs write (`players.json`, `items/`, `cands/`) and the progress timestamps in the logs, so it also works
after a job has stopped. Options: `--cohort`, `--anchors`, `--logs`, `--target` (players wanted).

## Logs

Long jobs write timestamped lines you can follow with `tail -f`. A convention: everything under `data/style/logs/`
(`cohort_fetch.log`, `cohort_analyze.log`, `anchors_analyze.log`, ...). Do not keep links or copies elsewhere: old
symlinks to files that a later run replaced silently show stale output.
Fetch logs show per anchor or player what was found, dropped and used; analysis logs show progress per player.

## Resuming

Every stage is resumable; rerunning the same command continues:

| Stage | How it resumes |
|---|---|
| `fetch` | only new games since the last download |
| `style-cohort-fetch` | `players.json` and `rejected.json` record decided players; the run skips them |
| `style-cohort-analyze` | skips players that already have a candidate file |
| `style-anchors-fetch` | skips anchors already done (`--redo` to rebuild) |

A job killed at the wrong moment can leave a half-written `.npz`; delete any file that fails to load (a check that
loads every candidate file is a good first step after a crash) and rerun.

## Laptops and sleep

`caffeinate -i -d` (macOS) stops *idle* sleep and display sleep, but **closing the lid still sleeps the machine**
(unless it is on power with an external display). A sleeping job is frozen, not killed, but network connections
time out on wake. Keep the lid open (screen dimmed), plug in, or stop the jobs cleanly and resume later.
Heavy analysis on battery drains it quickly.

## Memory pitfalls we hit

- **Never index a compressed `.npz` per item.** `z["name"][i]` inside a loop decompresses the whole array every time
  (quadratic time and memory; it once ballooned to tens of GB). Read each array once: `arrays = {k: z[k] for k in z.files}`.
- Several Stockfish workers with `Hash 64` use about 250 MB each; four workers plus the parent stay near 1.2 GB.
- On a memory-tight machine run **one heavy job at a time**, or accept slower progress from contention.
- Training: use CPU (`OMP_NUM_THREADS=4`) if the accelerator's memory is shared with the rest of the system.

## Disk space

- **Check `df -h` before long runs and after heavy test sessions.** A full disk shows up as odd failures (setup errors, files created empty, a
  model saving nothing), not as one clear message. The usual culprits: pytest temp folders (see [testing.md](testing.md)), model checkpoints
  (a training checkpoint holds the weights and two optimiser states, about three times the model), the Hugging Face cache, and scratch copies of
  datasets in `/tmp`.
- SQLite creates an **empty database file** if you point it at a path that does not exist; a query on a wrong path then fails with "no such table".

## Stopping and cleaning up

- `chessme control pause|resume|stop|clear|status [job]` works from any terminal; jobs check between units of work. Ctrl-C and SIGTERM also stop a
  job cleanly at its next checkpoint.
- After a crash or a killed session, look for stale processes (`pgrep -fl pytest`, `pgrep -fl stockfish`) before starting the next job: they hold
  memory and CPU, and timing-sensitive jobs (strength measurement, calibration) should not share the machine with anything heavy.
- In `zsh` a glob that matches nothing aborts the whole command line (`rm -rf /tmp/x*` with no match deletes nothing else either); use `bash -c`
  for cleanup scripts.

## On Kaggle

See [kaggle.md](kaggle.md): time budgets, checkpoints and resuming, and how to fetch the output.
