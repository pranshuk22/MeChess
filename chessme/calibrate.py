"""Play engines against Stockfish at known Elo to measure strength, and calibrate the MeChess dial.

Two entry points, both built on the match runner (paired openings, both colours) and the adaptive ladder in strength.py:

  measure(spec, ...)          how strong is one engine (e.g. the plain alpha-beta engine)?
  calibrate_dial(dials, ...)  how strong is MeChess at each dial setting? Writes a calibration file the controller can use.

Results are on Stockfish's UCI_Elo scale at the movetime used. Cost warning: strength needs hundreds of games per
measured engine; run it when the machine is otherwise idle (use --concurrency to parallelise)."""
import json
import sys
import time
from pathlib import Path

from . import strength
from .match import Adjudication, EngineSpec, SearchLimit, run_match
from .mechess.calibration import Calibration


def stockfish_options(elo, threads=1, hash_mb=16):
    """UCI options that make Stockfish play at about `elo` (see docs/stockfish.md)."""
    return {"UCI_LimitStrength": "true", "UCI_Elo": int(elo), "Threads": threads, "Hash": hash_mb}


def make_play(spec, opponent_command, openings, limit, adj=Adjudication(), *, concurrency=1,
              opponent_options=stockfish_options, name="opponent", log=print):
    """`play(opp_elo, pairs) -> (wins, draws, losses)` for `spec`, using the next `pairs` openings (cycling) each call."""
    state = {"next": 0, "faults": 0}

    def play(opp_elo, pairs):
        fens = [openings[(state["next"] + i) % len(openings)] for i in range(pairs)]
        state["next"] += pairs
        opp = EngineSpec.make(f"{name}-{opp_elo}", opponent_command, opponent_options(opp_elo))
        res = run_match(spec, opp, fens, limit, adj, concurrency=concurrency, max_pairs=pairs)
        if res.errors:
            state["faults"] += len(res.errors)
            log(f"  WARNING: {len(res.errors)} engine fault(s) in this round (scored as losses for the faulting engine): "
                f"{res.errors[0]}")
        return res.wins, res.draws, res.losses

    play.state = state
    return play


def measure(spec, opponent_command, openings, limit, *, start=None, opponent_options=stockfish_options,
            opp_range=None, pairs_per_round=5, target_se=35.0, min_games=40, max_games=400, concurrency=1, log=print):
    """Ladder for one engine. Returns a JSON-friendly dict with the estimate, the levels played and the settings."""
    info = strength.engine_info(opponent_command) if opp_range is None else {"name": "opponent", "uci_elo": (0,) + tuple(opp_range)}
    if not info["uci_elo"]:
        raise SystemExit(f"{opponent_command} has no UCI_Elo option: it cannot be used as a strength ladder")
    lo, hi = info["uci_elo"][1], info["uci_elo"][2]
    play = make_play(spec, opponent_command, openings, limit, concurrency=concurrency, opponent_options=opponent_options,
                     name="opponent", log=log)
    t0 = time.time()
    log(f"measuring {spec.name} against {info['name']} at UCI_Elo {lo}-{hi}; limit {limit.kwargs()}, "
        f"{pairs_per_round} pairs per round, target +/- {1.96 * target_se:.0f} Elo, at most {max_games} games")
    ladder = strength.run_ladder(play, start=start or (lo + hi) // 2, opp_min=lo, opp_max=hi, pairs_per_round=pairs_per_round,
                                 target_se=target_se, min_games=min_games, max_games=max_games, log=log)
    e = ladder.estimate
    log(f"  => {spec.name}: {e.elo:.0f} +/- {e.ci95:.0f} ({ladder.stop_reason})")
    return {"name": spec.name, "elo": round(e.elo, 1), "se": round(e.se, 1), "ci95": round(e.ci95, 1), "games": e.games,
            "pinned": e.pinned, "stop": ladder.stop_reason, "opponent": info["name"], "limit": limit.kwargs(),
            "levels": [{"opp": l.opp, "score": l.score, "games": l.games} for l in ladder.levels],
            "rounds": ladder.rounds, "faults": play.state["faults"], "seconds": round(time.time() - t0)}


def mechess_command(engine, prior="uniform", book=None):
    """Command line that starts MeChess as a UCI engine (used as the measured player)."""
    cmd = [sys.executable, "-m", "chessme", "mechess", "--engine", str(engine), "--prior", prior]
    return tuple(cmd + (["--book", str(book)] if book else []))


def calibrate_dial(dials, command, opponent_command, openings, limit, out_path, *, redo=False, offset=0.0,
                   log=print, **ladder_kw):
    """Measure MeChess at every dial setting in `dials` and write the calibration file after each one (resumable)."""
    out = Path(out_path)
    data = json.loads(out.read_text()) if out.exists() and not redo else {"points": []}
    done = {p["dial"] for p in data["points"]}
    for i, dial in enumerate(dials, 1):
        if dial in done:
            log(f"[{i}/{len(dials)}] dial {dial}: already measured ({[p['measured'] for p in data['points'] if p['dial'] == dial][0]:.0f})")
            continue
        log(f"[{i}/{len(dials)}] dial {dial}")
        spec = EngineSpec.make(f"mechess-{dial}", command, {"Elo": dial})
        r = measure(spec, opponent_command, openings, limit, start=dial, log=log, **ladder_kw)
        data["points"].append({"dial": dial, "measured": r["elo"], "se": r["se"], "games": r["games"], "stop": r["stop"],
                               "pinned": r["pinned"], "levels": r["levels"], "faults": r["faults"]})
        data["scale"] = "stockfish-UCI_Elo"
        data["offset"] = offset
        data["meta"] = {"opponent": r["opponent"], "limit": r["limit"], "date": time.strftime("%Y-%m-%d")}
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=1))
    cal = Calibration.load(out)
    log("\ncalibration (dial -> measured Elo, monotone fit):")
    for d, m in cal.curve():
        log(f"  dial {d:5d} -> {m:6.0f}")
    if cal.unmeasurable():
        log(f"  not usable (beyond the opponent's measurable range, kept in the file): dial {cal.unmeasurable()}")
    return cal
