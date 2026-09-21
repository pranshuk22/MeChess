import io
import sqlite3

import chess
import pytest

from chessme.book import explorer as X
from chessme.mechess.controller import BookReader

EDGES = (600, 1000, 1400, 1800, 2200)


def game(w, b, result, moves, tc="300+0", term="Normal", comments=None, site=None):
    """comments: optional list of strings placed after each move, e.g. '[%eval 0.3] [%clk 0:04:58]'."""
    r = {1.0: "1-0", 0.5: "1/2-1/2", 0.0: "0-1"}[result]
    parts = []
    for i, m in enumerate(moves):
        c = f" {{ {comments[i]} }}" if comments and comments[i] else ""
        parts.append((f"{i // 2 + 1}. " if i % 2 == 0 else "") + m + c)
    body = " ".join(parts) + f" {r}"
    site_tag = f"https://lichess.org/{site}" if site else "s"
    return (f'[Event "x"]\n[Site "{site_tag}"]\n[White "a"]\n[Black "b"]\n[Result "{r}"]\n[WhiteElo "{w}"]\n[BlackElo "{b}"]\n[TimeControl "{tc}"]\n'
            f'[Termination "{term}"]\n\n{body}\n\n')


ITALIAN = "e4 e5 Nf3 Nc6 Bc4 Bc5".split()
SCOTCH = "e4 e5 Nf3 Nc6 d4 exd4".split()
FRENCH = "e4 e6 d4 d5".split()


def dump(n_italian, n_scotch, n_french=0, rating=1500):
    return "".join([game(rating, rating, 1.0, ITALIAN)] * n_italian + [game(rating, rating, 0.5, SCOTCH)] * n_scotch
                   + [game(rating, rating, 0.0, FRENCH)] * n_french)


def stream(text):
    return lambda: io.StringIO(text)


def rec(text):
    return X.header_record(next(X.iter_games(io.StringIO(text))))


def run(tmp, text, **kw):
    """A small run with permissive thresholds (the tests state what they change)."""
    args = dict(edges=EDGES, max_ply=4, holdout=0, db_min_games=1, db_min_frac=0, book_min_games=1, book_min_frac=0, book_min_share=0.0,
                max_per_band=10 ** 9, opener=stream(text), log=lambda *_: None)
    args.update(kw)
    return X.run("x", tmp, **args)


# ---- keys, packing, parsing -------------------------------------------------------------------------------------------

def test_pack_unpack_and_keys():
    v = X.pack(1.0, 1500) + X.pack(0.5, 1600) + X.pack(0.0, 1400) + X.pack(1.0, 1500)
    assert X.unpack(v) == (4, 2, 1, 1) and X.avg_rating_of(v) == 1500.0
    assert X.unmove16(X.move16(chess.Move.from_uci("e7e8q"))) == chess.Move.from_uci("e7e8q")
    b = chess.Board()
    k = X.pos_key(b)
    b.push_uci("e2e4")
    assert X.pos_key(b) != k and X.pos_key(chess.Board()) == k and -(1 << 63) <= X.signed64(X.pos_key(b)) < (1 << 63)
    a, c = chess.Board(), chess.Board()                                    # transpositions merge
    for m in ("g1f3", "g8f6", "b1c3"):
        a.push_uci(m)
    for m in ("b1c3", "g8f6", "g1f3"):
        c.push_uci(m)
    assert X.pos_key(a) == X.pos_key(c)


def test_iter_games_reads_headers_and_the_first_plies_with_comments():
    text = ('[Event "x"]\n[WhiteElo "1500"]\n[BlackElo "1480"]\n[Result "1-0"]\n[TimeControl "300+3"]\n[Termination "Normal"]\n\n'
            '1. e4 { [%eval 0.3] [%clk 0:05:00] } 1... e5 { [%eval #-4] [%clk 0:04:58] } 2. Nf3 $1 Nc6 3. Bb5 a6 4. Ba4 Nf6 1-0\n\n' + game(1200, 1210, 0.0, FRENCH))
    games = [X.header_record(t) for t in X.iter_games(io.StringIO(text))]
    sans, evals, clocks, last = X.parse_moves(games[0]["line"], 5)
    assert sans == ["e4", "e5", "Nf3", "Nc6", "Bb5"] and evals[:2] == [30, -1000] and evals[2] is None and clocks[:2] == [300.0, 298.0] and last == 4
    assert games[0]["base"] == 300 and games[0]["inc"] == 3 and games[0]["result"] == 1.0 and games[1]["white"] == 1200
    assert X.parse_moves(games[1]["line"], 10)[0] == FRENCH


def test_eval_and_clock_parsing():
    assert X.eval_cp("[%eval 0.17]") == 17 and X.eval_cp("[%eval -2.5]") == -250 and X.eval_cp("[%eval #3]") == 1000 and X.eval_cp("[%eval #-3]") == -1000
    assert X.eval_cp("[%eval 45.0]") == 1000 and X.eval_cp("[%clk 0:01:00]") is None and X.eval_cp(None) is None
    assert X.clock_seconds("[%clk 1:02:03]") == 3723 and X.clock_seconds("[%clk 0:00:09.5]") == 9.5 and X.clock_seconds("x") is None


