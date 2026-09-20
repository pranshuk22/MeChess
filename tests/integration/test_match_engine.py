"""Integration: real engine binaries playing real matches through the UCI client and worker pool."""
import chess
import chess.pgn
import pytest

from chessme import openings, sprt
from chessme.match import Adjudication, EngineSpec, SearchLimit, run_match
from chessme.uci_client import EngineError
from tests.integration.uci_helper import run_uci

pytestmark = pytest.mark.integration

LIMIT = SearchLimit(nodes=1500)


def specs(engine_path, crippled_params):
    good = EngineSpec.make("normal", str(engine_path))
    bad = EngineSpec.make("no-queen-value", str(engine_path), {"EvalFile": str(crippled_params)})
    return good, bad


def test_engine_with_sane_evaluation_beats_one_that_gives_its_queen_away(engine_path, crippled_params, tmp_path):
    good, bad = specs(engine_path, crippled_params)
    fens = openings.random_openings(6, plies=6, seed=3)
    res = run_match(good, bad, fens, LIMIT, concurrency=2, pgn_path=tmp_path / "m.pgn")
    n = res.wins + res.draws + res.losses
    assert n == 12 and res.pairs == 6
    assert not res.errors, res.errors
    assert (res.wins + 0.5 * res.draws) / n > 0.75
    assert sprt.elo_estimate(res.penta)[0] > 100

    # every game in the PGN replays legally and the colours alternate per opening
    games = []
    with open(tmp_path / "m.pgn") as f:
        while g := chess.pgn.read_game(f):
            games.append(g)
    assert len(games) == 12
    for g in games:
        assert not g.errors
    assert {g.headers["White"] for g in games} == {"normal", "no-queen-value"}


def test_sprt_stops_early_on_a_clear_difference(engine_path, crippled_params):
    good, bad = specs(engine_path, crippled_params)
    fens = openings.random_openings(60, plies=6, seed=8)
    res = run_match(good, bad, fens, SearchLimit(nodes=800), concurrency=2, sprt=(0, 30))
    assert res.status == "H1"
    assert res.pairs < 60
    assert res.llr >= sprt.bounds()[1]


def test_identical_engines_are_not_declared_different(engine_path):
    a = EngineSpec.make("a", str(engine_path))
    b = EngineSpec.make("b", str(engine_path))
    fens = openings.random_openings(6, plies=6, seed=4)
    res = run_match(a, b, fens, LIMIT, concurrency=2)
    # deterministic engines with identical settings: every pair is a wash
    assert res.wins == res.losses
    assert res.penta[0] == res.penta[4] == 0


def test_match_is_reproducible(engine_path, crippled_params):
    good, bad = specs(engine_path, crippled_params)
    fens = openings.random_openings(3, plies=6, seed=6)
    first = run_match(good, bad, fens, LIMIT, concurrency=1)
    second = run_match(good, bad, fens, LIMIT, concurrency=1)
    assert [g.moves for g in first.games] == [g.moves for g in second.games]
    assert first.penta == second.penta


def test_concurrency_does_not_change_results(engine_path, crippled_params):
    good, bad = specs(engine_path, crippled_params)
    fens = openings.random_openings(4, plies=6, seed=9)
    serial = run_match(good, bad, fens, LIMIT, concurrency=1)
    parallel = run_match(good, bad, fens, LIMIT, concurrency=3)
    key = lambda r: sorted((g.start_fen, g.white, tuple(g.moves)) for g in r.games)
    assert key(serial) == key(parallel)


def test_adjudication_shortens_lopsided_games(engine_path, crippled_params):
    good, bad = specs(engine_path, crippled_params)
    fens = openings.random_openings(2, plies=6, seed=2)
    long_run = run_match(good, bad, fens, LIMIT, Adjudication(resign_cp=0, draw_cp=0))
    adjudicated = run_match(good, bad, fens, LIMIT, Adjudication(resign_cp=800, resign_plies=4, draw_cp=0))
    assert sum(len(g.moves) for g in adjudicated.games) < sum(len(g.moves) for g in long_run.games)
    # adjudication must not change who is winning: the sane engine still scores as well as without it
    score = lambda r: r.wins + 0.5 * r.draws
    assert score(adjudicated) >= score(long_run) - 1


def test_an_engine_that_cannot_start_is_a_loud_configuration_error(engine_path):
    broken = EngineSpec.make("broken", "/no/such/engine")
    good = EngineSpec.make("good", str(engine_path))
    with pytest.raises(EngineError, match="cannot start"):
        run_match(good, broken, openings.random_openings(1, 4, 1), LIMIT, concurrency=1)


def test_evalfile_option_changes_evaluation_and_bad_files_are_reported(engine_path, crippled_params):
    base = run_uci(engine_path, ["position fen 4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "eval"])
    cut = run_uci(engine_path, [f"setoption name EvalFile value {crippled_params}",
                                "position fen 4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "eval"])
    value = lambda out: int(out.split("eval cp ")[1].split()[0])
    assert value(base) > 700 and value(cut) < 200
    assert "loaded evaluation parameters" in cut

    bad = run_uci(engine_path, ["setoption name EvalFile value /no/such/file.txt",
                                "position fen 4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "eval"])
    assert "EvalFile error" in bad and value(bad) == value(base)  # error reported, engine keeps its old parameters

    reset = run_uci(engine_path, [f"setoption name EvalFile value {crippled_params}", "setoption name EvalFile value",
                                  "position fen 4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "eval"])
    assert value(reset) == value(base)


def test_filter_balanced_keeps_only_roughly_equal_openings(engine_path):
    fens = openings.random_openings(12, plies=6, seed=5)
    kept = openings.filter_balanced(str(engine_path), fens, depth=4, max_cp=60)
    assert set(kept) <= set(fens)
    assert 0 < len(kept) <= len(fens)
    for fen in kept:
        out = run_uci(engine_path, [f"position fen {fen}", "go depth 4"])
        assert abs(int(out.rsplit("score cp ", 1)[1].split()[0])) <= 60
