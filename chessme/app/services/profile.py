"""The player's profile: how they play, from their own games, filtered by speed, colour and period.

Sections (each answers a question a player asks): the summary (results, rating, performance by play and by result, results against stronger and weaker opponents), openings (score, accuracy and
how the opening goes by family and colour), habits (time of day, weekday, how a session goes and what happens after a loss), phases and endgames (where points are given away, in which kind of
endgame, against players of the same rating), tactics (which motifs are found and which are missed or allowed), the clock, converting and saving, and how the quality of the moves changes over
time. Everything is computed from the stored games and analyses; nothing is guessed when there are too few games, the section says how many it had."""
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import chess
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...analysis import accuracy as ACC
from ...analysis import motifs as MO
from ...analysis import performance as PERF
from ...coach import profile as PR
from ...prep import weakness as WK
from ..models import Analysis, Game
from .. import prep_job
from . import coach as CO
from . import games as G

MAX_GAMES = 3000                 # games read for the summary sections
MAX_DEEP = 400                   # analysed games read move by move (phases, tactics)
SESSION_GAP = timedelta(minutes=30)
MIN_SECTION = 20                 # games a habit needs before it is reported
GOOD = ("brilliant", "great", "best", "excellent")
BAD = ("inaccuracy", "mistake", "miss", "blunder")


def _outcome(g: Game):
    if g.result == "1/2-1/2":
        return 0.5
    if g.result not in ("1-0", "0-1"):
        return None
    return 1.0 if (g.user_colour == "white") == (g.result == "1-0") else 0.0


def _mine(g: Game, a: Analysis):
    return a.moves[0::2] if g.user_colour == "white" else a.moves[1::2]


def _when(g: Game):
    """The datetime a game was played (UTC), or None when only a date or nothing is known."""
    if not g.played_at or len(g.played_at) < 10:
        return None
    day = g.played_at[:10]
    t = g.played_time if g.played_time and len(g.played_time) >= 8 else None
    try:
        return datetime.fromisoformat(f"{day}T{t}") if t else datetime.fromisoformat(day)
    except ValueError:
        return None


def _bucket(score_list):
    n = len(score_list)
    return {"games": n, "score": sum(score_list) / n if n else None}


def load(session: Session, speed=None, colour=None, days=None):
    q = select(Game, Analysis).outerjoin(Analysis, Analysis.game_id == Game.id).where(Game.user_colour.in_(("white", "black")))
    if speed:
        q = q.where(Game.speed == speed)
    if colour in ("white", "black"):
        q = q.where(Game.user_colour == colour)
    if days:
        q = q.where(Game.played_at >= (datetime.now(timezone.utc) - timedelta(days=int(days))).date().isoformat())
    q = q.order_by(Game.played_at.desc().nulls_last(), Game.played_time.desc().nulls_last(), Game.created_at.desc()).limit(MAX_GAMES)
    return session.execute(q).all()


def summary(rows) -> dict:
    scores = [o for g, _ in rows if (o := _outcome(g)) is not None]
    res = Counter({1.0: "win", 0.5: "draw", 0.0: "loss"}[o] for o in scores)
    own = lambda g: g.white_elo if g.user_colour == "white" else g.black_elo
    opp = lambda g: g.black_elo if g.user_colour == "white" else g.white_elo
    vs = {"stronger": [], "similar": [], "weaker": []}
    for g, _ in rows:
        o = _outcome(g)
        if o is None or not own(g) or not opp(g):
            continue
        d = opp(g) - own(g)
        vs["stronger" if d >= 100 else "weaker" if d <= -100 else "similar"].append(o)
    analysed = [(g, a) for g, a in rows if a is not None and a.moves]
    acc = [a.accuracy_white if g.user_colour == "white" else a.accuracy_black for g, a in analysed]
    acc = [x for x in acc if x is not None]
    recent = analysed[:50]
    losses = [m["loss"] for g, a in recent for m in _mine(g, a)]
    speeds = Counter(g.speed for g, _ in recent if g.speed)
    est = PERF.estimate(losses, speeds.most_common(1)[0][0] if speeds else None, G.reference())
    elo_opp = [(opp(g), _outcome(g)) for g, _ in rows[:50] if opp(g) and _outcome(g) is not None]
    by_result = PERF.by_result(sum(e for e, _ in elo_opp) / len(elo_opp), sum(o == 1.0 for _, o in elo_opp), sum(o == 0.0 for _, o in elo_opp), sum(o == 0.5 for _, o in elo_opp)) if elo_opp else None
    series = defaultdict(list)
    for g, _ in reversed(rows):
        if g.speed and own(g) and g.played_at and len(g.played_at) >= 10:
            series[g.speed].append({"date": g.played_at[:10], "rating": own(g)})
    return {"games": len(rows), "analysed": len(analysed), "wins": res["win"], "draws": res["draw"], "losses": res["loss"], "score": sum(scores) / len(scores) if scores else None,
            "accuracy": sum(acc) / len(acc) if acc else None, "performance": {**est, "games": len(recent)} if est else None, "performanceByResult": by_result,
            "against": {k: _bucket(v) for k, v in vs.items()}, "ratings": {k: v[-200:] for k, v in series.items()}, "mistakesPerGame": (sum(1 for g, a in analysed for m in _mine(g, a) if m["cls"] in BAD and m["loss"] >= 0.1) / len(analysed)) if analysed else None}


