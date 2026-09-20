import io
import sqlite3

import chess
import pytest

from chessme.book import explorer as X
from chessme.mechess.controller import BookReader

EDGES = (600, 1000, 1400, 1800, 2200)


def game(w, b, result, moves, tc="300+0", term="Normal", comments=None):
    """comments: optional list of strings placed after each move, e.g. '[%eval 0.3] [%clk 0:04:58]'."""
    r = {1.0: "1-0", 0.5: "1/2-1/2", 0.0: "0-1"}[result]
    parts = []
    for i, m in enumerate(moves):
        c = f" {{ {comments[i]} }}" if comments and comments[i] else ""
        parts.append((f"{i // 2 + 1}. " if i % 2 == 0 else "") + m + c)
    body = " ".join(parts) + f" {r}"
    return (f'[Event "x"]\n[Site "s"]\n[White "a"]\n[Black "b"]\n[Result "{r}"]\n[WhiteElo "{w}"]\n[BlackElo "{b}"]\n[TimeControl "{tc}"]\n'
            f'[Termination "{term}"]\n\n{body}\n\n')


ITALIAN = "e4 e5 Nf3 Nc6 Bc4 Bc5".split()
SCOTCH = "e4 e5 Nf3 Nc6 d4 exd4".split()
FRENCH = "e4 e6 d4 d5".split()


def dump(n_italian, n_scotch, n_french=0, rating=1500):
    return "".join([game(rating, rating, 1.0, ITALIAN)] * n_italian + [game(rating, rating, 0.5, SCOTCH)] * n_scotch
                   + [game(rating, rating, 0.0, FRENCH)] * n_french)


def stream(text):
    return lambda: io.StringIO(text)


def test_pack_unpack_and_keys():
    v = X.pack(1.0, 1500) + X.pack(0.5, 1600) + X.pack(0.0, 1400) + X.pack(1.0, 1500)
    assert X.unpack(v) == (4, 2, 1, 1) and X.avg_rating_of(v) == 1500.0
    assert X.unmove16(X.move16(chess.Move.from_uci("e7e8q"))) == chess.Move.from_uci("e7e8q")
    b = chess.Board()
    k = X.pos_key(b)
    b.push_uci("e2e4")
    assert X.pos_key(b) != k and X.pos_key(chess.Board()) == k
    assert -(1 << 63) <= X.signed64(X.pos_key(b)) < (1 << 63)
    a, c = chess.Board(), chess.Board()                                    # transpositions merge
    for m in ("g1f3", "g8f6", "b1c3"):
        a.push_uci(m)
    for m in ("b1c3", "g8f6", "g1f3"):
        c.push_uci(m)
    assert X.pos_key(a) == X.pos_key(c)


def rec(text):
    return X.header_record(next(X.iter_games(io.StringIO(text))))


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


def test_band_filter_excludes_bullet_abnormal_and_mismatched_games():
    assert X.band_of(rec(game(1500, 1520, 1.0, ITALIAN)), EDGES) == 2
    assert X.band_of(rec(game(1500, 1520, 1.0, ITALIAN, tc="60+0")), EDGES) is None
    assert X.band_of(rec(game(1500, 1520, 1.0, ITALIAN, term="Abandoned")), EDGES) is None
    assert X.band_of(rec(game(1200, 1700, 1.0, ITALIAN)), EDGES) is None
    assert X.band_of(rec(game(3500, 3500, 1.0, ITALIAN)), EDGES) is None


