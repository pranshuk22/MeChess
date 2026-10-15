import io
import json

import chess.pgn

from chessme.coach import reference as R
from chessme.coach import server as CS
from tests.unit.test_coach_profile import analysis_for
from tests.unit.test_coach_server import fake_search

LONG = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 8. c3 O-O 9. h3 Nb8 10. d4 Nbd7 1-0"


def row(phase, loss, situation="level"):
    return {"phase": phase, "situation": situation, "loss": loss, "kind": "deeper" if loss >= 0.1 else None}


def game(white=1500, black=1520, tc="180+0", moves=LONG, event="Rated Blitz game", **extra):
    h = {"Event": event, "Result": "1-0", "WhiteElo": str(white), "BlackElo": str(black), "TimeControl": tc, "Termination": "Normal"}
    h.update(extra)
    pgn = "".join(f'[{k} "{v}"]\n' for k, v in h.items()) + "\n" + moves + "\n\n"
    return chess.pgn.read_game(io.StringIO(pgn))


def test_bands_are_clamped_to_the_bands_that_exist():
    assert R.band_of(1531) == 1400 and R.band_of(900) == 1000 and R.band_of(2650) == 2400 and R.band_of(1000) == 1000


def test_selection_fills_quotas_and_applies_the_filters():
    games = [game(), game(), game(),                                                  # the third blitz game is over the quota of 2
             game(1500, 1900),                                                        # players too far apart
             game(tc="60+0"),                                                         # bullet is not a requested speed
             game(tc="900+10"),                                                       # rapid: has its own quota
             game(event="Casual Blitz game"), game(Variant="Chess960"),
             game(moves="1. e4 e5 1-0")]                                              # too short
    picked = list(R.select_games(games, 2))
    assert sorted(R.speed_of(g.headers) for g in picked) == ["blitz", "blitz", "rapid"]


def test_selection_stops_reading_when_every_quota_is_full():
    def stream():
        for lo in range(R.LOWEST, R.HIGHEST + 1, R.BAND):
            yield game(lo + 50, lo + 60)
        raise AssertionError("read past the full quotas")
    assert len(list(R.select_games(stream(), 1, speeds=("blitz",)))) == len(range(R.LOWEST, R.HIGHEST + 1, R.BAND))


def test_counts_go_to_the_band_of_each_players_own_rating():
    a = analysis_for(["e2e4", "e7e5", "g1f3", "b8c6"], [0.0, 0.0, 0.15, 0.3])
    ref = R.tally([("blitz", {"white": 1450, "black": 1850}, a)], nodes=1000, multipv=5)
    w, b = ref["cells"]["blitz|1400"], ref["cells"]["blitz|1800"]
    assert (w["moves"], w["mistakes"], w["blunders"]) == (2, 1, 0) and (b["moves"], b["mistakes"], b["blunders"]) == (2, 1, 1)
    assert w["by_phase"]["middlegame"] == [2, 1] and w["kinds"] == {"deeper": 1}


