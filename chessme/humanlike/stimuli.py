"""Stimuli of the forced-choice study (protocol: which of two games was played by a human?).

A trial is one START (a position with its history, the ratings of the two players, the time control) and two fragments that continue it for the same
number of half-moves: the human game's and a generated game's. Nothing else is shown: no clocks, no thinking times, no result, no usernames, no game
id. The stimuli are cut into BLOCKS, one per participant, so that a participant sees a start only once, no start is used twice in the whole study, and
two conditions never share a human fragment. The answer key (which side is the human, condition, game id) is written to a separate file that stays
with the experimenter. Everything is drawn with a seed and recorded, no hand picking, no filtering by how good or human a fragment looks.

Conditions are pairs "human vs <generated set>"; an attention check is a human fragment against a fragment of random legal moves."""
import hashlib
import json
import random

import chess

VERSION = 1


def _band(rating):
    lo = int(rating) // 100 * 100
    return f"{lo} to {lo + 99}"


def _plies(record):
    return len(record["start"].split())


def eligible(human, generated, min_plies):
    """Starts present in every set whose continuations are at least `min_plies` half-moves long in all of them, in a stable order (sorted by hash of the id)."""
    by = {name: {r["gid"]: r for r in rs} for name, rs in generated.items()}
    out = []
    for h in human:
        g = h["gid"]
        if len(h["moves"].split()) < min_plies:
            continue
        if all(g in d and len(d[g]["moves"].split()) >= min_plies and d[g]["start"] == h["start"] for d in by.values()):
            out.append(g)
    return sorted(out, key=lambda g: hashlib.sha256(g.encode()).hexdigest())


def random_fragment(start, plies, rng):
    """`plies` random legal moves from the position after `start` (fewer if the game ends)."""
    board = chess.Board()
    for u in start.split():
        board.push_uci(u)
    moves = []
    while len(moves) < plies and not board.is_game_over():
        m = rng.choice(sorted(board.legal_moves, key=lambda x: x.uci()))
        moves.append(m.uci())
        board.push(m)
    return moves


def build(human, generated, conditions, *, blocks, per_condition, checks, fragment_plies=40, min_plies=24, seed=0):
    """Returns (stimuli, key). `conditions` is a list of generated-set names (each is a condition 'human vs that set'). Per block: `per_condition` trials
    of every condition and `checks` attention checks, all on different starts, in random order, with the human fragment on a random side. A fragment is
    the first `fragment_plies` half-moves after the start, or fewer when one of its two games ends earlier (both fragments always have the same length);
    starts where any game has fewer than `min_plies` are not used. Humans resign and lose on time, so many human games are short: the rule keeps the
    comparison fair (the generated fragment is cut at the human's length) but means the stimuli are drawn from the games that lasted."""
    for c in conditions:
        if c not in generated:
            raise ValueError(f"no games for condition {c}")
    h_by = {r["gid"]: r for r in human}
    g_by = {name: {r["gid"]: r for r in rs} for name, rs in generated.items()}
    ids = eligible(human, generated, min_plies)
    need = blocks * (per_condition * len(conditions) + checks)
    if len(ids) < need:
        raise ValueError(f"{len(ids)} usable starts, {need} needed ({blocks} blocks x ({per_condition} x {len(conditions)} conditions + {checks} checks))")
    rng = random.Random(seed)
    rng.shuffle(ids)
    take = iter(ids)
    stim, key = {"version": VERSION, "fragment_plies": fragment_plies, "blocks": []}, {}
    for b in range(blocks):
        plan = [c for c in conditions for _ in range(per_condition)] + ["check"] * checks
        rng.shuffle(plan)
        trials = []
        for i, kind in enumerate(plan):
            while True:                                              # a generated fragment equal to the human one tells nothing: that start is skipped
                gid = next(take, None)
                if gid is None:
                    raise ValueError("ran out of starts (some fragments were identical)")
                h = h_by[gid]
                human_moves = h["moves"].split()[:fragment_plies]
                if kind == "check":
                    other = random_fragment(h["start"], len(human_moves), rng)
                else:
                    gen_moves = g_by[kind][gid]["moves"].split()
                    human_moves = human_moves[:len(gen_moves)]
                    other = gen_moves[:len(human_moves)]
                if len(other) != len(human_moves):                       # a random game that ended early
                    human_moves = human_moves[:len(other)]
                if other != human_moves:
                    break
            side = rng.choice(["left", "right"])
            pair = {"left": human_moves, "right": other} if side == "left" else {"left": other, "right": human_moves}
            tid = f"B{b + 1:02d}-{i + 1:03d}"
            stim_trial = {"id": tid, "start": h["start"], "left": " ".join(pair["left"]), "right": " ".join(pair["right"]),
                          "white": _band(h["white"]), "black": _band(h["black"]), "time_control": f"{h['base'] / 60:g}+{int(h['inc'])}"}
            trials.append(stim_trial)
            key[tid] = {"condition": kind, "human_side": side, "gid": gid, "fragment_plies": len(human_moves)}
        stim["blocks"].append({"code": f"B{b + 1:02d}", "trials": trials})
    return stim, key


def audit(stim, key):
    """Checks the properties the protocol promises; returns a list of problems (empty: fine)."""
    problems = []
    gids = [k["gid"] for k in key.values()]
    if len(set(gids)) != len(gids):
        problems.append("a start is used more than once")
    text = json.dumps(stim)
    for k in key.values():
        if k["gid"].split("@")[0] in text:
            problems.append("a game id appears in the stimuli")
            break
    for blk in stim["blocks"]:
        for t in blk["trials"]:
            if set(t) != {"id", "start", "left", "right", "white", "black", "time_control"}:
                problems.append(f"{t['id']}: unexpected fields {sorted(t)}")
            if len(t["left"].split()) != len(t["right"].split()):
                problems.append(f"{t['id']}: fragments of different length")
            if t["left"] == t["right"]:
                problems.append(f"{t['id']}: identical fragments")
    sides = [k["human_side"] for k in key.values()]
    if sides and not 0.4 < sides.count("left") / len(sides) < 0.6:
        problems.append("the human side is not balanced")
    return problems