def test_counting_run_builds_db_books_and_report(tmp_path):
    res = X.run("x", tmp_path, edges=EDGES, max_ply=6, sample_every=1, holdout=10, db_min_games=5, book_min_games=10, book_min_share=0.05,
                opener=stream(dump(60, 20, 20)), log=lambda *_: None)
    assert res["scanned"] == 100 and res["counted"] == 100 - 10                        # 10 games held out of the counts
    rows = X.query(tmp_path / "explorer.db", chess.STARTING_FEN, rating=1500)
    assert [r["san"] for r in rows] == ["e4"] and rows[0]["games"] == 90
    after_e4_e5 = chess.Board(); after_e4_e5.push_san("e4"); after_e4_e5.push_san("e5"); after_e4_e5.push_san("Nf3"); after_e4_e5.push_san("Nc6")
    moves = X.query(tmp_path / "explorer.db", after_e4_e5.fen(), rating=1500)
    assert [m["san"] for m in moves][:2] == ["Bc4", "d4"] and moves[0]["games"] > moves[1]["games"]
    assert abs(moves[1]["draw"] - 1.0) < 1e-9 and abs(moves[0]["white"] - 1.0) < 1e-9        # Scotch games were draws; Italian games White wins
    book = BookReader(tmp_path / "theory_1400_1800.bin")
    assert {m.uci() for m, _ in book.moves(chess.Board())} == {"e2e4"}
    assert "1400-1800" in (tmp_path / "report.md").read_text() and res["coverage"][2][4] > 0.9
    assert abs(rows[0]["avg_rating"] - 1500) < 1e-9


def test_rating_picks_the_band_and_unknown_positions_return_nothing(tmp_path):
    X.run("x", tmp_path, edges=EDGES, max_ply=4, sample_every=1, holdout=0, db_min_games=1, book_min_games=1, opener=stream(dump(30, 0, 0, rating=1200) + dump(30, 0, 0, rating=1900)),
          log=lambda *_: None)
    assert X.query(tmp_path / "explorer.db", chess.STARTING_FEN, rating=1200)[0]["games"] == 30
    assert X.query(tmp_path / "explorer.db", chess.STARTING_FEN, rating=1900)[0]["games"] == 30
    assert X.query(tmp_path / "explorer.db", chess.STARTING_FEN, rating=5000)[0]["games"] == 30       # nearest band when outside all bands
    odd = chess.Board(); odd.push_san("a4")
    assert X.query(tmp_path / "explorer.db", odd.fen(), rating=1200) == []


def test_sampling_keeps_every_kth_game(tmp_path):
    c = X.Counts(len(EDGES) - 1)
    X.count_stream(stream(dump(40, 0)), c, edges=EDGES, max_ply=4, sample_every=4, holdout=0, log=lambda *_: None)
    assert c.scanned == 40 and c.games[2] == 10


def test_checkpoint_resume_skips_games_already_scanned(tmp_path):
    text = dump(30, 10)
    c = X.Counts(len(EDGES) - 1)
    X.count_stream(stream(text), c, edges=EDGES, max_ply=6, holdout=0, max_scan=25, log=lambda *_: None)
    assert c.scanned == 25
    X.save_state(tmp_path / "s.pkl.gz", c, c.scanned)
    c2 = X.load_state(tmp_path / "s.pkl.gz")
    X.count_stream(stream(text), c2, edges=EDGES, max_ply=6, holdout=0, log=lambda *_: None)
    full = X.Counts(len(EDGES) - 1)
    X.count_stream(stream(text), full, edges=EDGES, max_ply=6, holdout=0, log=lambda *_: None)
    assert c2.games == full.games and c2.tables == full.tables                             # the same counts as an uninterrupted run


def test_reconnects_after_a_dropped_stream_and_skips_what_it_already_read(tmp_path):
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


def test_memory_cap_prunes_rare_entries_first():
    c = X.Counts(1)
    board = chess.Board()
    for i in range(40):
        c.tables[0][i] = X.pack(1.0)
    c.tables[0][100] = X.pack(1.0) * 5
    c.prune(max_entries=5)
    assert 100 in c.tables[0] and len(c.tables[0]) == 1


def test_deadline_stops_counting_but_the_outputs_are_still_written(tmp_path):
    res = X.run("x", tmp_path, edges=EDGES, max_ply=4, sample_every=1, holdout=0, db_min_games=1, max_minutes=-1, opener=stream(dump(30, 10)), log=lambda *_: None)
    assert res["scanned"] == 1 and res["counted"] == 1 and (tmp_path / "explorer.db").exists() and (tmp_path / "report.md").exists()


