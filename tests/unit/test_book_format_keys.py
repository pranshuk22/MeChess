import chess
import pytest

from chessme.book import format as bf
from chessme.book.keys import book_key, fnv1a64, key_text


def test_fnv1a_matches_published_vectors():
    assert fnv1a64("") == 0xCBF29CE484222325
    assert fnv1a64("a") == 0xAF63DC4C8601EC8C
    assert fnv1a64("foobar") == 0x85944171F73967E8


def test_keys_match_the_constants_pinned_in_the_cpp_tests():
    # Same constants as engine/tests/test_book.cpp: if these ever diverge the book silently stops matching.
    assert book_key(chess.Board()) == 0x7BD6409C02270343
    b = chess.Board()
    b.push_san("e4")
    assert book_key(b) == 0xDF98C55FC062ADB4


def test_key_ignores_counters_and_ep_but_not_side_or_castling():
    a = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
    assert book_key(a) == book_key(chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 12 40"))
    assert book_key(a) != book_key(chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1"))
    assert book_key(a) != book_key(chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b Kkq - 0 1"))
    assert key_text(a) == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq"


def test_key_accepts_fen_strings_and_transpositions_collapse():
    a, b = chess.Board(), chess.Board()
    for m in ("Nf3", "Nf6", "Nc3", "Nc6"):
        a.push_san(m)
    for m in ("Nc3", "Nc6", "Nf3", "Nf6"):
        b.push_san(m)
    assert book_key(a) == book_key(b) == book_key(a.fen())


def entry(key=1, f=12, t=28, promo=0, weight=2.5, games=7, score=600):
    return bf.Entry(key, f, t, promo, weight, games, score)


def test_round_trip_sorted_by_key_then_weight(tmp_path):
    entries = [entry(9, weight=1), entry(3, f=11, t=27, weight=1.5), entry(3, weight=4.0), entry(9, f=1, t=18, weight=3)]
    p = tmp_path / "b.bin"
    bf.write_book(p, entries)
    back = bf.read_book(p)
    assert [(e.key, e.weight) for e in back] == [(3, 4.0), (3, 1.5), (9, 3.0), (9, 1.0)]
    assert {(e.key, e.from_sq, e.to_sq) for e in back} == {(e.key, e.from_sq, e.to_sq) for e in entries}


def test_entry_fields_survive_and_are_clamped(tmp_path):
    p = tmp_path / "b.bin"
    bf.write_book(p, [entry(games=999999, score=5000)])
    (e,) = bf.read_book(p)
    assert e.games == 65535 and e.score_permille == 1000
    assert e.uci() == "e2e4"


def test_promotion_uci(tmp_path):
    e = bf.Entry(1, chess.A7, chess.A8, chess.QUEEN, 1.0, 1, 0)
    assert e.uci() == "a7a8q"
    p = tmp_path / "b.bin"
    bf.write_book(p, [e])
    assert bf.read_book(p)[0].promo == chess.QUEEN


def test_empty_book_round_trips(tmp_path):
    p = tmp_path / "b.bin"
    bf.write_book(p, [])
    assert bf.read_book(p) == []


@pytest.mark.parametrize("bad", [
    entry(f=64), entry(t=70), entry(promo=1), entry(promo=6), entry(weight=0), entry(weight=-1),
])
def test_writer_rejects_invalid_entries(tmp_path, bad):
    with pytest.raises(bf.BookFormatError):
        bf.write_book(tmp_path / "b.bin", [bad])


def test_reader_rejects_corrupt_files(tmp_path):
    p = tmp_path / "b.bin"
    bf.write_book(p, [entry(1), entry(2)])
    good = p.read_bytes()
    cases = {
        "magic": b"XXXX" + good[4:],
        "short": good[:6],
        "truncated": good[:-3],
        "trailing": good + b"\0",
        "version": good[:4] + (7).to_bytes(4, "little") + good[8:],
    }
    for name, data in cases.items():
        p.write_bytes(data)
        with pytest.raises(bf.BookFormatError):
            bf.read_book(p)


def test_reader_rejects_unsorted_entries(tmp_path):
    p = tmp_path / "b.bin"
    bf.write_book(p, [entry(1), entry(2)])
    data = bytearray(p.read_bytes())
    a, b = bf.HEADER.size, bf.HEADER.size + bf.ENTRY.size
    data[a:a + 20], data[b:b + 20] = data[b:b + 20], data[a:a + 20]
    p.write_bytes(bytes(data))
    with pytest.raises(bf.BookFormatError, match="sorted"):
        bf.read_book(p)
