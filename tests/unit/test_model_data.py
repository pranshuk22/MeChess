import io
import json
import random

import chess
import chess.pgn
import numpy as np
import pytest
import zstandard

from chessme.dataset.weights import Weighter
from chessme.model import data as D
from chessme.model import encoding as enc
from tests.samples import make_row


def play(n, seed=1):
    """A legal random game of up to n plies, as chess.Move objects (retries seeds so it reaches n)."""
    while True:
        rng, b, moves = random.Random(seed), chess.Board(), []
        while len(moves) < n and not b.is_game_over():
            m = rng.choice(list(b.legal_moves))
            moves.append(m)
            b.push(m)
        if len(moves) == n:
            return moves
        seed += 1


def record(n=40, **kw):
    kw.setdefault("white_elo", 1600); kw.setdefault("black_elo", 1500); kw.setdefault("result", "1-0")
    return D.GameRecord(play(n), **kw)


def test_extract_labels_ratings_and_result_from_the_movers_view():
    buf = D.extract_samples(record(30), min_ply=10)
    a = buf.to_arrays()
    assert len(buf) == 20  # plies 10..29, both sides
    plies = a["ply"].tolist()
    assert plies == list(range(10, 30))
    white = a["ply"] % 2 == 0
    assert np.all(a["ratings"][white] == [1600, 1500]) and np.all(a["ratings"][~white] == [1500, 1600])
    assert np.all(a["result"][white] == 2) and np.all(a["result"][~white] == 0)  # White won: win for white, loss for black
    assert np.all(a["platform"] == 0) and np.all(a["weight"] == 1.0)


def test_sample_is_the_position_before_the_move():
    rec = record(20)
    buf = D.extract_samples(rec, min_ply=15)
    a = buf.to_arrays()
    board = chess.Board()
    for m in rec.moves[:15]:
        board.push(m)
    arr, castle, ep = enc.canonical_state(board)
    assert np.array_equal(a["board"][0], arr) and a["castle"][0] == castle and a["ep"][0] == ep
    assert a["move"][0] == enc.move_index(rec.moves[15], board)


def test_min_ply_and_sides():
    assert len(D.extract_samples(record(30), min_ply=25)) == 5
    only_white = D.GameRecord(play(30), 1600, 1500, "1-0", sides=(chess.WHITE,))
    assert set(D.extract_samples(only_white, min_ply=0).to_arrays()["ply"] % 2) == {0}


def test_forced_moves_are_skipped_as_uninformative():
    fen = "7k/8/8/8/8/8/q7/K7 w - - 0 1"  # White's only legal move is Kxa2
    assert chess.Board(fen).legal_moves.count() == 1
    rec = D.GameRecord([chess.Move.from_uci("a1a2")], 1500, 1500, "1-0", start_fen=fen)
    assert len(D.extract_samples(rec, min_ply=0)) == 0
    assert len(D.extract_samples(rec, min_ply=0, skip_forced=False)) == 1


def test_unfinished_games_produce_no_samples():
    assert len(D.extract_samples(record(30, result="*"), min_ply=0)) == 0


def test_clock_filter_drops_time_trouble_moves():
    clocks = [300.0] * 20 + [10.0] * 10
    buf = D.extract_samples(record(30, clocks=clocks), min_ply=10, min_clock=30)
    assert buf.to_arrays()["ply"].tolist() == list(range(10, 20))
    unknown = D.extract_samples(record(30, clocks=[]), min_ply=10, min_clock=30)
    assert len(unknown) == 20  # no clock information: keep


def test_weights_and_zero_weight_moves():
    weights = [0.0] * 15 + [0.5] * 15
    a = D.extract_samples(record(30, weights=weights), min_ply=10).to_arrays()
    assert a["ply"].tolist() == list(range(15, 30)) and np.all(a["weight"] == 0.5)


