import json
import os
from pathlib import Path

import pytest

from chessme.humanlike import allie as A

LINE = "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7 f1e1 b7b5 a4b3 d7d6".split()


def game(seconds, tc="180+2", moves=LINE, **kw):
    g = {"game-id": "https://lichess.org/abcd1234", "moves-uci": " ".join(moves), "moves-seconds": seconds, "event": "Rated Blitz game",
         "result": "1-0", "white-elo": 1700, "black-elo": 1650, "termination": "Normal", "time-control": tc}
    g.update(kw)
    return g


def test_clocks_are_rebuilt_from_the_seconds_spent_with_the_increment():
    # 180+2: white spends 3 s then 5 s ...; black spends 1 s then 10 s ...
    ps = A.game_positions(game([3, 1, 5, 10, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]), comparable_only=False)
    assert [p.clock for p in ps[:5]] == [180, 180, 180 + 2 - 3, 180 + 2 - 1, 180 + 4 - 8]
    assert ps[2].opp_clock == 181 and ps[2].spent == 5.0 and ps[0].me == 1700 and ps[1].me == 1650
    assert ps[4].fen == __import__("chess").Board().fen() or ps[4].moves == "e2e4 e7e5 g1f3 b8c6"
    assert ps[3].moves == "e2e4 e7e5 g1f3" and ps[0].gid == "abcd1234"


def test_the_first_ten_plies_and_everything_after_the_first_low_clock_are_dropped():
    # white spends 150 s on its 6th move (ply 10), leaving 25 s: at ply 11 (black to move) white is the opponent with under 30 s = the first event,
    # which is kept; ply 12 and 13 are late
    secs = [1] * 10 + [150, 1, 1, 1]
    ps = A.game_positions(game(secs, tc="180+0"))
    assert [p.ply for p in ps] == [10, 11]
    assert ps[1].opp_clock < 30 and not ps[1].late and ps[0].clock > 30
    full = A.game_positions(game(secs, tc="180+0"), comparable_only=False)
    assert [p.late for p in full] == [False] * 12 + [True] * 2


def test_a_game_without_time_trouble_keeps_everything_past_the_opening():
    ps = A.game_positions(game([2] * 14, tc="300+0"))
    assert [p.ply for p in ps] == [10, 11, 12, 13]


def test_inconsistent_games_are_an_error():
    with pytest.raises(ValueError, match="times"):
        A.game_positions(game([1, 2, 3]))


def test_the_published_test_set_size_is_reproduced_exactly():
    """884,049 positions from the 18,239 Allie test games (needs the 45 MB file: set CHESSME_ALLIE_TEST to its path)."""
    path = os.environ.get("CHESSME_ALLIE_TEST")
    if not path or not Path(path).exists():
        pytest.skip("the Allie test file is not provided (CHESSME_ALLIE_TEST)")
    n = sum(1 for _ in A.iter_positions(path))
    assert n == A.PUBLISHED_POSITIONS
