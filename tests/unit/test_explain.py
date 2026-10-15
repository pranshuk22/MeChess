"""Plain-language reasons for the moves of an analysed game, and the opening steps and clocks that come with a game."""
import chess
from fastapi.testclient import TestClient

from chessme.analysis import explain as E
from chessme.app.config import AppConfig
from chessme.app.main import create_app
from chessme.app.services import games as G

BASE = "http://127.0.0.1:8765"


def fen_after(*moves):
    b = chess.Board()
    for m in moves:
        b.push_uci(m)
    return b.fen()


def row(san, uci, cls, loss=0.0, best=None, wb=0.5, wa=0.5, lines=None):
    return {"san": san, "uci": uci, "cls": cls, "loss": loss, "best": best or uci, "winBefore": wb, "winAfter": wa, "lines": lines or []}


def test_a_blunder_that_allows_mate_says_so_with_the_move_and_what_was_better():
    fen = fen_after("e2e4", "e7e5", "d1h5", "b8c6", "f1c4")                                  # black to move
    m = row("Nf6", "g8f6", "blunder", 0.45, best="g7g6", wb=0.5, wa=0.03, lines=[{"uci": "g7g6", "cp": 150, "pv": ["g7g6", "h5f3"]}])
    why = " ".join(E.explain_move(fen, m, [{"uci": "h5f7", "cp": 10000, "pv": ["h5f7"]}]))
    assert "checkmate" in why and "Qxf7#" in why and "fall from 50% to 3%" in why and "Better was g6" in why


def test_a_missed_chance_is_named_and_a_book_move_is_just_theory():
    fen = fen_after("e2e4", "e7e5")
    m = row("Nf3", "g1f3", "miss", 0.15, best="d1h5", wb=0.6, wa=0.45, lines=[{"uci": "d1h5", "cp": 120, "pv": ["d1h5"]}])
    assert "You missed Qh5" in " ".join(E.explain_move(fen, m, None))
    assert E.explain_move(fen, row("Nf3", "g1f3", "book"), None) == ["Nf3 is opening theory."]


def test_a_best_move_says_why_it_is_best_and_an_only_move_is_called_one():
    fen = fen_after("e2e4", "e7e5")
    only = row("Nf3", "g1f3", "great", 0, best="g1f3", lines=[{"uci": "g1f3", "cp": 200, "pv": ["g1f3"]}, {"uci": "d2d3", "cp": -250, "pv": ["d2d3"]}])
    why = " ".join(E.explain_move(fen, only, None))
    assert why.startswith("A great move: Nf3") and "only good move" in why
    ok = row("d3", "d2d3", "good", 0.03, best="g1f3", lines=[{"uci": "g1f3", "cp": 40, "pv": ["g1f3"]}])
    assert "sound move" in " ".join(E.explain_move(fen, ok, None)) and "slightly prefers Nf3" in " ".join(E.explain_move(fen, ok, None))


def test_a_broken_row_never_breaks_the_page():
    assert E.explain_move(chess.STARTING_FEN, row("Qh5", "d1h5", "blunder"), None) == []                 # not legal there
    assert E.explain_all([row("e4", "e2e4", "best"), row("??", "zzzz", "good"), row("Nf3", "g1f3", "good")])[1] == []


def test_the_game_detail_carries_reasons_opening_steps_and_the_clocks(tmp_path):
    cfg = AppConfig(data_dir=tmp_path / "d", research_dir=tmp_path / "r", legacy_coach_dir=tmp_path / "c", port=8765)
    pgn = ('[Event "x"]\n[White "me"]\n[Black "o"]\n[Result "1-0"]\n[TimeControl "180+2"]\n\n'
           '1. e4 { [%clk 0:03:00] } e5 { [%clk 0:02:59] } 2. Nf3 { [%clk 0:02:55] } Nc6 { [%clk 0:02:50] } 3. Bb5 { [%clk 0:02:40] } 1-0\n')
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        s = c.app.state.sessions()
        G.store(s, id="x", source="t", headers={"White": "me", "Black": "o", "Result": "1-0", "TimeControl": "180+2"}, user_colour="white", pgn=pgn, uci_moves=["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"])
        s.commit()
        s.close()
        d = c.get("/api/games/x").json()
        assert d["clocks"] == [180.0, 179.0, 175.0, 170.0, 160.0] and d["base"] == 180 and d["inc"] == 2
        names = [st[2] for st in d["openingSteps"]]
        assert names[0] == "King's Pawn Game" and names[-1].startswith("Ruy Lopez") and d["bookEnd"] == 5
        assert all(st[0] <= 5 for st in d["openingSteps"])
