"""Do the famous anchor players look different from each other, and from the online cohort, through the game-level features and the embedding?

The anchors' PGN archives (PGN Mentor, classical over-the-board games) are read one player at a time: the game-level features (openings, game
shape; there are no clocks in these files) are computed for the anchor's games in the peak years, stored, and the archive is deleted. Only
derived numbers are kept (no moves, no clocks), under data/ (git-ignored), for local analysis. The files have the same format as the cohort's,
so `games_fetch.load_players` reads them.

`evaluate` then asks the identification question the cohort passed: with one half of an anchor's games as the reference and the other half as the
query, is the nearest anchor the right one? (raw aggregated features and the trained embedding; chance is 1 / number of anchors.) It also asks
what the embedding sees instead: whether nearest anchors are contemporaries (era) and where the anchors sit relative to the online cohort (format)."""
import json
import time
from pathlib import Path

import numpy as np

from . import anchor_sources as AS
from . import anchors as A
from . import embed as EM
from . import gamefeatures as G
from . import games_fetch as GF
from . import gamestats as S

MIN_GAMES = 30


def player_file(out, key):
    return Path(out) / "games" / f"anchor_{key}.json.gz"


def build_player(key, spec, paths, *, max_games=100, min_games=MIN_GAMES, seed=1):
    """The stored record for one anchor from its game files, or None when too few serious games are found in the peak years."""
    games, window, _ = A.games_in_peak(paths, spec, want=max_games)
    if len(games) > max_games:                                   # an even spread over the years, not the first ones
        pick = np.random.default_rng(seed).permutation(len(games))[:max_games]
        games = [games[i] for i in sorted(pick)]
    recs = []
    for text, color, elo in games:
        r = GF.game_record(text, color, elo)
        if r is None:
            continue
        r["moves"], r["clocks"] = "", []                        # derived numbers only
        r["meta"]["year"] = A._year(A.quick_headers(text))
        recs.append(r)
    if len(recs) < min_games:
        return None
    elos = [r["elo"] for r in recs if r["elo"]]
    return {"pid": f"anchor_{key}", "short": False, "rating": int(np.median(elos)) if elos else 0, "n": len(recs), "window": list(window),
            "names": list(G.FEATURE_NAMES), "games": recs}


def fetch(config, out, tmp, *, files_dir=None, only=None, max_games=100, pause=1.0, getter=None, keep_raw=False, log=print):
    """Resumable, one anchor at a time (a finished anchor is a file). Returns {"done", "missing", "short"}."""
    out, tmp = Path(out), Path(tmp)
    keys = [k for k, v in config["anchors"].items() if v.get("selected", True) and (not only or k in only)]
    stats = {"done": 0, "missing": [], "short": []}
    for n, key in enumerate(keys, 1):
        if player_file(out, key).exists():
            log(f"[{n}/{len(keys)}] {key}: already done")
            stats["done"] += 1
            continue
        spec = config["anchors"][key]
        local = [p for p in Path(files_dir).glob("*") if p.suffix.lower() in (".pgn", ".zip") and key in p.stem.lower()] if files_dir else []
        raw = None
        if local:
            paths = local
        else:
            raw = tmp / f"{key}.zip"
            if AS.download(AS.BASE.format(name=AS.file_stem(spec)), raw, getter=getter) is None:
                log(f"[{n}/{len(keys)}] {key}: no file (not on PGN Mentor, or the download failed)")
                stats["missing"].append(key)
                continue
            paths = [raw]
        try:
            rec = build_player(key, spec, paths, max_games=max_games)
        finally:
            if raw is not None and raw.exists() and not keep_raw:
                raw.unlink()
        if rec is None:
            log(f"[{n}/{len(keys)}] {key}: fewer than {MIN_GAMES} usable serious games in the peak years")
            stats["short"].append(key)
            continue
        GF.write_player(player_file(out, key), rec)
        stats["done"] += 1
        log(f"[{n}/{len(keys)}] {key}: {rec['n']} games, window {rec['window']}, rating ~{rec['rating'] or 'not given'}")
        if pause and raw is not None:
            time.sleep(pause)
    return stats


# ---- evaluation ------------------------------------------------------------------------------------------------------

def _halves(arrs, parity):
    return np.array([np.nanmean(np.where(np.isfinite(g[parity::2]), g[parity::2], np.nan), axis=0) for g in arrs])


def _cos_nearest(E):
    d = E @ E.T
    np.fill_diagonal(d, -np.inf)
    return d.argmax(1)


