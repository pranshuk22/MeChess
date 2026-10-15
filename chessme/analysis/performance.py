"""Performance rating of a game from how it was played, and from its result.

By play: at each rating the reference counts (`coach.reference`: Lichess games analysed with the app's own settings) say how often a move is fine, a mistake (gives away 10 to 20
points of win chance) or a blunder (20 or more). The moves of one player in one game are a sample of that; the rating whose rates make the sample most likely, weighed with a wide prior,
is the performance, with an 80% interval that is honest about how few moves one game has (about +-250 points for a typical game).

By result: the 400 rule, the opponent's rating + 400 x (wins - losses) / games."""
import math

BAND_CENTRE = {"low": 1100, "high": 2500}          # the first reference band is 1000-1199 (and below), the last 2400 and above
GRID = range(600, 2926, 25)
PRIOR_MEAN, PRIOR_SD = 1500.0, 800.0
SPEED_CELL = {"bullet": "blitz", "ultrabullet": "blitz", "blitz": "blitz", "rapid": "rapid", "classical": "rapid", "correspondence": "rapid"}
MISTAKE, BLUNDER = 0.10, 0.20


def counts(losses):
    """(fine, mistakes that are not blunders, blunders) of a list of expected-point losses."""
    k_b = sum(1 for l in losses if l >= BLUNDER)
    k_m = sum(1 for l in losses if MISTAKE <= l < BLUNDER)
    return len(losses) - k_m - k_b, k_m, k_b


def _rates(ref, speed):
    """[(rating at the centre of the band, p_fine, p_mistake, p_blunder)] for a speed, from the band cells; [] when the reference has none."""
    out = []
    for key, c in sorted(ref.get("cells", {}).items()):
        sp, band = key.split("|")
        if sp != speed or not c.get("moves"):
            continue
        n, m, b = c["moves"], c["mistakes"], c.get("blunders", 0)
        out.append((int(band) + 100, max(1e-4, 1 - m / n), max(1e-4, (m - b) / n), max(1e-4, b / n)))
    return sorted(out)


def _at(rows, rating):
    """The three rates at `rating`: linear interpolation of the log rates between band centres, the end bands' rates beyond them."""
    if rating <= rows[0][0]:
        return rows[0][1:]
    if rating >= rows[-1][0]:
        return rows[-1][1:]
    for (r0, *a), (r1, *b) in zip(rows, rows[1:]):
        if r0 <= rating <= r1:
            t = (rating - r0) / (r1 - r0)
            return tuple(math.exp((1 - t) * math.log(x) + t * math.log(y)) for x, y in zip(a, b))


def estimate(losses, speed, ref, *, counts_override=None):
    """{'rating', 'low', 'high', 'moves'} for one player's losses in one game (or in many: pass all of them together), or None when there is no reference for the speed or no moves."""
    cell = SPEED_CELL.get(speed or "")
    if ref is None or cell is None:
        return None
    rows = _rates(ref, cell)
    k = counts_override or counts(losses)
    n = sum(k)
    if len(rows) < 3 or n == 0:
        return None
    logp = []
    for r in GRID:
        p = _at(rows, r)
        ll = sum(ki * math.log(pi) for ki, pi in zip(k, p)) - 0.5 * ((r - PRIOR_MEAN) / PRIOR_SD) ** 2
        logp.append(ll)
    top = max(logp)
    w = [math.exp(x - top) for x in logp]
    z = sum(w)
    w = [x / z for x in w]
    mean = sum(r * x for r, x in zip(GRID, w))
    acc, low, high = 0.0, GRID[0], GRID[-1]
    got_low = False
    for r, x in zip(GRID, w):
        acc += x
        if not got_low and acc >= 0.10:
            low, got_low = r, True
        if acc >= 0.90:
            high = r
            break
    return {"rating": int(round(mean / 5) * 5), "low": int(low), "high": int(high), "moves": n}


def by_result(opponent_rating, wins, losses, draws=0):
    """Performance by the 400 rule from the opponent's mean rating and the results; None without an opponent rating or games."""
    games = wins + losses + draws
    if not opponent_rating or games == 0:
        return None
    return int(round(opponent_rating + 400 * (wins - losses) / games))
