"""Where the opponent's play is weak beyond the opening: by phase, by situation (ahead / level / behind), by kind of mistake, in which kind of endgame, under time
pressure, and in turning advantages into wins. Built on the same rows the player's own weakness profile uses (`coach.profile`), so the two are comparable, and set
against the reference rates of players of the opponent's rating when those exist (`coach.reference`)."""
import chess

from ..coach import profile as PR
from ..coach import reference as REF
from ..humanlike import blunders as B

LOW_CLOCK = 15.0                # seconds: moves played with less than this on the clock are "under time pressure" (or a tenth of the base time when that is smaller)
PIECES = {chess.KNIGHT: "minor", chess.BISHOP: "minor", chess.ROOK: "rook", chess.QUEEN: "queen"}


def endgame_type(board: chess.Board) -> str:
    kinds = {PIECES[p.piece_type] for p in board.piece_map().values() if p.piece_type in PIECES}
    if not kinds:
        return "pawn ending"
    if kinds == {"rook"}:
        return "rook ending"
    if kinds == {"minor"}:
        return "minor-piece ending"
    if kinds == {"queen"}:
        return "queen ending"
    if kinds == {"rook", "minor"}:
        return "rook and minor piece"
    return "queen and others"


def low_clock_limit(base):
    return min(LOW_CLOCK, 0.1 * base) if base else LOW_CLOCK


def rows(game, analysis_moves):
    """One row per move of the opponent: the profile fields (phase, situation, loss, kind) plus ply, the clock they had left, whether that was low, and the kind of
    endgame for moves played in the endgame."""
    board, out, by_ply = chess.Board(), [], {m["ply"]: m for m in analysis_moves}
    limit = low_clock_limit(game.base)
    for ply in range(1, len(game.moves) + 1):
        m = by_ply.get(ply)
        if m is None:
            break
        mv = chess.Move.from_uci(m["uci"])
        if m["color"] == game.colour:
            situation = next(n for n, f in PR.SITUATIONS if f(m["win_before"]))
            kind = B.classify(board.fen(), m["uci"])[0] if m["loss"] >= PR.MISTAKE else None
            clock = game.clocks[ply - 1] if ply - 1 < len(game.clocks) else None
            out.append({"phase": m["phase"], "situation": situation, "loss": m["loss"], "kind": kind, "ply": ply, "clock": clock,
                        "low_clock": clock is not None and clock < limit, "endgame": endgame_type(board) if m["phase"] == "endgame" else None,
                        "game": game.id, "fen": board.fen(), "played": m["move"], "best": m.get("best_move"), "uci": m["uci"]})
        board.push(mv)
    return out


def endgame_table(all_rows, min_moves=10):
    """Per kind of endgame: how many moves, how often they gave away points, the mean loss; and whether it is clearly worse than their other endgames."""
    eg = [r for r in all_rows if r["endgame"]]
    if not eg:
        return []
    base = sum(r["loss"] >= PR.MISTAKE for r in eg) / len(eg)
    out = []
    for t in sorted({r["endgame"] for r in eg}):
        sub = [r for r in eg if r["endgame"] == t]
        k = sum(r["loss"] >= PR.MISTAKE for r in sub)
        z = PR._z(k, len(sub), base) if 0 < base < 1 else 0.0
        out.append({"type": t, "moves": len(sub), "games": len({r["game"] for r in sub}), "mistakeRate": k / len(sub), "meanLoss": sum(r["loss"] for r in sub) / len(sub),
                    "weak": len(sub) >= min_moves and z >= PR.Z_CUT})
    return sorted(out, key=lambda r: -r["moves"])


def time_profile(games, all_rows):
    """The clock: how often they are short of time, what happens then, and how many of their losses came on time."""
    with_clock = [g for g in games if g.clocks and any(c is not None for c in g.clocks)]
    out = {"games": len(with_clock)}
    losses = [g for g in games if g.score == 0.0]
    out["flagLosses"] = sum(1 for g in losses if g.termination and "time" in g.termination.lower())
    out["losses"] = len(losses)
    if not with_clock:
        return out
    trouble = []
    for g in with_clock:
        limit = low_clock_limit(g.base)
        mine = [c for i, c in enumerate(g.clocks) if c is not None and (i % 2 == 0) == (g.colour == "white")]
        trouble.append(bool(mine) and min(mine) < limit)
    scores = [(t, g.score) for t, g in zip(trouble, with_clock) if g.score is not None]
    out["troubleShare"] = sum(trouble) / len(trouble)
    out["scoreInTrouble"] = _mean([s for t, s in scores if t])
    out["scoreOtherwise"] = _mean([s for t, s in scores if not t])
    low = [r for r in all_rows if r["low_clock"]]
    ok = [r for r in all_rows if r["clock"] is not None and not r["low_clock"]]
    out["mistakeRateLow"] = sum(r["loss"] >= PR.MISTAKE for r in low) / len(low) if low else None
    out["mistakeRateOk"] = sum(r["loss"] >= PR.MISTAKE for r in ok) / len(ok) if ok else None
    out["lowMoves"] = len(low)
    return out


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def conversion(games, analyses):
    """How well they turn advantages into points and rescue bad positions, from the analysed full games (peak and low of the expected points)."""
    won_chance = converted = lost_chance = saved = 0
    for g in games:
        a = analyses.get(g.id)
        if not a or g.score is None or len(a) < 30:
            continue
        mine = [m for m in a if m["color"] == g.colour]
        if not mine:
            continue
        peak = max(max(m["win_before"], m["win_after"]) for m in mine)
        low = min(min(m["win_before"], m["win_after"]) for m in mine)
        if peak >= 0.666:
            won_chance += 1
            converted += g.score == 1.0
        if low <= 0.333:
            lost_chance += 1
            saved += g.score > 0.0
    return {"hadWinning": won_chance, "converted": converted, "wasLosing": lost_chance, "saved": saved}


