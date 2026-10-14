import json
import random

import chess
import pytest

from chessme.humanlike import stimuli as S
from tests.unit.test_humanlike_c2st import random_game


def games(n, plies=50, seed=0, tag="x"):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        g = random_game(rng, f"{tag}{i:05d}@8", plies=plies)
        g.update({"white": 1500 + i % 400, "black": 1480 + i % 300, "base": 300, "inc": 0})
        out.append(g)
    return out


def sets(n=120, plies=50):
    human = games(n, plies, seed=1)
    gen = {}
    for k, name in enumerate(("frozen", "adapted")):
        rs = games(n, plies, seed=10 + k)
        for r, h in zip(rs, human):                              # same starts as the human games
            r["gid"], r["start"], r["white"], r["black"] = h["gid"], h["start"], h["white"], h["black"]
            board = chess.Board()
            for u in h["start"].split():
                board.push_uci(u)
            rng, moves = random.Random(hash(r["gid"]) % 1000 + k), []
            while len(moves) < plies and not board.is_game_over():
                m = rng.choice(sorted(board.legal_moves, key=lambda x: x.uci()))
                moves.append(m.uci()); board.push(m)
            r["moves"] = " ".join(moves)
        gen[name] = rs
    return human, gen


def test_eligible_needs_long_enough_fragments_in_every_set_and_is_stable():
    human, gen = sets(30, plies=50)
    gen["frozen"][0]["moves"] = "e2e4"                           # too short in one set
    ids = S.eligible(human, gen, 40)
    assert human[0]["gid"] not in ids and len(ids) <= 29
    assert ids == S.eligible(list(reversed(human)), gen, 40)       # does not depend on the order of the files
    assert S.eligible(human, gen, 70) == []


def test_blocks_hold_disjoint_starts_in_random_order_with_balanced_sides():
    human, gen = sets()
    stim, key = S.build(human, gen, ["frozen", "adapted"], blocks=4, per_condition=10, checks=3, seed=5)
    assert len(stim["blocks"]) == 4 and all(len(b["trials"]) == 23 for b in stim["blocks"]) and len(key) == 92
    assert S.audit(stim, key) == []
    for b in stim["blocks"]:
        kinds = [key[t["id"]]["condition"] for t in b["trials"]]
        assert kinds.count("frozen") == kinds.count("adapted") == 10 and kinds.count("check") == 3
        assert kinds != sorted(kinds)                              # shuffled
    for t in stim["blocks"][0]["trials"]:
        k = key[t["id"]]
        assert len(t["left"].split()) == len(t["right"].split()) == k["fragment_plies"] == 40
        h = next(r for r in human if r["gid"] == k["gid"])
        assert t[k["human_side"]] == " ".join(h["moves"].split()[:40])          # the key points to the human fragment
        assert t["start"] == h["start"]


def test_same_seed_same_stimuli_other_seed_other_stimuli():
    human, gen = sets()
    a, _ = S.build(human, gen, ["frozen"], blocks=2, per_condition=8, checks=2, seed=1)
    b, _ = S.build(human, gen, ["frozen"], blocks=2, per_condition=8, checks=2, seed=1)
    c, _ = S.build(human, gen, ["frozen"], blocks=2, per_condition=8, checks=2, seed=2)
    assert a == b and a != c


def test_nothing_that_gives_the_answer_away_is_in_the_stimuli():
    human, gen = sets()
    stim, key = S.build(human, gen, ["frozen", "adapted"], blocks=2, per_condition=5, checks=1, seed=3)
    text = json.dumps(stim)
    assert not any(w in text for w in ("clock", "spent", "result", "termination", "frozen", "adapted", "human", "gid"))
    assert not any(k["gid"].split("@")[0] in text for k in key.values())
    assert set(stim["blocks"][0]["trials"][0]) == {"id", "start", "left", "right", "white", "black", "time_control"}
    t = stim["blocks"][0]["trials"][0]
    assert t["time_control"] == "5+0" and " to " in t["white"]


def test_not_enough_starts_is_an_error_and_identical_fragments_are_skipped():
    human, gen = sets(30)
    with pytest.raises(ValueError, match="needed"):
        S.build(human, gen, ["frozen"], blocks=3, per_condition=10, checks=1, seed=0)
    assert human[0]["gid"] in S.eligible(human, gen, 40)
    gen["frozen"][0]["moves"] = human[0]["moves"]                # a generated fragment equal to the human one
    stim, key = S.build(human, gen, ["frozen"], blocks=1, per_condition=24, checks=0, seed=0)
    assert human[0]["gid"] not in {k["gid"] for k in key.values()}                 # the start with identical fragments was passed over
    assert all(t["left"] != t["right"] for t in stim["blocks"][0]["trials"])


def test_audit_finds_a_reused_start_and_a_leaked_field():
    human, gen = sets()
    stim, key = S.build(human, gen, ["frozen"], blocks=1, per_condition=6, checks=0, seed=0)
    ids = list(key)
    key[ids[1]]["gid"] = key[ids[0]]["gid"]
    stim["blocks"][0]["trials"][0]["result"] = "1-0"
    problems = S.audit(stim, key)
    assert any("more than once" in p for p in problems) and any("unexpected fields" in p for p in problems)


def test_attention_checks_pit_a_human_fragment_against_random_moves():
    human, gen = sets()
    stim, key = S.build(human, gen, ["frozen"], blocks=1, per_condition=3, checks=4, seed=9)
    checks = [t for t in stim["blocks"][0]["trials"] if key[t["id"]]["condition"] == "check"]
    assert len(checks) == 4
    for t in checks:
        board = chess.Board()
        for u in t["start"].split() + t["left"].split():             # both fragments are legal continuations of the start
            board.push_uci(u)
        board = chess.Board()
        for u in t["start"].split() + t["right"].split():
            board.push_uci(u)


def test_short_fragments_are_cut_at_the_shorter_game_and_games_below_the_minimum_are_not_used():
    human, gen = sets(60, plies=50)
    for r in human[:20]:
        r["moves"] = " ".join(r["moves"].split()[:30])             # humans who resigned after 30 half-moves
    for r in human[20:30]:
        r["moves"] = " ".join(r["moves"].split()[:10])             # and some after 10: below the minimum of 24
    gen["frozen"][40]["moves"] = " ".join(gen["frozen"][40]["moves"].split()[:28])
    assert not set(r["gid"] for r in human[20:30]) & set(S.eligible(human, gen, 24))
    stim, key = S.build(human, gen, ["frozen"], blocks=1, per_condition=45, checks=0, fragment_plies=40, min_plies=24, seed=2)
    lengths = {key[t["id"]]["gid"]: len(t["left"].split()) for t in stim["blocks"][0]["trials"]}
    assert all(len(t["left"].split()) == len(t["right"].split()) for t in stim["blocks"][0]["trials"])
    assert {lengths[r["gid"]] for r in human[:20] if r["gid"] in lengths} <= {30}
    assert {lengths[human[40]["gid"]]} <= {28} if human[40]["gid"] in lengths else True
    assert max(lengths.values()) == 40 and min(lengths.values()) >= 24