def test_keep_probability_is_seeded():
    a = D.extract_samples(record(60), min_ply=0, keep_prob=0.3, rng=random.Random(5)).to_arrays()["ply"]
    b = D.extract_samples(record(60), min_ply=0, keep_prob=0.3, rng=random.Random(5)).to_arrays()["ply"]
    c = D.extract_samples(record(60), min_ply=0, keep_prob=0.3, rng=random.Random(6)).to_arrays()["ply"]
    assert list(a) == list(b) and list(a) != list(c) and 5 < len(a) < 35


def test_extras_store_legal_moves_and_fens_that_match_the_position():
    buf = D.extract_samples(record(30), min_ply=10, extras=True)
    a = buf.to_arrays()
    assert a["legal"].shape == (20, D.LEGAL_WIDTH) and a["fen"].shape == (20,)
    for i in range(len(buf)):
        b = chess.Board(str(a["fen"][i]))
        legal = sorted(int(x) for x in a["legal"][i] if x >= 0)
        assert legal == sorted(enc.legal_indices(b)) and int(a["move"][i]) in legal


def test_shard_round_trip(tmp_path):
    a = D.extract_samples(record(30), min_ply=10, extras=True).to_arrays()
    D.save_shard(tmp_path / "s" / "x.npz", a)
    b = D.load_shards([tmp_path / "s" / "x.npz", tmp_path / "s" / "x.npz"])
    assert len(b["move"]) == 40 and np.array_equal(b["move"][:20], a["move"]) and b["board"].dtype == np.uint8
    D.save_shard(tmp_path / "s" / "y.npz", D.extract_samples(record(30), min_ply=10))
    with pytest.raises(ValueError):
        D.load_shards([tmp_path / "s" / "x.npz", tmp_path / "s" / "y.npz"])  # different fields


# ---- game records --------------------------------------------------------------------------------------------------

PGN = """[Event "Rated Blitz game"]
[Site "https://lichess.org/abc12345"]
[White "a"]
[Black "b"]
[Result "0-1"]
[WhiteElo "1500"]
[BlackElo "1620"]
[TimeControl "300+0"]
[Termination "Normal"]

1. e4 { [%clk 0:05:00] } e5 { [%clk 0:05:00] } 2. Nf3 { [%clk 0:04:58] } Nc6 { [%clk 0:04:57] } 3. Bb5 { [%clk 0:04:50] } a6 { [%clk 0:04:40] } 0-1
"""


def test_record_from_pgn_reads_moves_clocks_and_ratings():
    rec = D.record_from_pgn_game(chess.pgn.read_game(io.StringIO(PGN)))
    assert [m.uci() for m in rec.moves[:3]] == ["e2e4", "e7e5", "g1f3"]
    assert (rec.white_elo, rec.black_elo, rec.result) == (1500, 1620, "0-1")
    assert rec.clocks[:2] == [300.0, 300.0] and rec.clocks[5] == 280.0


def test_record_from_pgn_rejects_missing_ratings_and_bad_moves():
    assert D.record_from_pgn_game(chess.pgn.read_game(io.StringIO(PGN.replace('[WhiteElo "1500"]\n', '')))) is None
    assert D.record_from_pgn_game(chess.pgn.read_game(io.StringIO(PGN.replace("2. Nf3", "2. Nh9")))) is None


def test_record_from_row_uses_my_view_and_weights():
    cfg = {"filters": {"time_class_weights": {"blitz": 1.0}}}
    row = make_row(color="black", my_rating=1700, opp_rating=1650, moves="e4 e5 Nf3 Nc6 Bb5", result="1-0",
                   platform="chesscom", clocks=[10.0] * 5)
    rec = D.record_from_row(row, Weighter(cfg, [row]))
    assert (rec.white_elo, rec.black_elo, rec.platform, rec.sides) == (1650, 1700, 1, (chess.BLACK,))
    assert rec.weights == [1.0] * 5 and len(rec.moves) == 5
    assert D.record_from_row(make_row(moves="e4 e5 Qh9")) is None