def test_zstd_streams_are_read(tmp_path):
    zstandard = pytest.importorskip("zstandard")
    p = tmp_path / "g.pgn.zst"
    p.write_bytes(zstandard.ZstdCompressor().compress(dump(5, 5).encode()))
    games = [X.header_record(t) for t in X.iter_games(X.open_dump(str(p)))]
    assert len(games) == 10 and X.parse_moves(games[0]["line"], 6)[0] == ITALIAN


def test_check_passes_on_a_dump_and_fails_fast_on_garbage():
    r = X.check(stream(dump(20, 5)), n_games=10, edges=EDGES)
    assert r["games"] == 10 and r["usable"] == 10 and r["avg_plies"] == 6 and r["with_eval"] == 0
    with pytest.raises(RuntimeError, match="not a Lichess PGN dump"):
        X.check(stream("<html>500 Internal Server Error</html>\n"), edges=EDGES)


def test_run_reports_finished_only_when_the_deadline_was_not_hit(tmp_path):
    full = X.run("x", tmp_path / "a", edges=EDGES, max_ply=4, sample_every=1, holdout=0, opener=stream(dump(10, 0)), log=lambda *_: None)
    cut = X.run("x", tmp_path / "b", edges=EDGES, max_ply=4, sample_every=1, holdout=0, max_minutes=-1, opener=stream(dump(10, 0)), log=lambda *_: None)
    assert full["finished"] is True and cut["finished"] is False


def annotated_game(n, evals_after_e4, rating=1500, result=1.0):
    """n identical games with evaluations after the first white move and clocks (5+0 game, White spends 2 s then 10 s, Black 3 s)."""
    comments = [f"[%eval {evals_after_e4}] [%clk 0:04:58]", "[%clk 0:04:57]", "[%eval 0.1] [%clk 0:04:48]", "[%clk 0:04:52]"]
    return game(rating, rating, result, "e4 e5 Nf3 Nc6".split(), comments=comments) * n


def test_evaluations_ratings_clock_and_band_statistics_are_recorded(tmp_path):
    text = annotated_game(40, 0.3) + game(1500, 1500, 0.5, "e4 e5 Nf3 Nc6".split()) * 10
    X.run("x", tmp_path, edges=EDGES, max_ply=4, sample_every=1, holdout=0, db_min_games=5, book_min_games=5, opener=stream(text), log=lambda *_: None)
    rows = X.query(tmp_path / "explorer.db", chess.STARTING_FEN, rating=1500)
    assert rows[0]["san"] == "e4" and rows[0]["games"] == 50 and rows[0]["eval_n"] == 40 and abs(rows[0]["eval"] - 0.3) < 1e-9   # only annotated games count for eval
    db = sqlite3.connect(tmp_path / "explorer.db")
    band, games, white, draws, moves, analysed = db.execute("SELECT * FROM band_stats WHERE games > 0").fetchone()
    assert (games, white, draws, analysed) == (50, 40, 10, 40) and moves == 50 * 2                               # last full move number is 2 in every game
    spent = {ply: (n, s, inst) for _, ply, n, s, inst in db.execute("SELECT band, ply, n, spent_sum, instant FROM clock WHERE speed='blitz'")}
    assert spent[1] == (40, 40 * 2.0, 0)                        # White's first move: 300 s base -> 298 s: 2 s
    assert spent[2] == (40, 40 * 3.0, 0)                        # Black's first move: 300 -> 297
    assert abs(spent[3][1] / spent[3][0] - 10.0) < 1e-9         # White's second move: 298 -> 288
    db.close()


def test_result_bar_and_text_rows():
    assert X.bar(0.5, 0.0, 0.5, 10) == "░░░░░█████" and X.bar(1.0, 0.0, 0.0, 10) == "░" * 10 and len(X.bar(0.33, 0.34, 0.33, 30)) == 30
    text = X.format_rows([{"san": "e4", "games": 1234, "share": 0.6, "white": 0.5, "draw": 0.1, "black": 0.4, "avg_rating": 1512.3, "eval": 0.25, "eval_n": 80}])
    assert "e4" in text and "1,234" in text and "60.0%" in text and "+0.25" in text and "50/10/40" in text and "░" in text and "█" in text


