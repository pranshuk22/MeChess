"""MeChess learns to choose like a person from the games in the library."""
import json
import random
from types import SimpleNamespace

import chess
import pytest
from fastapi.testclient import TestClient

from chessme.analysis.runner import SimpleLine
from chessme.app import style_job
from chessme.app.config import AppConfig
from chessme.app.main import create_app
from chessme.mechess import humanprior as HP
from chessme.mechess import priors
from chessme.mechess.controller import MeChess
from tests.unit.prep_helpers import material

BASE = "http://127.0.0.1:8765"


def random_game(seed, plies=50):
    rng, b, out = random.Random(seed), chess.Board(), []
    while len(out) < plies and not b.is_game_over():
        mv = rng.choice(list(b.legal_moves))
        out.append(mv.uci())
        b.push(mv)
    return out


class FastEngine:
    """A stand-in for Stockfish: one-ply material, every legal move as a line, best first (scores for the side to move)."""

    def _send(self, line):
        pass

    def ready(self):
        pass

    def new_game(self):
        pass

    def close(self):
        pass

    def go(self, fen, moves=(), *, nodes=None, **kw):
        b = chess.Board(fen)
        lines = []
        for mv in b.legal_moves:
            b.push(mv)
            lines.append(SimpleLine(mv.uci(), -material(b), [mv.uci()]))
            b.pop()
        lines.sort(key=lambda l: -l.cp)
        return SimpleNamespace(lines=lines[:5], bestmove=lines[0].move)


def test_decisions_come_from_move_ten_on_spread_over_the_games_and_can_be_the_players_own():
    games = [(random_game(i), 1500, 1600, "white" if i % 2 else "black") for i in range(30)]
    ds = HP.sample_decisions(games, 300)
    assert 250 <= len(ds) <= 360 and all(d.ply >= HP.MIN_PLY for d in ds) and len({d.game for d in ds}) == 30
    mine = HP.sample_decisions(games, 300, only="user")
    assert all((games[d.game][3] == "white") == (chess.Board(d.fen).turn == chess.WHITE) for d in mine)
    assert HP.sample_decisions([([], None, None, None)], 100) == []


def test_stored_lines_make_positions_with_the_chosen_move_and_candidates_within_the_window():
    moves = []
    b = chess.Board()
    for u in random_game(3, 24):
        mv = chess.Move.from_uci(u)
        lines = [{"uci": u, "cp": 20, "pv": [u]}]
        other = next(m for m in b.legal_moves if m != mv)
        lines.append({"uci": other.uci(), "cp": -30 if b.turn == chess.WHITE else 30, "pv": [other.uci()]})       # 50 cp worse for the mover: inside the window
        moves.append({"uci": u, "lines": lines})
        b.push(mv)
    ps = HP.positions_from_game(moves, 1500, 1500)
    assert ps and all(p.ply >= HP.MIN_PLY and len(p.cands) == 2 and p.chosen == 0 and p.feats.shape == (2, len(HP.FEATURE_NAMES)) for p in ps)
    assert all(p.loss[0] == 0 and p.loss[1] > 0 for p in ps)
    white_only = HP.positions_from_game(moves, 1500, 1500, only="white")
    assert len(white_only) < len(ps)


def test_the_model_learns_and_the_prior_it_makes_is_a_distribution_over_the_legal_moves(monkeypatch, tmp_path):
    monkeypatch.setattr(HP, "MIN_USABLE", 30)
    games = [(random_game(i), 1500, 1500, None) for i in range(60)]
    items = HP.sample_decisions(games, 600)
    model, rep = HP.fit_from_decisions(FastEngine(), items, nodes=1, multipv=5, window=400)
    assert rep["positions"] >= 30 and rep["held_out"]["n"] > 0 and len(rep["top"]) == 6 and "uniform" in rep["held_out"]
    from chessme.style import model as SM
    SM.save_model(model, tmp_path / "m.json", positions=rep["positions"])
    prior = priors.StylePrior(tmp_path / "m.json")
    p = prior(chess.Board(), 1500, 1500, 0)
    assert set(p) == set(chess.Board().legal_moves) and sum(p.values()) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="only"):
        monkeypatch.setattr(HP, "MIN_USABLE", 10 ** 6)
        HP.fit_from_decisions(FastEngine(), items[:50], nodes=1, window=400)


