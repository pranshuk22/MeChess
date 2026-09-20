import sys
from pathlib import Path

import chess
import numpy as np
import pytest

from chessme.model import baselines
from chessme.model import data as D
from chessme.model import encoding as enc

FAKE = str(Path(__file__).resolve().parents[1] / "fake_engine.py")  # always answers bestmove e2e4


def shard(moves_uci, fen=chess.STARTING_FEN, rating=1500):
    buf = D.SampleBuffer(with_extras=True)
    for uci in moves_uci:
        b = chess.Board(fen)
        buf.add(b, chess.Move.from_uci(uci), (rating, rating), 0, 1, 10, 1.0)
    return buf.to_arrays()


def test_engine_match_counts_agreements():
    data = shard(["e2e4", "e2e4", "d2d4", "g1f3"])  # the stub engine always plays e2e4: 2 of 4 agree
    res = baselines.engine_match([sys.executable, FAKE, "normal"], data, nodes=10, limit=100)
    assert res["n"] == 4 and res["top1"] == pytest.approx(0.5)
    assert res["by_rating"] == {1400: 0.5}


def test_engine_match_respects_the_limit_and_is_seeded():
    data = shard(["e2e4", "d2d4"] * 10)
    a = baselines.engine_match([sys.executable, FAKE, "normal"], data, limit=6, seed=1)
    b = baselines.engine_match([sys.executable, FAKE, "normal"], data, limit=6, seed=1)
    assert a["n"] == 6 and a == b


def test_engine_match_needs_fens():
    data = shard(["e2e4"])
    data.pop("fen")
    with pytest.raises(ValueError, match="FEN"):
        baselines.engine_match([sys.executable, FAKE, "normal"], data)