# ---- Lichess stream ---------------------------------------------------------------------------------------------------

def make_pgn(i, white=1500, black=1500, tc="300+0", event="Rated Blitz game", variant=None, result="1-0", n=44):
    board, sans = chess.Board(), []
    rng = random.Random(i)
    while len(sans) < n and not board.is_game_over():
        m = rng.choice(list(board.legal_moves))
        sans.append(board.san(m))
        board.push(m)
    body = " ".join(f"{k // 2 + 1}. {s}" if k % 2 == 0 else s for k, s in enumerate(sans))
    tags = [("Event", event), ("Site", f"https://lichess.org/g{i:07d}"), ("Result", result), ("WhiteElo", white),
            ("BlackElo", black), ("TimeControl", tc), ("Termination", "Normal")] + ([("Variant", variant)] if variant else [])
    return "".join(f'[{k} "{v}"]\n' for k, v in tags) + f"\n{body} {result}\n\n"


def test_game_texts_are_split_on_event_lines():
    text = make_pgn(1) + make_pgn(2) + make_pgn(3)
    assert len(list(D.iter_game_texts(io.StringIO(text)))) == 3


def test_quick_headers():
    tags = D.quick_headers(make_pgn(1, white=1800, black=1750))
    assert tags["WhiteElo"] == "1800" and tags["TimeControl"] == "300+0"


def test_filter_accepts_and_bins_by_average_rating():
    f = D.LichessFilter(rating_min=1100, rating_max=2300, bin_width=100)
    assert f.game_bin(D.quick_headers(make_pgn(1, 1500, 1520))) == 4      # avg 1510 -> [1500, 1600)
    assert f.game_bin(D.quick_headers(make_pgn(1, 1100, 1110))) == 0
    assert f.game_bin(D.quick_headers(make_pgn(1, 2250, 2280))) == 11


@pytest.mark.parametrize("kwargs", [
    dict(white=1050, black=1500), dict(white=2300, black=2100), dict(white=1500, black=1950),  # ratings out of range / gap
    dict(tc="60+0"), dict(tc="15+0"), dict(tc="-"),                                            # bullet / correspondence
    dict(event="Casual Blitz game"), dict(variant="Chess960"), dict(variant="Atomic"),
    dict(result="*"),
])
def test_filter_rejects(kwargs):
    assert D.LichessFilter().game_bin(D.quick_headers(make_pgn(1, **kwargs))) is None


def test_filter_rejects_abandoned_games():
    text = make_pgn(1).replace('[Termination "Normal"]', '[Termination "Abandoned"]')
    assert D.LichessFilter().game_bin(D.quick_headers(text)) is None


def test_split_of_is_deterministic_and_roughly_proportional():
    splits = [D.split_of(f"https://lichess.org/{i}", 5, 5) for i in range(4000)]
    assert splits == [D.split_of(f"https://lichess.org/{i}", 5, 5) for i in range(4000)]
    counts = {k: splits.count(k) for k in ("train", "val", "test")}
    assert 130 < counts["val"] < 270 and 130 < counts["test"] < 270


def write_zst(path, text):
    path.write_bytes(zstandard.ZstdCompressor().compress(text.encode()))


def db(n_per_bin=40, bins=(1200, 1500, 1800)):
    out, i = [], 0
    for elo in bins:
        for _ in range(n_per_bin):
            out.append(make_pgn(i, elo, elo + 20))
            i += 1
    out.append(make_pgn(9001, 1500, 1500, tc="60+0"))  # bullet: filtered
    return "".join(out)


def build(tmp_path, source, **kw):
    kw.setdefault("flt", D.LichessFilter(rating_min=1100, rating_max=2000))
    kw.setdefault("keep_prob", 0.5)
    return D.build_lichess(source, tmp_path / "out", **kw)