def test_opening_names_are_stored_and_found_by_position(tmp_path):
    names = tmp_path / "names"
    names.mkdir()
    (names / "a.tsv").write_text("eco\tname\tpgn\nC44\tKing's Pawn Game\t1. e4 e5 2. Nf3\nB00\tKing's Pawn\t1. e4\n")
    X.run("x", tmp_path / "o", edges=EDGES, max_ply=4, sample_every=1, holdout=0, opener=stream(dump(10, 0)), openings_dir=names, log=lambda *_: None)
    b = chess.Board(); b.push_san("e4")
    assert X.opening_at(tmp_path / "o" / "explorer.db", b.fen()) == ("B00", "King's Pawn")
    assert X.opening_at(tmp_path / "o" / "explorer.db", chess.STARTING_FEN) is None


def test_the_evaluation_test_drops_a_popular_but_bad_move_when_asked(tmp_path):
    # 1.e4 e5 2.Nf3: 60 games play ...Nc6 (eval +0.2 for White) and 30 games play ...f6 (eval +3.0 for White, so bad for Black)
    good = game(1500, 1500, 1.0, "e4 e5 Nf3 Nc6".split(), comments=[None, None, None, "[%eval 0.2]"]) * 60
    bad = game(1500, 1500, 1.0, "e4 e5 Nf3 f6".split(), comments=[None, None, None, "[%eval 3.0]"]) * 30
    kw = dict(edges=EDGES, max_ply=4, sample_every=1, holdout=0, db_min_games=1, book_min_games=5, book_min_share=0.05, opener=stream(good + bad), log=lambda *_: None)
    plain = X.run("x", tmp_path / "a", **kw)
    strict = X.run("x", tmp_path / "b", eval_margin_cp=150, **kw)
    assert plain["books"][2][0] > strict["books"][2][0] and strict["books"][2][2] == 1           # ...f6 dropped by the evaluation test
    b = chess.Board()
    for m in ("e4", "e5", "Nf3"):
        b.push_san(m)
    moves = {m.uci() for m, _ in BookReader(tmp_path / "b" / "theory_1400_1800.bin").moves(b)}
    assert moves == {"b8c6"} and {m.uci() for m, _ in BookReader(tmp_path / "a" / "theory_1400_1800.bin").moves(b)} == {"b8c6", "f7f6"}


def test_resume_glob_restores_a_checkpoint_and_finished_runs_drop_it(tmp_path):
    first = X.run("x", tmp_path / "a", edges=EDGES, max_ply=4, sample_every=1, holdout=0, max_scan=20, opener=stream(dump(40, 0)), log=lambda *_: None)
    assert first["scanned"] == 20 and (tmp_path / "a" / "state.pkl.gz").exists()
    second = X.run("x", tmp_path / "b", edges=EDGES, max_ply=4, sample_every=1, holdout=0, resume_glob=str(tmp_path / "a" / "state.pkl.gz"),
                   drop_state_when_finished=True, opener=stream(dump(40, 0)), log=lambda *_: None)
    assert second["scanned"] == 40 and second["counted"] == 40 and second["finished"] and not (tmp_path / "b" / "state.pkl.gz").exists()


def test_rare_top_bands_keep_every_game_while_common_bands_are_sampled():
    edges = (0, 1800, 2200, 4000)
    c = X.Counts(3)
    X.count_stream(stream(dump(40, 0, rating=1500) + dump(40, 0, rating=2500)), c, edges=edges, max_ply=4, sample_every=4, full_from=2200, holdout=0,
                   log=lambda *_: None)
    assert c.games[0] == 10 and c.games[2] == 40 and c.games[1] == 0                 # 1500: one in four; 2500: all of them


def test_all_default_bands_cover_the_whole_rating_range_without_gaps():
    e = X.DEFAULT_BANDS
    assert e[0] == 0 and e[-1] >= 3500 and all(a < b for a, b in zip(e, e[1:])) and 2600 in e and 800 in e
    for r in (100, 799, 800, 1500, 2599, 2600, 3200):
        assert X.band_of({"base": 300, "termination": "Normal", "white": r, "black": r}, e) is not None


