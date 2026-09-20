import pytest
import numpy as np

from chessme.style import gamefeatures as G
from chessme.style import gamestats as S

NF = len(S.NAMES)


def synth(n=120, seed=0, signal=(0, 1), noise=0.3):
    """Players with a stable personal value on `signal` features (both halves = value + noise); all other features are pure noise."""
    rng = np.random.default_rng(seed)
    ratings = rng.uniform(1500, 2500, n)
    XA, XB = rng.normal(size=(n, NF)), rng.normal(size=(n, NF))
    for j in signal:
        trait = rng.normal(size=n)
        XA[:, j] = trait + noise * rng.normal(size=n)
        XB[:, j] = trait + noise * rng.normal(size=n)
    return XA, XB, ratings


def rows_for(XA, XB, ratings):
    return S.feature_reliability(XA, XB, ratings)


def test_stable_features_are_reliable_and_noise_is_not():
    XA, XB, R = synth()
    rows = rows_for(XA, XB, R)
    assert rows[0]["r_full"] > 0.85 and rows[1]["r_full"] > 0.85
    assert abs(rows[5]["r_half"]) < 0.3
    assert S.passes_gate(rows[0]) and not S.passes_gate(rows[5])


def test_missing_values_lower_coverage_and_fail_the_gate():
    XA, XB, R = synth()
    XA[: int(0.6 * len(XA)), 0] = np.nan
    row = rows_for(XA, XB, R)[0]
    assert row["coverage"] < 0.6 and not S.passes_gate(row)


def test_too_few_players_gives_nan_not_a_crash():
    XA, XB, R = synth(n=10)
    row = rows_for(XA, XB, R)[0]
    assert np.isnan(row["r_full"]) and not S.passes_gate(row)


def test_a_feature_that_only_tracks_rating_is_not_kept_when_net_reliability_is_low():
    XA, XB, R = synth()
    rng = np.random.default_rng(1)
    XA[:, 2] = (R - 2000) / 300 + 0.3 * rng.normal(size=len(R))
    XB[:, 2] = (R - 2000) / 300 + 0.3 * rng.normal(size=len(R))
    row = rows_for(XA, XB, R)[2]
    assert row["rating_corr"] > 0.9 and row["r_full"] > 0.9 and row["r_net"] < 0.3
    assert not S.passes_gate(row)


def test_identification_beats_chance_with_signal_and_matches_chance_without():
    XA, XB, R = synth(n=100, signal=(0, 1, 2, 3, 4), noise=0.2)
    good = S.identification(XA, XB, [0, 1, 2, 3, 4])
    assert good["top1"] > 0.8 and good["topk"] >= good["top1"] and good["chance"] == pytest.approx(0.01)
    bad = S.identification(XA, XB, [10, 11, 12])
    assert bad["top1"] < 0.15
    assert S.identification(XA, XB, [])["n_features"] == 0


def test_identification_treats_missing_values_as_average():
    XA, XB, R = synth(n=50, signal=(0, 1, 2))
    XA[0, 0] = np.nan
    res = S.identification(XA, XB, [0, 1, 2])
    assert np.isfinite(res["top1"])


def test_identification_by_family_reports_families_with_data_and_all():
    XA, XB, R = synth(n=60)
    rows = rows_for(XA, XB, R)
    out = S.identification_by_family(XA, XB, rows)
    assert "all" in out and set(out) <= {"opening", "shape", "clock", "repertoire", "all"}
    gated = S.identification_by_family(XA, XB, rows, gated_only=True)
    assert gated["all"]["n_features"] <= out["all"]["n_features"]


def test_factor_analysis_finds_a_shared_reliable_factor_on_held_out_players():
    rng = np.random.default_rng(3)
    n = 200
    R = rng.uniform(1500, 2500, n)
    factor = rng.normal(size=n)
    XA, XB = rng.normal(size=(n, NF)), rng.normal(size=(n, NF))
    for j in (0, 1, 2, 3):
        XA[:, j] = factor + 0.3 * rng.normal(size=n)
        XB[:, j] = factor + 0.3 * rng.normal(size=n)
    fa = S.factor_analysis(XA, XB, R, [0, 1, 2, 3, 10, 11, 12, 13], max_components=3)
    top = fa["components"][0]
    assert top["kept"] and top["reliability"] > 0.8 and top["congruence"] > 0.85
    assert {n for n, _ in top["top_loadings"][:4]} == {S.NAMES[j] for j in (0, 1, 2, 3)}
    assert fa["n_dev"] + fa["n_test"] == n


