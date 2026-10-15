"""The whole preparation report from the opponent's games, the player's own games and an engine."""
import chess

from . import graph as GR
from .games import summarise
from . import openings as OP
from . import plan as PL
from . import weakness as WK

MIN_GAMES_FOR_PLAN = 3


def user_matchup(opp_fam, user_fam, colour):
    """For the openings the opponent plays (with the colour `colour` that the opponent has), how the player has done against that opening family:
    [{'name', 'theirGames', 'theirScore', 'yourGames', 'yourScore'}] most played by the opponent first. `user_fam` are the player's rows (from the games where the
    player had the other colour) keyed by the opening family name of those games."""
    mine = {r["name"]: r for r in user_fam}
    out = []
    for r in opp_fam[:10]:
        u = mine.get(r["name"])
        out.append({"name": r["name"], "theirGames": r["games"], "theirScore": r["score"], "yourGames": u["games"] if u else 0, "yourScore": u["score"] if u else None, "weak": r["weak"]})
    return out


def headline(plan, opp_sets, weak_families, traps, wk):
    """The few things to remember, in plain sentences."""
    out = []
    for colour, p in plan.items():
        if not p.get("tree"):
            continue
        top = p["tree"]["children"]
        if colour == "white" and top:
            first = top[0]
            out.append(f"As White start with {first['san']}: against what this opponent plays, the plan expects {round(100 * p['tree']['value'])}% "
                       f"({round(100 * p['tree']['gain']):+d} points over best play).")
        elif colour == "black" and top:
            parts = [f"against {k['san']} ({round(100 * k['p'])}% of their games) play {k['children'][0]['san']}" for k in top[:3] if k.get("children")]
            if parts:
                out.append("As Black: " + "; ".join(parts) + ".")
    for colour, fam in weak_families:
        out.append(f"Their weak opening as {colour}: {fam['name']} ({fam['games']} games, they score {round(100 * fam['score'])}%" + (f", {round(100 * fam['earlyMistakes'])}% of those games had an early mistake" if fam.get("earlyMistakes") else "") + ").")
    if traps:
        t = traps[0]
        out.append(f"Best trap: after {t['path'] or 'the start'} they play {t['move']} in {t['games']} of {t['visits']} games, which gives away {round(100 * t['loss'])}% (better: {t['best']}).")
    out.extend(wk["sentences"][:3])
    return out


def build(opp_games, analyses, user_games, user_analyses, search, *, handles, you=None, ref=None, nodes=None, multipv=None, budget=600, depth=5, progress=None):
    """`opp_games`, `user_games`: lists of `OppGame` (the player's own games parsed from the player's side); `analyses` / `user_analyses`: {game id: analysis moves}."""
    say = progress or (lambda f, m: None)
    out = {"opponent": {**summarise(opp_games), "handles": handles}, "notes": []}
    opp_fam = OP.families(opp_games, analyses)
    user_fam = OP.families(user_games, user_analyses) if user_games else {"white": {"families": [], "overall": None, "games": 0}, "black": {"families": [], "overall": None, "games": 0}}
    out["openings"] = opp_fam
    out["you"] = {"games": len(user_games), "white": user_fam["white"], "black": user_fam["black"], "rating": you}
    ev = PL.Evaluator(search, budget=budget)
    graphs = {c: GR.build([g for g in opp_games if g.colour == c]) for c in ("white", "black")}
    ugraphs = {c: GR.build([g for g in user_games if g.colour == c]) for c in ("white", "black")}
    count = {c: sum(1 for g in opp_games if g.colour == c) for c in ("white", "black")}

    say(0.05, "looking for places where they go wrong early")
    traps = {}
    for c in ("white", "black"):
        traps[c] = PL.find_traps(graphs[c], ev, c) if count[c] >= MIN_GAMES_FOR_PLAN else []
    out["traps"] = traps

    plan = {}
    for i, you_c in enumerate(("white", "black")):
        opp_c = "black" if you_c == "white" else "white"
        say(0.3 + 0.3 * i, f"planning your openings as {you_c}")
        if count[opp_c] < MIN_GAMES_FOR_PLAN:
            plan[you_c] = {"tree": None, "reason": f"Only {count[opp_c]} of their games were played as {opp_c}: not enough to plan against ({MIN_GAMES_FOR_PLAN} needed)."}
            continue
        planner = PL.Planner(ev, graphs[opp_c], ugraphs[you_c], you_c, depth=depth)
        tree = planner.tree()
        plan[you_c] = {"tree": tree, "lines": PL.pick_lines(tree), "pgn": PL.to_pgn(tree, you_c, f"Prepared as {you_c}"),
                       "matchup": user_matchup(opp_fam[opp_c]["families"], user_fam["white" if you_c == "black" else "black"]["families"], opp_c)}
    out["plan"] = plan
    if ev.exhausted:
        out["notes"].append("The engine search budget ran out: the deepest parts of the plan use fewer searches. Run the preparation again with a bigger budget for more.")

    say(0.85, "looking at their middlegames and endgames")
    wk = WK.report(opp_games, analyses, ref=ref, nodes=nodes, multipv=multipv)
    out["weakness"] = wk
    weak = [(c, f) for c in ("white", "black") for f in opp_fam[c]["families"] if f["weak"]][:4]
    out["headline"] = headline(plan, opp_fam, weak, sorted(traps["white"] + traps["black"], key=lambda t: -(t["games"] * t["loss"])), wk)
    if wk["games"] < 10:
        out["notes"].append(f"Only {wk['games']} of their games were analysed in full: middlegame and endgame findings are tentative. Use a deeper preparation for more.")
    if opp_games and len(opp_games) < 30:
        out["notes"].append(f"Only {len(opp_games)} games of this opponent were found: the picture is rough.")
    out["searches"] = ev.searches
    say(1.0, "done")
    return out
