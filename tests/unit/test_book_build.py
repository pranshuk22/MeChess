import json
import sys

import chess
import pytest
import yaml

from chessme import cli, config
from chessme.book import build
from chessme.book import format as bf
from chessme.book.keys import book_key
from tests.samples import make_row

FILTERS = {"min_rating": {"lichess": 1400}, "recency": {"half_life_days": 3650, "min_weight": 0.1},
           "time_class_weights": {"blitz": 1.0}}
CFG = {"filters": FILTERS, "book": {"max_ply": 20, "min_games": 2, "min_position_games": 3, "min_share": 0.05}}


def rows():
    out = []
    for i in range(8):
        out.append(make_row(game_id=f"qgd{i}", color="white", my_result="win", moves="d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7"))
    for i in range(4):
        out.append(make_row(game_id=f"ind{i}", color="white", my_result="loss", moves="d4 Nf6 c4 g6 Nc3 Bg7"))
    for i in range(6):
        out.append(make_row(game_id=f"sic{i}", color="black", my_result="win", moves="e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6"))
    out.append(make_row(game_id="junk", color="white", moves="e4 e5", usable=False))
    return out


def test_params_merge_defaults_config_and_overrides():
    assert build.book_params({}) == build.DEFAULTS
    p = build.book_params({"book": {"max_ply": 12, "min_share": 0.1, "sanity": {"depth": 3}}})
    assert p["max_ply"] == 12 and p["min_share"] == 0.1 and "sanity" not in p
    p = build.book_params({"book": {"max_ply": 12}}, {"max_ply": 8, "min_games": None})
    assert p["max_ply"] == 8 and p["min_games"] == build.DEFAULTS["min_games"]  # None means "not given"


def test_build_produces_entries_for_the_repeated_lines():
    res = build.build_book(CFG, rows())
    ucis = {(e.key, e.uci()) for e in res.entries}
    start = book_key(chess.Board())
    assert (start, "d2d4") in ucis
    b = chess.Board(); b.push_san("d4"); b.push_san("d5")
    assert (book_key(b), "c2c4") in ucis
    b = chess.Board(); b.push_san("e4")
    assert (book_key(b), "c7c5") in ucis  # black repertoire is in the same book
    assert res.tree.games_used == 18  # the unusable game was ignored
    assert res.sanity_dropped is None


def test_report_describes_repertoire_and_coverage():
    res = build.build_book(CFG, rows())
    text = res.report_text
    assert "Games used: **18**" in text
    assert "**As White** (8 plies)" in text
    assert "1.d4 (12) d5 (8) 2.c4 (8) e6 (8) 3.Nc3 (8) Nf6 (8) 4.Bg5 (8) Be7 (8)" in text
    assert "**As Black vs 1.e4** (6 games)" in text and "1...c5 (6)" in text
    # every game's first four moves of mine are book moves (the 1.d4 Nf6 games run out after three)
    assert "median of **4**" in text and "0% of games have their first 5 moves fully in the book" in text
    assert "Most-visited book positions" in text
    assert "d4 100%" in text  # the start position row
    # the two second-moves are both present as variety at the position after 1.d4
    assert "Nf6" in text and "d5" in text


def test_save_writes_book_and_report(tmp_path):
    res = build.build_book(CFG, rows())
    out, report = build.save(res, tmp_path / "profiles" / "alice" / "book.bin")
    assert out.exists() and report.name == "book_report.md" and report.exists()
    assert len(bf.read_book(out)) == len(res.entries)
    assert "Opening book report" in report.read_text()


def test_book_respects_min_share_and_min_position_games():
    strict = build.build_book(CFG, rows(), {"min_position_games": 9})
    assert {e.uci() for e in strict.entries if e.key == book_key(chess.Board())} == {"d2d4"}
    # after 1.d4 d5 only 8 games arrive: below 9, so that position is not in the strict book
    b = chess.Board(); b.push_san("d4"); b.push_san("d5")
    assert book_key(b) not in {e.key for e in strict.entries}
    loose = build.build_book(CFG, rows(), {"min_position_games": 1, "min_games": 1})
    assert len(loose.entries) > len(strict.entries)


def test_max_ply_caps_book_depth():
    res = build.build_book(CFG, rows(), {"max_ply": 2})
    b = chess.Board(); b.push_san("d4"); b.push_san("d5")
    assert book_key(b) not in {e.key for e in res.entries}  # my second move is at ply 2: out of range


# ---- the command itself, against a temporary profile -----------------------------------------------------------

@pytest.fixture()
def alice(tmp_path, monkeypatch):
    (tmp_path / "configs" / "profiles").mkdir(parents=True)
    (tmp_path / "data" / "processed").mkdir(parents=True)
    cfg = {"profile": "alice", "accounts": [], "paths": {"raw": "data/raw"}, "filters": FILTERS,
           "book": {"max_ply": 20, "min_games": 2, "min_position_games": 3, "min_share": 0.05}}
    (tmp_path / "configs" / "profiles" / "alice.yaml").write_text(yaml.safe_dump(cfg))
    (tmp_path / "data" / "processed" / "games.jsonl").write_text("\n".join(json.dumps(r) for r in rows()))
    monkeypatch.setattr(config, "ROOT", tmp_path)
    return tmp_path


def run_cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["chessme", *argv])
    cli.main()


def test_book_command_writes_book_and_report(alice, monkeypatch, capsys):
    run_cli(monkeypatch, "book", "--profile", "alice")
    out = capsys.readouterr().out
    assert "book moves" in out and "from 18 games" in out
    book = alice / "profiles" / "alice" / "book.bin"
    assert book.exists() and (alice / "profiles" / "alice" / "book_report.md").exists()
    assert any(e.uci() == "d2d4" for e in bf.read_book(book))


def test_book_command_options_override_the_profile(alice, monkeypatch):
    run_cli(monkeypatch, "book", "--profile", "alice", "--out", str(alice / "custom" / "b.bin"),
            "--min-position-games", "1", "--min-games", "1", "--min-share", "0")
    loose = bf.read_book(alice / "custom" / "b.bin")
    run_cli(monkeypatch, "book", "--profile", "alice", "--out", str(alice / "custom" / "s.bin"),
            "--min-position-games", "9")
    strict = bf.read_book(alice / "custom" / "s.bin")
    assert len(loose) > len(strict)
    assert (alice / "custom" / "b_report.md").exists()
