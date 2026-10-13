import json

import chess
import pytest

from chessme.humanlike import gamestats as G


def record(start, moves, termination="checkmate", result="1-0", spent=None, after=None):
    n = len(moves.split())
    return {"gid": "x@0", "white": 1500, "black": 1500, "base": 180, "inc": 0, "start": start, "moves": moves,
            "spent": spent if spent is not None else [1.0] * n, "clock_after": after if after is not None else [100.0] * n,
            "result": result, "termination": termination, "plies": len(start.split()) + n}


def test_replay_counts_captures_checks_castlings_promotions():
    # 1.e4 d5 2.exd5 (capture) Qxd5 3.Nc3 Qa5 4.Nf3 Nf6 5.Be2 e6 6.O-O (castling) Bd6 7.Bb5+ (check)
    c = G.replay_counts(record("e2e4 d7d5", "e4d5 d8d5 b1c3 d5a5 g1f3 g8f6 f1e2 e7e6 e1g1 f8d6 e2b5"))
    assert (c["captures"], c["castlings"], c["checks"], c["moves"], c["promotions"]) == (2, 1, 1, 11, 0)
    p = G.replay_counts({"start": "", "moves": ""})
    assert p["moves"] == 0


def test_replay_counts_counts_a_promotion():
    # 1.h4 g5 2.hxg5 a6 3.g6 a5 4.gxh7 a4 5.hxg8=Q: a pawn captures its way to the eighth rank
    c = G.replay_counts(record("h2h4 g7g5 h4g5 a7a6", "g5g6 a6a5 g6h7 a5a4 h7g8q"))
    assert c["promotions"] == 1 and c["captures"] == 2 and c["moves"] == 5


def test_summarize_counts_endings_and_results():
    a = record("e2e4 e7e5", "g1f3 b8c6", "time_forfeit", "0-1", spent=[2.0, 4.0], after=[5.0, 50.0])
    b = record("e2e4 e7e5", "g1f3 b8c6 f1c4 g8f6", "stalemate", "1/2-1/2")
    s = G.summarize([a, b])
    assert s["games"] == 2 and s["draws"] == 0.5 and s["black_wins"] == 0.5 and s["white_wins"] == 0
    assert s["endings"] == {"time_forfeit": 0.5, "stalemate": 0.5}
    assert s["moves_played"] == 6
    assert s["share_moves_with_under_10s_left"] == pytest.approx(1 / 6)
    assert s["share_under_1s"] == 0 and s["spent_median"] == 1.0


def test_summarize_rejects_empty():
    with pytest.raises(ValueError):
        G.summarize([])


def test_read_games_and_table(tmp_path):
    path = tmp_path / "g.jsonl"
    path.write_text("\n".join(json.dumps(record("e2e4 e7e5", "g1f3 b8c6")) for _ in range(3)) + "\n")
    games = G.read_games(path)
    assert len(games) == 3
    text = G.table({"model": G.summarize(games)})
    assert text.startswith("| statistic | model |") and "| games | 3 |" in text


def lichess_game(**kw):
    game = {"id": "abcd1234", "status": "resign", "winner": "white", "moves": "e4 e5 Nf3 Nc6 Bb5",
            "clocks": [18003, 18003, 17900, 17850, 17700, 17000], "clock": {"initial": 180, "increment": 2},
            "players": {"white": {"rating": 1500}, "black": {"rating": 1450}}}
    game.update(kw)
    return game


def test_real_continuation_converts_san_clocks_and_status():
    r = G.real_continuation(lichess_game(), 2)
    assert r["start"] == "e2e4 e7e5" and r["moves"] == "g1f3 b8c6 f1b5" and r["plies"] == 5
    assert r["result"] == "1-0" and r["termination"] == "resign" and (r["white"], r["black"]) == (1500, 1450)
    assert r["clock_after"] == [179.0, 178.5, 177.0]
    assert r["spent"] == [pytest.approx(3.03), pytest.approx(3.53), pytest.approx(4.0)]       # 180.03 + 2 - 179.0, 180.03 + 2 - 178.5, 179.0 + 2 - 177.0
    assert "gid" in r and r["gid"] == "abcd1234@2"


def test_real_continuation_draws_and_missing_clocks():
    assert G.real_continuation(lichess_game(winner=None, status="draw"), 4)["result"] == "1/2-1/2"
    assert G.real_continuation(lichess_game(status="outoftime"), 0)["termination"] == "time_forfeit"
    with pytest.raises(ValueError):
        G.real_continuation(lichess_game(clocks=[18003]), 2)
    g = lichess_game()
    del g["clocks"]
    with pytest.raises(ValueError):
        G.real_continuation(g, 2)


def test_truncate_keeps_the_start_and_cuts_every_series():
    r = record("e2e4 e7e5", "g1f3 b8c6 f1b5", spent=[1.0, 2.0, 3.0], after=[9.0, 8.0, 7.0])
    t = G.truncate(r, 4)
    assert t["moves"] == "g1f3 b8c6" and t["spent"] == [1.0, 2.0] and t["clock_after"] == [9.0, 8.0] and t["plies"] == 4
    assert G.truncate(r, 99)["moves"] == r["moves"] and G.truncate(r, 1)["moves"] == "" and G.truncate(r, 1)["spent"] == []


def test_table_can_leave_out_the_whole_game_rows():
    s = G.summarize([record("e2e4 e7e5", "g1f3 b8c6")])
    full, part = G.table({"m": s}), G.table({"m": s}, per_move_only=True)
    assert "checkmate" in full and "checkmate" not in part and "plies" not in part and "captures per move" in part