def test_band_filter_keeps_bullet_and_excludes_ultrabullet_abnormal_and_mismatched_games():
    assert X.band_of(rec(game(1500, 1520, 1.0, ITALIAN)), EDGES) == 2
    assert X.band_of(rec(game(1500, 1520, 1.0, ITALIAN, tc="60+0")), EDGES) == 2                    # bullet is counted
    assert X.band_of(rec(game(1500, 1520, 1.0, ITALIAN, tc="15+0")), EDGES) is None                # ultra-bullet is not
    assert X.band_of(rec(game(1500, 1520, 1.0, ITALIAN, tc="60+0")), EDGES, min_base=180) is None   # unless asked to skip bullet
    assert X.band_of(rec(game(1500, 1520, 1.0, ITALIAN, term="Abandoned")), EDGES) is None
    assert X.band_of(rec(game(1200, 1700, 1.0, ITALIAN)), EDGES) is None
    assert X.band_of(rec(game(3500, 3500, 1.0, ITALIAN)), EDGES) is None


def test_speed_classes_follow_the_lichess_estimated_duration():
    assert [X.speed_of(*t) for t in ((60, 0), (120, 1), (180, 0), (300, 3), (600, 0), (900, 10), (1800, 0))] == ["bullet", "bullet", "blitz", "blitz", "rapid", "rapid", "classical"]


def test_all_default_bands_cover_the_whole_rating_range_without_gaps():
    e = X.DEFAULT_BANDS
    assert e[0] == 0 and e[-1] >= 3500 and all(a < b for a, b in zip(e, e[1:])) and 2600 in e and 800 in e
    for r in (100, 799, 800, 1500, 2599, 2600, 3200):
        assert X.band_of({"base": 300, "termination": "Normal", "white": r, "black": r}, e) is not None


# ---- the counting run: exact numbers ------------------------------------------------------------------------------------

def test_counting_run_builds_db_books_and_report_with_exact_totals(tmp_path):
    res = run(tmp_path, dump(60, 20, 20), holdout=10, max_ply=6, book_min_games=10, book_min_share=0.05, db_min_games=5)
    assert res["scanned"] == 100 and res["counted"] == 100                            # the 10 held-out games are counted too, after the coverage test
    rows = X.query(tmp_path / "explorer.db", chess.STARTING_FEN, rating=1500)
    assert [r["san"] for r in rows] == ["e4"] and rows[0]["games"] == 100 and abs(rows[0]["avg_rating"] - 1500) < 1e-9
    b = chess.Board()
    for m in ("e4", "e5", "Nf3", "Nc6"):
        b.push_san(m)
    moves = X.query(tmp_path / "explorer.db", b.fen(), rating=1500)
    assert [(m["san"], m["games"]) for m in moves] == [("Bc4", 60), ("d4", 20)]                # exact: nothing sampled, nothing lost
    assert abs(moves[1]["draw"] - 1.0) < 1e-9 and abs(moves[0]["white"] - 1.0) < 1e-9
    assert {m.uci() for m, _ in BookReader(tmp_path / "theory_1400_1800.bin").moves(chess.Board())} == {"e2e4"}
    assert "1400-1800" in (tmp_path / "report.md").read_text() and res["coverage"][2][4] > 0.9


def test_the_statistics_equal_an_independent_tally_of_the_same_games(tmp_path):
    text = dump(30, 12, 8, rating=1500) + dump(9, 0, 0, rating=1100) + dump(4, 1, 0, rating=2000) + game(1500, 1900, 1.0, ITALIAN) * 3
    res = run(tmp_path, text)
    db = sqlite3.connect(tmp_path / "explorer.db")
    counted = {b: g for b, g in db.execute("SELECT id, games FROM bands")}
    expect = {}
    for tags in X.iter_games(io.StringIO(text)):                                       # a plain, separate count of the qualifying games
        g = X.header_record(tags)
        b = X.band_of(g, EDGES)
        if b is not None:
            expect[b] = expect.get(b, 0) + 1
    assert {b: n for b, n in counted.items() if n} == expect and sum(counted.values()) == res["counted"] == 30 + 12 + 8 + 9 + 4 + 1
    per_move = {b: g for b, g in db.execute("SELECT band, SUM(games) FROM moves WHERE uci='e2e4' GROUP BY band")}
    assert per_move == {b: n for b, n in expect.items()}                                # every game starts with e4: the move counts add up exactly


def test_rating_picks_the_band_and_unknown_positions_return_nothing(tmp_path):
    run(tmp_path, dump(30, 0, 0, rating=1200) + dump(30, 0, 0, rating=1900))
    assert X.query(tmp_path / "explorer.db", chess.STARTING_FEN, rating=1200)[0]["games"] == 30
    assert X.query(tmp_path / "explorer.db", chess.STARTING_FEN, rating=1900)[0]["games"] == 30
    assert X.query(tmp_path / "explorer.db", chess.STARTING_FEN, rating=5000)[0]["games"] == 30       # nearest band when outside all bands
    odd = chess.Board(); odd.push_san("a4")
    assert X.query(tmp_path / "explorer.db", odd.fen(), rating=1200) == []