def test_build_from_a_compressed_stream(tmp_path):
    write_zst(tmp_path / "db.pgn.zst", db())
    meta = build(tmp_path, tmp_path / "db.pgn.zst", samples_per_bin=10**9, val_pct=10, test_pct=10)
    assert meta["games_used"] == 120 and meta["games_seen"] == 121
    assert meta["train_samples"] > 500 and meta["val_samples"] > 0 and meta["test_samples"] > 0
    tr = D.load_shards([tmp_path / "out" / n for n in meta["train_shards"]])
    assert tr["board"].shape[1] == 64 and "legal" not in tr             # train shards are lean
    val = D.load_shards([tmp_path / "out" / "val.npz"])
    assert "legal" in val and "fen" in val                              # val/test carry legal moves and FENs
    assert (tmp_path / "out" / "meta.json").exists()


def test_plain_pgn_files_work_too(tmp_path):
    (tmp_path / "db.pgn").write_text(db(10))
    meta = build(tmp_path, tmp_path / "db.pgn", samples_per_bin=10**9)
    assert meta["games_used"] == 30


def test_rating_quotas_balance_the_bins(tmp_path):
    text = "".join(make_pgn(i, 1200, 1220) for i in range(200)) + "".join(make_pgn(1000 + i, 1800, 1820) for i in range(20))
    write_zst(tmp_path / "db.pgn.zst", text)
    meta = build(tmp_path, tmp_path / "db.pgn.zst", samples_per_bin=100, val_pct=0, test_pct=0, keep_prob=1.0)
    assert 100 <= meta["per_bin"]["1200"] <= 100 + 60 and meta["per_bin"]["1800"] >= 100  # both bins filled to their quota
    assert meta["games_used"] < 220  # the common bin stopped early


@pytest.mark.slow
def test_byte_budget_stops_reading(tmp_path):
    write_zst(tmp_path / "db.pgn.zst", db(1500, bins=(1200, 1500, 1800)))
    size = (tmp_path / "db.pgn.zst").stat().st_size
    assert size > 400_000  # several read chunks, so a budget can bite
    full = build(tmp_path, tmp_path / "db.pgn.zst", samples_per_bin=10**9)
    cut = build(tmp_path, tmp_path / "db.pgn.zst", samples_per_bin=10**9, budget_bytes=150_000)
    assert full["games_used"] == 4500 and full["compressed_bytes_read"] >= size
    assert 0 < cut["games_used"] < 0.8 * full["games_used"]
    assert cut["compressed_bytes_read"] <= 150_000 + 2 * 131072  # at most a couple of read chunks over the budget


def test_counting_reader_is_a_proper_stream():
    r = D.CountingReader(io.BytesIO(b"x" * 1000), limit=300)
    assert r.readable() and len(r.read(200)) == 200 and r.count == 200
    assert len(r.read(200)) == 200 and r.count == 400   # the check happens before each read
    assert r.read(200) == b"" and r.count == 400          # limit reached: EOF
    assert D.CountingReader(io.BytesIO(b"abc")).read() == b"abc"  # unlimited


def test_max_games_and_seed_determinism(tmp_path):
    write_zst(tmp_path / "db.pgn.zst", db(40))
    a = build(tmp_path, tmp_path / "db.pgn.zst", samples_per_bin=10**9, max_games=50, seed=3)
    a_moves = D.load_shards([tmp_path / "out" / n for n in a["train_shards"]])["move"]
    b = build(tmp_path, tmp_path / "db.pgn.zst", samples_per_bin=10**9, max_games=50, seed=3)
    b_moves = D.load_shards([tmp_path / "out" / n for n in b["train_shards"]])["move"]
    assert a["games_seen"] == 51 and np.array_equal(a_moves, b_moves)


def test_every_game_lands_in_the_split_its_id_dictates():
    """The split is decided per game from its Site id, so a game's positions can never leak across splits."""
    for i in range(60):
        text = make_pgn(i, 1500, 1520)
        site = f"https://lichess.org/g{i:07d}"
        res = D.process_game_text((text, 4, 1, 1.0, 10, 0, 10, 10))
        assert res is not None and res[0] == D.split_of(site, 10, 10)
        assert len(res[2]) > 0


