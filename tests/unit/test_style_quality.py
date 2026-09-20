import shutil
from types import SimpleNamespace

import numpy as np
import pytest

from chessme.analysis import runner as AR
from chessme.style import gamestats as GS
from chessme.style import quality as Q
from chessme.style.games_fetch import write_player

MOVES = "e2e4 e7e5 g1f3 b8c6 f1c4 g8f6"


def rec(color="white", result=1.0, moves=MOVES):
    return {"feat": [], "meta": {"color": color, "result": result, "eco": "C50"}, "moves": moves, "clocks": [], "elo": 1800}


def flat_search(board):
    return [SimpleNamespace(move=next(iter(board.legal_moves)).uci(), cp=0, pv=[])]


def test_game_from_record_replays_moves_and_sets_result_from_the_players_side():
    g = Q.game_from_record(rec("white", 1.0))
    assert [n.move.uci() for n in g.mainline()] == MOVES.split() and g.headers["Result"] == "1-0"
    assert Q.game_from_record(rec("black", 1.0)).headers["Result"] == "0-1"
    assert Q.game_from_record(rec("white", 0.5)).headers["Result"] == "1/2-1/2"


def test_quality_vector_has_every_name_and_marks_not_applicable_as_none():
    res = AR.analyse_game(Q.game_from_record(rec()), lambda b: [SimpleNamespace(move=list(b.legal_moves)[0].uci(), cp=0, pv=[])])
    v = Q.quality_vector(res, "white")
    assert len(v) == len(Q.QUALITY_NAMES)
    d = dict(zip(Q.QUALITY_NAMES, v))
    assert d["q_accuracy"] is not None and d["q_blunder_rate"] == 0.0
    assert d["q_acc_endgame"] is None and d["q_converted"] is None       # never reached a winning moment / no endgame


def test_load_quality_reads_none_as_nan(tmp_path):
    (tmp_path / "quality").mkdir()
    write_player(tmp_path / "quality" / "p1.json.gz", {"pid": "p1", "rating": 1700, "games": [{"feat": [1.0] + [None] * 15, "color": "white"}]})
    out = Q.load_quality(tmp_path)
    rating, arr, metas = out["p1"]
    assert rating == 1700 and arr.shape == (1, 16) and np.isnan(arr[0, 1]) and metas == [{"color": "white"}]


def test_quality_matrices_split_halves_and_skip_short_players():
    arr = np.arange(24, dtype=float).reshape(8, 3)
    ids, XA, XB, R = GS.quality_matrices({"a": (1500, arr, []), "b": (1600, arr[:3], [])}, min_games=6)
    assert ids == ["a"] and XA[0].tolist() == arr[0::2].mean(0).tolist() and XB[0].tolist() == arr[1::2].mean(0).tolist()


@pytest.mark.skipif(not shutil.which("stockfish"), reason="stockfish not installed")
def test_run_analyses_a_sample_and_resumes(tmp_path):
    (tmp_path / "games").mkdir()
    for i in range(3):
        write_player(tmp_path / "games" / f"p{i}.json.gz", {"pid": f"p{i}", "short": False, "rating": 1700 + i, "games": [rec(), rec("black", 0.0)]})
    write_player(tmp_path / "games" / "short.json.gz", {"pid": "short", "short": True, "games": []})
    logs = []
    kw = dict(nodes=3000, n_games=2, max_players=2, workers=2, task_timeout=90, control_dir=str(tmp_path / "ctl"), log=logs.append)
    assert Q.run(tmp_path, **kw) == {"done": 2, "stopped": False}
    assert len(list((tmp_path / "quality").glob("*.json.gz"))) == 2
    assert Q.run(tmp_path, **kw) == {"done": 0, "stopped": False}         # finished players are not redone
    players = Q.load_quality(tmp_path)
    assert all(a.shape == (2, len(Q.QUALITY_NAMES)) for _, a, _ in players.values())
