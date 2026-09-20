"""Integration: MultiPV output of the real engine, checked with python-chess and independent searches."""
import random
import re

import chess
import pytest

from tests.integration.uci_helper import run_uci

pytestmark = pytest.mark.integration

LINE = re.compile(r"^info depth (\d+) multipv (\d+) score (cp|mate) (-?\d+) .*? pv (\S+)", re.M)


def multipv_lines(engine_path, fen, n, depth):
    """{line number: (move, score in cp)} of the deepest finished iteration."""
    out = run_uci(engine_path, [f"setoption name MultiPV value {n}", f"position fen {fen}", f"go depth {depth}"])
    rows = [(int(d), int(k), kind, int(v), mv) for d, k, kind, v, mv in LINE.findall(out)]
    deepest = max(r[0] for r in rows)
    lines = {}
    for d, k, kind, v, mv in rows:
        if d == deepest:
            lines[k] = (mv, v if kind == "cp" else (100000 - abs(v)) * (1 if v > 0 else -1))
    return lines, out


def random_position(rng):
    b = chess.Board()
    for _ in range(rng.randint(8, 50)):
        moves = list(b.legal_moves)
        if not moves:
            break
        b.push(rng.choice(moves))
    return b


def test_lines_are_legal_distinct_and_ordered(engine_path):
    rng = random.Random(4)
    checked = 0
    while checked < 12:
        b = random_position(rng)
        if b.is_game_over() or b.legal_moves.count() < 4:
            continue
        lines, _ = multipv_lines(engine_path, b.fen(), 4, 5)
        assert sorted(lines) == [1, 2, 3, 4], b.fen()
        moves = [lines[k][0] for k in sorted(lines)]
        assert len(set(moves)) == 4 and all(chess.Move.from_uci(m) in b.legal_moves for m in moves)
        scores = [lines[k][1] for k in sorted(lines)]
        assert scores == sorted(scores, reverse=True), (b.fen(), scores)
        checked += 1


def test_first_line_is_the_normal_best_move(engine_path):
    rng, agree, total = random.Random(8), 0, 0
    while total < 15:
        b = random_position(rng)
        if b.is_game_over():
            continue
        lines, _ = multipv_lines(engine_path, b.fen(), 3, 6)
        single = run_uci(engine_path, [f"position fen {b.fen()}", "go depth 6"])
        best = re.search(r"^bestmove (\S+)", single, re.M).group(1)
        agree += lines[1][0] == best
        total += 1
    assert agree >= 12  # tiny differences (transposition-table state) can pick a near-equal move, but rarely


def test_each_lines_score_matches_an_independent_search_of_that_move(engine_path):
    """The k-th line's score must be what you get by playing that move and searching the reply position."""
    rng, checked = random.Random(3), 0
    while checked < 6:
        b = random_position(rng)
        if b.is_game_over() or b.legal_moves.count() < 4:
            continue
        lines, _ = multipv_lines(engine_path, b.fen(), 4, 5)
        for k, (move, score) in lines.items():
            child = b.copy()
            child.push_uci(move)
            if child.is_game_over():
                continue
            out = run_uci(engine_path, [f"position fen {child.fen()}", "go depth 4"])
            kind, val = re.findall(r"score (cp|mate) (-?\d+)", out)[-1]
            if kind == "mate":
                continue
            assert abs(score - (-int(val))) < 150, (b.fen(), move, score, -int(val))  # different depths / reductions: loose
        checked += 1


def test_a_blunder_scores_far_below_the_best_move(engine_path):
    lines, _ = multipv_lines(engine_path, "4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1", 10, 5)
    assert lines[1][0] == "d1d5" and lines[1][1] - lines[max(lines)][1] > 300


def test_more_lines_than_legal_moves_is_fine(engine_path):
    lines, out = multipv_lines(engine_path, "7k/8/8/8/8/8/5q2/6K1 w - - 0 1", 20, 4)
    assert sorted(lines) == [1, 2] and "bestmove" in out
