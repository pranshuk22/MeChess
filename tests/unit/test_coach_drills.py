import json

from chessme.coach import drills as D
from chessme.coach import exercises as X
from chessme.coach import server as CS
from tests.unit.test_coach_server import AFTER_F3_E5, PGN, fake_search

DAY = D.DAY


def ex():
    return X.exercise(AFTER_F3_E5, "g2g4", "e2e4", 0.9, 0.55, 0.0, ply=3, phase="opening", cls="blunder")


def test_a_new_position_is_due_after_ten_minutes_if_missed_and_moves_up_boxes_when_solved():
    s = D.DrillStore()
    s.record(ex(), success=False, now=0)
    assert s.due(now=5 * 60) == [] and len(s.due(now=11 * 60)) == 1
    assert s.items[ex()["id"]]["box"] == 0
    s.record(ex(), success=True, now=11 * 60)
    item = s.items[ex()["id"]]
    assert item["box"] == 1 and abs(item["due"] - (11 * 60 + DAY)) < 1
    for i in range(10):
        s.record(ex(), success=True, now=100 * DAY * (i + 1))
    assert s.items[ex()["id"]]["box"] == D.MAX_BOX
    s.record(ex(), success=False, now=2000 * DAY)
    assert s.items[ex()["id"]]["box"] == 0
    assert s.stats(now=2000 * DAY + 3600)["due"] == 1 and s.stats()["total"] == 1


def test_the_store_survives_a_restart_and_keeps_only_recent_history(tmp_path):
    path = tmp_path / "d" / "drills.json"
    s = D.DrillStore(path)
    for i in range(30):
        s.record(ex(), success=i % 2 == 0, now=float(i))
    again = D.DrillStore(path)
    assert again.items.keys() == s.items.keys() and len(again.items[ex()["id"]]["history"]) == 20
    assert json.loads(path.read_text())["items"]


def test_the_app_records_first_try_successes_and_misses_and_serves_due_drills(tmp_path):
    app = CS.CoachApp(fake_search, drills=D.DrillStore(tmp_path / "d.json"))
    assert app.start_drills()["none"] is True
    sid = app.start(PGN, 0, "white")["session"]
    app.act(sid, "attempt", {"uci": "g2g4"})                                  # a wrong try: nothing recorded yet
    assert app.drills.stats()["total"] == 0
    app.act(sid, "attempt", {"uci": "e2e4"})                                  # found, but after a wrong try: counts as missed
    item = next(iter(app.drills.items.values()))
    assert item["box"] == 0 and item["history"][-1][1] is False
    sid2 = app.start(PGN, 0, "white")["session"]
    app.act(sid2, "next")                                                    # skipped without finding it
    assert next(iter(app.drills.items.values()))["history"][-1][1] is False
    app.drills.items[ex()["id"]]["due"] = 0                                   # make it due
    started = app.start_drills()
    assert started["n"] == 1 and started["view"]["mode"] == "find"
    app.act(started["session"], "attempt", {"uci": "e2e4"})                   # first try without a hint: success
    assert next(iter(app.drills.items.values()))["box"] == 1


def test_reviewed_games_are_kept_once_and_feed_the_profile(tmp_path):
    app = CS.CoachApp(fake_search, data_dir=tmp_path / "coach")
    assert app.profile()["games"] == 0 and app.profile()["moves"] == 0
    app.start(PGN, 0, "white")
    app.start(PGN, 0, "white")                                                # the same game again: stored once
    prof = app.profile()
    assert prof["games"] == 1 and prof["moves"] == 2 and prof["sentences"] and "kinds" in prof
