"""Audit report over data/processed/games.jsonl (stdlib only)."""
import json
import statistics
from datetime import datetime
from collections import Counter, defaultdict


def load(path):
    return [json.loads(l) for l in open(path)]


def table(headers, rows):
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)] if rows else [len(h) for h in headers]
    fmt = "| " + " | ".join(f"{{:<{w}}}" for w in widths) + " |"
    out = [fmt.format(*headers), "|" + "|".join("-" * (w + 2) for w in widths) + "|"]
    out += [fmt.format(*[str(x) for x in r]) for r in rows]
    return "\n".join(out)


def pct(n, d):
    return f"{100 * n / d:.0f}%" if d else "-"


def wdl(rows):
    c = Counter(r["my_result"] for r in rows)
    return f"{c['win']}/{c['draw']}/{c['loss']}"


def family(r):
    o = r.get("opening")
    if not o:
        return f"({r.get('eco') or '?'})"
    return o.split(":")[0].strip()


def build(rows, cfg=None):
    out = []
    add = out.append
    usable = [r for r in rows if r["usable"]]
    add("# Data audit\n")
    dates = [r["played_at"][:10] for r in rows if r["played_at"]]
    add(f"- Games ingested: **{len(rows)}** ({min(dates)} to {max(dates)})")
    add(f"- Usable for training: **{len(usable)}** ({pct(len(usable), len(rows))})")
    add(f"- Plies in usable games: {sum(r['plies'] for r in usable)}; "
        f"my moves: ~{sum((r['plies'] + (r['color'] == 'white')) // 2 for r in usable)}\n")

    add("## Unusable games by reason\n")
    reasons = Counter(r["unusable_reason"] for r in rows if not r["usable"])
    add(table(["reason", "games"], reasons.most_common()) + "\n")

    add("## Games per account (all / usable)\n")
    byacc = defaultdict(list)
    for r in rows:
        byacc[(r["platform"], r["account"])].append(r)
    add(table(["platform", "account", "all", "usable"],
              [(p, a, len(v), sum(x["usable"] for x in v)) for (p, a), v in sorted(byacc.items())]) + "\n")

    add("## Games per time control (usable)\n")
    tcs = Counter((r["platform"], r["time_class"]) for r in usable)
    add(table(["platform", "time class", "games"], [(p, t, n) for (p, t), n in sorted(tcs.items())]) + "\n")

    add("## Variants (all games)\n")
    add(table(["variant", "games"], Counter(r["variant"] for r in rows).most_common()) + "\n")

    add("## Colour split and results, usable (W/D/L from my side)\n")
    rr = []
    for col in ("white", "black"):
        sub = [r for r in usable if r["color"] == col]
        rr.append((col, len(sub), pct(len(sub), len(usable)), wdl(sub)))
    add(table(["colour", "games", "share", "W/D/L"], rr) + "\n")

    add("## Rating over time (usable; mean [min-max] of your rating per half-year)\n")
    for plat, tc in [("lichess", "blitz"), ("lichess", "rapid"), ("chesscom", "blitz"), ("chesscom", "rapid")]:
        sub = [r for r in usable if r["platform"] == plat and r["time_class"] == tc and r["my_rating"]]
        if len(sub) < 20:
            continue
        buckets = defaultdict(list)
        for r in sub:
            y, m = int(r["played_at"][:4]), int(r["played_at"][5:7])
            buckets[f"{y}-H{1 if m <= 6 else 2}"].append(r["my_rating"])
        add(f"**{plat} {tc}** ({len(sub)} games)\n")
        add(table(["period", "games", "mean", "min-max"],
                  [(k, len(v), round(statistics.mean(v)), f"{min(v)}-{max(v)}") for k, v in sorted(buckets.items())]) + "\n")
    rated = [r for r in usable if r["my_rating"]]
    if rated:
        peak = max(rated, key=lambda r: r["my_rating"])
        add(f"Peak rating seen: **{peak['my_rating']}** ({peak['platform']} {peak['time_class']}, {peak['played_at'][:10]})\n")

    add("## Most frequent openings, usable (by opening family; W/D/L from my side)\n")
    for col in ("white", "black"):
        sub = [r for r in usable if r["color"] == col]
        fam = defaultdict(list)
        for r in sub:
            fam[family(r)].append(r)
        top = sorted(fam.items(), key=lambda kv: -len(kv[1]))[:12]
        add(f"**As {col}**\n")
        add(table(["opening", "games", "share", "W/D/L"],
                  [(k, len(v), pct(len(v), len(sub)), wdl(v)) for k, v in top]) + "\n")

    add("## Repertoire snapshot (first moves)\n")
    w1 = Counter(r["moves"].split()[0] for r in usable if r["color"] == "white" and r["moves"])
    tot = sum(w1.values())
    add("As white, first move: " + ", ".join(f"{m} {pct(n, tot)}" for m, n in w1.most_common(5)) + "\n")
    for first in ("e4", "d4"):
        sub = [r for r in usable if r["color"] == "black" and r["moves"].split()[0] == first and r["plies"] > 1]
        rep = Counter(r["moves"].split()[1] for r in sub)
        add(f"As black vs 1.{first} ({len(sub)} games): " + ", ".join(f"{m} {pct(n, len(sub))}" for m, n in rep.most_common(5)) + "\n")

    if cfg:
        from .dataset.weights import Weighter
        w = Weighter(cfg, rows)
        add("## Effective training data under this profile's filters\n")
        kept = [r for r in rows if w.game_weight(r) > 0]
        add(f"- Games kept after rating floors / excluded time classes: **{len(kept)}** of {len(usable)} usable")
        floor_drop = Counter(r["platform"] for r in usable if w.game_weight(r) == 0)
        add("- Dropped by filters (per platform): " + (", ".join(f"{k} {v}" for k, v in sorted(floor_drop.items())) or "none"))
        agg = defaultdict(lambda: [0, 0.0])  # (platform, tc) -> [my moves, weighted moves]
        early = [0, 0.0]
        for r in kept:
            for ply in w.my_plies(r):
                mw = w.move_weight(r, ply)
                a = agg[(r["platform"], r["time_class"])]
                a[0] += 1
                a[1] += mw
        rows_t = [(p, t, n, round(m)) for (p, t), (n, m) in sorted(agg.items())]
        add("")
        add(table(["platform", "time class", "my moves", "weighted moves"], rows_t))
        tot_n = sum(v[0] for v in agg.values())
        tot_w = sum(v[1] for v in agg.values())
        add(f"\n- Total my moves kept: **{tot_n}**; effective (weighted) size: **{round(tot_w)}**")
        ratings = defaultdict(list)
        for r in kept:
            ratings[r["platform"]].append(r["my_rating"])
        add("- Rating ranges kept (scales kept separate): " + ", ".join(
            f"{k} {min(v)}-{max(v)}" for k, v in sorted(ratings.items())))
        recent = sum(1 for r in kept if (w.ref - datetime.fromisoformat(r["played_at"])).days <= 365)
        add(f"- Games in the last 12 months of data: {recent} ({pct(recent, len(kept))})\n")

    add("## Data quality notes\n")
    clk = sum(1 for r in usable if any(c is not None for c in r["clocks"]))
    add(f"- Usable games with clock data: {clk} ({pct(clk, len(usable))})")
    unr = sum(1 for r in usable if not r["rated"])
    add(f"- Casual (unrated) usable games: {unr} ({pct(unr, len(usable))})")
    norat = sum(1 for r in usable if not r["my_rating"])
    add(f"- Usable games missing your rating: {norat}")
    return "\n".join(out)
