import json

import pytest

from chessme.analysis import leaks as LK


def game(key, eco, losses, color="white", phase="middlegame"):
    moves = [{"color": color, "loss": v, "phase": phase} for v in losses]
    moves.append({"color": "black" if color == "white" else "white", "loss": 999.0, "phase": phase})  # the opponent: must be ignored
    return key, {"player_color": color, "headers": {"ECO": eco}, "moves": moves}


def test_opening_key_falls_back_eco_then_name_then_unknown():
    assert LK.opening_key({"ECO": "B90"}) == "B90"
    assert LK.opening_key({"ECO": "", "Opening": "Sicilian"}) == "Sicilian"
    assert LK.opening_key({}) == "unknown"


def test_player_moves_keeps_only_the_players_colour_and_tags_the_bucket():
    results = [game("g1", "A00", [0.1, 0.2], color="black")]
    rows = LK.player_moves(results, by="opening")
    assert len(rows) == 2 and all(r["key"] == "A00" and r["game"] == "g1" for r in rows)
    rows = LK.player_moves(results, by="phase")
    assert all(r["key"] == "middlegame" for r in rows)


def test_split_halves_alternates_by_sorted_key():
    results = [game(f"g{i}", "A00", [0.1]) for i in (3, 1, 2, 4)]
    a, b = LK.split_halves(results)
    assert [k for k, _ in a] == ["g1", "g3"] and [k for k, _ in b] == ["g2", "g4"]


def test_bucket_stats_respects_min_n_and_computes_mean_and_total():
    rows = [{"key": "A", "loss": 0.2}, {"key": "A", "loss": 0.4}, {"key": "B", "loss": 0.5}]
    stats = LK.bucket_stats(rows, min_n=2)
    assert set(stats) == {"A"}
    assert stats["A"]["n"] == 2 and stats["A"]["mean_loss"] == pytest.approx(0.3) and stats["A"]["total_loss"] == pytest.approx(0.6)


def test_spearman_perfect_reversed_and_constant():
    assert LK.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert LK.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    assert LK.spearman([1, 1, 1], [1, 2, 3]) != LK.spearman([1, 1, 1], [1, 2, 3])  # NaN != NaN


def _consistent_openings():
    # opening -> loss is the same rank in both halves (A costliest .. D cheapest); games alternate into the two halves.
    return [game("g01", "A00", [0.40] * 3), game("g02", "A00", [0.40] * 3),
            game("g03", "B00", [0.30] * 3), game("g04", "B00", [0.30] * 3),
            game("g05", "C00", [0.20] * 3), game("g06", "C00", [0.20] * 3),
            game("g07", "D00", [0.10] * 3), game("g08", "D00", [0.10] * 3)]


def _flipped_openings():
    # same four openings, but the ranking is exactly reversed between the two halves (g01/03/05/07 vs g02/04/06/08).
    return [game("g01", "A00", [0.40] * 3), game("g02", "A00", [0.10] * 3),
            game("g03", "B00", [0.30] * 3), game("g04", "B00", [0.20] * 3),
            game("g05", "C00", [0.20] * 3), game("g06", "C00", [0.30] * 3),
            game("g07", "D00", [0.10] * 3), game("g08", "D00", [0.40] * 3)]


def test_stability_is_true_when_the_leak_ranking_agrees_across_halves():
    stab = LK.stability(_consistent_openings(), by="opening", min_n=4)
    assert stab["n_buckets_compared"] == 4
    assert stab["correlation"] == pytest.approx(1.0)
    assert stab["stable"] is True
    assert [k for k, _ in stab["table"]] == ["A00", "B00", "C00", "D00"]        # ranked by mean loss, highest first


def test_stability_is_false_when_the_leak_ranking_flips_between_halves():
    stab = LK.stability(_flipped_openings(), by="opening", min_n=4)
    assert stab["n_buckets_compared"] == 4
    assert stab["correlation"] == pytest.approx(-1.0)
    assert stab["stable"] is False


def test_stability_is_none_when_there_are_too_few_overlapping_buckets():
    results = [game("g1", "A00", [0.3, 0.3]), game("g2", "B00", [0.1, 0.1])]
    stab = LK.stability(results, by="opening", min_n=2)
    assert stab["stable"] is None


def test_stability_by_phase_is_computable_with_exactly_the_three_phases():
    # 'phase' only ever has 3 possible buckets, so the minimum-overlap requirement must not exceed 3.
    results = [game("g01", "A00", [0.40] * 3, phase="opening"), game("g02", "A00", [0.40] * 3, phase="opening"),
               game("g03", "A00", [0.25] * 3, phase="middlegame"), game("g04", "A00", [0.25] * 3, phase="middlegame"),
               game("g05", "A00", [0.10] * 3, phase="endgame"), game("g06", "A00", [0.10] * 3, phase="endgame")]
    stab = LK.stability(results, by="phase", min_n=4)
    assert stab["n_buckets_compared"] == 3
    assert stab["stable"] is True


def test_render_reports_the_ranking_and_the_verdict():
    stab = LK.stability(_consistent_openings(), by="opening", min_n=4)
    text = LK.render(stab)
    assert "A00" in text and "D00" in text
    assert "stable enough to build on" in text


def test_load_results_reads_the_analyse_output_directory(tmp_path):
    d = tmp_path / "games"
    d.mkdir()
    (d / "00001-a.json").write_text(json.dumps({"player_color": "white", "headers": {"ECO": "A00"}, "moves": []}))
    (d / "00002-b.json").write_text(json.dumps({"player_color": "black", "headers": {"ECO": "B00"}, "moves": []}))
    results = LK.load_results(tmp_path)
    assert [k for k, _ in results] == ["00001-a", "00002-b"]