def openings(rows) -> list[dict]:
    by: dict = {}
    for g, a in rows:
        if not g.opening:
            continue
        o = _outcome(g)
        e = by.setdefault((g.opening.split(":")[0], g.user_colour), {"scores": [], "acc": [], "early": [], "eval12": [], "dates": []})
        if o is not None:
            e["scores"].append(o)
        if g.played_at:
            e["dates"].append(g.played_at[:10])
        if a is not None and a.moves:
            mine = (a.accuracy_white if g.user_colour == "white" else a.accuracy_black)
            if mine is not None:
                e["acc"].append(mine)
            early = [m for i, m in enumerate(a.moves[:24]) if (i % 2 == 0) == (g.user_colour == "white")]
            e["early"].append(any(m["loss"] >= 0.1 for m in early))
            if len(a.moves) >= 24:
                cp = a.moves[23]["cp"]
                e["eval12"].append(PERF_WIN(cp if g.user_colour == "white" else -cp))
    out = []
    overall = {c: [o for g, _ in rows if g.user_colour == c and (o := _outcome(g)) is not None] for c in ("white", "black")}
    for (name, colour), e in by.items():
        n = len(e["scores"])
        base = sum(overall[colour]) / len(overall[colour]) if overall[colour] else None
        score = sum(e["scores"]) / n if n else None
        out.append({"name": name, "colour": colour, "games": n, "score": score, "wins": sum(1 for s in e["scores"] if s == 1), "draws": sum(1 for s in e["scores"] if s == 0.5), "losses": sum(1 for s in e["scores"] if s == 0),
                    "accuracy": sum(e["acc"]) / len(e["acc"]) if e["acc"] else None, "earlyMistakes": sum(e["early"]) / len(e["early"]) if e["early"] else None,
                    "after12": sum(e["eval12"]) / len(e["eval12"]) if e["eval12"] else None, "last": max(e["dates"]) if e["dates"] else None,
                    "weak": bool(n >= 5 and base is not None and score is not None and base - score >= 0.12), "strong": bool(n >= 5 and base is not None and score is not None and score - base >= 0.12)})
    return sorted(out, key=lambda r: -r["games"])[:30]


def PERF_WIN(cp):
    from ...analysis import classify as C
    return C.win_prob(cp, cap=C.LICHESS_CP_CAP)


