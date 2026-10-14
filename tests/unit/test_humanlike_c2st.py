import chess
import numpy as np
import pytest

from chessme.humanlike import c2st as C


def random_game(rng, gid, plies=30, capture_bias=0.0, start_plies=8):
    board, ucis = chess.Board(), []
    for _ in range(start_plies):
        m = rng.choice(sorted(board.legal_moves, key=lambda x: x.uci()))
        ucis.append(m.uci()); board.push(m)
    start, moves = list(ucis), []
    while len(moves) < plies and not board.is_game_over():
        legal = sorted(board.legal_moves, key=lambda x: x.uci())
        caps = [m for m in legal if board.is_capture(m)]
        m = rng.choice(caps) if caps and rng.random() < capture_bias else rng.choice(legal)
        moves.append(m.uci()); board.push(m)
    return {"gid": gid, "start": " ".join(start), "moves": " ".join(moves), "plies": len(start) + len(moves), "spent": [], "clock_after": []}


def test_auc_values_and_ties():
    assert C.auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == 1.0
    assert C.auc([0.9, 0.8, 0.2, 0.1], [0, 0, 1, 1]) == 0.0
    assert C.auc([0.5, 0.5, 0.5, 0.5], [0, 0, 1, 1]) == 0.5
    assert C.auc([0.1, 0.9, 0.5, 0.4], [0, 1, 1, 0]) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        C.auc([0.1, 0.2], [1, 1])


def test_move_rows_describe_the_moves_from_the_movers_side():
    # after 1.e4 d5: 2.exd5 Qxd5 3.Nc3 Nf6 4.Bb5+
    rec = {"start": "e2e4 d7d5", "moves": "e4d5 d8d5 b1c3 g8f6 f1b5", "plies": 7}
    rows = C.move_rows(rec)
    f = {n: i for i, n in enumerate(C.MOVE_FEATURES)}
    assert rows.shape == (5, len(C.MOVE_FEATURES))
    assert rows[0, f["pawn"]] == 1 and rows[0, f["capture"]] == 1 and rows[0, f["captured_value"]] == pytest.approx(1 / 9)
    assert rows[1, f["queen"]] == 1 and rows[1, f["capture"]] == 1 and rows[1, f["recapture"]] == 1
    assert rows[2, f["knight"]] == 1 and rows[2, f["capture"]] == 0
    assert rows[4, f["bishop"]] == 1 and rows[4, f["check"]] == 1
    assert rows[1, f["lands_attacked"]] == 0 and rows[2, f["lands_attacked"]] == 0       # Qxd5 is not attacked yet; Nc3 hits no attacked square
    assert C.move_rows(rec, plies=4).shape[0] == 2 and C.move_rows(rec, plies=2).shape[0] == 0


def test_forward_is_from_the_movers_side_and_castling_promotion_are_flagged():
    rec = {"start": "e2e4 e7e5 g1f3 b8c6 f1c4 g8f6", "moves": "e1g1 f6e4", "plies": 8}
    f = {n: i for i, n in enumerate(C.MOVE_FEATURES)}
    rows = C.move_rows(rec)
    assert rows[0, f["castle"]] == 1 and rows[0, f["king"]] == 1
    assert rows[1, f["knight"]] == 1 and rows[1, f["capture"]] == 1 and rows[1, f["captured_value"]] == pytest.approx(1 / 9)      # Nxe4
    white_forward = C.move_rows({"start": "", "moves": "e2e4", "plies": 1})[0, f["forward"]]
    black_forward = C.move_rows({"start": "e2e4", "moves": "e7e5", "plies": 2})[0, f["forward"]]
    assert white_forward > 0 and black_forward > 0                                         # both push forward: the sign is the mover's
    promo = C.move_rows({"start": "h2h4 g7g5 h4g5 a7a6", "moves": "g5g6 a6a5 g6h7 a5a4 h7g8q", "plies": 9})
    assert promo[4, f["promotion"]] == 1 and promo[4, f["capture"]] == 1


def test_game_vector_has_three_blocks_and_handles_short_games():
    rows = np.arange(8 * len(C.MOVE_FEATURES), dtype=np.float32).reshape(8, -1)
    v = C.game_vector(rows)
    n = len(C.MOVE_FEATURES)
    assert v.shape == (3 * n,) and np.allclose(v[:n], rows.mean(0)) and np.allclose(v[n:2 * n], rows[:4].mean(0)) and np.allclose(v[2 * n:], rows[4:].mean(0))
    assert C.game_vector(np.zeros((0, n), dtype=np.float32)).shape == (3 * n,)
    assert C.game_vector(rows[:1]).shape == (3 * n,)


