import json

import chess

from chessme import openings


def write_games(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows))


def row(moves, usable=True):
    return {"moves": moves, "usable": usable}


def test_from_games_returns_positions_after_n_plies(tmp_path):
    p = tmp_path / "g.jsonl"
    write_games(p, [row("e4 e5 Nf3 Nc6 Bb5 a6")])
    (fen,) = openings.from_games(p, plies=4)
    b = chess.Board()
    for m in ("e4", "e5", "Nf3", "Nc6"):
        b.push_san(m)
    assert fen == b.fen()


def test_transpositions_and_duplicates_collapse(tmp_path):
    p = tmp_path / "g.jsonl"
    write_games(p, [row("Nf3 Nf6 Nc3 Nc6 e4"), row("Nc3 Nc6 Nf3 Nf6 d4"), row("Nf3 Nf6 Nc3 Nc6 e4")])
    assert len(openings.from_games(p, plies=4)) == 1


def test_short_and_unusable_games_are_skipped(tmp_path):
    p = tmp_path / "g.jsonl"
    write_games(p, [row("e4 e5"), row("d4 d5 c4 e6 Nc3", usable=False), row("d4 d5 c4 e6 Nc3")])
    fens = openings.from_games(p, plies=4)
    assert len(fens) == 1
    assert len(openings.from_games(p, plies=4, usable_only=False)) == 1  # same position either way


def test_unreplayable_games_are_skipped_not_fatal(tmp_path):
    p = tmp_path / "g.jsonl"
    write_games(p, [row("e4 e5 Nf3 Ke8 Nc6"), row("e4 e5 Nf3 Nc6 Bb5")])
    assert len(openings.from_games(p, plies=4)) == 1


def test_seed_controls_order_and_limit(tmp_path):
    p = tmp_path / "g.jsonl"
    firsts = ["e4", "d4", "c4", "Nf3", "g3", "b3", "f4", "Nc3"]
    write_games(p, [row(f"{m} a6 h3 a5 h4") for m in firsts])
    a = openings.from_games(p, plies=4, seed=1)
    assert a == openings.from_games(p, plies=4, seed=1)
    assert a != openings.from_games(p, plies=4, seed=2)
    assert sorted(a) == sorted(openings.from_games(p, plies=4, seed=2))
    assert len(openings.from_games(p, plies=4, limit=3)) == 3


def test_random_openings_are_legal_unique_and_reproducible():
    a = openings.random_openings(30, plies=6, seed=5)
    assert a == openings.random_openings(30, plies=6, seed=5)
    assert len(set(a)) == len(a) == 30
    for fen in a:
        b = chess.Board(fen)
        assert b.is_valid() and not b.is_game_over()
        assert b.fullmove_number == 4  # 6 plies played from the start


def test_write_read_round_trip(tmp_path):
    fens = openings.random_openings(5, plies=4, seed=1)
    path = tmp_path / "sub" / "o.fen"
    openings.write_openings(path, fens)
    assert openings.read_openings(path) == fens


def test_read_ignores_blank_lines_and_comments(tmp_path):
    p = tmp_path / "o.fen"
    p.write_text("# comment\n\n" + chess.STARTING_FEN + "\n\n")
    assert openings.read_openings(p) == [chess.STARTING_FEN]
