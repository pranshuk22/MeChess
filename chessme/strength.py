"""Strength measurement: an Elo estimate from game results against opponents of known Elo.

The standard tool is a *ladder*: play short matches against Stockfish limited to a chosen Elo (`UCI_LimitStrength` +
`UCI_Elo`), always at the current estimate so every game is informative, and stop when the estimate is precise enough.

The estimate is the rating R at which the expected total score against the opponents played equals the actual score
(the maximum-likelihood fit of the logistic Elo model). Each opponent level gets half a pseudo-game scored as a draw,
which keeps all-win / all-loss results finite. The standard error uses the logistic Fisher information and ignores the
variance reduction from draws, so it is slightly conservative. The result is on **Stockfish's UCI_Elo scale at the
time control used**; it is not the Lichess or chess.com scale (see docs/calibration.md).
"""
import math
import re
import subprocess
from dataclasses import dataclass, field

LN10_400 = math.log(10) / 400.0
_UCI_ELO = re.compile(r"option name UCI_Elo type spin default (-?\d+) min (-?\d+) max (-?\d+)")
_ID_NAME = re.compile(r"^id name (.+)$", re.M)


def expected(rating, opp):
    """Expected score of `rating` against `opp` (logistic Elo model)."""
    return 1.0 / (1.0 + 10 ** ((opp - rating) / 400.0))


@dataclass
class Level:
    """Aggregate result against one opponent strength: `score` points from `games` games."""
    opp: int
    score: float = 0.0
    games: int = 0


@dataclass
class Estimate:
    elo: float
    se: float
    games: int
    pinned: str = ""  # "high" / "low": far beyond every opponent played, i.e. outside the measurable range

    @property
    def ci95(self):
        return 1.96 * self.se


def estimate(levels, pseudo_games=0.5, lo=-1000.0, hi=5000.0):
    """Maximum-likelihood Elo from `levels` (iterable of Level)."""
    lv = [(l.opp, l.score + 0.5 * pseudo_games, l.games + pseudo_games) for l in levels if l.games > 0]
    if not lv:
        raise ValueError("no games to estimate from")

    def gap(r):  # actual minus expected total score: decreasing in r
        return sum(s - n * expected(r, o) for o, s, n in lv)

    a, b = lo, hi
    for _ in range(80):
        mid = (a + b) / 2
        a, b = (mid, b) if gap(mid) > 0 else (a, mid)
    r = (a + b) / 2
    info = sum(n * expected(r, o) * (1 - expected(r, o)) for o, _, n in lv) * LN10_400 ** 2
    se = 1.0 / math.sqrt(info) if info > 0 else float("inf")
    opps = [o for o, _, _ in lv]
    pinned = "high" if r > max(opps) + 500 else "low" if r < min(opps) - 500 else ""
    return Estimate(r, se, sum(l.games for l in levels), pinned)


@dataclass
class Ladder:
    estimate: Estimate
    levels: list
    rounds: list = field(default_factory=list)
    stop_reason: str = ""


def next_opponent(est, opp_min, opp_max, granularity=25):
    """The opponent strength to play next: the current estimate, rounded and clamped to the opponent's range."""
    return int(min(max(round(est / granularity) * granularity, opp_min), opp_max))


