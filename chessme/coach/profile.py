"""Your weaknesses, from the games you have reviewed: how often your moves give away points (a mistake = at least 0.10 expected points, a blunder = at least 0.20)
by phase, by what the position was like (ahead, level, behind), and by the kind of mistake (rules on the board, `humanlike.blunders`).

This is a profile of YOUR game, not of how you compare with other players: a category shows up when your own rate there is clearly above your rate elsewhere
(a one-sided test against your overall rate, and at least `MIN_N` moves), so one bad game cannot make a weakness. Comparing with what players of your rating usually do
(the human-like model's expected loss) is the next step. Every finding names the practice that fits it."""
import math

import chess

from ..humanlike import blunders as B

MISTAKE, BLUNDER = 0.10, 0.20
MIN_N = 30                       # moves in a category before it can be called a weakness
Z_CUT = 1.64                     # one-sided 95%
SITUATIONS = (("ahead", lambda w: w >= 0.65), ("level", lambda w: 0.35 < w < 0.65), ("behind", lambda w: w <= 0.35))
PRACTICE = {"endgame": "endgame practice", "opening": "opening practice", "middlegame": "a steered middlegame game",
            "ahead": "converting a better position (steered game)", "behind": "defending a worse position (steered game)", "level": "a steered middlegame game",
            "mate in 1": "the threat-check habit: before each move ask what the opponent threatens", "ignores a threat": "the threat-check habit",
            "walks into a capture": "the threat-check habit: check that the square you move to is safe", "deeper": "a steered middlegame game and drills from your mistakes"}


def player_rows(analysis, color):
    """One row per move of `color`: phase, situation (from the win chance before the move), loss, and the kind of mistake for the moves that lost at least 0.10."""
    board = chess.Board()
    rows, by_ply = [], {m["ply"]: m for m in analysis["moves"]}
    ply = 1
    while ply in by_ply:
        m = by_ply[ply]
        fen = board.fen()
        move = chess.Move.from_uci(m["uci"])
        if m["color"] == color:
            situation = next(n for n, f in SITUATIONS if f(m["win_before"]))
            kind = B.classify(fen, m["uci"])[0] if m["loss"] >= MISTAKE else None
            rows.append({"phase": m["phase"], "situation": situation, "loss": m["loss"], "kind": kind})
        board.push(move)
        ply += 1
    return rows


def _z(k, n, p0):
    """One-sided normal-approximation z for k of n above the rate p0."""
    if n == 0 or p0 <= 0 or p0 >= 1:
        return 0.0
    return (k / n - p0) / math.sqrt(p0 * (1 - p0) / n)


def profile(rows):
    """{'moves', 'mistake_rate', 'blunder_rate', 'by_phase', 'by_situation', 'kinds', 'findings'} from the rows of many games."""
    n = len(rows)
    if n == 0:
        return {"moves": 0, "findings": []}
    mistakes = [r for r in rows if r["loss"] >= MISTAKE]
    base = len(mistakes) / n
    out = {"moves": n, "mistake_rate": base, "blunder_rate": sum(r["loss"] >= BLUNDER for r in rows) / n, "by_phase": {}, "by_situation": {}, "kinds": {}}
    findings = []
    for key, name in (("phase", "by_phase"), ("situation", "by_situation")):
        for value in sorted({r[key] for r in rows}):
            sub = [r for r in rows if r[key] == value]
            k = sum(r["loss"] >= MISTAKE for r in sub)
            rest_n, rest_k = n - len(sub), len(mistakes) - k
            rest = rest_k / rest_n if rest_n else base
            z = _z(k, len(sub), rest) if rest_n else 0.0
            out[name][value] = {"moves": len(sub), "mistake_rate": k / len(sub), "mean_loss": sum(r["loss"] for r in sub) / len(sub), "z": z}
            if len(sub) >= MIN_N and z >= Z_CUT:
                findings.append({"area": f"{key}: {value}", "moves": len(sub), "rate": k / len(sub), "elsewhere": rest, "z": z, "practice": PRACTICE.get(value, "drills from your mistakes")})
    kinds = {}
    for r in mistakes:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    out["kinds"] = {k: {"count": c, "share": c / len(mistakes)} for k, c in kinds.items()}
    for k, c in kinds.items():
        if k in ("mate in 1", "ignores a threat", "walks into a capture"):
            share = c / len(mistakes)
            if len(mistakes) >= MIN_N // 2 and share >= 0.40:
                findings.append({"area": f"kind: {k}", "moves": len(mistakes), "rate": share, "elsewhere": None, "z": None, "practice": PRACTICE[k]})
    out["findings"] = sorted(findings, key=lambda f: -(f["z"] if f["z"] is not None else 99))
    return out


def sentences(prof):
    """Plain sentences for the findings (an empty list when there is not enough data or nothing stands out)."""
    out = []
    for f in prof.get("findings", []):
        if f["area"].startswith("kind: "):
            out.append(f"{100 * f['rate']:.0f}% of your mistakes are the kind where you {B.TYPE_TEXT[f['area'][6:]]} (of {f['moves']}). Try: {f['practice']}.")
        else:
            area = f["area"].split(": ")[1]
            out.append(f"In the {area} situations ({f['moves']} moves) you give away points on {100 * f['rate']:.0f}% of your moves, against {100 * f['elsewhere']:.0f}% elsewhere. Try: {f['practice']}.")
    return out or ["Nothing stands out yet (or there are not enough moves): review a few more games."]
