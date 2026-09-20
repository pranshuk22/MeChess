import io
import sqlite3

import chess
import pytest

from chessme.book import explorer as X
from chessme.mechess.controller import BookReader

EDGES = (600, 1000, 1400, 1800, 2200)


def game(w, b, result, moves, tc="300+0", term="Normal"):
    r = {1.0: "1-0", 0.5: "1/2-1/2", 0.0: "0-1"}[result]
    body = " ".join(f"{i // 2 + 1}. {m}" if i % 2 == 0 else m for i, m in enumerate(moves)) + f" {r}"
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
    v = X.pack(1.0) + X.pack(0.5) + X.pack(0.0) + X.pack(1.0)
    assert X.unpack(v) == (4, 2, 1, 1)
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


def test_iter_games_reads_headers_and_only_the_first_plies_ignoring_comments():
    text = ('[Event "x"]\n[WhiteElo "1500"]\n[BlackElo "1480"]\n[Result "1-0"]\n[TimeControl "300+3"]\n[Termination "Normal"]\n\n'
            '1. e4 { [%clk 0:05:00] } 1... e5 { [%eval 0.3] } 2. Nf3 $1 Nc6 3. Bb5 a6 4. Ba4 Nf6 1-0\n\n' + game(1200, 1210, 0.0, FRENCH))
    games = [X.normalise(t) for t in X.iter_games(io.StringIO(text), max_ply=5)]
    assert games[0]["moves"] == ["e4", "e5", "Nf3", "Nc6", "Bb5"] and games[0]["base"] == 300 and games[0]["result"] == 1.0
    assert games[1]["moves"] == FRENCH and games[1]["white"] == 1200


def test_band_filter_excludes_bullet_abnormal_and_mismatched_games():
    ok = X.normalise(next(X.iter_games(io.StringIO(game(1500, 1520, 1.0, ITALIAN)))))
    assert X.band_of(ok, EDGES) == 2
    assert X.band_of(X.normalise(next(X.iter_games(io.StringIO(game(1500, 1520, 1.0, ITALIAN, tc="60+0"))))), EDGES) is None
    assert X.band_of(X.normalise(next(X.iter_games(io.StringIO(game(1500, 1520, 1.0, ITALIAN, term="Abandoned"))))), EDGES) is None
    assert X.band_of(X.normalise(next(X.iter_games(io.StringIO(game(1200, 1700, 1.0, ITALIAN))))), EDGES) is None
    assert X.band_of(X.normalise(next(X.iter_games(io.StringIO(game(3500, 3500, 1.0, ITALIAN))))), EDGES) is None


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
    games = [X.normalise(t) for t in X.iter_games(X.open_dump(str(p)), 6)]
    assert len(games) == 10 and games[0]["moves"] == ITALIAN


def test_check_passes_on_a_dump_and_fails_fast_on_garbage():
    r = X.check(stream(dump(20, 5)), n_games=10, edges=EDGES)
    assert r["games"] == 10 and r["usable"] == 10 and r["avg_plies"] == 6
    with pytest.raises(RuntimeError, match="not a Lichess PGN dump"):
        X.check(stream("<html>500 Internal Server Error</html>\n"), edges=EDGES)


def test_run_reports_finished_only_when_the_deadline_was_not_hit(tmp_path):
    full = X.run("x", tmp_path / "a", edges=EDGES, max_ply=4, sample_every=1, holdout=0, opener=stream(dump(10, 0)), log=lambda *_: None)
    cut = X.run("x", tmp_path / "b", edges=EDGES, max_ply=4, sample_every=1, holdout=0, max_minutes=-1, opener=stream(dump(10, 0)), log=lambda *_: None)
    assert full["finished"] is True and cut["finished"] is False