def test_a_checkpoint_from_other_settings_is_refused(tmp_path):
    X.run("x", tmp_path, edges=EDGES, max_ply=4, sample_every=1, holdout=0, max_scan=10, opener=stream(dump(30, 0)), log=lambda *_: None)
    with pytest.raises(ValueError, match="different settings"):
        X.run("x", tmp_path, edges=EDGES, max_ply=6, sample_every=1, holdout=0, opener=stream(dump(30, 0)), log=lambda *_: None)
    X.run("x", tmp_path, edges=EDGES, max_ply=6, sample_every=1, holdout=0, resume=False, opener=stream(dump(30, 0)), log=lambda *_: None)   # --fresh works


def test_a_checkpoint_is_written_on_a_timer_not_only_by_game_count(tmp_path):
    logs = []
    c = X.Counts(len(EDGES) - 1)
    X.count_stream(stream(dump(30, 0)), c, edges=EDGES, max_ply=4, holdout=0, checkpoint=tmp_path / "s.pkl.gz", checkpoint_every=10 ** 9,
                   checkpoint_minutes=1e-9, log=logs.append)
    assert (tmp_path / "s.pkl.gz").exists() and any("checkpoint saved" in l for l in logs)
    assert not list(tmp_path.glob("*.tmp"))                                           # written atomically


def test_a_stop_request_ends_counting_cleanly_and_the_run_can_continue(tmp_path):
    calls = {"n": 0}
    def stop():
        calls["n"] += 1
        return calls["n"] > 12
    first = X.run("x", tmp_path, edges=EDGES, max_ply=4, sample_every=1, holdout=0, should_stop=stop, opener=stream(dump(40, 0)), log=lambda *_: None)
    assert first["finished"] is False and first["scanned"] == 13 and (tmp_path / "state.pkl.gz").exists()
    second = X.run("x", tmp_path, edges=EDGES, max_ply=4, sample_every=1, holdout=0, drop_state_when_finished=True, opener=stream(dump(40, 0)), log=lambda *_: None)
    assert second["finished"] and second["counted"] == 40 and not (tmp_path / "state.pkl.gz").exists()


def test_memory_guard_prunes_rare_entries_when_over_the_limit():
    logs = []
    c = X.Counts(len(EDGES) - 1)
    X.count_stream(stream(dump(60, 0) + game(1500, 1500, 1.0, "d4 d5 c4 c5".split())), c, edges=EDGES, max_ply=4, holdout=0, max_memory_gb=1e-6,
                   progress_every=10, log=logs.append)
    assert any("over the" in l for l in logs) and c.games[2] == 61


def test_rebuild_from_a_checkpoint_applies_new_thresholds_without_the_stream(tmp_path):
    X.run("x", tmp_path / "a", edges=EDGES, max_ply=4, sample_every=1, holdout=5, db_min_games=1, book_min_games=1, opener=stream(dump(60, 20, 20)), log=lambda *_: None)
    strict = X.rebuild(tmp_path / "a" / "state.pkl.gz", tmp_path / "b", db_min_games=50, book_min_games=50, book_min_share=0.05, log=lambda *_: None)
    loose = X.rebuild(tmp_path / "a" / "state.pkl.gz", tmp_path / "c", db_min_games=1, book_min_games=1, book_min_share=0.0, log=lambda *_: None)
    assert loose["db_rows"] > strict["db_rows"] and loose["books"][2][0] > strict["books"][2][0]
    assert (tmp_path / "b" / "report.md").exists() and X.query(tmp_path / "c" / "explorer.db", chess.STARTING_FEN, rating=1500)[0]["san"] == "e4"
    shallow = X.rebuild(tmp_path / "a" / "state.pkl.gz", tmp_path / "d", db_min_games=1, book_min_games=1, book_min_share=0.0, max_ply=2, log=lambda *_: None)
    assert shallow["books"][2][0] < loose["books"][2][0]
