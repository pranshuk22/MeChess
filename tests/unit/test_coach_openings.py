import chess

from chessme.coach import openings as O

REP = "1. e4 e5 2. Nf3 Nc6 3. Bb5 (3. Bc4 Bc5) 3... a6 4. Ba4 *"


def table(fen_to_rows):
    """A fake explorer: position key -> [(uci, share)]."""
    def replies(fen):
        return fen_to_rows.get(O.key(chess.Board(fen)), [])
    return replies


def explorer():
    b = chess.Board()
    t = {}

    def at(moves, rows):
        bb = chess.Board()
        for m in moves:
            bb.push_san(m)
        t[O.key(bb)] = rows
    at(["e4"], [("e7e5", 0.6), ("c7c5", 0.4)])
    at(["e4", "e5", "Nf3"], [("b8c6", 0.7), ("g8f6", 0.3)])
    at(["e4", "e5", "Nf3", "Nc6", "Bb5"], [("a7a6", 0.8), ("g8f6", 0.2)])
    return table(t)


def test_repertoire_reads_variations_and_both_colours():
    rep = O.Repertoire.from_pgn(REP, "white")
    start = chess.Board()
    assert rep.prepared(start) == {"e2e4": "e4"} and rep.size == 5          # e4, Nf3, Bb5, Bc4, Ba4
    b = chess.Board()
    for m in ["e4", "e5", "Nf3", "Nc6"]:
        b.push_san(m)
    assert rep.prepared(b) == {"f1b5": "Bb5", "f1c4": "Bc4"}                 # both branches are prepared
    assert O.Repertoire.from_pgn(REP, "black").prepared(chess.Board()) == {}


def test_the_drill_accepts_prepared_moves_and_rejects_others_with_the_expected_move():
    rep = O.Repertoire.from_pgn(REP, "white")
    d = O.OpeningDrill(rep, explorer(), seed=1)
    assert d.view()["color"] == "white" and "e2e4" in d.view()["legal"]
    bad = d.move("d2d4")
    assert bad["verdict"] == "not in your repertoire" and bad["expected"] == ["e4"] and d.mistakes == 1
    ok = d.move("e2e4")
    assert ok["verdict"] == "ok"
    v = d.view()
    assert v["line"][0] == "e4" and len(v["line"]) == 2                       # the opponent answered


def test_an_unanswered_reply_ends_the_line_and_says_how_common_it_is():
    rep = O.Repertoire.from_pgn(REP, "white")
    seen = set()
    for seed in range(40):
        d = O.OpeningDrill(rep, explorer(), seed=seed)
        d.move("e2e4")
        if d.over:
            seen.add(d.report["reason"])
            assert d.report["reason"] == "unanswered" and "c5" in d.report["reply"] and abs(d.report["share"] - 0.4) < 1e-9
            assert "no answer" in d.report["message"]
            assert d.move("e2e4")["error"] == "this line is finished"
    assert "unanswered" in seen


def test_playing_black_lets_the_opponent_start_and_theory_can_end():
    rep = O.Repertoire.from_pgn("1. e4 e5 2. Nf3 Nc6 *", "black")
    d = O.OpeningDrill(rep, explorer(), seed=0)
    assert d.view()["color"] == "black" and d.view()["line"] == []
    # the fake explorer knows nothing about the start position, so the white opponent cannot move: theory ends at once
    assert d.over and d.report["reason"] == "theory-ends"


def test_coverage_reports_the_share_kept_and_the_biggest_gaps():
    rep = O.Repertoire.from_pgn(REP, "white")
    cov = O.coverage(rep, explorer(), max_plies=10)
    assert abs(cov["covered"] - 0.6 * 0.7 * 0.8) < 1e-9                       # e5 (0.6), Nc6 (0.7), a6 (0.8): the prepared line ends after Ba4
    assert [g["line"] for g in cov["gaps"]] == ["e4 c5", "e4 e5 Nf3 Nf6", "e4 e5 Nf3 Nc6 Bb5 Nf6"]
    assert [round(g["share"], 3) for g in cov["gaps"]] == [0.4, 0.18, 0.084]
    assert abs(cov["covered"] + sum(g["share"] for g in cov["gaps"]) - 1.0) < 1e-9          # every game ends in exactly one of the two


def test_the_app_starts_an_opening_drill_checks_coverage_and_reports_missing_pieces():
    from chessme.coach import server as CS
    from tests.unit.test_coach_server import fake_search
    app = CS.CoachApp(fake_search, explorer=lambda rating: explorer())
    started = app.opening_start(REP, "white", 1500)
    assert started["moves"] == 5 and started["view"]["color"] == "white"
    sid = started["session"]
    assert app.opening_move(sid, "e2e4")["verdict"] == "ok"
    assert app.opening_move("nope", "e2e4")["error"] == "unknown session"
    cov = app.opening_coverage(REP, "white", 1500)
    assert abs(cov["covered"] - 0.336) < 1e-9 and cov["gaps"][0]["line"] == "e4 c5"
    assert "no moves of your colour" in app.opening_start("1. e4 *", "black", 1500)["error"]
    assert "not set up" in CS.CoachApp(fake_search).opening_start(REP, "white", 1500)["error"]
    assert "color" in app.opening_start(REP, "green", 1500)["error"]


def test_reaching_the_end_of_a_prepared_line_is_a_success_not_a_gap():
    rep = O.Repertoire.from_pgn("1. e4 e5 2. Nf3 *", "white")
    ends = set()
    for seed in range(40):
        d = O.OpeningDrill(rep, explorer(), seed=seed)
        d.move("e2e4")
        if d.view()["line"][-1] == "e5":
            d.move("g1f3")
            assert d.over and d.report["reason"] == "repertoire-ends" and "end of your prepared line" in d.report["message"]
            ends.add(True)
    assert ends