def worst_moments(all_rows, limit=8):
    """The biggest slips in the middlegame and endgame (openings have their own part), each with the position, the move played and the better one."""
    pool = [r for r in all_rows if r["phase"] != "opening" and r["loss"] >= 0.2]
    pool.sort(key=lambda r: -r["loss"])
    out, seen = [], set()
    for r in pool:
        if r["game"] in seen:                                                    # one per game: different games, different lessons
            continue
        seen.add(r["game"])
        out.append({k: r[k] for k in ("game", "fen", "played", "best", "uci", "loss", "phase", "ply", "kind", "situation")})
        if len(out) >= limit:
            break
    return out


ADVICE = {"phase: endgame": "Aim for an endgame: trade queens and pieces when you are equal or better.",
          "phase: middlegame": "Keep the middlegame complicated: they go wrong when the position stays tense.",
          "phase: opening": "They are shaky in the opening: prepare sharp lines.",
          "situation: ahead": "When they get an advantage they let it slip: stay solid, they may give it back.",
          "situation: behind": "When they are worse they make it worse: keep up the pressure instead of simplifying.",
          "situation: level": "In balanced positions they give away points: keep the position equal and wait."}
KIND_ADVICE = {"mate in 1": "they overlook checkmate in one: set up mating threats",
               "ignores a threat": "they often do not deal with your threats: make a threat every move",
               "walks into a capture": "they put pieces where they can be captured: look for tactics every move",
               "deeper": "they lose the thread over longer sequences: play for positions that need calculation"}


def opponent_sentences(prof):
    """Plain sentences about the opponent from a profile of their moves (the findings of `coach.profile`, worded for the one who plays against them)."""
    out = []
    for f in prof.get("findings", []):
        if f["area"].startswith("kind: "):
            kind = f["area"][6:]
            out.append(f"{100 * f['rate']:.0f}% of their mistakes (of {f['moves']}): {KIND_ADVICE.get(kind, kind)}.")
        else:
            area = f["area"].split(": ")[1]
            out.append(f"In {area} positions ({f['moves']} moves) they give away points on {100 * f['rate']:.0f}% of their moves, against {100 * f['elsewhere']:.0f}% elsewhere. {ADVICE.get(f['area'], '')}".strip())
    return out


def reference_sentences(cmp_):
    """The comparison with players of the opponent's rating, worded for the one who plays against them."""
    if not cmp_:
        return []
    who = f"players rated {cmp_['band']} to {cmp_['band'] + REF.BAND - 1}" if cmp_["band"] < REF.HIGHEST else f"players rated {REF.HIGHEST} and above"
    o, out = cmp_["overall"], []
    if o["moves"] >= REF.MIN_N and abs(o["z"]) >= REF.Z_CUT:
        out.append(f"Overall they give away points on {100 * o['you']:.0f}% of their moves, {'more' if o['z'] > 0 else 'less'} than {who} in {cmp_['speed']} ({100 * o['ref']:.0f}%).")
    for f in cmp_["findings"]:
        out.append(f"In {f['area'].split(': ')[1]} positions they give away points on {100 * f['you']:.0f}% of their moves, {'more' if f['z'] > 0 else 'less'} than {who} ({100 * f['ref']:.0f}%).")
    if not cmp_["comparable"]:
        out.append("(The reference used another analysis budget: treat the comparison as rough.)")
    return out


def report(games, analyses, ref=None, nodes=None, multipv=None):
    """Everything about the opponent's weaknesses outside the opening, from the games with a full analysis."""
    full = [g for g in games if analyses.get(g.id) and len(analyses[g.id]) >= 30]
    all_rows = [r for g in full for r in rows(g, analyses[g.id])]
    prof = PR.profile(all_rows)
    speeds = {}
    for g in full:
        speeds[g.speed] = speeds.get(g.speed, 0) + 1
    speed = max(speeds, key=speeds.get) if speeds else None
    rating = next((g.opp_elo for g in sorted(full, key=lambda g: g.date or "", reverse=True) if g.opp_elo), None)
    cmp_ = REF.compare([{k: r[k] for k in ("phase", "situation", "loss", "kind")} for r in all_rows], rating, speed, ref, nodes, multipv) if ref and rating and speed and all_rows else None
    return {"games": len(full), "moves": len(all_rows), "profile": prof, "sentences": opponent_sentences(prof), "reference": cmp_,
            "referenceSentences": reference_sentences(cmp_), "endgames": endgame_table(all_rows), "time": time_profile(games, all_rows),
            "conversion": conversion(full, analyses), "moments": worst_moments(all_rows)}