# ---- windows: every band has its own ----------------------------------------------------------------------------------

def test_a_full_band_stops_collecting_while_a_rare_band_keeps_going_over_the_whole_scan(tmp_path):
    text = dump(40, 0, 0, rating=1500) + dump(3, 0, 0, rating=2000) + dump(40, 0, 0, rating=1500) + dump(3, 0, 0, rating=2000)
    res = run(tmp_path, text, max_per_band=25)
    db = sqlite3.connect(tmp_path / "explorer.db")
    bands = {b: (g, w) for b, g, w in db.execute("SELECT id, games, window_end FROM bands")}
    assert bands[2] == (25, 25)                       # the dense band filled at game 25 and ignored the rest
    assert bands[3][0] == 6 and bands[3][1] is None   # the rare band never filled: all its games over the whole scan are counted
    report = (tmp_path / "report.md").read_text()
    assert "first 25 games of the scan" in report and "whole scan (86 games)" in report and res["counted"] == 25 + 6
    pop = dict(db.execute("SELECT band, SUM(games) FROM population GROUP BY band"))
    assert pop[2] == 80 and pop[3] == 6              # the population statistics still cover every scanned game


def test_the_scan_stops_early_when_every_band_is_full(tmp_path):
    res = run(tmp_path, dump(50, 0, 0, rating=1500) + dump(50, 0, 0, rating=2000), edges=(0, 1800, 4000), max_per_band=10)
    assert res["scanned"] == 60 and res["finished"]                       # the 1500 band fills at game 10; the 2000 band gets its 10th game at game 60


def test_held_out_games_test_coverage_honestly_and_are_then_counted(tmp_path):
    # the first 5 games play an opening that no other game plays: the book (built without them) cannot contain it
    unique = game(1500, 1500, 1.0, "d4 d5 c4 e6".split()) * 5
    res = run(tmp_path, unique + dump(40, 0, 0), holdout=5, book_min_games=10)
    assert res["coverage"][2][4] == 0.0                                           # held-out games are not in the book: 0% covered
    assert res["counted"] == 45                                                     # ...but they are in the final counts
    b = chess.Board(); b.push_san("d4")
    assert {m.uci() for m, _ in BookReader(tmp_path / "theory_1400_1800.bin").moves(chess.Board())} == {"e2e4"}     # d4 is not in the book
    assert X.query(tmp_path / "explorer.db", chess.STARTING_FEN, rating=1500)[1]["san"] == "d4"                     # but it is in the explorer


def test_thresholds_scale_with_the_size_of_the_band(tmp_path):
    assert X.scaled_min(20, 5e-5, 1_000_000) == 50 and X.scaled_min(20, 5e-5, 100_000) == 20 and X.scaled_min(5, 1e-5, 2_000_000) == 20
    # a dense band ignores a move that a thin band keeps: both have 3 games of 1.e4 c5
    dense = dump(300, 0, 0, rating=1500) + game(1500, 1500, 1.0, "e4 c5".split()) * 3
    thin = dump(30, 0, 0, rating=1100) + game(1100, 1100, 1.0, "e4 c5".split()) * 3
    run(tmp_path, dense + thin, db_min_games=2, db_min_frac=0.02)              # floor: max(2, 2% of the band): 6 games in the dense band, 2 in the thin one
    b = chess.Board(); b.push_san("e4")
    assert {m["san"] for m in X.query(tmp_path / "explorer.db", b.fen(), rating=1500)} == {"e5"}                # 3 games < 6
    assert {m["san"] for m in X.query(tmp_path / "explorer.db", b.fen(), rating=1100)} == {"e5", "c5"}


# ---- what is recorded --------------------------------------------------------------------------------------------------

def annotated_game(n, evals_after_e4, rating=1500, result=1.0):
    """n identical games with evaluations after the first white move and clocks (5+0 game, White spends 2 s then 10 s, Black 3 s)."""
    comments = [f"[%eval {evals_after_e4}] [%clk 0:04:58]", "[%clk 0:04:57]", "[%eval 0.1] [%clk 0:04:48]", "[%clk 0:04:52]"]
    return game(rating, rating, result, "e4 e5 Nf3 Nc6".split(), comments=comments) * n


def test_evaluations_ratings_clock_and_band_statistics_are_recorded(tmp_path):
    text = annotated_game(40, 0.3) + game(1500, 1500, 0.5, "e4 e5 Nf3 Nc6".split()) * 10
    run(tmp_path, text, db_min_games=5)
    rows = X.query(tmp_path / "explorer.db", chess.STARTING_FEN, rating=1500)
    assert rows[0]["san"] == "e4" and rows[0]["games"] == 50 and rows[0]["eval_n"] == 40 and abs(rows[0]["eval"] - 0.3) < 1e-9
    db = sqlite3.connect(tmp_path / "explorer.db")
    band, games, white, draws, moves, analysed = db.execute("SELECT * FROM band_stats WHERE games > 0").fetchone()
    assert (games, white, draws, analysed) == (50, 40, 10, 40) and moves == 50 * 2
    spent = {ply: (n, s, inst) for _, ply, n, s, inst in db.execute("SELECT band, ply, n, spent_sum, instant FROM clock WHERE speed='blitz'")}
    assert spent[1] == (40, 40 * 2.0, 0) and spent[2] == (40, 40 * 3.0, 0) and abs(spent[3][1] / spent[3][0] - 10.0) < 1e-9


