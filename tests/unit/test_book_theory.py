import chess

from chessme.book import theory as TH
from chessme.book.format import read_book, write_book
from chessme.mechess.controller import BookReader

TSV = "eco\tname\tpgn\nC50\tItalian Game\t1. e4 e5 2. Nf3 Nc6 3. Bc4\nC44\tScotch Game\t1. e4 e5 2. Nf3 Nc6 3. d4\nB20\tSicilian Defense\t1. e4 c5\nD00\tQueen's Pawn\t1. d4 d5\n"


def lines(tmp_path):
    p = tmp_path / "a.tsv"
    p.write_text(TSV)
    return TH.load_lines([p])


def games(n_italian, n_scotch, n_odd=0):
    g = [("e2e4 e7e5 g1f3 b8c6 f1c4".split(), "white", 1.0)] * n_italian + [("e2e4 e7e5 g1f3 b8c6 d2d4".split(), "white", 0.5)] * n_scotch
    return g + [("e2e4 e7e5 b1c3".split(), "white", 1.0)] * n_odd                      # 2.Nc3 is not in any named line here


def test_load_lines_replays_moves_and_skips_broken_lines(tmp_path):
    p = tmp_path / "b.tsv"
    p.write_text(TSV + "X00\tBroken\t1. e4 e5 2. Ke5\n")
    ls = TH.load_lines([p])
    assert len(ls) == 4 and ls[0][0] == "C50" and [m.uci() for m in ls[0][2]] == "e2e4 e7e5 g1f3 b8c6 f1c4".split()


def test_theory_positions_mark_named_moves_only(tmp_path):
    pos = TH.theory_positions(lines(tmp_path))
    b = chess.Board()
    assert TH.is_theory(b, chess.Move.from_uci("e2e4"), pos) and TH.is_theory(b, chess.Move.from_uci("d2d4"), pos)
    assert not TH.is_theory(b, chess.Move.from_uci("a2a3"), pos)
    b.push_uci("e2e4"); b.push_uci("e7e5")
    assert not TH.is_theory(b, chess.Move.from_uci("b1c3"), pos)
    assert TH.is_theory(b, chess.Move.from_uci("g1f3"), pos)


def test_weights_follow_how_often_players_choose_each_theory_move(tmp_path):
    entries, stats = TH.build(lines(tmp_path), games(30, 10, n_odd=5))
    book = tmp_path / "book.bin"
    write_book(book, entries)
    reader = BookReader(book)
    b = chess.Board()
    for u in "e2e4 e7e5 g1f3 b8c6".split():
        b.push_uci(u)
    w = {m.uci(): x for m, x in reader.moves(b)}
    assert set(w) == {"f1c4", "d2d4"} and w["f1c4"] > 2.5 * w["d2d4"]                    # Italian was played 3x as often
    assert stats["left_theory"] == 5 and stats["games"] == 45                             # the off-theory 2.Nc3 games stopped there
    b2 = chess.Board(); b2.push_uci("e2e4"); b2.push_uci("e7e5")
    assert "b1c3" not in {m.uci() for m, _ in reader.moves(b2)}


def test_without_games_every_named_move_is_kept_with_equal_prior(tmp_path):
    entries, stats = TH.build(lines(tmp_path), [])
    reader_moves = {(e.key, e.uci()) for e in entries}
    b = chess.Board()
    assert (TH.book_key(b), "e2e4") in reader_moves and (TH.book_key(b), "d2d4") in reader_moves
    assert stats["games"] == 0


def test_rare_moves_are_dropped_by_min_share(tmp_path):
    g = games(100, 1)
    entries, stats = TH.build(lines(tmp_path), g, min_share=0.05)
    assert stats["dropped"].get("below min_share", 0) >= 1
    b = chess.Board()
    for u in "e2e4 e7e5 g1f3 b8c6".split():
        b.push_uci(u)
    moves = {e.uci() for e in entries if e.key == TH.book_key(b)}
    assert moves == {"f1c4"}                                                              # 1 Scotch game in 101 is below 5%


def test_band_filter_and_pgn_reader(tmp_path):
    pgn = tmp_path / "g.pgn"
    pgn.write_text('[WhiteElo "1500"]\n[BlackElo "1500"]\n\n1. e4 e5 2. Nf3 *\n\n[WhiteElo "2500"]\n[BlackElo "2500"]\n\n1. d4 d5 *\n\n')
    assert [m[0][0] for m in TH.games_from_pgn([pgn], band=(1400, 1600))] == ["e2e4"]
    assert len(list(TH.games_from_pgn([pgn]))) == 2


def test_render_summarises():
    text = TH.render({"lines": 4, "positions": 9, "entries": 12, "games": 45, "left_theory": 5, "dropped": {}}, (1400, 1800))
    assert "1400-1800" in text and "12 book moves" in text


def test_coverage_measures_how_deep_the_book_carries_games(tmp_path):
    g = games(30, 10, n_odd=10)
    entries, stats = TH.build(lines(tmp_path), g, max_ply=20)
    cov = stats["coverage"]
    assert abs(cov[4] - 40 / 50) < 1e-9 and cov[8] == 0.0      # the 10 Nc3 games leave the book after 2 plies; the named lines here are only 5 plies long


def test_pick_book_chooses_the_band_containing_the_elo_or_the_nearest(tmp_path):
    for name in ("theory_1500_1800.bin", "theory_1800_2100.bin", "theory_2100_2400.bin", "other.bin"):
        (tmp_path / name).write_bytes(b"")
    assert TH.pick_book(tmp_path, 1650).name == "theory_1500_1800.bin"
    assert TH.pick_book(tmp_path, 2200).name == "theory_2100_2400.bin"
    assert TH.pick_book(tmp_path, 900).name == "theory_1500_1800.bin" and TH.pick_book(tmp_path, 2800).name == "theory_2100_2400.bin"
    assert TH.pick_book(tmp_path / "missing", 1500) is None


def test_extension_follows_popular_moves_beyond_the_names_and_deepens_coverage(tmp_path):
    ls = lines(tmp_path)
    long_games = [("e2e4 e7e5 g1f3 b8c6 f1c4 g8f6 d2d3 f8c5".split(), "white", 1.0)] * 40 + [("e2e4 e7e5 g1f3 b8c6 f1c4 f8c5 c2c3".split(), "white", 0.5)] * 3
    named, s0 = TH.build(ls, long_games, extend_min_games=0)
    ext, s1 = TH.build(ls, long_games, extend_min_games=15, extend_min_share=0.08)
    assert s0["extension_moves"] == 0 and s1["extension_moves"] >= 3                     # ...Nf6, d3, ...Bc5 follow the 40 games
    assert s1["coverage"][8] > s0["coverage"][8] == 0.0
    b = chess.Board()
    for u in "e2e4 e7e5 g1f3 b8c6 f1c4".split():
        b.push_uci(u)
    moves = {e.uci() for e in ext if e.key == TH.book_key(b)}
    assert moves == {"g8f6"}                                                                # the 3 Bc5 games are 7% of the position: below 8%


def test_extension_ignores_rare_moves(tmp_path):
    g = [("e2e4 e7e5 g1f3 b8c6 f1c4 g8f6".split(), "white", 1.0)] * 5
    _, s = TH.build(lines(tmp_path), g, extend_min_games=15)
    assert s["extension_moves"] == 0