def make_ref(mistakes, moves, nodes=100000):
    cell = {"games": 100, "moves": moves, "mistakes": mistakes, "blunders": 0, "by_phase": {"endgame": [moves // 4, mistakes // 4], "middlegame": [moves // 2, mistakes // 2]},
            "by_situation": {"level": [moves, mistakes]}, "kinds": {}}
    return {"version": 1, "nodes": nodes, "multipv": 5, "cells": {"blitz|1400": cell}}


def test_a_clear_difference_is_reported_in_both_directions_and_a_small_one_is_not():
    ref = make_ref(mistakes=10000, moves=100000)                                      # 10% in the band, in every area
    worse = [row("endgame", 0.2)] * 30 + [row("endgame", 0.0)] * 70 + [row("middlegame", 0.0)] * 200
    cmp = R.compare(worse, 1450, "blitz", ref)
    assert "phase: endgame" in [f["area"] for f in cmp["findings"]] and cmp["areas"]["phase: endgame"]["z"] > 0
    text = " ".join(R.sentences(cmp))
    assert "more than players rated 1400 to 1599" in text and cmp["comparable"]
    fine = [row("endgame", 0.2)] * 6 + [row("endgame", 0.0)] * 54
    assert R.compare(fine, 1450, "blitz", ref)["findings"] == []
    better = [row("middlegame", 0.0)] * 300
    assert "less than" in " ".join(R.sentences(R.compare(better, 1450, "blitz", ref)))


def test_no_cell_or_no_rows_gives_no_comparison_and_another_budget_is_flagged():
    ref = make_ref(10000, 100000)
    assert R.compare([row("endgame", 0.0)] * 40, 1450, "rapid", ref) is None and R.compare([], 1450, "blitz", ref) is None
    assert R.compare([row("endgame", 0.0)] * 40, 1450, "blitz", None) is None
    cmp = R.compare([row("endgame", 0.0)] * 40, 1450, "blitz", ref, nodes=5000)
    assert not cmp["comparable"] and "another budget or number of lines" in " ".join(R.sentences(cmp))
    assert not R.compare([row("endgame", 0.0)] * 40, 1450, "blitz", ref, nodes=100000, multipv=2)["comparable"]      # same nodes, other lines
    assert R.compare([row("endgame", 0.0)] * 40, 1450, "blitz", ref, nodes=100000, multipv=5)["comparable"]


def test_save_and_load_round_trip_and_a_missing_file_is_none(tmp_path):
    ref = make_ref(10, 100)
    R.save(ref, tmp_path / "r.json")
    assert R.load(tmp_path / "r.json") == ref and R.load(tmp_path / "none.json") is None


PGN_RATED = """[Event "Rated Blitz game"]
[White "a"]
[Black "b"]
[Result "0-1"]
[WhiteElo "1450"]
[BlackElo "1500"]
[TimeControl "180+0"]

1. f3 e5 2. g4 Qh4# 0-1
"""


def test_the_profile_compares_with_the_reference_when_the_games_carry_ratings(tmp_path):
    ref = make_ref(mistakes=1000, moves=100000)
    app = CS.CoachApp(fake_search, data_dir=tmp_path / "coach", reference=ref, nodes=777)
    app.start(PGN_RATED, 0, "white")
    prof = app.profile()
    assert prof["reference"]["band"] == 1400 and prof["reference"]["speed"] == "blitz" and not prof["reference"]["comparable"]
    stored = json.loads(next((tmp_path / "coach" / "games").glob("*.json")).read_text())
    assert stored["rating"] == 1450 and stored["speed"] == "blitz"
    assert "reference" not in CS.CoachApp(fake_search, data_dir=tmp_path / "coach").profile()      # no reference: no comparison, nothing breaks


def test_a_game_without_ratings_is_kept_and_skipped_by_the_comparison(tmp_path):
    app = CS.CoachApp(fake_search, data_dir=tmp_path / "coach", reference=make_ref(10, 100))
    app.start(PGN_RATED.replace('[WhiteElo "1450"]\n', "").replace('[BlackElo "1500"]\n', ""), 0, "white")
    prof = app.profile()
    assert prof["games"] == 1 and "reference" not in prof


# ---- reading a dump by byte windows, and the three commands ---------------------------------------------------------------------

def _dump(tmp_path):
    from tests.unit.test_explorer_rangescan import make_dump
    from tests.unit.test_humanlike_testset import make_game
    games = [str(make_game(site=f"win{i:05d}", WhiteElo=str(1000 + 100 * (i % 15)), BlackElo=str(1000 + 100 * (i % 15)))) + "\n\n" for i in range(60)]
    games[7] = games[7].replace("Rated Blitz", "Casual Blitz")
    buf, _ = make_dump(["".join(games[i:i + 10]) for i in range(0, 60, 10)])
    p = tmp_path / "month.pgn.zst"
    p.write_bytes(buf)
    return p


def test_a_header_test_skips_the_moves_of_the_games_that_are_not_wanted():
    text = str(game(1500, 1520)) + "\n\n" + str(game(1500, 1520, Site="x2")) + "\n\n"
    both = list(R.reader(io.StringIO(text), None))
    assert len(both) == 2 and all(g.next() is not None for g in both)
    some = list(R.reader(io.StringIO(text), lambda h: h.get("Site") == "x2"))
    assert len(some) == 2 and some[0].next() is None and some[1].next() is not None       # skipped: headers only, no moves


def test_windows_of_a_dump_give_the_wanted_games_without_the_cut_ones(tmp_path):
    dump = _dump(tmp_path)
    got = list(R.iter_window_games(str(dump), 6, [0, 1, 2, 3, 4, 5], wants=lambda h: h.get("Event", "").startswith("Rated")))
    ids = {g.headers["Site"] for g in got}
    assert ids and all(g.next() is not None for g in got) and len(ids) < 60 and "https://lichess.org/win00007" not in ids      # the casual game is not wanted


def test_the_commands_pick_games_analyse_nothing_and_count(tmp_path, monkeypatch, capsys):
    import sys

    from chessme import cli
    dump = _dump(tmp_path)

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["chessme", *map(str, argv)])
        cli.main()
    run("coach-reference-games", "--source", dump, "--parts", 6, "--windows", "0,1,2,3,4,5", "--per-band", 1, "--min-plies", 8, "--out", tmp_path / "ref.pgn")
    out = capsys.readouterr().out
    n = len(list(R.reader(open(tmp_path / "ref.pgn"), None)))
    assert 0 < n <= 16 and f"{n} games written" in out and "quotas not filled" in out        # 16 cells of one game each; rapid has none
    # a fake analysis folder for the picked games, then the build command
    import json

    from chessme.analysis import runner as AR
    (tmp_path / "an" / "games").mkdir(parents=True)
    f = open(tmp_path / "ref.pgn")
    for g in iter(lambda: chess.pgn.read_game(f), None):
        (tmp_path / "an" / "games" / f"{AR.game_key(g)}.json").write_text(json.dumps(analysis_for([m.uci() for m in g.mainline_moves()], [0.0, 0.3] * 6)))
    run("coach-reference-build", "--pgn", tmp_path / "ref.pgn", "--analysis", tmp_path / "an", "--nodes", 123, "--multipv", 5, "--out", tmp_path / "r.json")
    ref = R.load(tmp_path / "r.json")
    assert ref["nodes"] == 123 and sum(c["games"] for c in ref["cells"].values()) == 2 * n and all(k.startswith("blitz|") for k in ref["cells"])
    assert all(c["mistakes"] * 2 == c["moves"] for c in ref["cells"].values())                # every second move lost 0.3
