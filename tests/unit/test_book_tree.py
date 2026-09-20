import chess
import pytest

from chessme.book import sanity
from chessme.book.keys import book_key
from chessme.book.sanity import cp_of, sanity_filter
from chessme.book.tree import BookTree, move_id
from chessme.dataset.weights import Weighter
from chessme.uci_client import GoResult
from tests.samples import make_row

CFG = {"filters": {"min_rating": {"lichess": 1400}, "recency": {"half_life_days": 365, "min_weight": 0.1},
                   "time_class_weights": {"blitz": 1.0, "bullet": {"full_until_ply": 6, "late_weight": 0.1}}}}


def tree_from(rows, max_ply=30, cfg=CFG):
    w = Weighter(cfg, rows)
    t = BookTree(max_ply)
    for r in rows:
        t.add_game(r, w)
    return t


def game(moves, color="white", result="win", gid=None, **kw):
    return make_row(game_id=gid or f"{moves}-{color}-{result}", moves=moves, color=color, my_result=result, **kw)


START = book_key(chess.Board())
E4 = move_id(chess.Move.from_uci("e2e4"))
D4 = move_id(chess.Move.from_uci("d2d4"))


def test_records_only_my_moves_as_book_moves():
    t = tree_from([game("e4 e5 Nf3 Nc6")])
    assert START in t.mine and t.mine[START].games == 1 and set(t.mine[START].moves) == {E4}
    # my second move (Nf3) is recorded at the position after 1.e4 e5
    b = chess.Board()
    b.push_san("e4"); b.push_san("e5")
    assert set(t.mine[book_key(b)].moves) == {move_id(chess.Move.from_uci("g1f3"))}
    # the opponent's replies are counted separately
    b1 = chess.Board(); b1.push_san("e4")
    assert t.opp[book_key(b1)]["e7e5"] == 1
    assert book_key(b1) not in t.mine


def test_playing_black_records_blacks_moves():
    t = tree_from([game("e4 c5 Nf3 d6", color="black")])
    b = chess.Board(); b.push_san("e4")
    assert set(t.mine[book_key(b)].moves) == {move_id(chess.Move.from_uci("c7c5"))}
    assert START not in t.mine and t.opp[START]["e2e4"] == 1


def test_counts_and_weights_accumulate_across_games():
    rows = [game("e4 e5", gid="a"), game("e4 c5", gid="b"), game("d4 d5", gid="c")]
    t = tree_from(rows)
    node = t.mine[START]
    assert node.games == 3
    assert node.moves[E4].games == 2 and node.moves[D4].games == 1
    assert node.moves[E4].weight == pytest.approx(2 * node.moves[D4].weight)


def test_transpositions_merge_into_one_node():
    rows = [game("Nf3 Nf6 Nc3 Nc6 e4", gid="a"), game("Nc3 Nc6 Nf3 Nf6 e4", gid="b")]
    t = tree_from(rows)
    b = chess.Board()
    for m in ("Nf3", "Nf6", "Nc3", "Nc6"):
        b.push_san(m)
    node = t.mine[book_key(b)]
    assert node.games == 2 and node.moves[E4].games == 2


def test_result_scores_are_recorded_per_move():
    rows = [game("e4 e5", result="win", gid="a"), game("e4 c5", result="loss", gid="b"), game("e4 c6", result="draw", gid="c")]
    stat = tree_from(rows).mine[START].moves[E4]
    assert stat.games == 3 and stat.score_sum == pytest.approx(1.5)


def test_weights_follow_recency_and_time_control():
    old = game("d4 d5", gid="old", played_at="2022-01-01T00:00:00+00:00")
    new = game("e4 e5", gid="new", played_at="2024-01-01T00:00:00+00:00")
    node = tree_from([old, new]).mine[START]
    assert node.moves[E4].weight > 2 * node.moves[D4].weight  # two years older => much lower weight (floored at 0.1)
    # bullet: plies 0-5 full weight, from ply 6 on 0.1 (see CFG)
    moves = "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6"
    t = tree_from([game(moves, time_class="bullet", gid="bu")])
    weights = {}
    b = chess.Board()
    for ply, san in enumerate(moves.split()):
        move = b.parse_san(san)
        node = t.mine.get(book_key(b))
        if node:
            weights[ply] = node.moves[move_id(move)].weight
        b.push(move)
    assert weights == {0: pytest.approx(1.0), 2: pytest.approx(1.0), 4: pytest.approx(1.0), 6: pytest.approx(0.1)}


def test_filtered_games_are_ignored():
    rows = [game("e4 e5", my_rating=1000, gid="low"), game("e4 e5", usable=False, gid="bad"),
            game("e4 e5", time_class="correspondence", gid="corr")]
    w = Weighter({"filters": {**CFG["filters"], "time_class_weights": {"correspondence": 0.0, "blitz": 1.0}}}, rows)
    t = BookTree()
    assert [t.add_game(r, w) for r in rows] == [False, False, False]
    assert t.mine == {} and t.games_used == 0


def test_max_ply_limits_how_deep_we_record():
    t = tree_from([game("e4 e5 Nf3 Nc6 Bb5 a6")], max_ply=2)
    assert len(t.mine) == 1 and START in t.mine  # only ply 0 is a move of mine within 2 plies