def evaluate(anchors, model, norm, cohort=None, era_gap=15):
    """`anchors`, `cohort`: {id: (rating, features (n, F), metas)}. Returns identification of the anchors by raw features and by the embedding, whether the
    embedding's nearest anchor is a contemporary (within `era_gap` years, against the share of all anchor pairs that are), and (with a cohort) how far
    the anchors are from the cohort compared with each other."""
    ids = sorted(anchors)
    games = [np.asarray(anchors[i][1], dtype=np.float32) for i in ids]
    n = len(ids)
    gn = [norm(g) for g in games]
    EA, EB = EM.embed_bags(model, gn, list(range(n)), 0), EM.embed_bags(model, gn, list(range(n)), 1)
    emb = S.identification(EA, EB, list(range(EA.shape[1])))
    XA, XB = _halves(games, 0)[:, norm.keep], _halves(games, 1)[:, norm.keep]
    raw = S.identification(XA, XB, list(range(len(norm.keep))))
    years = np.array([np.nanmean([m.get("year") if m.get("year") else np.nan for m in anchors[i][2]]) if anchors[i][2] else np.nan for i in ids])
    out = {"n_anchors": n, "chance": emb["chance"], "embedding_top1": emb["top1"], "embedding_top5": emb["topk"], "raw_top1": raw["top1"], "raw_top5": raw["topk"]}
    ok = np.isfinite(years)
    if ok.sum() > 3:
        E = (EA + EB) / 2
        E = E / np.linalg.norm(E, axis=1, keepdims=True)
        near = _cos_nearest(E)
        gap = np.abs(years[:, None] - years[None, :])
        pair_share = float(np.mean([(gap[i][ok & (np.arange(n) != i)] <= era_gap).mean() for i in range(n) if ok[i]]))
        hit = np.mean([abs(years[i] - years[near[i]]) <= era_gap for i in range(n) if ok[i] and ok[near[i]]])
        out.update(nearest_is_contemporary=float(hit), contemporary_pair_share=pair_share, era_gap_years=era_gap,
                   nearest={ids[i]: ids[int(near[i])] for i in range(n)})
    if cohort:
        cg = [norm(np.asarray(v[1], dtype=np.float32)) for v in cohort.values()]
        C = EM.embed_bags(model, cg, list(range(len(cg))), 0)
        A_ = (EA + EB) / 2
        A_ = A_ / np.linalg.norm(A_, axis=1, keepdims=True)
        to_cohort = float(np.mean((A_ @ C.T).max(1)))
        aa = A_ @ A_.T
        np.fill_diagonal(aa, -np.inf)
        out.update(nearest_cohort_similarity=to_cohort, nearest_anchor_similarity=float(aa.max(1).mean()))
    return out


def render(res):
    lines = ["# Anchors through the game-level features and the embedding", "",
             f"{res['n_anchors']} anchor players (classical over-the-board games in their peak years; no clock data). Identification: one half of an anchor's games "
             "is the reference, the other half the query; is the nearest anchor the right one?", "",
             "| Method | top-1 | top-5 | chance (top-1) |", "|---|---|---|---|",
             f"| raw aggregated features | {100 * res['raw_top1']:.1f}% | {100 * res['raw_top5']:.1f}% | {100 * res['chance']:.1f}% |",
             f"| trained embedding | {100 * res['embedding_top1']:.1f}% | {100 * res['embedding_top5']:.1f}% | {100 * res['chance']:.1f}% |", ""]
    if "nearest_is_contemporary" in res:
        lines += [f"The embedding's nearest anchor is a contemporary (within {res['era_gap_years']} years) for {100 * res['nearest_is_contemporary']:.0f}% of the anchors; "
                  f"{100 * res['contemporary_pair_share']:.0f}% of all anchor pairs are, so that is the level of chance. A value well above it means the embedding sees era "
                  "(openings and game shape change over the decades), not personal style.", ""]
    if "nearest_cohort_similarity" in res:
        lines += [f"Mean cosine similarity of an anchor to its most similar cohort player: {res['nearest_cohort_similarity']:.2f}; to its most similar other anchor: "
                  f"{res['nearest_anchor_similarity']:.2f}. Anchors closer to each other than to the online players means the format (classical over-the-board against online "
                  "blitz and rapid) dominates the embedding.", ""]
    lines += ["Reading it: the embedding was trained on online games only, so a failure here is not a failure on the cohort (where it identifies held-out players about 85% of the time). "
              "What is tested is whether *the same features* carry a stable per-player signature for players from other eras and formats.", ""]
    return "\n".join(lines)
