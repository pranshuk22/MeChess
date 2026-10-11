import io
import random
from collections import Counter

import chess
import chess.pgn
import pytest

from chessme.humanlike import testset as T
from tests.unit.test_explorer_rangescan import make_dump

# a legal 12-ply opening line used by most tests
LINE = "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7 f1e1 b7b5".split()


def make_game(moves=LINE, clocks=None, base=180, inc=0, site="abcd1234", **headers):
    """A python-chess game with [%clk] comments. `clocks[i]` is the clock of the mover AFTER ply i (seconds)."""
    g = chess.pgn.Game()
    h = {"Event": "Rated Blitz game", "Site": f"https://lichess.org/{site}", "White": "w", "Black": "b", "Result": "1-0",
         "WhiteElo": "1700", "BlackElo": "1650", "TimeControl": f"{base}+{inc}", "Termination": "Normal"}
    h.update(headers)
    for k, v in h.items():
        if v is None:
            g.headers.pop(k, None)
        else:
            g.headers[k] = v
    clocks = clocks if clocks is not None else [base] * len(moves)
    node = g
    for uci, c in zip(moves, clocks):
        node = node.add_variation(chess.Move.from_uci(uci))
        if c is not None:
            node.set_clock(float(c))
    return g


def positions_of(game, **kw):
    kw.setdefault("per_game", 100)
    return T.game_positions(game, **kw)


def test_every_field_of_a_position_is_computed_from_the_game():
    # base 180 + 2 s increment; each side's clock after its moves: white 179, 178, ... black 181 (gained time), 183, ...
    clocks = [179, 181, 178, 183, 175, 185, 172, 187, 170, 189, 168, 191]
    ps = positions_of(make_game(clocks=clocks, base=180, inc=2))
    assert len(ps) == 12
    first, second, third = ps[0], ps[1], ps[2]
    assert (first.ply, first.played, first.me, first.opp, first.base, first.inc) == (0, "e2e4", 1700, 1650, 180, 2)
    assert first.clock == 180 and first.opp_clock == 180 and first.spent == pytest.approx(180 + 2 - 179)
    assert (second.me, second.opp) == (1650, 1700)                         # the mover's rating comes first
    assert second.clock == 180 and second.opp_clock == 179 and second.spent == pytest.approx(180 + 2 - 181)
    assert third.clock == 179 and third.opp_clock == 181 and third.spent == pytest.approx(179 + 2 - 178)
    assert third.moves == "e2e4 e7e5" and third.ply == 2 and third.result == "1-0"
    board = chess.Board()
    for p in ps:                                                           # the FEN and the move list agree at every position
        assert p.fen == board.fen() and p.n_legal == board.legal_moves.count()
        board.push_uci(p.played)


def test_after_low_turns_on_at_the_first_position_with_under_30_s_and_stays_on_for_that_player_only():
    # white's clock AFTER its moves is 170, 100, 40, 25, 24, 23, so BEFORE its moves it is 180, 170, 100, 40, 25, 24:
    # the first position with under 30 s is white's fifth move
    clocks = [170, 170, 100, 150, 40, 140, 25, 130, 24, 120, 23, 110]
    ps = positions_of(make_game(clocks=clocks, base=180, inc=0))
    white = [p for p in ps if p.ply % 2 == 0]
    black = [p for p in ps if p.ply % 2 == 1]
    assert [p.clock for p in white] == [180, 170, 100, 40, 25, 24]
    assert [p.after_low for p in white] == [False, False, False, False, True, True]
    assert not any(p.after_low for p in black)                              # black never fell under 30 s


def test_the_flag_stays_on_after_the_clock_recovers():
    """Allie drops the positions AFTER the first time a player is under 30 s, even if the clock is later above 30 s again."""
    # white's clock before its moves: 180, 175, 25, 90, 80, 70
    g = make_game(clocks=[175, 175, 25, 175, 90, 175, 80, 175, 70, 175, 60, 175], base=180)
    ps = [p for p in positions_of(g) if p.ply % 2 == 0]
    assert [p.clock for p in ps] == [180, 175, 25, 90, 80, 70]
    assert [p.after_low for p in ps] == [False, False, True, True, True, True]    # 90 s, 80 s, 70 s are above 30 but the flag is on


@pytest.mark.parametrize("changes", [
    {"Event": "Casual Blitz game"},                       # unrated
    {"TimeControl": "60+0"},                              # bullet
    {"TimeControl": "-"},                                 # correspondence
    {"TimeControl": "600+0"},                             # rapid
    {"Variant": "Chess960"},
    {"Termination": "Abandoned"},
    {"Termination": "Rules infraction"},
    {"Result": "*"},
    {"WhiteTitle": "BOT"},
    {"BlackTitle": "BOT"},
    {"WhiteElo": None},
    {"BlackElo": "?"},
])
def test_games_that_should_not_be_in_the_set_are_left_out(changes):
    assert positions_of(make_game(**changes)) == []


