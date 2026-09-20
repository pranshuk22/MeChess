import json

from chessme.style import status as S

PS = """  PID ELAPSED   RSS COMMAND
  101 22:11   11000 .venv/bin/python -u -m chessme style-cohort-fetch https://example.org/dump.pgn.zst --players 1000
  102 22:03   10240 .venv/bin/python -u -m chessme style-cohort-analyze --out data/style/cohort --workers 4
  103 01:50   65536 stockfish
  104 01:50   65536 stockfish
  105 22:11    2048 /bin/bash tools/watch.sh 1500 .venv/bin/python -u -m chessme style-cohort-fetch x
  106 00:01    1024 grep stockfish
  107 00:05    9000 unrelated_program --flag
"""


def test_ps_output_is_parsed_and_only_known_jobs_are_listed():
    procs = S.parse_ps(PS)
    assert (101, "22:11", 10, ".venv/bin/python -u -m chessme style-cohort-fetch https://example.org/dump.pgn.zst --players 1000") in procs
    jobs = S.running(PS)
    assert set(jobs) == {"cohort fetch", "cohort / anchors analysis", "stockfish workers"}
    assert jobs["stockfish workers"]["processes"] == 2 and jobs["stockfish workers"]["rss_mb"] == 128
    assert jobs["cohort fetch"]["processes"] == 1        # the watch.sh wrapper and grep are not counted


def test_garbage_ps_lines_are_ignored():
    assert S.parse_ps("header\nnot a number here\n12 abc 5 cmd\n") == []
    assert S.running("header only") == {}


def test_folder_progress_counts_files_and_tolerates_missing_folders(tmp_path):
    assert S.folder_progress(tmp_path / "nothing") == {"fetched": 0, "rejected": 0, "items": 0, "analysed": 0}
    (tmp_path / "items").mkdir()
    (tmp_path / "cands").mkdir()
    for n in ("a", "b", "c"):
        (tmp_path / "items" / f"{n}.jsonl").write_text("{}")
    (tmp_path / "cands" / "a.npz").write_bytes(b"x")
    (tmp_path / "players.json").write_text(json.dumps({"a": {}, "b": {}, "c": {}}))
    (tmp_path / "rejected.json").write_text(json.dumps(["z"]))
    assert S.folder_progress(tmp_path) == {"fetched": 3, "rejected": 1, "items": 3, "analysed": 1}
    (tmp_path / "players.json").write_text("{broken")
    assert S.folder_progress(tmp_path)["fetched"] == 0


def test_rate_comes_from_the_recent_progress_lines(tmp_path):
    log = tmp_path / "l.log"
    log.write_text("start\n  [  100s] 10/1000 players\n  [  200s] 20/1000 players\nnoise\n  [  300s] 30/1000 players\n")
    assert abs(S.rate_from_log(log) - 0.1) < 1e-9
    log.write_text("nothing useful\n")
    assert S.rate_from_log(log) is None and S.rate_from_log(tmp_path / "missing.log") is None
    log.write_text("  [  100s] 10/1000 x\n  [  100s] 10/1000 x\n")     # no time or count change: no rate
    assert S.rate_from_log(log) is None


def test_null_bytes_from_an_overwritten_log_do_not_break_parsing(tmp_path):
    log = tmp_path / "l.log"
    log.write_bytes(b"\0\0\0\n  [  100s] 10/1000 x\n  [  200s] 30/1000 x\n")
    assert abs(S.rate_from_log(log) - 0.2) < 1e-9 and S.last_lines(log, 1) == ["  [  200s] 30/1000 x"]


def test_eta_text():
    assert S.eta_text(0, 1.0) == "done"
    assert "unknown" in S.eta_text(50, None)
    assert S.eta_text(600, 1.0) == "about 10 min"
    assert S.eta_text(36000, 1.0) == "about 10.0 h"


def test_render_shows_progress_eta_jobs_and_log_lines(tmp_path):
    cohort, anchors, logs = tmp_path / "c", tmp_path / "a", tmp_path / "logs"
    (cohort / "items").mkdir(parents=True)
    (cohort / "players.json").write_text(json.dumps({str(i): {} for i in range(250)}))
    logs.mkdir()
    (logs / "cohort_fetch.log").write_text("  [   10s] 100/1000 players\n  [  110s] 200/1000 players\n")
    text = S.render(cohort=cohort, anchors=anchors, target=1000, logs=logs, jobs=S.running(PS), now="12:00:00")
    for needle in ("12:00:00", "cohort fetch", "fetched     250 / 1000", "(25%)", "ETA about", "cohort_fetch:",
                   "200/1000 players", "(log not found)", "stockfish workers"):
        assert needle in text, needle
    assert "nothing running" in S.render(cohort=cohort, anchors=anchors, target=1000, logs=logs, jobs={})