def test_population_statistics_cover_every_scanned_game_not_only_counted_ones(tmp_path):
    text = (dump(8, 0, rating=1500) + game(1500, 1500, 1.0, ITALIAN, tc="60+0") * 4 + game(1500, 1500, 1.0, ITALIAN, term="Time forfeit") * 3
            + game(1500, 1500, 1.0, ITALIAN, term="Abandoned") * 2 + game(2450, 2450, 1.0, ITALIAN, tc="60+0") * 6 + game(1500, 1900, 1.0, ITALIAN) * 5)
    res = run(tmp_path, text, edges=EDGES + (2600,))
    db = sqlite3.connect(tmp_path / "explorer.db")
    pop = {(b, s, t): n for b, s, t, n in db.execute("SELECT band, speed, termination, games FROM population")}
    assert pop[(2, "bullet", "Normal")] == 4 and pop[(2, "blitz", "Time forfeit")] == 3 and pop[(2, "blitz", "Abandoned")] == 2          # nothing filtered out
    hist = dict(db.execute("SELECT bin, games FROM rating_hist"))
    assert hist[1500] == 8 + 4 + 3 + 2 and hist[1700] == 5 and hist[2450] == 6 and sum(hist.values()) == 28 == res["scanned"]
    mix = {(b, s): n for b, s, n in db.execute("SELECT band, speed, games FROM speed_mix")}
    assert mix[(2, "bullet")] == 4 and mix[(2, "blitz")] == 8 + 3
    text_report = (tmp_path / "report.md").read_text()
    assert "Who plays what" in text_report and "exact" in text_report


def test_result_bar_and_text_rows():
    assert X.bar(0.5, 0.0, 0.5, 10) == "░░░░░█████" and X.bar(1.0, 0.0, 0.0, 10) == "░" * 10 and len(X.bar(0.33, 0.34, 0.33, 30)) == 30
    text = X.format_rows([{"san": "e4", "games": 1234, "share": 0.6, "white": 0.5, "draw": 0.1, "black": 0.4, "avg_rating": 1512.3, "eval": 0.25, "eval_n": 80}])
    assert "e4" in text and "1,234" in text and "60.0%" in text and "+0.25" in text and "50/10/40" in text and "░" in text and "█" in text


def test_opening_names_are_stored_and_found_by_position(tmp_path):
    names = tmp_path / "names"
    names.mkdir()
    (names / "a.tsv").write_text("eco\tname\tpgn\nC44\tKing's Pawn Game\t1. e4 e5 2. Nf3\nB00\tKing's Pawn\t1. e4\n")
    run(tmp_path / "o", dump(10, 0), openings_dir=names)
    b = chess.Board(); b.push_san("e4")
    assert X.opening_at(tmp_path / "o" / "explorer.db", b.fen()) == ("B00", "King's Pawn")
    assert X.opening_at(tmp_path / "o" / "explorer.db", chess.STARTING_FEN) is None


def test_the_evaluation_test_drops_a_popular_but_bad_move_when_asked(tmp_path):
    good = game(1500, 1500, 1.0, "e4 e5 Nf3 Nc6".split(), comments=[None, None, None, "[%eval 0.2]"]) * 60
    bad = game(1500, 1500, 1.0, "e4 e5 Nf3 f6".split(), comments=[None, None, None, "[%eval 3.0]"]) * 30
    plain = run(tmp_path / "a", good + bad, book_min_games=5, book_min_share=0.05)
    strict = run(tmp_path / "b", good + bad, book_min_games=5, book_min_share=0.05, eval_margin_cp=150)
    assert plain["books"][2][0] > strict["books"][2][0] and strict["books"][2][2] == 1
    b = chess.Board()
    for m in ("e4", "e5", "Nf3"):
        b.push_san(m)
    assert {m.uci() for m, _ in BookReader(tmp_path / "b" / "theory_1400_1800.bin").moves(b)} == {"b8c6"}
    assert {m.uci() for m, _ in BookReader(tmp_path / "a" / "theory_1400_1800.bin").moves(b)} == {"b8c6", "f7f6"}


# ---- checkpoints, resuming, stopping ------------------------------------------------------------------------------------

def test_checkpoint_resume_skips_games_already_scanned_and_matches_an_uninterrupted_run():
    text = dump(30, 10)
    ref = X.Counts(len(EDGES) - 1)
    X.count_stream(stream(text), ref, edges=EDGES, max_ply=6, holdout=0, log=lambda *_: None)
    c = X.Counts(len(EDGES) - 1)
    X.count_stream(stream(text), c, edges=EDGES, max_ply=6, holdout=0, max_scan=25, log=lambda *_: None)
    assert c.scanned == 25
    X.count_stream(stream(text), c, edges=EDGES, max_ply=6, holdout=0, log=lambda *_: None)
    assert c.games == ref.games and c.tables == ref.tables and c.population == ref.population


