"""The opponent's openings: for each opening family and colour, how many games, their score, and how often they went wrong early (a move in the first
`EARLY_PLIES` half-moves that gave away at least a mistake's worth) -- compared with how they do overall with that colour, so that a family only stands out when it
is clearly worse than their usual."""
MISTAKE = 0.10
EARLY_PLIES = 24
MIN_GAMES = 4


def early_loss(analysis_moves, colour, plies=EARLY_PLIES):
    """(mean loss of the opponent's moves in the first `plies` half-moves, whether one of them was at least a mistake, the worst one) from an analysis."""
    losses = [m["loss"] for m in analysis_moves if m["color"] == colour and m["ply"] <= plies]
    if not losses:
        return None, False, 0.0
    return sum(losses) / len(losses), max(losses) >= MISTAKE, max(losses)


def families(games, analyses):
    """`games`: OppGame list; `analyses`: {game id: analysis moves (may be missing)}. Returns {'white': [...], 'black': [...]} where each family row has
    name, games, score, earlyMistakes (share of analysed games with an early mistake), meanLoss, below (how far under their overall score with that colour), weak (bool),
    last (latest date) and the share of the colour's games."""
    out = {}
    for colour in ("white", "black"):
        mine = [g for g in games if g.colour == colour]
        scored = [g.score for g in mine if g.score is not None]
        overall = sum(scored) / len(scored) if scored else None
        by: dict[str, list] = {}
        for g in mine:
            by.setdefault(g.family or "Unknown opening", []).append(g)
        rows = []
        for name, gs in by.items():
            sc = [g.score for g in gs if g.score is not None]
            score = sum(sc) / len(sc) if sc else None
            early = [early_loss(analyses[g.id], colour) for g in gs if analyses.get(g.id)]
            mistakes = sum(1 for _, bad, _ in early if bad)
            mean = sum(m for m, _, _ in early if m is not None) / len(early) if early else None
            below = overall - score if overall is not None and score is not None else None
            weak_score = len(gs) >= MIN_GAMES and below is not None and below >= 0.12
            weak_early = len(early) >= MIN_GAMES and mistakes / len(early) >= 0.35
            rows.append({"name": name, "games": len(gs), "share": len(gs) / len(mine), "score": score, "wins": sum(1 for s in sc if s == 1), "draws": sum(1 for s in sc if s == 0.5),
                         "losses": sum(1 for s in sc if s == 0), "analysed": len(early), "earlyMistakes": mistakes / len(early) if early else None, "meanLoss": mean,
                         "below": below, "weak": bool(weak_score or weak_early), "why": [w for w, ok in (("scores badly", weak_score), ("often errs early", weak_early)) if ok],
                         "last": max((g.date for g in gs if g.date), default=None)})
        rows.sort(key=lambda r: -r["games"])
        out[colour] = {"overall": overall, "games": len(mine), "families": rows}
    return out