def test_a_slip_follows_what_a_person_would_be_tempted_by_mostly_and_anything_sometimes():
    class Eng:
        def _send(self, *a): pass
        def ready(self): pass
        def go(self, *a, **k): raise AssertionError("not searched")
    board = chess.Board()
    legal = list(board.legal_moves)
    favourite = legal[7]
    prior = lambda b, e, o, p: {m: (0.9 if m == favourite else 0.1 / (len(legal) - 1)) for m in legal}
    from chessme.mechess.controller import Choice
    from chessme.mechess.dial import DialSettings
    mc = MeChess(Eng(), prior, seed=1)
    settings = DialSettings(1500, 100, 3, 100, 1.0, 100.0, 0, blunder_rate=1.0)
    picks = [mc._with_blunder(board, Choice(legal[0], "search", []), settings).move for _ in range(400)]
    assert picks.count(favourite) / 400 > 0.55 and len(set(picks)) > 8                       # the tempting move most of the time, others now and then


def test_the_training_job_stores_a_model_the_options_report_and_play_can_use(tmp_path, monkeypatch):
    monkeypatch.setattr(HP, "MIN_USABLE", 30)
    cfg = AppConfig(data_dir=tmp_path / "d", research_dir=tmp_path / "r", legacy_coach_dir=tmp_path / "c", port=8765)
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        c.app.state.style_engine_factory = lambda: FastEngine()
        from chessme.app.services import games as G
        s = c.app.state.sessions()
        for i in range(60):
            moves = random_game(i, 40)
            G.store(s, id=f"r{i}", source="lichess", headers={"White": "me", "Black": "x", "Result": "1-0", "WhiteElo": "1500", "BlackElo": "1500"}, user_colour="white", uci_moves=moves)
        s.commit()
        s.close()
        assert c.get("/api/play/options").json()["mechess"]["styles"]["population"]["available"] is False
        assert c.post("/api/play/start", json={"opponent": "mechess", "level": 1500, "style": "population"}).status_code == 409      # not learned yet
        assert c.post("/api/play/start", json={"opponent": "mechess", "level": 1500, "style": "weird"}).status_code == 422
        assert c.post("/api/play/train-style", json={"scope": "other"}).status_code == 422
        job = c.post("/api/play/train-style", json={"scope": "population", "decisions": 500}).json()["id"]
        import time
        end = time.time() + 120
        while time.time() < end:
            j = next(x for x in c.get("/api/jobs").json() if x["id"] == job)
            if j["status"] in ("done", "failed"):
                break
            time.sleep(0.2)
        assert j["status"] == "done", j["message"]
        st = c.get("/api/play/options").json()["mechess"]["styles"]
        assert st["population"]["available"] and st["population"]["positions"] >= 30 and st["me"]["available"] is False
        assert json.loads(style_job.model_path(cfg, "population").read_text())["meta"]["scope"] == "population"


def test_a_library_that_is_too_small_says_so(tmp_path):
    cfg = AppConfig(data_dir=tmp_path / "d", research_dir=tmp_path / "r", legacy_coach_dir=tmp_path / "c", port=8765)
    with TestClient(create_app(cfg, static=False), base_url=BASE) as c:
        c.app.state.style_engine_factory = lambda: FastEngine()
        job = c.post("/api/play/train-style", json={"scope": "me"}).json()["id"]
        import time
        time.sleep(1.0)
        j = next(x for x in c.get("/api/jobs").json() if x["id"] == job)
        assert j["status"] == "failed" and "Not enough games" in j["message"]