def test_shards_are_split_by_size(tmp_path):
    write_zst(tmp_path / "db.pgn.zst", db(60))
    meta = build(tmp_path, tmp_path / "db.pgn.zst", samples_per_bin=10**9, keep_prob=1.0, shard_size=400, val_pct=0, test_pct=0)
    assert len(meta["train_shards"]) >= 3
    total = sum(len(D.load_shards([tmp_path / "out" / n])["move"]) for n in meta["train_shards"])
    assert total == meta["train_samples"]


# ---- user data -----------------------------------------------------------------------------------------------------

def user_rows(n=40):
    rows = []
    for i in range(n):
        moves = " ".join(_san(play(30, seed=100 + i)))
        rows.append(make_row(game_id=f"g{i}", moves=moves, color="white" if i % 2 == 0 else "black",
                             played_at=f"2024-03-{(i % 28) + 1:02d}T{i // 28:02d}:00:00+00:00", result="1-0",
                             my_rating=1800, opp_rating=1750, my_result="win"))
    return rows


def _san(moves):
    b, out = chess.Board(), []
    for m in moves:
        out.append(b.san(m))
        b.push(m)
    return out


CFG = {"filters": {"min_rating": {"lichess": 1400}, "recency": {"half_life_days": 3650, "min_weight": 0.1},
                   "time_class_weights": {"blitz": 1.0}}}


def test_user_shards_split_by_time_and_contain_only_my_moves(tmp_path):
    rows = user_rows()
    meta = D.build_user(rows, Weighter(CFG, rows), tmp_path, test_fraction=0.25, val_fraction=0.1, min_ply=8)
    assert meta["splits"]["test"]["games"] == 10 and meta["splits"]["val"]["games"] == 3
    assert meta["splits"]["train"]["games"] == 27
    tr = D.load_shards([tmp_path / "train.npz"])
    te = D.load_shards([tmp_path / "test.npz"])
    assert "legal" not in tr and "legal" in te
    assert np.all(tr["ratings"][:, 0] == 1800) and np.all(tr["ratings"][:, 1] == 1750)  # mover is always me
    assert np.all(tr["weight"] > 0)
    assert tr["ply"].min() >= 8


def test_user_shards_skip_filtered_games(tmp_path):
    rows = user_rows(20)
    rows[0]["my_rating"] = 1000
    meta = D.build_user(rows, Weighter(CFG, rows), tmp_path, test_fraction=0.0, val_fraction=0.0)
    assert meta["splits"]["train"]["games"] == 19


def test_fix_shard_ep_rewrites_only_uncapturable_squares(tmp_path):
    """Shards built with the old rule mark the ep square after every double push; the fix keeps only capturable ones."""
    boards = [chess.Board("rnbqkbnr/pppp1ppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"),      # not capturable
              chess.Board("rnbqkbnr/pppp1ppp/8/8/3Pp3/8/PPP1PPPP/RNBQKBNR b KQkq d3 0 3")]      # capturable
    buf = D.SampleBuffer()
    for b in boards:
        buf.add(b, next(iter(b.legal_moves)), (1500, 1500), 0, 1, 12, 1.0)
    arrays = buf.to_arrays()
    # emulate the old rule in the stored field
    arrays["ep"] = np.array([chess.E3 ^ 56, chess.D3 ^ 56], np.uint8)
    path = tmp_path / "s.npz"
    D.save_shard(path, arrays)
    assert D.fix_shard_ep(path) == 1
    assert D.load_shards([path])["ep"].tolist() == [enc.NO_EP, chess.D3 ^ 56]
    assert D.fix_shard_ep(path) == 0  # idempotent


def test_subset_selects_rows_of_every_field():
    a = D.extract_samples(record(30), min_ply=10, extras=True).to_arrays()
    mask = np.arange(len(a["move"])) % 2 == 0
    sub = D.subset(a, mask)
    assert len(sub["move"]) == mask.sum() and sub["legal"].shape[0] == mask.sum() and len(sub["fen"]) == mask.sum()
    assert np.array_equal(sub["board"], a["board"][mask])


