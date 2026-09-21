import chess.pgn
import io

from chessme.analysis import runner as AR
from chessme.analysis import select as SEL


def pgn(gid, moves="1. e4 e5 2. Nf3 Nc6 *"):
    return f'[Event "rated blitz game"]\n[Site "https://lichess.org/{gid}"]\n[White "a"]\n[Black "b"]\n[Result "*"]\n[GameId "{gid}"]\n\n{moves}\n\n'


def row(gid, when, cls="blitz", color="white", **kw):
    return {"game_id": f"lichess:{gid}", "platform": "lichess", "usable": True, "variant": "standard", "plies": 40, "played_at": when, "time_class": cls,
            "color": color, **kw}


ROWS = [row("g1", "2026-01-01T00:00:00"), row("g2", "2026-03-01T00:00:00", "bullet"), row("g3", "2026-02-01T00:00:00", "blitz", "black"),
        row("g4", "2026-04-01T00:00:00", "bullet"), row("g5", "2026-05-01T00:00:00", "rapid"), row("x", "2026-06-01T00:00:00", plies=5),
        row("y", "2026-06-02T00:00:00", usable=False), row("z", "2026-06-03T00:00:00", variant="chess960"),
        {**row("w", "2026-06-04T00:00:00"), "platform": "chesscom", "game_id": "chesscom:w"}]


def test_choose_takes_the_newest_usable_standard_long_games():
    got = [r["game_id"] for r in SEL.choose(ROWS, n=3)]
    assert got == ["lichess:g5", "lichess:g4", "lichess:g2"]                    # short, unusable, variant and other-platform games are out


def test_choose_per_class_and_since_and_classes():
    per = [r["game_id"] for r in SEL.choose(ROWS, n=0, per_class=1)]
    assert per == ["lichess:g5", "lichess:g4", "lichess:g3"]                    # the newest of rapid, bullet, blitz
    assert [r["game_id"] for r in SEL.choose(ROWS, n=10, since="2026-03-01")] == ["lichess:g5", "lichess:g4", "lichess:g2"]
    assert [r["game_id"] for r in SEL.choose(ROWS, n=10, time_classes=["blitz"])] == ["lichess:g3", "lichess:g1"]


def test_raw_games_reads_ids_and_write_pgn_adds_the_side_and_reports_missing(tmp_path):
    (tmp_path / "a.pgn").write_text(pgn("g1") + pgn("g3"))
    raw = SEL.raw_games([tmp_path / "a.pgn"])
    assert set(raw) == {"lichess:g1", "lichess:g3"}
    n, missing = SEL.write_pgn([ROWS[2], ROWS[0], ROWS[3]], raw, tmp_path / "out" / "sel.pgn")
    assert n == 2 and missing == ["lichess:g4"]
    games = []
    with open(tmp_path / "out" / "sel.pgn") as f:
        while (g := chess.pgn.read_game(f)) is not None:
            games.append(g)
    assert [g.headers["MeChessSide"] for g in games] == ["black", "white"] and [len(list(g.mainline())) for g in games] == [4, 4]


def test_the_marked_side_wins_over_the_player_name():
    g = chess.pgn.read_game(io.StringIO(pgn("g1").replace("[Result", '[MeChessSide "black"]\n[Result')))
    assert AR.side_of(g, "a") == "black" and AR.side_of(g, None) == "black"
    plain = chess.pgn.read_game(io.StringIO(pgn("g1")))
    assert AR.side_of(plain, "a") == "white" and AR.side_of(plain, "nobody") is None