def habits(rows) -> dict:
    """Results by weekday and time of day, and how sessions go (games played within 30 minutes of each other): score by the game's place in a session, and after a win or a loss."""
    dated = [(w, g) for g, _ in rows if (w := _when(g)) is not None and _outcome(g) is not None]
    by_day = defaultdict(list)
    by_part = defaultdict(list)
    for w, g in dated:
        by_day[w.weekday()].append(_outcome(g))
        if g.played_time and len(g.played_time) >= 8:
            h = w.hour
            by_part["night" if h < 6 else "morning" if h < 12 else "afternoon" if h < 18 else "evening"].append(_outcome(g))
    timed = sorted([(w, g) for w, g in dated if g.played_time and len(g.played_time) >= 8], key=lambda t: t[0])
    sessions, cur = [], []
    for w, g in timed:
        if cur and w - cur[-1][0] > SESSION_GAP:
            sessions.append(cur)
            cur = []
        cur.append((w, g))
    if cur:
        sessions.append(cur)
    pos = defaultdict(list)
    after = {"win": [], "loss": [], "two_losses": []}
    acc_pos = defaultdict(list)
    analysed = {g.id: a for g, a in rows if a is not None and a.moves}
    for s in sessions:
        for i, (_, g) in enumerate(s):
            pos[min(i, 4)].append(_outcome(g))
            a = analysed.get(g.id)
            if a is not None:
                m = a.accuracy_white if g.user_colour == "white" else a.accuracy_black
                if m is not None:
                    acc_pos[min(i, 4)].append(m)
            if i >= 1:
                prev = _outcome(s[i - 1][1])
                after["win" if prev == 1.0 else "loss" if prev == 0.0 else "win"].append(_outcome(g)) if prev != 0.5 else None
            if i >= 2 and _outcome(s[i - 1][1]) == 0.0 and _outcome(s[i - 2][1]) == 0.0:
                after["two_losses"].append(_outcome(g))
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    out = {"weekday": [{"name": days[d], **_bucket(v)} for d, v in sorted(by_day.items())], "timeOfDay": [{"name": k, **_bucket(by_part[k])} for k in ("morning", "afternoon", "evening", "night") if by_part.get(k)],
           "sessionPlace": [{"place": k + 1, **_bucket(v), "accuracy": (sum(acc_pos[k]) / len(acc_pos[k])) if acc_pos.get(k) else None} for k, v in sorted(pos.items())],
           "afterWin": _bucket(after["win"]), "afterLoss": _bucket(after["loss"]), "afterTwoLosses": _bucket(after["two_losses"]), "sessions": len(sessions), "sentences": []}
    sent = out["sentences"]
    if after["loss"] and after["win"] and len(after["loss"]) >= MIN_SECTION:
        a_l, a_w = sum(after["loss"]) / len(after["loss"]), sum(after["win"]) / len(after["win"])
        if a_w - a_l >= 0.10:
            sent.append(f"After a loss you score {round(100 * a_l)}% in the next game, after a win {round(100 * a_w)}% ({len(after['loss'])} and {len(after['win'])} games): a break after a loss may be worth it.")
    if len(after["two_losses"]) >= 10:
        a2 = sum(after["two_losses"]) / len(after["two_losses"])
        if a2 <= 0.35:
            sent.append(f"After two losses in a row you score only {round(100 * a2)}% ({len(after['two_losses'])} games): stop there.")
    late = [v for k, v in pos.items() if k >= 3 for v in v]
    early = [v for k, v in pos.items() if k <= 1 for v in v]
    if len(late) >= MIN_SECTION and len(early) >= MIN_SECTION and sum(early) / len(early) - sum(late) / len(late) >= 0.10:
        sent.append(f"Your fourth game of a session and later scores {round(100 * sum(late) / len(late))}%, your first two {round(100 * sum(early) / len(early))}%: long sessions cost you.")
    parts = [(k, v) for k, v in by_part.items() if len(v) >= MIN_SECTION]
    if len(parts) >= 2:
        best, worst = max(parts, key=lambda kv: sum(kv[1]) / len(kv[1])), min(parts, key=lambda kv: sum(kv[1]) / len(kv[1]))
        if sum(best[1]) / len(best[1]) - sum(worst[1]) / len(worst[1]) >= 0.10:
            sent.append(f"You play best in the {best[0]} ({round(100 * sum(best[1]) / len(best[1]))}%) and worst in the {worst[0]} ({round(100 * sum(worst[1]) / len(worst[1]))}%). (Times are as the games were stamped, in UTC.)")
    return out


def deep(rows, ref) -> dict:
    """The sections that read the moves: phases, kinds of mistake, endgames, the clock, converting, tactics, quality over time and opportunism."""
    analysed = [(g, a) for g, a in rows if a is not None and a.moves][:MAX_DEEP]
    games, analyses, all_rows, by_game_ar = [], {}, [], {}
    for g, a in analysed:
        og = prep_job.oppgame_from_row(g)
        if og is None:
            continue
        ar = CO.analysis_moves(g, a)
        for r in ar:                                                        # the fields the opponent report reads
            r["move"] = a.moves[r["ply"] - 1]["san"]
        games.append(og)
        analyses[og.id] = ar
        all_rows += WK.rows(og, ar)
    out: dict = {"games": len(games), "moves": len(all_rows)}
    if not all_rows:
        return out
    prof = PR.profile(all_rows)
    meta = [(og.speed, og.opp_elo, [{k: r[k] for k in ("phase", "situation", "loss", "kind")} for r in all_rows if r["game"] == og.id]) for og in games]
    cmp_ = CO.reference_comparison(None, meta, ref)
    out["weakness"] = {"profile": prof, "sentences": PR.sentences(prof) if prof.get("findings") else [], "reference": cmp_}
    out["endgames"] = WK.endgame_table(all_rows)
    out["time"] = WK.time_profile(games, all_rows)
    out["conversion"] = WK.conversion(games, analyses)
    # accuracy by phase (combined like the game accuracy)
    ph = defaultdict(list)
    for g, a in analysed:
        for p_, v in ACC.from_api_moves(a.moves)["by_phase"][g.user_colour].items():
            if v is not None:
                ph[p_].append(v)
    out["accuracyByPhase"] = {p_: (sum(v) / len(v) if v else None) for p_, v in ph.items()}
    out["tactics"] = tactics(analysed)
    out["quality"] = quality(analysed)
    out["opportunism"] = opportunism(analysed)
    return out