def test_the_state_file_round_trips_everything(tmp_path):
    c = X.Counts(len(EDGES) - 1)
    X.count_stream(stream(annotated_game(6, 0.3) + dump(5, 0)), c, edges=EDGES, max_ply=4, holdout=2, max_per_band=8, log=lambda *_: None)
    X.save_state(tmp_path / "s.pkl.gz", c, c.scanned, {"k": 1})
    d = X.load_state(tmp_path / "s.pkl.gz")
    assert (d.tables, d.evals, d.clock, d.stats, d.games, d.speed_games, d.population, d.rating_hist, d.window_end, d.scanned, d.config) == \
           (c.tables, c.evals, c.clock, c.stats, c.games, c.speed_games, c.population, c.rating_hist, c.window_end, c.scanned, {"k": 1})
    assert len(d.held_out[2]) == 2 and d.held_out[2][0]["white"] == 1500


def test_reconnects_after_a_dropped_stream_and_skips_what_it_already_read():
    text = dump(30, 10)
    calls = {"n": 0}

    class Flaky(io.StringIO):
        def __iter__(self):
            for i, line in enumerate(iter(self.readline, "")):
                if calls["n"] == 1 and i > 120:
                    raise OSError("connection reset")
                yield line

    def opener():
        calls["n"] += 1
        return Flaky(text)
    c = X.Counts(len(EDGES) - 1)
    X.count_stream(opener, c, edges=EDGES, max_ply=6, holdout=0, log=lambda *_: None)
    ref = X.Counts(len(EDGES) - 1)
    X.count_stream(stream(text), ref, edges=EDGES, max_ply=6, holdout=0, log=lambda *_: None)
    assert calls["n"] == 2 and c.tables == ref.tables and c.scanned == 40


def test_a_checkpoint_from_other_settings_is_refused(tmp_path):
    run(tmp_path, dump(30, 0), max_scan=10)
    with pytest.raises(ValueError, match="different settings"):
        run(tmp_path, dump(30, 0), max_ply=6)
    run(tmp_path, dump(30, 0), max_ply=6, resume=False)                                # --fresh works


def test_a_checkpoint_is_written_on_a_timer_not_only_by_game_count(tmp_path):
    logs = []
    c = X.Counts(len(EDGES) - 1)
    X.count_stream(stream(dump(30, 0)), c, edges=EDGES, max_ply=4, holdout=0, checkpoint=tmp_path / "s.pkl.gz", checkpoint_every=10 ** 9,
                   checkpoint_minutes=1e-9, log=logs.append)
    assert (tmp_path / "s.pkl.gz").exists() and any("checkpoint saved" in l for l in logs) and not list(tmp_path.glob("*.tmp"))


def test_a_stop_request_ends_counting_cleanly_and_the_run_can_continue(tmp_path):
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 12
    first = run(tmp_path, dump(40, 0), should_stop=stop)
    assert first["finished"] is False and first["scanned"] == 13 and (tmp_path / "state.pkl.gz").exists()
    second = run(tmp_path, dump(40, 0), drop_state_when_finished=True)
    assert second["finished"] and second["counted"] == 40 and not (tmp_path / "state.pkl.gz").exists()


def test_the_deadline_stops_counting_but_the_outputs_are_still_written(tmp_path):
    res = run(tmp_path, dump(30, 10), max_minutes=-1)
    assert res["scanned"] == 1 and res["counted"] == 1 and not res["finished"] and (tmp_path / "explorer.db").exists() and (tmp_path / "report.md").exists()


def test_resume_glob_restores_a_checkpoint(tmp_path):
    first = run(tmp_path / "a", dump(40, 0), max_scan=20)
    assert first["scanned"] == 20 and (tmp_path / "a" / "state.pkl.gz").exists()
    second = run(tmp_path / "b", dump(40, 0), resume_glob=str(tmp_path / "a" / "state.pkl.gz"), drop_state_when_finished=True)
    assert second["scanned"] == 40 and second["counted"] == 40 and second["finished"] and not (tmp_path / "b" / "state.pkl.gz").exists()


# ---- memory guard: pruning is recorded, never silent ----------------------------------------------------------------------

def test_the_memory_guard_prunes_rare_entries_and_records_that_it_did(tmp_path):
    logs = []
    text = dump(60, 0) + game(1500, 1500, 1.0, "d4 d5 c4 c5".split())
    res = run(tmp_path, text, max_memory_gb=1e-6, progress_every=10, log=logs.append)
    assert any("incomplete" in l for l in logs)
    db = sqlite3.connect(tmp_path / "explorer.db")
    assert int(dict(db.execute("SELECT key, value FROM meta"))["pruned_below"]) >= 1
    assert "may be missing" in (tmp_path / "report.md").read_text()


def test_nothing_is_reported_dropped_when_nothing_was_pruned(tmp_path):
    run(tmp_path, dump(20, 0))
    assert int(dict(sqlite3.connect(tmp_path / "explorer.db").execute("SELECT key, value FROM meta"))["pruned_below"]) == 0
    assert "nothing was dropped" in (tmp_path / "report.md").read_text()