def test_unreplayable_game_keeps_its_valid_prefix():
    t = tree_from([game("e4 e5 Qh9 Nc6 Nf3")])
    # 1.e4 is recorded; the position where "Qh9" fails is not, and nothing after it is processed
    assert list(t.mine) == [START] and t.mine[START].games == 1


def test_habit_filters():
    rows = [game("e4 e5", gid=f"e{i}") for i in range(6)] + [game("d4 d5", gid="d1"), game("d4 d5", gid="d2")] + \
           [game("c4 e5", gid="c1")]
    t = tree_from(rows)
    entries, dropped = t.entries(min_games=2, min_position_games=3, min_share=0.05)
    ucis = {e.uci() for e in entries if e.key == START}
    assert ucis == {"e2e4", "d2d4"}  # c4 was played once: below min_games
    assert dropped["moves below min_games"] >= 1

    entries, _ = t.entries(min_games=1, min_position_games=3, min_share=0.2)
    assert {e.uci() for e in entries if e.key == START} == {"e2e4", "d2d4"}  # c4 is 1/9 of moves: below 20%

    entries, dropped = t.entries(min_games=1, min_position_games=10, min_share=0.0)
    assert not entries and dropped["positions below min_position_games"] > 0


def test_entries_carry_games_and_score():
    rows = [game("e4 e5", result="win", gid="1"), game("e4 e5", result="win", gid="2"),
            game("e4 e5", result="loss", gid="3"), game("e4 e5", result="draw", gid="4")]
    entries, _ = tree_from(rows).entries(min_games=1, min_position_games=1, min_share=0)
    e = next(x for x in entries if x.key == START)
    assert e.games == 4 and e.score_permille == 625  # (1+1+0+0.5)/4
    assert e.weight > 0


def test_promotion_moves_keep_their_piece():
    moves = "a4 b5 axb5 a6 bxa6 Nf6 a7 e6 axb8=Q"
    board = chess.Board()
    for san in moves.split():
        board.push_san(san)  # the sample game itself must be legal
    t = tree_from([game(moves, gid="p")])
    promos = [mid for node in t.mine.values() for mid in node.moves if mid[2]]
    assert promos == [(chess.A7, chess.B8, chess.QUEEN)]
    entries, _ = t.entries(min_games=1, min_position_games=1, min_share=0)
    assert "a7b8q" in {e.uci() for e in entries}


# ---- engine sanity check -------------------------------------------------------------------------------------

class StubEngine:
    """Reports scripted centipawn scores: parent position and each child, from the side-to-move's view."""

    def __init__(self, parent_score, children):
        self.parent, self.children, self.calls = parent_score, children, 0

    def new_game(self):
        pass

    def go(self, fen, moves=(), *, depth=None, **kw):
        self.calls += 1
        if not moves:
            return GoResult("e2e4", "cp", self.parent)
        return GoResult("e7e5", *self.children[moves[0]])


def entries_for(rows):
    t = tree_from(rows)
    entries, _ = t.entries(min_games=1, min_position_games=1, min_share=0)
    return t, [e for e in entries if e.key == START]


def test_cp_conversion_of_mate_scores():
    assert cp_of("cp", 35) == 35 and cp_of(None, None) is None
    assert cp_of("mate", 2) > 9900 and cp_of("mate", -2) < -9900 and cp_of("mate", 1) > cp_of("mate", 4)


def test_sanity_drops_moves_that_lose_too_much():
    t, entries = entries_for([game("e4 e5", gid="1"), game("d4 d5", gid="2"), game("f3 e5", gid="3")])
    # scores after each move are from the opponent's view, so a good move for me is a negative child score
    engine = StubEngine(parent_score=30, children={"e2e4": ("cp", -25), "d2d4": ("cp", -20), "f2f3": ("cp", 90)})
    kept, dropped = sanity_filter(t, entries, engine, max_cp_loss=80)
    assert {e.uci() for e in kept} == {"e2e4", "d2d4"}
    assert [d.move for d in dropped] == ["f2f3"] and dropped[0].loss_cp == 30 - (-90)


def test_sanity_threshold_is_inclusive_of_small_losses():
    t, entries = entries_for([game("e4 e5", gid="1")])
    engine = StubEngine(30, {"e2e4": ("cp", 45)})  # my score after the move: -45, i.e. 75 cp below best: within 80
    kept, dropped = sanity_filter(t, entries, engine, max_cp_loss=80)
    assert len(kept) == 1 and not dropped


def test_sanity_treats_a_mate_against_me_as_a_blunder():
    t, entries = entries_for([game("f3 e5", gid="1")])
    engine = StubEngine(20, {"f2f3": ("mate", 2)})  # opponent mates in 2 after my move
    kept, dropped = sanity_filter(t, entries, engine, max_cp_loss=80)
    assert not kept and len(dropped) == 1


def test_sanity_leaves_positions_alone_when_the_engine_gives_no_score():
    t, entries = entries_for([game("e4 e5", gid="1")])

    class Silent(StubEngine):
        def go(self, fen, moves=(), **kw):
            return GoResult("e2e4")

    kept, dropped = sanity_filter(t, entries, Silent(0, {}), max_cp_loss=10)
    assert len(kept) == 1 and not dropped