def test_bots_can_be_allowed_and_a_title_other_than_bot_is_fine():
    assert positions_of(make_game(WhiteTitle="BOT"), allow_bots=True)
    assert positions_of(make_game(WhiteTitle="GM"))


def test_a_game_without_clocks_is_dropped_unless_clocks_are_not_required():
    g = make_game(clocks=[None] * len(LINE))
    assert positions_of(g) == []
    ps = positions_of(g, require_clocks=False)
    assert len(ps) == len(LINE) and all(p.clock == 180 for p in ps[:1]) and ps[0].spent != ps[0].spent    # spent is NaN


def test_sampling_is_deterministic_per_game_seed_and_independent_of_the_clocks():
    a = T.game_positions(make_game(), per_game=4, seed=7)
    b = T.game_positions(make_game(clocks=[60] * len(LINE)), per_game=4, seed=7)
    assert [p.ply for p in a] == [p.ply for p in b] and len(a) == 4          # the same plies whatever the clock says
    assert [p.ply for p in a] == sorted(p.ply for p in a)
    c = T.game_positions(make_game(), per_game=4, seed=8)
    d = T.game_positions(make_game(site="zzzz9999"), per_game=4, seed=7)
    assert [p.ply for p in a] != [p.ply for p in c] or [p.ply for p in a] != [p.ply for p in d]


def test_sampling_covers_all_plies_uniformly():
    """No filter hides the opening or the late game: over many games every ply index is drawn about equally often."""
    counts = Counter()
    for i in range(3000):
        for p in T.game_positions(make_game(site=f"g{i:07d}"), per_game=2, seed=1):
            counts[p.ply] += 1
    assert set(counts) == set(range(len(LINE)))
    expected = 3000 * 2 / len(LINE)
    assert all(0.8 * expected < c < 1.2 * expected for c in counts.values())


def test_a_stream_with_several_games_and_the_window_edges():
    text = "\n\n".join(str(make_game(site=f"game{i:04d}")) for i in range(5)) + "\n\n"
    all_ids = {p.gid for p in T.parse_text(text, per_game=2)}
    assert all_ids == {f"game{i:04d}" for i in range(5)}
    inner = {p.gid for p in T.parse_text(text, per_game=2, skip_edges=True)}
    assert inner == {f"game{i:04d}" for i in range(1, 4)}                    # first and last are fragments of a window


def test_round_trip_and_the_manifest_hash(tmp_path):
    ps = positions_of(make_game())
    m1 = T.write_testset(tmp_path / "t.jsonl.gz", ps, {"source": "unit test"})
    assert T.read_testset(tmp_path / "t.jsonl.gz") == ps
    assert m1["positions"] == len(ps) and m1["source"] == "unit test" and (tmp_path / "t.jsonl.gz.manifest.json").exists()
    m2 = T.write_testset(tmp_path / "u.jsonl.gz", ps)
    assert m1["sha256"] == m2["sha256"]                                       # the same content has the same hash ...
    m3 = T.write_testset(tmp_path / "v.jsonl.gz", ps[:-1])
    assert m3["sha256"] != m1["sha256"]                                       # ... and any change shows


def test_to_items_carry_the_clock_and_history_for_the_scorers():
    ps = positions_of(make_game(clocks=[170] * len(LINE)))
    items = T.to_items(ps)
    it = items[3]
    assert it.fen == ps[3].fen and it.played == ps[3].played and it.moves == tuple(LINE[:3]) and it.has_history
    assert it.clock == ps[3].clock and it.game == "abcd1234" and (it.base, it.inc) == (180, 0)


def test_positions_are_read_from_byte_windows_of_a_compressed_dump(tmp_path):
    """Whole path: a multi-frame .zst, cut into windows, decoded, and sampled; the games cut by a window edge are not used."""
    games = [str(make_game(site=f"win{i:05d}")) + "\n\n" for i in range(12)]
    buf, _ = make_dump(["".join(games[i:i + 3]) for i in range(0, 12, 3)])
    dump = tmp_path / "month.pgn.zst"
    dump.write_bytes(buf)
    got = list(T.iter_window_positions(str(dump), 4, [0, 1, 2, 3], per_game=2))
    ids = {p.gid for p in got}
    assert ids and ids <= {f"win{i:05d}" for i in range(12)}
    assert len(got) == 2 * len(ids)                                           # two positions per kept game
    assert len(ids) < 12                                                      # the first and last game of every window were dropped


def test_late_is_the_game_level_rule_that_defines_the_published_test_set():
    """Allie / Maia-3: a game is cut at the first position where EITHER player has under 30 s; that position is kept, later ones are not."""
    # white's clock after ply 2 is 25 s: from the next position (ply 3, black to move) white is the OPPONENT with under 30 s, so ply 3 is the first
    # event; it is kept and everything after it is late (even though white's clock is back above 30 s from ply 4 on)
    g = make_game(clocks=[175, 175, 25, 175, 90, 175, 80, 175, 70, 175, 60, 175], base=180)
    ps = positions_of(g)
    assert [(p.clock, p.opp_clock) for p in ps if p.ply == 3] == [(175, 25)]
    assert [p.ply for p in ps if not p.late] == [0, 1, 2, 3]
    assert all(p.late for p in ps if p.ply > 3)
    # the mover's own low clock is an event as well: black falls to 20 s after ply 3, which white sees as opp_clock at ply 4 ... so the same rule
    g2 = make_game(clocks=[175, 175, 170, 20, 160, 100, 150, 90, 140, 80, 130, 70], base=180)
    ps2 = positions_of(g2)
    first_event = min(p.ply for p in ps2 if p.clock < 30 or p.opp_clock < 30)
    assert first_event == 4 and [p.ply for p in ps2 if not p.late] == list(range(first_event + 1))


