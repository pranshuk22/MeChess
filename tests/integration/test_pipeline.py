"""Integration: raw files -> ingest -> weights -> audit, end to end, on synthetic data (no network)."""
import json

import pytest

from chessme import audit
from chessme.dataset.weights import Weighter
from chessme.ingest import normalize
from tests.samples import LICHESS_GAME, chesscom_game, fill

pytestmark = pytest.mark.integration


def test_raw_to_audit_pipeline(tmp_path):
    raw = tmp_path / "data" / "raw"
    (raw / "lichess" / "Me").mkdir(parents=True)
    (raw / "chesscom" / "MeCC").mkdir(parents=True)
    g1 = fill(LICHESS_GAME, "Me", "Opp1")
    g2 = fill(LICHESS_GAME, "Opp2", "Me").replace("abcd1234", "second99").replace("1-0", "0-1").replace("2024.03.30", "2024.06.01")
    (raw / "lichess" / "Me" / "games_1.pgn").write_text(g1 + g2)
    (raw / "chesscom" / "MeCC" / "2024-05.json").write_text(json.dumps({"games": [
        chesscom_game(white="MeCC", black="rival", uuid="c1"),
        chesscom_game(white="MeCC", black="rival2", uuid="c2", rules="chess960"),
    ]}))
    cfg = {
        "_raw_dir": raw,
        "accounts": [{"platform": "lichess", "username": "Me"}, {"platform": "chesscom", "username": "MeCC"}],
        "filters": {"min_rating": {"lichess": 1400, "chesscom": 1800},  # chess.com game (1700) falls below floor
                    "recency": {"half_life_days": 365, "min_weight": 0.1},
                    "time_class_weights": {"blitz": 1.0, "rapid": 1.0}},
    }
    normalize.ingest(cfg)
    rows = audit.load(tmp_path / "data" / "processed" / "games.jsonl")
    assert len(rows) == 4 and sum(r["usable"] for r in rows) == 3

    w = Weighter(cfg, rows)
    kept = [r for r in rows if w.game_weight(r) > 0]
    assert {r["game_id"] for r in kept} == {"lichess:abcd1234", "lichess:second99"}  # chess.com game floored out
    newest = max(kept, key=lambda r: r["played_at"])
    assert w.game_weight(newest) == pytest.approx(1.0)

    text = audit.build(rows, cfg)
    assert "Games ingested: **4**" in text and "Usable for training: **3**" in text
    assert "Games kept after rating floors / excluded time classes: **2** of 3 usable" in text
    # repertoire counts every usable game: 1.e4 (Lichess) and 1.d4 (chess.com)
    assert "As white, first move: e4 50%, d4 50%" in text