def test_remap_platform_shifts_ratings_without_touching_the_original():
    a = D.extract_samples(record(30), min_ply=10).to_arrays()
    a["platform"][:5] = 1
    b = D.remap_platform(a, shift=300)
    assert np.all(b["platform"] == 0) and np.array_equal(b["ratings"][:5], a["ratings"][:5] + 300)
    assert np.array_equal(b["ratings"][5:], a["ratings"][5:]) and np.all(a["platform"][:5] == 1)


def test_merge_combines_datasets_without_copying_train_shards(tmp_path):
    write_zst(tmp_path / "a.pgn.zst", db(30, bins=(1200, 1500)))
    write_zst(tmp_path / "b.pgn.zst", db(30, bins=(1800,)))
    ma = D.build_lichess(tmp_path / "a.pgn.zst", tmp_path / "A", samples_per_bin=10**9, flt=D.LichessFilter(1100, 2000),
                         keep_prob=0.5, val_pct=10, test_pct=10)
    mb = D.build_lichess(tmp_path / "b.pgn.zst", tmp_path / "B", samples_per_bin=10**9, flt=D.LichessFilter(1100, 2000),
                         keep_prob=0.5, val_pct=10, test_pct=10)
    meta = D.merge_datasets([tmp_path / "A", tmp_path / "B"], tmp_path / "M")
    assert meta["train_shards"] == len(ma["train_shards"]) + len(mb["train_shards"])
    assert meta["val_samples"] == ma["val_samples"] + mb["val_samples"]
    assert meta["test_samples"] == ma["test_samples"] + mb["test_samples"]
    links = sorted((tmp_path / "M").glob("train*.npz"))
    assert len(links) == meta["train_shards"] and all(l.is_symlink() for l in links)
    assert sum(len(D.load_shards([l])["move"]) for l in links) == ma["train_samples"] + mb["train_samples"]
    val = D.load_shards([tmp_path / "M" / "val.npz"])
    assert len(val["move"]) == meta["val_samples"] and "legal" in val
    D.merge_datasets([tmp_path / "A", tmp_path / "B"], tmp_path / "M")  # re-running is fine


def test_lichess_filter_can_select_other_time_controls():
    bullet = D.quick_headers(make_pgn(1, 1700, 1720, tc="60+0"))
    blitz = D.quick_headers(make_pgn(2, 1700, 1720, tc="300+0"))
    assert D.LichessFilter().game_bin(bullet) is None and D.LichessFilter().game_bin(blitz) is not None
    only_bullet = D.LichessFilter(time_classes=("bullet",))
    assert only_bullet.game_bin(bullet) is not None and only_bullet.game_bin(blitz) is None


def test_user_shards_can_train_on_selected_time_controls_only(tmp_path):
    rows = user_rows(40)
    for i, r in enumerate(rows):
        r["time_class"] = "blitz" if i < 20 else "bullet"
        r["played_at"] = f"2024-{i // 28 + 1:02d}-{i % 28 + 1:02d}T00:00:00+00:00"
    cfg = {"filters": {"min_rating": {"lichess": 1400}, "time_class_weights": {"blitz": 1.0, "bullet": 1.0}}}
    everything = D.build_user(rows, Weighter(cfg, rows), tmp_path / "all", test_fraction=0.25, val_fraction=0.1)
    only_blitz = D.build_user(rows, Weighter(cfg, rows), tmp_path / "blitz", test_fraction=0.25, val_fraction=0.1,
                              train_time_classes=("blitz",))
    assert 0 < only_blitz["splits"]["train"]["games"] < everything["splits"]["train"]["games"]
    assert only_blitz["splits"]["val"] == everything["splits"]["val"] and only_blitz["splits"]["test"] == everything["splits"]["test"]