def run_ladder(play, *, start, opp_min, opp_max, pairs_per_round=5, target_se=35.0, min_games=40, max_games=400,
               granularity=25, margin=150, log=print):
    """Adaptive ladder. `play(opp_elo, pairs) -> (wins, draws, losses)` from the measured engine's point of view.

    Stops when the standard error is at most `target_se` (after `min_games`), when `max_games` are played, or when the
    estimate is more than `margin` Elo beyond the opponent's range while playing at its edge (the engine is stronger /
    weaker than any available opponent)."""
    levels, rounds, games, est = {}, [], 0, float(start)
    stop = "max games reached"
    e = None
    while games < max_games:
        opp = next_opponent(est, opp_min, opp_max, granularity)
        w, d, l = play(opp, pairs_per_round)
        n = w + d + l
        if n == 0:
            stop = "no games were played"
            break
        lv = levels.setdefault(opp, Level(opp))
        lv.score += w + 0.5 * d
        lv.games += n
        games += n
        e = estimate(levels.values())
        est = e.elo
        rounds.append({"opp": opp, "w": w, "d": d, "l": l, "elo": round(e.elo, 1), "se": round(e.se, 1)})
        log(f"  vs {opp}: +{w} ={d} -{l}   estimate {e.elo:.0f} +/- {e.ci95:.0f} after {games} games")
        # Out of range only counts against the range the opponent CAN be set to, and only after playing at its edge:
        # a bad first guess (e.g. losing 0-10 to a much stronger opponent) is not evidence of being off the ladder.
        if e.elo > opp_max + margin and opp == opp_max:
            stop = "stronger than the strongest opponent available"
            break
        if e.elo < opp_min - margin and opp == opp_min:
            stop = "weaker than the weakest opponent available"
            break
        if games >= min_games and e.se <= target_se:
            stop = "target precision reached"
            break
    if e is None:
        raise RuntimeError("the ladder played no games")
    return Ladder(e, sorted(levels.values(), key=lambda x: x.opp), rounds, stop)


# ---- linking players that cannot be measured directly ----------------------------------------------------------------

def joint_fit(matches, anchors, *, iterations=60, pseudo=0.5, weak_prior_sd=1500.0):
    """Ratings of several players from games between them plus absolute measurements of some of them.

    `matches`: [(a, b, score_a, games)] between named players; `anchors`: {name: (elo, se)} absolute ratings measured
    elsewhere (each acts as a Gaussian prior). Players without an anchor get a very weak prior only, so their rating is
    fixed by the games linking them to anchored players. Maximum a posteriori by Newton's method; returns
    {name: (elo, se)}. Each match gets `pseudo` games scored as draws so lopsided results stay finite."""
    import numpy as np

    names = sorted({a for a, _, _, _ in matches} | {b for _, b, _, _ in matches} | set(anchors))
    idx = {n: i for i, n in enumerate(names)}
    ref = float(np.mean([v[0] for v in anchors.values()])) if anchors else 1500.0
    R = np.array([anchors[n][0] if n in anchors else ref for n in names], dtype=float)
    mu = R.copy()
    inv_var = np.array([1.0 / max(anchors[n][1], 1.0) ** 2 if n in anchors else 1.0 / weak_prior_sd ** 2 for n in names])
    for _ in range(iterations):
        g = -(R - mu) * inv_var
        H = -np.diag(inv_var)
        for a, b, s, n in matches:
            i, j = idx[a], idx[b]
            s, n = s + 0.5 * pseudo, n + pseudo
            e = expected(R[i], R[j])
            d = (s - n * e) * LN10_400
            w = n * e * (1 - e) * LN10_400 ** 2
            g[i] += d
            g[j] -= d
            H[i, i] -= w
            H[j, j] -= w
            H[i, j] += w
            H[j, i] += w
        step = np.linalg.solve(H - 1e-9 * np.eye(len(names)), -g)
        R += step
        if np.max(np.abs(step)) < 1e-6:
            break
    cov = np.linalg.inv(-H + 1e-9 * np.eye(len(names)))
    return {n: (float(R[idx[n]]), float(np.sqrt(max(cov[idx[n], idx[n]], 0.0)))) for n in names}


# ---- asking an engine about itself ---------------------------------------------------------------------------

def parse_uci_elo_range(text):
    """(default, min, max) of the UCI_Elo option in the engine's reply to `uci`, or None if it has none."""
    m = _UCI_ELO.search(text)
    return tuple(int(x) for x in m.groups()) if m else None


def engine_info(command, timeout=15):
    """{"name": ..., "uci_elo": (default, min, max) or None} from a UCI engine's reply to `uci`."""
    cmd = [command] if isinstance(command, str) else list(command)
    out = subprocess.run(cmd, input="uci\nquit\n", capture_output=True, text=True, timeout=timeout).stdout
    m = _ID_NAME.search(out)
    return {"name": m.group(1).strip() if m else "unknown", "uci_elo": parse_uci_elo_range(out)}
