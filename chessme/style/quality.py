"""Move-quality features per game from engine analysis (plan 8m F4 and 8n): accuracy by phase, class rates, opportunism, luck,
conversion, resourcefulness. Computed for a capped sample of each cohort player's own games (`chessme style-games-quality`), one
file per player, so the job can be stopped and resumed, and paused between players."""
import gzip
import json
from pathlib import Path

import chess
import chess.pgn

from ..analysis import runner as AR
from ..jobs import JobControl, Stopped, run_pool
from .games_fetch import read_player, write_player

QUALITY_NAMES = (
    "q_accuracy", "q_acc_opening", "q_acc_middlegame", "q_acc_endgame", "q_mean_loss",
    "q_best_rate", "q_great_rate", "q_brilliant_rate", "q_inaccuracy_rate", "q_mistake_rate", "q_miss_rate", "q_blunder_rate",
    "q_opportunism", "q_luck", "q_converted", "q_saved",
)
NAN = None


def game_from_record(rec):
    """A python-chess game from a cohort game record (UCI moves, the player's colour, the result)."""
    g = chess.pgn.Game()
    g.headers["Result"] = {1.0: "1-0", 0.0: "0-1", 0.5: "1/2-1/2"}.get(rec["meta"].get("result"), "*") if rec["meta"]["color"] == "white" \
        else {1.0: "0-1", 0.0: "1-0", 0.5: "1/2-1/2"}.get(rec["meta"].get("result"), "*")
    node = g
    for uci in rec["moves"].split():
        node = node.add_variation(chess.Move.from_uci(uci))
    return g


def quality_vector(analysis, color):
    """QUALITY_NAMES values (None when not applicable) from an `analyse_game` result, for `color`."""
    s = analysis["summary"][color]
    n = max(s["moves"], 1)
    c = s["classes"]
    ph = s["accuracy_by_phase"]
    losses = [m["loss"] for m in analysis["moves"] if m["color"] == color]
    vals = {
        "q_accuracy": s["accuracy"], "q_acc_opening": ph["opening"], "q_acc_middlegame": ph["middlegame"], "q_acc_endgame": ph["endgame"],
        "q_mean_loss": sum(losses) / len(losses) if losses else None,
        "q_best_rate": (c["best"] + c["great"] + c["brilliant"]) / n, "q_great_rate": c["great"] / n, "q_brilliant_rate": c["brilliant"] / n,
        "q_inaccuracy_rate": c["inaccuracy"] / n, "q_mistake_rate": c["mistake"] / n, "q_miss_rate": c["miss"] / n, "q_blunder_rate": c["blunder"] / n,
        "q_opportunism": s["opportunism"], "q_luck": s["luck"],
        "q_converted": None if s["converted"] is None else float(s["converted"]), "q_saved": None if s["saved"] is None else float(s["saved"]),
    }
    return [None if vals[k] is None else round(float(vals[k]), 5) for k in QUALITY_NAMES]


def _analyse_player(task):
    """Worker: analyse the first `games` games of one player with its own engine; writes the player's file. Returns (pid, n_games)."""
    from ..uci_client import UciEngine
    src, dst, engine, nodes, n_games = task
    d = read_player(src)
    rows = []
    with UciEngine([engine], options={"Threads": 1, "Hash": 16}) as eng:
        search = AR.engine_search(eng, nodes=nodes, multipv=2)
        for rec in d["games"][:n_games]:
            res = AR.analyse_game(game_from_record(rec), search)
            rows.append({"feat": quality_vector(res, rec["meta"]["color"]), "color": rec["meta"]["color"]})
    write_player(dst, {"pid": d["pid"], "rating": d["rating"], "names": list(QUALITY_NAMES), "nodes": nodes, "games": rows})
    return d["pid"], len(rows)


def run(data_dir, *, engine="stockfish", nodes=25000, n_games=10, max_players=400, seed=0, workers=3, job="quality",
        control_dir="data/control", task_timeout=900, log=print):
    """Analyse a seeded sample of `max_players` players (those with data), skipping finished ones. Returns {"done", "stopped"}."""
    import random
    data = Path(data_dir)
    (data / "quality").mkdir(exist_ok=True)
    files = sorted((data / "games").glob("*.json.gz"))
    rng = random.Random(seed)
    rng.shuffle(files)
    sample = []
    for f in files:
        if len(sample) >= max_players:
            break
        if not read_player(f).get("short"):
            sample.append(f)
    todo = [(f, data / "quality" / f.name, engine, nodes, n_games) for f in sample if not (data / "quality" / f.name).exists()]
    log(f"{len(sample)} players in the sample, {len(todo)} to analyse ({n_games} games each, {nodes} nodes/position, {workers} workers)")
    ctl = JobControl(job, control_dir, log=log)
    done, stopped = 0, False
    with ctl.signals():
        try:
            for pid, n in run_pool(_analyse_player, todo, workers, ctl, task_timeout=task_timeout):
                done += 1
                log(f"  [{done}/{len(todo)}] {pid[:8]}: {n} games")
        except Stopped as e:
            stopped = True
            log(f"stopped: {e} (rerun the same command to resume)")
    return {"done": done, "stopped": stopped}


def load_quality(data_dir):
    """{pid: (rating, array (n, len(QUALITY_NAMES)) with NaN, metas)} for the analysed players."""
    import numpy as np
    out = {}
    for f in sorted((Path(data_dir) / "quality").glob("*.json.gz")):
        d = read_player(f)
        arr = np.array([[float("nan") if v is None else v for v in g["feat"]] for g in d["games"]], dtype=float)
        out[d["pid"]] = (d["rating"], arr, [{"color": g["color"]} for g in d["games"]])
    return out