def test_prune_drops_the_rarest_entries_first():
    c = X.Counts(1)
    for i in range(40):
        c.tables[0][i] = X.pack(1.0)
    c.tables[0][100] = X.pack(1.0) * 5
    c.prune(max_entries=5)
    assert 100 in c.tables[0] and len(c.tables[0]) == 1 and c.pruned_below >= 1


# ---- checks, sources, rebuild ---------------------------------------------------------------------------------------------

def test_check_passes_on_a_dump_and_fails_fast_on_garbage():
    r = X.check(stream(dump(20, 5)), n_games=10, edges=EDGES)
    assert r["games"] == 10 and r["usable"] == 10 and r["avg_plies"] == 6 and r["with_eval"] == 0
    with pytest.raises(RuntimeError, match="not a Lichess PGN dump"):
        X.check(stream("<html>500 Internal Server Error</html>\n"), edges=EDGES)


def test_zstd_streams_are_read(tmp_path):
    zstandard = pytest.importorskip("zstandard")
    p = tmp_path / "g.pgn.zst"
    p.write_bytes(zstandard.ZstdCompressor().compress(dump(5, 5).encode()))
    games = [X.header_record(t) for t in X.iter_games(X.open_dump(str(p)))]
    assert len(games) == 10 and X.parse_moves(games[0]["line"], 6)[0] == ITALIAN


def test_rebuild_from_a_checkpoint_applies_new_thresholds_without_the_stream(tmp_path):
    run(tmp_path / "a", dump(60, 20, 20), holdout=5)
    strict = X.rebuild(tmp_path / "a" / "state.pkl.gz", tmp_path / "b", db_min_games=50, db_min_frac=0, book_min_games=50, book_min_frac=0, book_min_share=0.05, log=lambda *_: None)
    loose = X.rebuild(tmp_path / "a" / "state.pkl.gz", tmp_path / "c", db_min_games=1, db_min_frac=0, book_min_games=1, book_min_frac=0, book_min_share=0.0, log=lambda *_: None)
    assert loose["db_rows"] > strict["db_rows"] and loose["books"][2][0] > strict["books"][2][0]
    assert X.query(tmp_path / "c" / "explorer.db", chess.STARTING_FEN, rating=1500)[0]["games"] == 100      # the held-out games are folded in on rebuild too
    shallow = X.rebuild(tmp_path / "a" / "state.pkl.gz", tmp_path / "d", db_min_games=1, db_min_frac=0, book_min_games=1, book_min_frac=0, book_min_share=0.0, max_ply=2, log=lambda *_: None)
    assert shallow["books"][2][0] < loose["books"][2][0]


def test_position_keys_follow_the_fen_identity_of_placement_turn_and_castling():
    from chessme.book.keys import key_text
    boards = [chess.Board(), chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"), chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w - - 0 1"),
              chess.Board("r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1"), chess.Board("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2")]
    keys = [X.pos_key(b) for b in boards]
    assert len(set(keys)) == len(keys)                                          # all different positions, all different keys
    same = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 5 9")     # only the counters and the ep square differ
    assert X.pos_key(same) == X.pos_key(boards[4]) and key_text(same) == key_text(boards[4])
    # two random-ish games: the key identifies positions exactly as the FEN text does
    import random
    rnd, seen = random.Random(1), {}
    for _ in range(30):
        b = chess.Board()
        for _ in range(40):
            if b.is_game_over():
                break
            b.push(rnd.choice(list(b.legal_moves)))
            k, t = X.pos_key(b), key_text(b)
            assert seen.setdefault(k, t) == t                                     # a key never maps to two different FEN identities


def test_shares_are_of_the_true_total_and_rare_moves_are_reported_as_other(tmp_path):
    # 1.e4 in 90 games; 1.a3 in 4 games and 1.h4 in 3 games: below the database minimum of 5, so not listed, but counted in the total
    text = dump(90, 0) + game(1500, 1500, 1.0, "a3 a6 b3 b6".split()) * 4 + game(1500, 1500, 0.0, "h4 h5 g3 g6".split()) * 3
    run(tmp_path, text, db_min_games=5)
    ans = X.query_position(tmp_path / "explorer.db", chess.STARTING_FEN, rating=1500)
    assert ans["total"] == 97 and ans["other"] == 7 and [m["san"] for m in ans["moves"]] == ["e4"]
    assert abs(ans["moves"][0]["share"] - 90 / 97) < 1e-9                             # not 100%: the unlisted moves count
    assert "other" in X.format_rows(ans["moves"], other=ans["other"]) and X.query(tmp_path / "explorer.db", chess.STARTING_FEN, rating=1500)[0]["games"] == 90


def test_the_move_counts_of_a_position_add_up_to_the_games_that_reached_it(tmp_path):
    c = X.Counts(len(EDGES) - 1)
    text = dump(30, 12, 8) + game(1500, 1500, 1.0, "a3 a6 b3 b6".split()) * 5
    X.count_stream(stream(text), c, edges=EDGES, max_ply=6, holdout=0, log=lambda *_: None)
    start = X.pos_key(chess.Board())
    first = sum(X.unpack(v)[0] for k, v in c.tables[2].items() if k >> 16 == start)
    assert first == c.games[2] == 55                                                  # every game has exactly one first move
    e4 = chess.Board(); e4.push_san("e4")
    second = sum(X.unpack(v)[0] for k, v in c.tables[2].items() if k >> 16 == X.pos_key(e4))
    assert second == 30 + 12 + 8                                                        # exactly the games that played 1.e4


