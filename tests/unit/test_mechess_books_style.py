"""Layered opening books (own repertoire, then theory per rating band) and the style prior of the bot."""
import chess
import numpy as np
import pytest

from chessme.book import format as bf
from chessme.book.keys import book_key
from chessme.mechess.controller import BookReader, BookStack, MeChess, TheoryBands, load_books
from chessme.mechess.priors import StylePrior
from chessme.style import model as SM
from chessme.style.features import FEATURE_NAMES
from tests.unit.test_mechess import L, StubEngine, prior_of, table


def write(path, board, *ucis):
    entries = []
    for i, u in enumerate(ucis):
        m = chess.Move.from_uci(u)
        entries.append(bf.Entry(book_key(board), m.from_square, m.to_square, 0, 10.0 - i, 5, 500))
    bf.write_book(path, entries)


def test_stack_first_book_that_knows_the_position_decides(tmp_path):
    start = chess.Board()
    write(tmp_path / "own.bin", start, "d2d4")
    write(tmp_path / "theory.bin", start, "e2e4")
    stack = load_books(f"{tmp_path / 'own.bin'},{tmp_path / 'theory.bin'}")
    assert [m.uci() for m, _ in stack.moves(start, 1500)] == ["d2d4"]
    after = chess.Board()
    after.push_uci("g1f3")                                       # unknown to my own book: theory answers
    write(tmp_path / "theory2.bin", after, "d7d5")
    stack = load_books(f"{tmp_path / 'own.bin'},{tmp_path / 'theory2.bin'}")
    assert [m.uci() for m, _ in stack.moves(after, 1500)] == ["d7d5"]
    assert stack.moves(chess.Board("8/8/8/8/8/8/8/K1k5 w - - 0 1"), 1500) == []


def test_theory_bands_follow_the_elo_being_played(tmp_path):
    start = chess.Board()
    write(tmp_path / "theory_0_1500.bin", start, "d2d4")
    write(tmp_path / "theory_1500_4000.bin", start, "e2e4")
    bands = TheoryBands(tmp_path)
    assert bands.moves(start, 1000)[0][0].uci() == "d2d4"
    assert bands.moves(start, 2200)[0][0].uci() == "e2e4"
    assert len(bands._readers) == 1                              # one band in memory at a time


def test_load_books_rejects_a_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_books(str(tmp_path / "nope.bin"))
    assert load_books("") is None


def test_controller_plays_the_stack_and_passes_the_elo(tmp_path):
    start = chess.Board()
    write(tmp_path / "theory_0_1500.bin", start, "d2d4")
    write(tmp_path / "theory_1500_4000.bin", start, "e2e4")
    engine = StubEngine([L("a2a3", 0)])
    mc = MeChess(engine, prior_of({}), load_books(str(tmp_path)), table=table(book=10), seed=1)
    assert mc.choose(chess.Board(), 1000).move.uci() == "d2d4"
    assert mc.choose(chess.Board(), 2200).move.uci() == "e2e4"
    assert engine.calls == []                                    # inside the book: no search


def fake_model(**weights):
    w = np.zeros(len(FEATURE_NAMES))
    for k, v in weights.items():
        w[FEATURE_NAMES.index(k)] = v
    return SM.StyleModel(np.zeros(len(FEATURE_NAMES)), np.ones(len(FEATURE_NAMES)), w, 1.0)


def test_style_model_roundtrip_and_feature_guard(tmp_path):
    m = fake_model(capture=1.5)
    SM.save_model(m, tmp_path / "s.json", n=10)
    back = SM.load_model(tmp_path / "s.json")
    assert np.allclose(back.w, m.w) and back.loss_coef == 1.0
    import json
    d = json.loads((tmp_path / "s.json").read_text())
    d["names"][0] = "something_else"
    (tmp_path / "bad.json").write_text(json.dumps(d))
    with pytest.raises(ValueError, match="other features"):
        SM.load_model(tmp_path / "bad.json")


def test_style_prior_prefers_what_you_seek_and_avoid(tmp_path):
    board = chess.Board("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")   # e4xd5 is the only capture
    SM.save_model(fake_model(capture=2.0), tmp_path / "seek.json")
    SM.save_model(fake_model(capture=-2.0), tmp_path / "avoid.json")
    cap = chess.Move.from_uci("e4d5")
    seek = StylePrior(tmp_path / "seek.json")(board, 1800, 1800, 0)
    avoid = StylePrior(tmp_path / "avoid.json")(board, 1800, 1800, 0)
    assert seek.keys() == set(board.legal_moves) and abs(sum(seek.values()) - 1) < 1e-9
    assert seek[cap] > 1 / len(seek) > avoid[cap]
    flat = StylePrior(tmp_path / "seek.json", strength=0)(board, 1800, 1800, 0)
    assert max(flat.values()) - min(flat.values()) < 1e-12       # strength 0 switches the style off


def test_style_prior_steers_the_choice_among_equal_candidates(tmp_path):
    board = chess.Board("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    SM.save_model(fake_model(capture=6.0), tmp_path / "s.json")
    engine = StubEngine([L("e4d5", 0), L("b1c3", 0), L("g1f3", 0)])
    mc = MeChess(engine, StylePrior(tmp_path / "s.json"), None, table=table(temp=1.0, scale=1e9), seed=3)
    picks = [mc.choose(board, 1800).move.uci() for _ in range(60)]
    assert picks.count("e4d5") > 50