def test_a_game_that_never_goes_below_30_s_is_never_late():
    assert not any(p.late for p in positions_of(make_game(clocks=[170] * len(LINE))))


def test_a_subset_can_be_read_without_loading_the_rest(tmp_path):
    ps = positions_of(make_game())
    T.write_testset(tmp_path / "t.jsonl.gz", ps)
    assert T.read_testset(tmp_path / "t.jsonl.gz", [0, 3, 7]) == [ps[0], ps[3], ps[7]]
    assert T.read_testset(tmp_path / "t.jsonl.gz", []) == []
    assert T.read_testset(tmp_path / "t.jsonl.gz", range(len(ps))) == ps


# ---- balanced sets built from many windows, in parallel -------------------------------------------------------------------

def rated_dump(tmp_path, n_per_level=60, levels=(800, 1700, 2300)):
    games = []
    for k, lvl in enumerate(levels):
        for i in range(n_per_level):
            games.append(str(make_game(site=f"l{lvl}g{i:04d}", WhiteElo=str(lvl), BlackElo=str(lvl - 50),
                                       clocks=[170 - 2 * (j // 2) for j in range(len(LINE))])) + "\n\n")
    random.Random(0).shuffle(games)
    size = len(games) // 6
    buf, _ = make_dump(["".join(games[i:i + size]) for i in range(0, len(games), size)])
    dump = tmp_path / "month.pgn.zst"
    dump.write_bytes(buf)
    return dump


def test_the_cap_thins_crowded_rating_bins_only(tmp_path):
    dump = rated_dump(tmp_path)
    m = T.build_balanced(str(dump), 6, list(range(6)), tmp_path / "bal.jsonl.gz", cap_per_bin=40, per_game=3, log=lambda *a: None)
    before, after = m["rating_bins_before"], m["rating_bins_after"]
    assert len(before) == 3 and any(after[b] < before[b] for b in before)            # three rating levels, and the cap really removed positions
    for b, n in before.items():
        assert after[b] <= 1.6 * 40 + 5                                          # thinned towards the cap (a hash threshold: approximate)
        if n <= 40:
            assert after[b] == n                                                 # a bin under the cap is left whole
    assert sum(after.values()) == m["positions"] and m["cap_per_bin"] == 40 and m["windows"] == list(range(6))


def test_no_cap_keeps_everything_and_the_shards_are_removed(tmp_path):
    dump = rated_dump(tmp_path)
    m = T.build_balanced(str(dump), 6, list(range(6)), tmp_path / "all.jsonl.gz", per_game=3, log=lambda *a: None)
    assert m["rating_bins_before"] == m["rating_bins_after"]
    assert not (tmp_path / "all.jsonl.gz.shards").exists()
    T.build_balanced(str(dump), 6, [0, 1], tmp_path / "k.jsonl.gz", per_game=3, keep_shards=True, log=lambda *a: None)
    assert len(list((tmp_path / "k.jsonl.gz.shards").glob("w*.jsonl.gz"))) == 2


def test_the_result_is_identical_for_any_number_of_workers(tmp_path):
    """Regression guard for parallel building: the keep rule is a hash of the position, never of the order or the process."""
    dump = rated_dump(tmp_path)
    one = T.build_balanced(str(dump), 6, list(range(6)), tmp_path / "w1.jsonl.gz", workers=1, cap_per_bin=40, per_game=3, log=lambda *a: None)
    two = T.build_balanced(str(dump), 6, list(range(6)), tmp_path / "w2.jsonl.gz", workers=2, cap_per_bin=40, per_game=3, log=lambda *a: None)
    assert one["sha256"] == two["sha256"] and one["positions"] == two["positions"]
    assert T.read_testset(tmp_path / "w1.jsonl.gz") == T.read_testset(tmp_path / "w2.jsonl.gz")


def test_another_seed_keeps_other_positions_but_the_same_amount_roughly(tmp_path):
    dump = rated_dump(tmp_path)
    a = T.build_balanced(str(dump), 6, list(range(6)), tmp_path / "a.jsonl.gz", cap_per_bin=40, per_game=3, seed=1, log=lambda *a: None)
    b = T.build_balanced(str(dump), 6, list(range(6)), tmp_path / "b.jsonl.gz", cap_per_bin=40, per_game=3, seed=2, log=lambda *a: None)
    assert a["sha256"] != b["sha256"] and abs(a["positions"] - b["positions"]) < 0.5 * a["positions"]