def test_fit_predict_separates_a_shifted_class_and_folds_are_stable():
    rng = np.random.default_rng(0)
    X = np.concatenate([rng.normal(0, 1, (300, 5)), rng.normal(0.8, 1, (300, 5))]).astype(np.float32)
    y = np.array([0] * 300 + [1] * 300)
    s = C.fit_predict(X[::2], y[::2], X[1::2])
    assert C.auc(s, y[1::2]) > 0.75
    assert C.fold_of("a", 5, 0) == C.fold_of("a", 5, 0) and 0 <= C.fold_of("b", 5, 1) < 5


def test_out_of_fold_scores_never_train_on_the_start_they_score(monkeypatch):
    seen = []
    orig = C.fit_predict

    def spy(X_train, y_train, X_test, **kw):
        seen.append((len(X_train), len(X_test)))
        return orig(X_train, y_train, X_test, **kw)
    monkeypatch.setattr(C, "fit_predict", spy)
    rng = np.random.default_rng(1)
    X0, X1 = rng.normal(size=(100, 4)).astype(np.float32), rng.normal(size=(100, 4)).astype(np.float32)
    gids = [f"g{i}" for i in range(100)]
    s0, s1 = C.out_of_fold_scores(X0, X1, gids, folds=4, epochs=2)
    assert len(seen) == 4 and sum(t for _, t in seen) == 200 and all(a + t == 200 for a, t in seen)
    assert s0.shape == s1.shape == (100,)


def test_end_to_end_a_capture_biased_player_is_found_and_the_control_is_chance():
    rng = __import__("random").Random(3)
    human = [random_game(rng, f"g{i}@8", capture_bias=0.0) for i in range(300)]
    biased = [random_game(rng, f"g{i}@8", capture_bias=0.8) for i in range(300)]
    same = [random_game(rng, f"g{i}@8", capture_bias=0.0) for i in range(300)]
    res = C.run(human, {"biased": biased, "same": same}, folds=4, boot=50, epochs=30)
    assert res["starts"] == 300
    assert res["models"]["biased"]["linear"]["auc"] > 0.8 and res["models"]["biased"]["network"]["auc"] > 0.75
    assert 0.35 < res["models"]["same"]["linear"]["auc"] < 0.65 and 0.35 < res["null"]["linear"] < 0.65
    pair = next(p for p in res["pairs"] if p["kind"] == "linear")
    assert pair["diff"] > 0.2 and pair["ci"][0] > 0                                         # the biased set is easier to find than the same-policy one
    text = C.report(res)
    assert "biased" in text and "control: human against human" in text and "Paired differences" in text


def test_feature_table_cuts_generated_games_at_the_human_length_and_keeps_common_starts():
    rng = __import__("random").Random(4)
    human = [random_game(rng, f"g{i}@8", plies=20) for i in range(5)]
    gen = [random_game(rng, f"g{i}@8", plies=40) for i in range(4)]                           # the 5th start is missing
    gids, X_h, X = C.feature_table(human, {"m": gen})
    assert gids == [f"g{i}@8" for i in range(4)] and X_h.shape[0] == 4 and X["m"].shape == X_h.shape
    short = C.move_rows(gen[0], plies=human[0]["plies"])
    assert len(short) == human[0]["plies"] - 8


def test_feature_effects_name_the_feature_that_differs_and_the_report_lists_it():
    rng = np.random.default_rng(3)
    n, d = 300, len(C.FEATURE_NAMES)
    X_h, Xg = rng.normal(size=(n, d)).astype(np.float32), rng.normal(size=(n, d)).astype(np.float32)
    j = C.FEATURE_NAMES.index("whole stretch: check")
    Xg[:, j] -= 1.0                                                  # the generated games give fewer checks
    rows = C.feature_effects(X_h, Xg, top=3)
    name, a, mh, mg = rows[0]
    assert name == "whole stretch: check" and a < 0.3 and mg < mh and len(rows) == 3
    text = C.report({"starts": n, "models": {"m": {"linear": {"auc": 0.6, "ci": (0.5, 0.7)}, "network": {"auc": 0.6, "ci": (0.5, 0.7)}}},
                     "null": {"linear": 0.5, "network": 0.5}, "pairs": [], "features": {"m": rows}})
    assert "whole stretch: check" in text and "one feature at a time" in text