# ---- top games: a link to the highest-rated game of each move ----------------------------------------------------------------

def test_game_ids_round_trip_and_are_read_from_the_site_tag():
    assert X.int_to_gid(X.gid_to_int("AbCd1234")) == "AbCd1234" and X.gid_to_int("") == 0 and X.gid_to_int("zzzzzzzz") < 2 ** 48
    assert rec(game(1500, 1500, 1.0, ITALIAN, site="AbCd1234"))["gid"] == X.gid_to_int("AbCd1234")
    assert rec(game(1500, 1500, 1.0, ITALIAN))["gid"] == 0                                   # a game without a Lichess id has none
    assert rec(game(1500, 1500, 1.0, ITALIAN, site="toolong123"))["gid"] == 0


def test_each_move_keeps_the_highest_rated_game_that_played_it(tmp_path):
    text = (game(1500, 1500, 1.0, ITALIAN, site="lowRated") + game(1590, 1590, 1.0, ITALIAN, site="highRate")
            + game(1550, 1550, 1.0, SCOTCH, site="scotch01"))
    run(tmp_path, text, max_ply=6)
    b = chess.Board()
    for m in ("e4", "e5", "Nf3", "Nc6"):
        b.push_san(m)
    moves = {m["san"]: m for m in X.query(tmp_path / "explorer.db", b.fen(), rating=1500)}
    assert moves["Bc4"]["top_game"] == "highRate" and moves["Bc4"]["top_rating"] == 1590 and moves["Bc4"]["top_url"] == "https://lichess.org/highRate"
    assert moves["d4"]["top_game"] == "scotch01"
    first = X.query(tmp_path / "explorer.db", chess.STARTING_FEN, rating=1500)[0]
    assert first["san"] == "e4" and first["top_game"] == "highRate"                              # the best of all three games that played 1.e4


def test_games_without_an_id_leave_no_link_and_deep_plies_keep_none(tmp_path):
    line = "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O".split()                 # 16 plies
    run(tmp_path, game(1500, 1500, 1.0, line, site="deepGame") + game(1500, 1500, 1.0, ITALIAN), max_ply=16)
    b = chess.Board()
    assert X.query(tmp_path / "explorer.db", b.fen(), rating=1500)[0]["top_game"] == "deepGame"        # ply 1: kept
    for m in line[:14]:
        b.push_san(m)
    late = X.query(tmp_path / "explorer.db", b.fen(), rating=1500)[0]                                 # ply 15: beyond TOP_PLY, no link
    assert late["san"] == "c3" and late["top_game"] is None and late["top_url"] is None
    plain = X.Counts(len(EDGES) - 1)
    plain.add_game(2, rec(game(1500, 1500, 1.0, ITALIAN)), 6)
    assert not plain.top[2]                                                                        # no id, nothing stored


def test_top_games_survive_the_checkpoint_pruning_and_rebuild_and_store_no_names(tmp_path):
    text = game(1500, 1500, 1.0, ITALIAN, site="keepMe01") * 3 + game(1500, 1500, 1.0, "a3 a6".split(), site="rareOne1")
    res = run(tmp_path / "a", text, max_ply=6)
    st = X.load_state(tmp_path / "a" / "state.pkl.gz")
    assert len(st.top[2]) > 0 and all(v >> 48 == 1500 for v in st.top[2].values())
    rebuilt = X.rebuild(tmp_path / "a" / "state.pkl.gz", tmp_path / "b", log=lambda *_: None, db_min_games=1, db_min_frac=0)
    assert X.query(tmp_path / "b" / "explorer.db", chess.STARTING_FEN, rating=1500)[0]["top_game"] == "keepMe01"
    for g in st.held_out[2]:
        assert "White" not in g and "Black" not in g                                           # records hold ratings and ids, never names
    st.prune(0)
    assert not st.top[2]                                                                       # pruned entries lose their link with them
    db = sqlite3.connect(tmp_path / "a" / "explorer.db")
    assert not any(c in ("white_name", "black_name", "player") for _, c, *_ in db.execute("PRAGMA table_info(moves)"))


def test_the_text_answer_lists_the_top_game_links():
    rows = [{"san": "e4", "games": 100, "share": 1.0, "white": 0.5, "draw": 0.1, "black": 0.4, "avg_rating": 1500.0, "eval": None, "eval_n": 0,
             "top_game": "AbCd1234", "top_url": "https://lichess.org/AbCd1234", "top_rating": 2650}]
    assert "https://lichess.org/AbCd1234" not in X.format_rows(rows)
    text = X.format_rows(rows, links=True)
    assert "top game after e4: https://lichess.org/AbCd1234 (average rating 2650)" in text


# ---- a compressed file with several frames, and a stream that ends early ------------------------------------------------------