def tactics(analysed) -> dict:
    """Per motif: found (your best move was that tactic and you played it), missed (the engine's better move was it and you played something else, losing 10 points or more) and allowed
    (the engine's best reply to your mistake was it); with the worst missed examples."""
    found, missed, allowed = Counter(), Counter(), Counter()
    examples = []
    for g, a in analysed:
        board = chess.Board()
        mine_is_white = g.user_colour == "white"
        for i, m in enumerate(a.moves):
            mine = (i % 2 == 0) == mine_is_white
            fen = board.fen()
            try:
                board.push_uci(m["uci"])
            except ValueError:
                break
            if not mine or not m.get("lines"):
                continue
            best = m["lines"][0]
            if m["cls"] in ("best", "great", "brilliant") and m["uci"] == best["uci"]:
                mo = MO.motif_of(fen, best["uci"], best["pv"])
                if mo in MO.TACTICS:
                    found[mo] += 1
            elif m["cls"] in BAD and m["loss"] >= 0.1:
                mo = MO.motif_of(fen, best["uci"], best["pv"])
                nxt = a.moves[i + 1] if i + 1 < len(a.moves) else None
                if mo in MO.TACTICS:
                    missed[mo] += 1
                    examples.append({"game": g.id, "ply": i + 1, "fen": fen, "played": m["san"], "best": best["uci"], "bestSan": chess.Board(fen).san(chess.Move.from_uci(best["uci"])), "motif": mo, "loss": m["loss"], "playedUci": m["uci"]})
                reply = (nxt or {}).get("lines")
                if reply:
                    am = MO.motif_of(board.fen(), reply[0]["uci"], reply[0]["pv"])
                    if am in MO.TACTICS:
                        allowed[am] += 1
    names = [k for k in MO.TACTICS if found[k] or missed[k] or allowed[k]]
    return {"table": [{"motif": k, "name": MO.NAMES[k], "found": found[k], "missed": missed[k], "allowed": allowed[k]} for k in sorted(names, key=lambda k: -(missed[k] + found[k]))],
            "examples": sorted(examples, key=lambda e: -e["loss"])[:8]}


def quality(analysed) -> list[dict]:
    """Per month: your moves by quality: share of excellent-or-better moves, and mistakes per 100 moves; accuracy."""
    by = defaultdict(lambda: {"moves": 0, "good": 0, "bad": 0, "acc": []})
    for g, a in analysed:
        if not g.played_at or len(g.played_at) < 7:
            continue
        e = by[g.played_at[:7]]
        for m in _mine(g, a):
            e["moves"] += 1
            e["good"] += m["cls"] in GOOD
            e["bad"] += m["cls"] in BAD and m["loss"] >= 0.1
        acc = a.accuracy_white if g.user_colour == "white" else a.accuracy_black
        if acc is not None:
            e["acc"].append(acc)
    return [{"month": k, "moves": v["moves"], "good": v["good"] / v["moves"], "mistakesPer100": 100 * v["bad"] / v["moves"], "accuracy": sum(v["acc"]) / len(v["acc"]) if v["acc"] else None}
            for k, v in sorted(by.items()) if v["moves"] >= 100]


def opportunism(analysed) -> dict:
    """Opportunism: how often you took the advantage after the opponent's mistake; luck: how often your own mistakes went unpunished (as Lichess Insights defines them)."""
    took = replied = unpunished = my_replied = 0
    for g, a in analysed:
        mine_white = g.user_colour == "white"
        for i, m in enumerate(a.moves[:-1]):
            mine = (i % 2 == 0) == mine_white
            nxt = a.moves[i + 1]
            if not mine and m["loss"] >= 0.10:
                replied += 1
                took += nxt["loss"] <= 0.05
            elif mine and m["loss"] >= 0.10:
                my_replied += 1
                unpunished += nxt["loss"] > 0.05
    return {"opportunism": took / replied if replied else None, "opportunismN": replied, "luck": unpunished / my_replied if my_replied else None, "luckN": my_replied}


def compute(session: Session, *, speed=None, colour=None, days=None, ref=None) -> dict:
    rows = load(session, speed, colour, days)
    return {"filters": {"speed": speed, "colour": colour, "days": days}, "summary": summary(rows), "openings": openings(rows), "habits": habits(rows), "deep": deep(rows, ref if ref is not None else G.reference())}