def test_factor_analysis_keeps_nothing_on_pure_noise():
    XA, XB, R = synth(n=200, signal=())
    fa = S.factor_analysis(XA, XB, R, list(range(10)), max_components=3)
    assert not any(c["kept"] for c in fa["components"])


def test_factor_analysis_is_deterministic_for_a_seed():
    XA, XB, R = synth(n=100)
    a = S.factor_analysis(XA, XB, R, list(range(8)), seed=5)
    b = S.factor_analysis(XA, XB, R, list(range(8)), seed=5)
    assert [c["reliability"] for c in a["components"]] == [c["reliability"] for c in b["components"]]


def test_render_lists_gate_identification_and_factors():
    XA, XB, R = synth(n=80)
    rows = rows_for(XA, XB, R)
    idx = [j for j, r in enumerate(rows) if r["coverage"] >= 0.6][:8]
    text = S.render(rows, S.identification_by_family(XA, XB, rows), S.identification_by_family(XA, XB, rows, True),
                    S.factor_analysis(XA, XB, R, idx, max_components=2), 80)
    assert "RELIABILITY" in text and "IDENTIFICATION" in text and "FACTORS" in text and "80 players" in text
    assert "KEEP" in text


def test_player_matrices_split_games_into_alternating_halves():
    nfeat = len(G.FEATURE_NAMES)
    arr = np.array([[float(i)] * nfeat for i in range(6)])          # game i has every feature equal to i
    metas = [{"color": "white" if i % 2 == 0 else "black", "eco": "C50"} for i in range(6)]
    ids, XT, XA, XB, R = S.player_matrices({"p": (1800, arr, metas), "q": (1600, arr + 10, metas)})
    assert ids == ["p", "q"] and R.tolist() == [1800.0, 1600.0]
    assert XA.shape == XB.shape == XT.shape == (2, NF)
    assert XA[0, 0] == np.mean([0, 2, 4]) and XB[0, 0] == np.mean([1, 3, 5]) and XT[0, 0] == 2.5
    assert XA[1, 0] == 12.0


def test_time_control_profile_is_share_per_half_and_identifies_single_tc_players():
    players = {}
    for i, tc in enumerate(["180+0", "300+0", "600+0", "180+2"] * 5):
        metas = [{"color": "white", "eco": "C50", "time_control": tc} for _ in range(6)]
        players[f"p{i}"] = (1800, np.zeros((6, len(G.FEATURE_NAMES))), metas)
    XA, XB, labels = S.time_control_profile(players)
    assert labels == ["180+0", "180+2", "300+0", "600+0"] and XA.sum(1).tolist() == [1.0] * 20
    assert XA[0].tolist() == XB[0].tolist() == [1.0, 0.0, 0.0, 0.0]
    # 4 time controls among 20 players (5 each): identical profiles are ties, so top-1 is 1/5, not 1
    assert S.identification(XA, XB, list(range(len(labels))))["top1"] == pytest.approx(0.2)


def test_identification_counts_identical_profiles_as_ties_not_hits():
    A = np.zeros((10, 3))
    res = S.identification(A, A.copy(), [0, 1, 2])
    assert abs(res["top1"] - 0.1) < 1e-9


def test_excluded_artefact_feature_never_counts():
    XA, XB, R = synth(signal=(G.ALL_NAMES.index("first_think_rel"),))
    j = S.NAMES.index("first_think_rel")
    rows = rows_for(XA, XB, R)
    assert rows[j]["coverage"] == 0.0 and not S.passes_gate(rows[j])
    assert S.identification_by_family(XA, XB, rows)["all"]["n_features"] == sum(r["coverage"] >= 0.6 for r in rows)


def test_rating_matched_identification_only_lets_close_ratings_compete():
    XA, XB, R = synth(n=60, signal=(0, 1, 2), noise=0.3)
    R = np.linspace(1500, 2500, 60)
    plain = S.identification(XA, XB, [0, 1, 2])
    matched = S.identification(XA, XB, [0, 1, 2], ratings=R, window=100)
    assert matched["chance"] > plain["chance"] and matched["top1"] >= plain["top1"] - 1e-9
    assert matched["chance"] == pytest.approx(np.mean([1 / (np.abs(R - r) <= 100).sum() for r in R]))
    # with a window wider than the whole rating range nothing is excluded
    assert S.identification(XA, XB, [0, 1, 2], ratings=R, window=10 ** 6)["top1"] == pytest.approx(plain["top1"])
