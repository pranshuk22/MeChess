import chess
import pytest

from chessme.book import build, evaluate
from chessme.book import format as bf
from chessme.dataset.weights import Weighter
from tests.samples import make_row

FILTERS = {"min_rating": {"lichess": 1400}, "recency": {"half_life_days": 36500, "min_weight": 0.1},
           "time_class_weights": {"blitz": 1.0}}
CFG = {"filters": FILTERS, "book": {"max_ply": 20, "min_games": 1, "min_position_games": 1, "min_share": 0.0}}


def g(moves, gid, when="2024-01-01T00:00:00+00:00", color="white", **kw):
    return make_row(game_id=gid, moves=moves, color=color, my_result="win", played_at=when, **kw)


def book_from(rows):
    return build.build_book(CFG, rows).entries


def evaluate_book(train, test):
    return evaluate.evaluate(book_from(train), test, Weighter(CFG, train + test), 20)


def test_split_by_time_puts_the_newest_games_in_the_test_set():
    rows = [g("e4 e5", f"g{i}", when=f"2024-01-{i + 1:02d}T00:00:00+00:00") for i in range(10)]
    rows.append(g("e4 e5", "junk", usable=False))
    train, test = evaluate.split_by_time(rows, 0.2)
    assert len(train) == 8 and len(test) == 2
    assert max(r["played_at"] for r in train) < min(r["played_at"] for r in test)
    assert all(r["usable"] for r in train + test)


def test_perfectly_predictable_player_scores_100_percent():
    train = [g("d4 d5 c4 e6", f"t{i}") for i in range(5)]
    test = [g("d4 d5 c4 e6", "x1"), g("d4 d5 c4 e6", "x2")]
    res = evaluate_book(train, test)["overall"]
    assert res["moves"] == 4 and res["coverage"] == 1.0 and res["top1"] == 1.0 and res["sampled"] == 1.0


def test_a_different_repertoire_is_a_miss_where_covered_and_uncovered_after():
    train = [g("d4 d5 c4 e6", f"t{i}") for i in range(5)]
    test = [g("e4 e5 Nf3 Nc6", "x1")]  # a repertoire the book has never seen
    res = evaluate_book(train, test)["overall"]
    # 1.e4: the start position is in the book (it holds 1.d4), so it is covered but predicted wrongly.
    # 2.Nf3: the position after 1.e4 e5 was never seen, so it is not covered at all.
    assert res["moves"] == 2 and res["coverage"] == 0.5
    assert res["top1"] == 0.0 and res["sampled"] == 0.0


def test_top1_top3_and_sampling_probability():
    # at the start position the book has d4 (weight 6), e4 (weight 3), c4 (weight 1)
    train = [g("d4 d5", f"d{i}") for i in range(6)] + [g("e4 e5", f"e{i}") for i in range(3)] + [g("c4 e5", "c0")]
    for pick, top1, top3 in (("d4", 1.0, 1.0), ("e4", 0.0, 1.0), ("c4", 0.0, 1.0), ("Nf3", 0.0, 0.0)):
        res = evaluate_book_first_move(train, g(f"{pick} d5", "x"))
        assert res["top1"] == top1 and res["top3"] == top3, pick
    assert evaluate_book_first_move(train, g("e4 d5", "x"))["sampled"] == pytest.approx(0.3)


def evaluate_book_first_move(train, test):
    res = evaluate.evaluate(book_from(train), [test], Weighter(CFG, train + [test]), max_ply=1)
    assert res["overall"]["moves"] == 1
    if res["overall"]["coverage"] == 0:
        return {"top1": 0.0, "top3": 0.0, "sampled": 0.0}
    return res["overall"]


def test_only_my_moves_count_and_colour_is_respected():
    train = [g("e4 c5 Nf3 d6", f"b{i}", color="black") for i in range(4)]
    test = [g("e4 c5 Nf3 d6", "x", color="black")]
    res = evaluate_book(train, test)["overall"]
    assert res["moves"] == 2  # Black's two moves: ...c5 and ...d6
    assert res["coverage"] == 1.0


def test_filtered_test_games_are_skipped():
    train = [g("d4 d5", f"t{i}") for i in range(3)]
    low = g("d4 d5", "low", my_rating=900)
    res = evaluate.evaluate(book_from(train), [low], Weighter(CFG, train + [low]), 20)
    assert res["games"] == 0 and res["overall"]["moves"] == 0


def test_per_move_table_and_formatting():
    train = [g("d4 d5 c4 e6 Nc3 Nf6", f"t{i}") for i in range(5)]
    test = [g("d4 d5 c4 e6 Nf3 Nf6", "x")]  # my 3rd move (Nf3 instead of Nc3) is a miss on top-1
    res = evaluate_book(train, test)
    assert res["by_move"][1]["top1"] == 1.0 and res["by_move"][3]["top1"] == 0.0
    text = evaluate.format_evaluation(res)
    assert "Hold-out evaluation on 1 newest games" in text and "| my move # |" in text


def test_book_command_prints_holdout_evaluation(tmp_path, monkeypatch, capsys):
    import json
    import sys

    import yaml

    from chessme import cli, config

    (tmp_path / "configs" / "profiles").mkdir(parents=True)
    (tmp_path / "data" / "processed").mkdir(parents=True)
    cfg = {"profile": "alice", "accounts": [], "paths": {"raw": "data/raw"}, "filters": FILTERS, "book": CFG["book"]}
    (tmp_path / "configs" / "profiles" / "alice.yaml").write_text(yaml.safe_dump(cfg))
    rows = [g("d4 d5 c4 e6", f"g{i}", when=f"2024-02-{i + 1:02d}T00:00:00+00:00") for i in range(20)]
    (tmp_path / "data" / "processed" / "games.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["chessme", "book", "--profile", "alice", "--holdout", "0.2"])
    cli.main()
    out = capsys.readouterr().out
    assert "Hold-out evaluation on 4 newest games" in out and "top-1 **100%**" in out
    assert (tmp_path / "profiles" / "alice" / "book.bin").exists()  # the shipped book still uses ALL games
    assert len(bf.read_book(tmp_path / "profiles" / "alice" / "book.bin")) >= 2