def test_a_zst_file_with_several_frames_is_read_to_the_end(tmp_path):
    zstandard = pytest.importorskip("zstandard")
    c = zstandard.ZstdCompressor()
    p = tmp_path / "multi.pgn.zst"
    p.write_bytes(c.compress(dump(5, 0).encode()) + c.compress(dump(0, 7).encode()) + c.compress(dump(0, 0, 4).encode()))   # three separate frames
    games = [X.header_record(t) for t in X.iter_games(X.open_dump(str(p)))]
    assert len(games) == 5 + 7 + 4                                                                 # the default reader would stop after the first frame (5 games)
    assert X.parse_moves(games[-1]["line"], 4)[0] == FRENCH


def test_a_stream_that_ends_before_the_scan_limit_is_reported_loudly(tmp_path):
    logs = []
    res = run(tmp_path, dump(20, 0), max_scan=1000, log=logs.append)
    assert res["ended_early"] and any("WARNING: the stream ended after 20 games" in l for l in logs)
    assert "WARNING: the stream ended after 20 games" in (tmp_path / "report.md").read_text()
    quiet = run(tmp_path / "b", dump(20, 0), max_scan=20, log=lambda *_: None)            # the limit was reached: nothing to warn about
    assert not quiet["ended_early"] and "WARNING" not in (tmp_path / "b" / "report.md").read_text()


def test_opening_names_are_fetched_when_the_folder_is_empty(tmp_path, monkeypatch):
    from chessme import cli
    from chessme.books import openings as OP
    calls = []
    monkeypatch.setattr(OP, "download", lambda d, opener=None: calls.append(str(d)) or [])
    logs = []
    cli._ensure_opening_names(tmp_path / "names", logs.append)
    assert calls == [str(tmp_path / "names")] and any("downloaded the opening names" in l for l in logs)
    (tmp_path / "have").mkdir()
    (tmp_path / "have" / "a.tsv").write_text("eco\tname\tpgn\n")
    cli._ensure_opening_names(tmp_path / "have", logs.append)
    assert len(calls) == 1                                                                       # already there: no download
    monkeypatch.setattr(OP, "download", lambda d, opener=None: (_ for _ in ()).throw(OSError("offline")))
    cli._ensure_opening_names(tmp_path / "other", logs.append)
    assert any("WARNING: no opening names" in l for l in logs)                                   # offline: a warning, not a crash


# ---- a connection that closes early must not look like the end of the file ------------------------------------------------------

def test_the_checked_reader_raises_when_the_download_ends_before_the_promised_size():
    ok = X.CheckedReader(io.BytesIO(b"abcdef"), expected=6)
    assert ok.read(4) == b"abcd" and ok.read(4) == b"ef" and ok.read(4) == b""                      # complete: a normal end
    short = X.CheckedReader(io.BytesIO(b"abcdef"), expected=10)
    assert short.read(6) == b"abcdef"
    with pytest.raises(ConnectionError, match="6 of 10 bytes"):
        short.read(4)
    assert X.CheckedReader(io.BytesIO(b"abc"), expected=0).read(10) == b"abc"                        # no size promised: nothing to check


def test_open_dump_reports_a_truncated_url_download(monkeypatch):
    body = dump(5, 0).encode()

    class Resp(io.BytesIO):
        headers = {"Content-Length": str(len(body) + 5000)}                                          # the server promised more than it sent
    monkeypatch.setattr(X.urllib.request, "urlopen", lambda req, timeout=None: Resp(body))
    with pytest.raises(ConnectionError, match="the connection closed"):
        list(X.iter_games(X.open_dump("https://example.org/dump.pgn")))
    Resp.headers = {"Content-Length": str(len(body))}
    assert len(list(X.iter_games(X.open_dump("https://example.org/dump.pgn")))) == 5              # a complete download reads fine


def test_reconnecting_many_times_is_fine_as_long_as_each_connection_makes_progress(monkeypatch):
    monkeypatch.setattr(X.time, "sleep", lambda s: None)
    text = dump(120, 0)
    calls = {"n": 0}

    class Flaky(io.StringIO):
        def __iter__(self):
            for i, line in enumerate(iter(self.readline, "")):
                if i > 150 * calls["n"]:                                                             # each connection gets a little further, then drops
                    raise ConnectionError("closed")
                yield line

    def opener():
        calls["n"] += 1
        return Flaky(text)
    c = X.Counts(len(EDGES) - 1)
    X.count_stream(opener, c, edges=EDGES, max_ply=6, holdout=0, log=lambda *_: None)
    ref = X.Counts(len(EDGES) - 1)
    X.count_stream(stream(text), ref, edges=EDGES, max_ply=6, holdout=0, log=lambda *_: None)
    assert calls["n"] > 6 and c.tables == ref.tables and c.scanned == 120                            # more than 5 drops, no abort


def test_reconnecting_without_any_progress_gives_up(monkeypatch):
    monkeypatch.setattr(X.time, "sleep", lambda s: None)

    def opener():
        raise ConnectionError("the server is down")
    with pytest.raises(ConnectionError):
        X.count_stream(opener, X.Counts(len(EDGES) - 1), edges=EDGES, max_ply=6, holdout=0, log=lambda *_: None)
