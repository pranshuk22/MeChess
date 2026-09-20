import chess

from chessme.books import text as T


def test_descriptive_spellings_of_opening_moves():
    b = chess.Board()
    lk = T.descriptive_lookup(b)
    assert lk["P-K4"] == chess.Move.from_uci("e2e4") and lk["N-KB3"] == chess.Move.from_uci("g1f3")
    assert "P-QB4" in lk and lk["QN-B3"] == chess.Move.from_uci("b1c3") and "N-B3" not in lk       # N-B3 is ambiguous (QN or KN)
    b.push_uci("e2e4")
    lk = T.descriptive_lookup(b)
    assert lk["P-K4"] == chess.Move.from_uci("e7e5")                     # Black counts ranks from its own side


def test_descriptive_captures_castling_and_promotion():
    b = chess.Board()
    for m in "e2e4 d7d5".split():
        b.push_uci(m)
    forms = T.descriptive_forms(b, chess.Move.from_uci("e4d5"))
    assert {"PxP", "PxQ4" if False else "PxQP", "PxQ5"} <= forms and "KPxP" in forms
    b = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    assert T.descriptive_forms(b, chess.Move.from_uci("e1g1")) == {"O-O"}
    assert T.descriptive_forms(b, chess.Move.from_uci("e1c1")) == {"O-O-O"}
    b = chess.Board("8/P6k/8/8/8/8/8/K7 w - - 0 1")
    assert "P-QR8=Q" in T.descriptive_forms(b, chess.Move.from_uci("a7a8q"))


def test_parse_a_descriptive_line_in_both_book_spacings():
    a = "1. P-K4 P-K4 2. Kt-KB3 Kt-QB3 3. B-Kt5 P-QR3 4. B-R4 Kt-B3 and White"
    moves, used = T.parse_line(a)
    assert moves[:6] == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"] and len(moves) == 8
    spaced = "1. P - K 4 P - K 4 2. Kt - K B 3 Kt - Q B 3"
    assert T.parse_line(spaced)[0][:4] == ["e4", "e5", "Nf3", "Nc6"]


def test_parse_algebraic_line_with_ocr_junk_stops_at_the_first_illegal_token():
    good, _ = T.parse_line("1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5 4.c3 Nf6 5.d4 exd4")
    assert good == ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "c3", "Nf6", "d4", "exd4"]
    junk, _ = T.parse_line("1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5 4.c3 NiS 5.d4 exd4")           # NiS is an OCR reading of Nf6
    assert junk == ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "c3"]


def test_annotations_and_check_marks_are_skipped():
    m, _ = T.parse_line("1. P-K4 P-K4 2. Q-R5 Kt-QB3 3. B-B4 Kt-B3?? 4. Qxf7 ch. mate")
    assert m[:3] == ["e4", "e5", "Qh5"] and m[-1] == "Qxf7#"


def test_find_lines_only_from_the_initial_position_and_reports_notation():
    text = "In the Ruy Lopez: 1. P-K4 P-K4 2. Kt-KB3 Kt-QB3 3. B-Kt5 P-QR3. Later, from a diagram, 1. Q-Kt7 wins."
    lines = T.find_lines(text)
    assert len(lines) == 1 and lines[0]["notation"] == "descriptive" and lines[0]["moves"][-1] == "a6"
    assert T.find_lines("Play 1.e4 e5 2.Nf3 Nc6 3.Bb5 a6", min_plies=6)[0]["notation"] == "algebraic"
    assert T.find_lines("A fair game: 1.e4 e5 only") == []                                # too short to be a line


def test_concepts_paragraphs_and_gutenberg_strip():
    c = T.concept_counts("The knight on an outpost; the bad bishop and a passed pawn. Prophylaxis!")
    assert {"outpost", "good_bad_bishop", "passed_pawn", "prophylaxis"} <= set(c)
    assert T.paragraphs("A line-\nbreak here.\nSecond line.\n\nNext paragraph.") == ["A linebreak here. Second line.", "Next paragraph."]
    book = "junk\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\nBODY\n*** END OF THE PROJECT GUTENBERG EBOOK X ***\nlicence"
    assert T.strip_gutenberg(book).strip() == "BODY"


def test_analyse_book_links_concepts_to_paragraphs_with_a_line():
    text = ("The centre matters.\n\nAn outpost helps: 1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 shows it.\n\n"
            "A blockade can win, but no moves here.")
    res = T.analyse_book(text)
    assert res["paragraphs"] == 3 and res["notation"]["algebraic"] == 1
    assert res["concepts"]["outpost"] == 1 and res["concept_with_moves"] == {"outpost": 1}
    assert "blockade" in res["concepts"] and "blockade" not in res["concept_with_moves"]
