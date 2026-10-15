"""The analysis worker keeps one engine for all its games; a dead engine must be replaced, not reused."""
import json

from chessme.analysis import pool as P

PGN = '[White "A"]\n[Black "B"]\n[Result "1-0"]\n[Site "https://lichess.org/Ab12Cd34"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n'


class FakeProc:
    def __init__(self):
        self.alive = True

    def poll(self):
        return None if self.alive else 1


class FakeEngine:
    def __init__(self, die_after=None):
        self.proc, self.die_after, self.closed, self.searches = FakeProc(), die_after, False, 0

    def new_game(self):
        if not self.proc.alive:
            raise RuntimeError("engine is not running")

    def close(self):
        self.closed = True
        self.proc.alive = False


def install(monkeypatch, engines):
    """Make _start hand out the given fake engines in turn; the search just answers with a flat position."""
    started = []

    def fake_start(engine, nodes, openings_dir, multipv=2):
        eng = engines[len(started)]
        started.append(eng)

        class L:
            move, cp, pv = "e2e4", 0, []

        def search(board):
            eng.searches += 1
            if eng.die_after is not None and eng.searches > eng.die_after:
                eng.proc.alive = False                                  # killed in the middle of a game (e.g. after a timeout)
            if not eng.proc.alive:
                raise RuntimeError("engine is not running")
            return [L()]
        eng.multipv = multipv
        return {"engine": eng, "search": search, "book": None, "nodes": nodes, "multipv": multipv}
    monkeypatch.setattr(P, "_start", fake_start)
    P._STATE.clear()
    return started


def task(tmp_path, name, *multipv):
    return (name, PGN, str(tmp_path / f"{name}.json"), "stockfish", 1000, None, "A", *multipv)


def test_a_dead_engine_costs_one_game_not_the_rest_of_the_worker(tmp_path, monkeypatch):
    """Regression: the dead engine stayed cached, so every later game of the worker failed with 'engine is not running'."""
    engines = [FakeEngine(die_after=3), FakeEngine()]
    started = install(monkeypatch, engines)
    assert P.analyse_task(task(tmp_path, "one"))[2] is not None          # the engine dies in the middle of this game: it is lost ...
    key, plies, err = P.analyse_task(task(tmp_path, "two"))              # ... but the next one runs on a fresh engine
    assert err is None and plies == 7 and len(started) == 2
    assert json.loads((tmp_path / "two.json").read_text())["player_color"] == "white"
    P.close()
    assert engines[1].closed and not P._STATE


def test_an_engine_that_died_between_games_is_replaced_before_use(tmp_path, monkeypatch):
    engines = [FakeEngine(), FakeEngine()]
    started = install(monkeypatch, engines)
    assert P.analyse_task(task(tmp_path, "a"))[2] is None
    engines[0].proc.alive = False
    assert P.analyse_task(task(tmp_path, "b"))[2] is None and len(started) == 2
    P.close()


def test_another_number_of_lines_starts_a_new_engine_and_two_is_the_default(tmp_path, monkeypatch):
    engines = [FakeEngine(), FakeEngine(), FakeEngine()]
    started = install(monkeypatch, engines)
    assert P.analyse_task(task(tmp_path, "a"))[2] is None and started[0].multipv == 2          # a seven-field task: two lines, as before
    assert P.analyse_task(task(tmp_path, "b", 2))[2] is None and len(started) == 1             # the same setting: the engine is kept
    assert P.analyse_task(task(tmp_path, "c", 5))[2] is None and len(started) == 2 and started[1].multipv == 5
    P.close()
