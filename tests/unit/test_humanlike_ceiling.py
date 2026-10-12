import sqlite3
from dataclasses import replace

import chess
import numpy as np
import pytest

from chessme.book import explorer as EX
from chessme.humanlike import ceiling as C
from chessme.humanlike import report as R
from chessme.humanlike import score as S
from chessme.humanlike import testset as T
from tests.unit.test_humanlike_testset import make_game, positions_of

START_KEY = EX.signed64(EX.pos_key(chess.Board()))


def make_db(path, moves, total, band_games=1_000_000):
    """A minimal explorer database: one band 1600-1800 (id 5), the moves listed at the start position and its true total."""
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE bands(id INTEGER PRIMARY KEY, lo INTEGER, hi INTEGER, games INTEGER, window_end INTEGER);
        CREATE TABLE moves(band INTEGER, pos INTEGER, move INTEGER, uci TEXT, games INTEGER);
        CREATE TABLE positions(band INTEGER, pos INTEGER, games INTEGER);
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);""")
    db.execute("INSERT INTO bands VALUES (5, 1600, 1800, ?, NULL)", (band_games,))
    db.executemany("INSERT INTO moves VALUES (5, ?, 0, ?, ?)", [(START_KEY, u, g) for u, g in moves.items()])
    db.execute("INSERT INTO positions VALUES (5, ?, ?)", (START_KEY, total))
    db.executemany("INSERT INTO meta VALUES (?, ?)", [("min_games", "5"), ("min_frac", "1e-05")])        # floor = max(5, 10) = 10 for 1M games
    db.commit()
    db.close()


def first_position(played, me=1700, opp=1650, ply=0):
    p = [q for q in positions_of(make_game(site="g0000001", WhiteElo=str(me), BlackElo=str(opp))) if q.ply == 0][0]
    return replace(p, played=played, ply=ply)


def test_the_oracle_removes_the_games_own_move(tmp_path):
    make_db(tmp_path / "e.db", {"e2e4": 600, "d2d4": 300, "c2c4": 50}, total=1000)
    ps = [first_position("e2e4"), first_position("d2d4"), first_position("g1f3")]
    look = C.lookup(tmp_path / "e.db", ps)
    orc = C.oracle(look)
    assert orc["ok"].all() and (orc["t_other"] == 999).all()
    assert orc["top1"].tolist() == [1.0, 0.0, 0.0]                                    # 599 vs 300; 299 vs 600; unlisted move
    assert orc["sampled_lo"][0] == pytest.approx(599 / 999) and orc["sampled_lo"][1] == pytest.approx(299 / 999)
    assert orc["sampled_lo"][2] == 0.0 and orc["sampled_hi"][2] == pytest.approx(9 / 999)      # unlisted: between 0 and floor - 1 games
    assert orc["stratum"][0] == 2                                                     # 999 other games: 100-999


def test_ties_are_split_and_a_game_between_unequal_players_is_not_removed(tmp_path):
    make_db(tmp_path / "e.db", {"e2e4": 101, "d2d4": 100}, total=201)
    tie = C.oracle(C.lookup(tmp_path / "e.db", [first_position("e2e4")]))
    assert tie["top1"][0] == 0.5                                                      # 100 vs 100 once the own game is out
    far = first_position("e2e4", me=1790, opp=1450)                                   # rating gap over 300: the explorer never counted this game
    look = C.lookup(tmp_path / "e.db", [far])
    assert look["own"][0] == 0 and C.oracle(look)["top1"][0] == 1.0 and C.oracle(look)["t_other"][0] == 201


def test_positions_without_an_oracle(tmp_path):
    make_db(tmp_path / "e.db", {"e2e4": 600}, total=600)
    late = first_position("e2e4", ply=30)
    other_band = first_position("e2e4", me=2500, opp=2450)                            # no row for that band
    unseen = replace(first_position("e2e4"), fen=chess.Board("rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 1 1").fen())
    look = C.lookup(tmp_path / "e.db", [late, other_band, unseen])
    orc = C.oracle(look)
    assert not orc["ok"].any() and (orc["stratum"] == -1).all()


def test_the_table_compares_a_model_with_the_oracle(tmp_path):
    make_db(tmp_path / "e.db", {"e2e4": 600, "d2d4": 300, "c2c4": 50}, total=1000)
    ps = [replace(first_position("e2e4"), gid=f"g{i}") for i in range(150)]
    look = C.lookup(tmp_path / "e.db", ps)
    orc = C.oracle(look)
    n = len(ps)
    scores = {"top1": np.zeros(n, dtype=bool), "p": np.full(n, 0.2)}                  # a model that never picks e4 and gives it 0.2
    rows = C.table(scores, R.position_arrays(ps), orc, n_boot=50)
    r = rows["all positions with an oracle"]
    assert r["n"] == 150 and r["oracle_top1"][0] == 1.0 and r["model_top1"][0] == 0.0
    assert r["gap_top1"][0] == pytest.approx(-1.0) and r["oracle_sampled_lo"] == pytest.approx(599 / 999)
    assert "seen by 100-999 other games" in rows and "| all positions with an oracle |" in C.render(rows)
