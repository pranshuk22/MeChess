import io

import chess.pgn

from chessme.books import annotated as A
from chessme.books import glyphs as G
from chessme.books import text as T


def test_glyph_table_agrees_with_the_python_chess_standard():
    assert G.check_against_library() == []
    assert [G.symbol(n) for n in G.JUDGEMENT] == ["!!", "!", "!?", "?!", "?", "??"]
    assert G.info(16)[:3] == ("±", "White has a moderate advantage", "evaluation") and G.info(17)[3] == "black"
    assert G.info(999)[2] == "other" and G.symbol(999) == ""
    assert G.EVAL_SCORE[14] == 1 and G.EVAL_SCORE[19] == -3 and 13 not in G.EVAL_SCORE          # unclear claims no side


def test_marks_after_moves_and_symbols_in_text():
    assert G.marks_after_move("! Ke7") == [1] and G.marks_after_move("?? 2.") == [4] and G.marks_after_move("!?") == [5] and G.marks_after_move(" x") == []
    assert G.symbols_in("After Nf3! and Bxh7+?? White is better ± but =+ later, ∞ overall") == [1, 4, 16, 15, 13]
    assert G.symbols_in("Did he really play that? What!") == []                               # prose punctuation is not a glyph
    assert G.symbols_in("+- and -+ and +/-") == [18, 19, 16]


def test_figurines_become_letters():
    assert G.normalise_figurines("1. ♙e4 ♙e5 2. ♘f3 ♞c6 3. ♗b5") == "1. e4 e5 2. Nf3 Nc6 3. Bb5"
    moves, _ = T.parse_line("1. ♙e4 ♙e5 2. ♘f3 ♞c6 3. ♗b5 a6")
    assert moves == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]


def test_book_lines_keep_the_marks_after_moves():
    line = T.find_lines("1. P-K4! P-K4 2. Kt-KB3 Kt-QB3?! 3. B-Kt5 P-QR3?? 4. B-R4 Kt-B3")[0]
    assert line["glyphs"] == [[0, 1], [3, 6], [5, 4]] or line["glyphs"] == [(0, 1), (3, 6), (5, 4)]
    alg = T.find_lines("1.e4! e5 2.Nf3 Nc6 3.Bb5 a6!! 4.Ba4 Nf6")[0]
    assert [tuple(g) for g in alg["glyphs"]] == [(0, 1), (5, 3)]


def test_annotated_moves_record_all_nags_evaluation_and_text_glyphs():
    pgn = '[Result "*"]\n\n1. e4 $1 e5 $10 2. Nf3 $14 {Better ±: ♘f3 develops. Then Nc6! follows.} Nc6 $146 3. Bb5 $22 *\n'
    moves = A.annotated_moves(chess.pgn.read_game(io.StringIO(pgn)))
    by_san = {m["san"]: m for m in moves}
    assert by_san["e4"]["glyph"] == "!" and by_san["e4"]["nags"] == [1]
    assert by_san["e5"]["glyph"] is None and by_san["e5"]["eval"] == "=" and by_san["e5"]["nags"] == [10]
    assert by_san["Nf3"]["eval"] == "⩲" and "Nf3 develops" in by_san["Nf3"]["comment"] and by_san["Nf3"]["text_nags"] == [1, 16]
    assert by_san["Nc6"]["nags"] == [146] and by_san["Bb5"]["nags"] == [22]


def test_extract_counts_every_nag_and_text_glyph(tmp_path):
    from tests.unit.test_books_annotated import make_archive
    stats = A.extract(make_archive(tmp_path), tmp_path / "o", log=lambda *_: None)
    assert stats["nags"] == {"1": 1, "6": 1, "2": 2} and stats["glyphs"] == {"!": 1, "?!": 1, "?": 2}
