import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import audit as audit_mod
from . import config
from .ingest import chesscom, lichess, normalize

DEFAULT_PROFILE = os.environ.get("CHESSME_PROFILE", "example")  # your own profile: see configs/profiles/example.yaml
ENGINE_BIN = config.ROOT / "engine" / "build" / "chessme-engine"
TEXEL_BIN = config.ROOT / "engine" / "build" / "texel"

FETCHERS = {"lichess": lichess.fetch, "chesscom": chesscom.fetch}


def cmd_fetch(args):
    cfg = config.load_profile(args.profile)
    for acct in cfg["accounts"]:
        if args.only and acct["username"].lower() not in {u.lower() for u in args.only}:
            continue
        print(f"[{acct['platform']}] {acct['username']}")
        FETCHERS[acct["platform"]](acct["username"], cfg["_raw_dir"])


def cmd_ingest(args):
    normalize.ingest(config.load_profile(args.profile))


def cmd_audit(args):
    cfg = config.load_profile(args.profile)
    proc = cfg["_raw_dir"].parent / "processed"
    text = audit_mod.build(audit_mod.load(proc / "games.jsonl"), cfg)
    (proc / "audit.md").write_text(text)
    print(text)
    print(f"\n(saved to {proc / 'audit.md'})")


def _opts(pairs):
    out = {}
    for item in pairs or []:
        k, _, v = item.partition("=")
        out[k] = v
    return out


def _limit(args):
    from .match import SearchLimit
    lim = SearchLimit(nodes=args.nodes, depth=args.depth, movetime=args.movetime)
    if not lim.kwargs():
        raise SystemExit("choose a search limit: --nodes N, --depth D or --movetime MS")
    return lim


def _adjudication(args):
    from .match import Adjudication
    return Adjudication(resign_cp=0, draw_cp=0) if args.no_adjudicate else Adjudication()


def cmd_openings(args):
    from . import openings
    cfg = config.load_profile(args.profile)
    games = cfg["_raw_dir"].parent / "processed" / "games.jsonl"
    if args.random:
        fens = openings.random_openings(args.random, plies=args.plies, seed=args.seed)
    else:
        fens = openings.from_games(games, plies=args.plies, limit=args.n, seed=args.seed)
    print(f"{len(fens)} unique opening positions after {args.plies} plies")
    if args.balance_engine:
        fens = openings.filter_balanced(args.balance_engine, fens, depth=args.balance_depth, max_cp=args.balance_cp)
        print(f"{len(fens)} within +-{args.balance_cp} cp at depth {args.balance_depth}")
    openings.write_openings(args.out, fens)
    print(f"wrote {args.out}")


def cmd_match(args):
    from . import openings
    from .match import EngineSpec, run_match
    a = EngineSpec.make(args.a_name or Path(args.a).name, args.a, _opts(args.a_opt))
    b = EngineSpec.make(args.b_name or Path(args.b).name, args.b, _opts(args.b_opt))
    fens = openings.read_openings(args.openings)
    sprt = tuple(args.sprt) if args.sprt else None

    def progress(r):
        if r.pairs % 10 == 0:
            print(f"  {r.pairs} pairs  W/D/L {r.wins}/{r.draws}/{r.losses}  LLR {r.llr:+.2f}", flush=True)

    res = run_match(a, b, fens, _limit(args), _adjudication(args), concurrency=args.concurrency,
                    max_pairs=args.pairs, sprt=sprt, pgn_path=args.pgn, progress=progress)
    print(res.summary(*(sprt[:2] if sprt else (None, None))))


def cmd_selfplay(args):
    from . import openings, selfplay
    from .match import EngineSpec
    spec = EngineSpec.make(Path(args.engine).name, args.engine, _opts(args.opt))
    fens = openings.read_openings(args.openings)

    def progress(games, positions):
        if games % 50 == 0:
            print(f"  {games} games, {positions} positions", flush=True)

    played, positions, errors = selfplay.generate(
        spec, fens, args.games, args.out, _limit(args), _adjudication(args), concurrency=args.concurrency,
        seed=args.seed, keep_prob=args.keep_prob, progress=progress)
    print(f"{played} games, {positions} positions, {errors} games with engine errors -> {args.out}")


def cmd_texel_data(args):
    from .dataset import texel_data
    from .dataset.weights import Weighter
    cfg = config.load_profile(args.profile)
    rows = audit_mod.load(cfg["_raw_dir"].parent / "processed" / "games.jsonl")
    weighter = Weighter(cfg, rows)
    n = 0
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        for fen, value, weight in texel_data.from_games(rows, weighter, keep_prob=args.keep_prob,
                                                        weight_scale=args.weight_scale, seed=args.seed):
            f.write(f"{fen} | {value} | {weight:.4f}\n")
            n += 1
    print(f"wrote {n} positions -> {args.out}")


def cmd_tune(args):
    if not TEXEL_BIN.exists():
        raise SystemExit(f"{TEXEL_BIN} not found: run `make -C engine` first")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as merged:
        for path in args.data:
            merged.write(Path(path).read_text())
    cmd = [str(TEXEL_BIN), "--data", merged.name, "--out", args.out, "--epochs", str(args.epochs),
           "--lr", str(args.lr), "--l2", str(args.l2), "--val", str(args.val)]
    if args.params_in:
        cmd += ["--params-in", args.params_in]
    if args.max_positions:
        cmd += ["--max-positions", str(args.max_positions)]
    if args.freeze:
        cmd += ["--freeze", args.freeze]
    try:
        sys.exit(subprocess.run(cmd).returncode)
    finally:
        Path(merged.name).unlink(missing_ok=True)


def cmd_book(args):
    from .book import build
    from .uci_client import UciEngine
    cfg = config.load_profile(args.profile)
    rows = audit_mod.load(cfg["_raw_dir"].parent / "processed" / "games.jsonl")
    overrides = {"max_ply": args.max_ply, "min_games": args.min_games,
                 "min_position_games": args.min_position_games, "min_share": args.min_share}
    if args.holdout:
        from .book import evaluate
        from .dataset.weights import Weighter
        train, test = evaluate.split_by_time(rows, args.holdout)
        held = build.build_book(cfg, train, overrides)
        res = evaluate.evaluate(held.entries, test, Weighter(cfg, rows), held.params["max_ply"])
        print(evaluate.format_evaluation(res))
        print()
    engine = UciEngine(args.sanity_engine).start() if args.sanity_engine else None
    try:
        result = build.build_book(cfg, rows, overrides, sanity_engine=engine)
    finally:
        if engine:
            engine.close()
    out, report_path = build.save(result, args.out or config.ROOT / "profiles" / args.profile / "book.bin")
    print(f"{len(result.entries)} book moves in {len({e.key for e in result.entries})} positions "
          f"from {result.tree.games_used} games")
    if result.sanity_dropped is not None:
        print(f"engine check removed {len(result.sanity_dropped)} moves")
    print(f"wrote {out} and {report_path}")


def cmd_me_data(args):
    from .model import data as D
    if args.source == "user":
        from .dataset.weights import Weighter
        cfg = config.load_profile(args.profile)
        rows = audit_mod.load(cfg["_raw_dir"].parent / "processed" / "games.jsonl")
        meta = D.build_user(rows, Weighter(cfg, rows), args.out, test_fraction=args.test_fraction, min_ply=args.min_ply,
                            train_time_classes=tuple(args.train_time_classes.split(",")) if args.train_time_classes else None)
    else:
        flt = D.LichessFilter(rating_min=args.rating_min, rating_max=args.rating_max, bin_width=args.bin_width,
                              time_classes=tuple(args.time_classes.split(",")))

        def progress(seen, accepted, samples, nbytes):
            print(f"  {seen} games read, {accepted} used, {samples} samples, {nbytes / 1e6:.0f} MB", flush=True)

        meta = D.build_lichess(args.source, args.out, samples_per_bin=args.samples_per_bin, flt=flt,
                               keep_prob=args.keep_prob, min_ply=args.min_ply, min_clock=args.min_clock,
                               budget_bytes=int(args.budget_mb * 1e6) if args.budget_mb else None, workers=args.workers,
                               seed=args.seed, progress=progress)
    print(json.dumps(meta, indent=2))


def cmd_me_train(args):
    from .model import data as D
    from .model import net, train
    tr = D.load_shards(sorted(Path(args.data).glob("train*.npz")))
    val = D.load_shards([Path(args.val_data or args.data) / "val.npz"])
    net_cfg = net.NetConfig(blocks=args.blocks, channels=args.channels, policy_dim=args.policy_dim)
    tcfg = train.TrainConfig(batch_size=args.batch_size, lr=args.lr, epochs=args.epochs, eval_every=args.eval_every,
                             patience=args.patience, device=args.device, init_from=args.init_from or "",
                             freeze_body=args.freeze_body, max_steps=args.max_steps, weight_decay=args.weight_decay,
                             warmup_steps=args.warmup_steps, seed=args.seed)
    train.train(tr, val, net_cfg, tcfg, args.out)


def cmd_me_eval(args):
    from .model import data as D
    from .model import net, train
    device = train.pick_device(args.device)
    model, meta = net.load_checkpoint(args.ckpt, device)
    data = D.load_shards([Path(args.data) / f"{args.split}.npz"])
    print(train.format_eval(train.evaluate(model, data, device, limit=args.limit),
                            f"{args.ckpt} on {args.data}/{args.split}.npz"))


def cmd_me_baseline(args):
    from .model import baselines
    from .model import data as D
    data = D.load_shards([Path(args.data) / f"{args.split}.npz"])
    res = baselines.engine_match(args.engine, data, nodes=args.nodes, limit=args.limit)
    print(f"engine (nodes={args.nodes}) best move == played move: {100 * res['top1']:.1f}% of {res['n']} positions")
    for k, v in res["by_rating"].items():
        print(f"  mover rating {k}-{k + 199}: {100 * v:.1f}%")


def cmd_me_fix_ep(args):
    from .model import data as D
    total = 0
    for path in sorted(Path(args.data).glob("*.npz")):
        n = D.fix_shard_ep(path)
        total += n
        print(f"{path.name}: {n} en-passant fields changed")
    print(f"{total} changed in total")


def cmd_me_merge(args):
    from .model import data as D
    print(json.dumps(D.merge_datasets(args.sources, args.out), indent=2))


def _compare_items(args):
    import numpy as np

    from .book import evaluate as bev
    from .dataset.weights import Weighter
    from .model import compare, data as D
    if args.set == "lichess-test":
        items = compare.items_from_shard(D.load_shards([Path(args.data) / "test.npz"]), limit=args.limit, seed=args.seed)
    else:
        cfg = config.load_profile(args.profile)
        rows = audit_mod.load(cfg["_raw_dir"].parent / "processed" / "games.jsonl")
        usable, test_rows = bev.split_by_time(rows, 0.1)
        val_rows = usable[int(len(usable) * 0.95):]
        items = compare.items_from_games(test_rows if args.set == "user-test" else val_rows, Weighter(cfg, rows))
        if args.limit and args.limit < len(items):
            keep = np.sort(np.random.default_rng(args.seed).permutation(len(items))[:args.limit])
            items = [items[i] for i in keep]
    return items


def _style_split(args):
    """(train items, test items) of the player's own moves: the newest 10% of games are the test set."""
    from .book import evaluate as bev
    from .dataset.weights import Weighter
    from .model import compare
    cfg = config.load_profile(args.profile)
    rows = audit_mod.load(cfg["_raw_dir"].parent / "processed" / "games.jsonl")
    usable, test_rows = bev.split_by_time(rows, 0.1)
    w = Weighter(cfg, rows)
    return compare.items_from_games(usable, w), compare.items_from_games(test_rows, w)


def _candidates_for_items(items, args, label):
    import time

    from .style import candidates as SC
    from .uci_client import UciEngine
    print(f"{label}: {len(items)} positions, engine {args.nodes} nodes, MultiPV {args.multipv}, window {args.window} cp", flush=True)
    positions, t0 = [], time.time()
    with UciEngine(args.engine, options=SC.engine_options(args.engine, args.multipv)) as eng:
        for i, it in enumerate(items):
            p = SC.candidates_for(eng, it, nodes=args.nodes, multipv=args.multipv, window=args.window)
            if p is not None:
                positions.append(p)
            if (i + 1) % 500 == 0:
                print(f"  {i + 1}/{len(items)}  {time.time() - t0:.0f}s", flush=True)
    chose = sum(p.chosen >= 0 for p in positions)
    print(f"  {len(positions)} positions with a choice; the played move was an approved candidate in {chose} "
          f"({100 * chose / max(len(positions), 1):.1f}%)")
    return positions


def cmd_style_pop_data(args):
    import time

    from .style import candidates as SC, population as SP
    t0 = time.time()

    def show(st):
        fill = " ".join(f"{b}:{c}" for b, c in st["per_bin"].items())
        print(f"  [{time.time() - t0:5.0f}s] {st['games_seen']:,} games scanned, {st['games_used']:,} used, "
              f"{st['decisions']:,} decisions, {st['bytes_read'] / 1e6:.0f} MB read (streamed, nothing stored)\n"
              f"        per bin -> {fill}", flush=True)

    stats = {}
    print(f"sampling players rated {args.rating_lo}-{args.rating_hi}, {args.per_bin} decisions per {args.bin_width}-point bin, "
          f"time classes {args.time_classes}, read budget {args.budget_mb:.0f} MB", flush=True)
    items = SP.population_items(args.source, lo=args.rating_lo, hi=args.rating_hi, per_bin=args.per_bin,
                                bin_width=args.bin_width, time_classes=tuple(args.time_classes),
                                per_game=args.per_game, seed=args.seed, budget_bytes=int(args.budget_mb * 1e6),
                                progress=show, stats=stats)
    show(stats)
    print(f"stopped because: {stats['stop_reason']}; sampled {len(items)} decisions")
    short = {b: c for b, c in stats["per_bin"].items() if c < args.per_bin}
    if short:
        print(f"WARNING: bins below the target of {args.per_bin} (the read budget ran out or the dump has too few "
              f"games there): {short}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "sampling.json").write_text(json.dumps({**stats, "source": args.source, "per_bin_target": args.per_bin}, indent=1))
    SC.save(_candidates_for_items(items, args, "population"), out / "train.npz", judge=SC.judge_label(args.engine, args.nodes))


def cmd_style_cohort_fetch(args):
    import secrets

    from .style import cohort as CO
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    salt_path = out / "salt"
    if not salt_path.exists():
        salt_path.write_text(secrets.token_hex(16))
    salt = salt_path.read_text().strip()
    cand_path = out / "candidates.json"  # usernames: local only, never publish
    if cand_path.exists():
        cand = json.loads(cand_path.read_text())
        print(f"reusing {len(cand)} candidates from {cand_path}")
    else:
        nb = CO.n_bins(args.rating_lo, args.rating_hi)
        per_bin = -(-args.players * args.oversample // nb)
        st = {}
        print(f"collecting about {per_bin} candidates in each of {nb} rating bins from {args.source} "
              f"(headers only, budget {args.budget_mb:.0f} MB, nothing stored)", flush=True)
        cand = CO.collect_candidates(args.source, lo=args.rating_lo, hi=args.rating_hi, per_bin=per_bin,
                                     budget_bytes=int(args.budget_mb * 1e6), stats=st)
        cand_path.write_text(json.dumps(cand))
        print(f"  {len(cand)} candidates; {st['games_seen']:,} games scanned, {st['bytes_read'] / 1e6:.0f} MB read, "
              f"stopped: {st['stop_reason']}; per bin {st['per_bin']}")
    res = CO.fetch_cohort(cand, out, salt, players=args.players, lo=args.rating_lo, hi=args.rating_hi,
                          n_games=args.games, per_game=args.per_game, min_games=args.min_games, pause=args.pause,
                          log=lambda m: print(m, flush=True))
    print(f"done: {res}")


def cmd_style_cohort_analyze(args):
    from .style import cohort as CO
    CO.analyse_cohort(args.out, args.engine, nodes=args.nodes, multipv=args.multipv, window=args.window,
                      workers=args.workers)


def cmd_style_cohort_report(args):
    from .style import reliability as RL
    players = RL.load_cohort(args.out)
    sh = RL.split_half(players, min_usable=args.min_usable)
    trait = RL.personal_vs_population(players, min_usable=args.min_usable)
    text = RL.render(sh, trait)
    shr = RL.shrunk_trait_test(players, min_usable=args.min_usable)
    m, se = shr["gain"]
    text += ("\n\nFair test (each preference shrunk towards the population by its own reliability; reliabilities estimated on other players):"
             f"\n  {shr['n_players']} players scored: gain {m:+.4f} +/- {se:.4f} log-loss per decision over the population style"
             f" ({'a real, small personal signal' if m > 3 * se else 'no detectable personal signal'})"
             + "".join(f"\n  fixed alpha {a}: {g:+.4f} +/- {e:.4f}" for a, (g, e) in shr["fixed"].items()))
    print(text)
    (Path(args.out) / "reliability.txt").write_text(text)


def cmd_style_data(args):
    import numpy as np

    from .style import candidates as SC
    train, test = _style_split(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    for name, items, limit in (("train", train, args.limit), ("test", test, max(args.limit // 4, 1))):
        if len(items) > limit:
            items = [items[i] for i in np.sort(rng.permutation(len(items))[:limit])]
        SC.save(_candidates_for_items(items, args, name), out / f"{name}.npz", judge=SC.judge_label(args.engine, args.nodes))


def cmd_style_anchors_build(args):
    import yaml

    from .style import anchors as SA
    cfg = yaml.safe_load(Path(args.config).read_text())
    SA.build_anchors(cfg, args.files, args.out, max_games=args.max_games, per_game=args.per_game, only_selected=not args.all)
    print(f"next: chessme style-cohort-analyze --out {args.out} --engine stockfish")


def _file_logger(path):
    """A log(msg) function that prints to the terminal AND appends to `path`, every line timestamped and flushed."""
    import time as _t

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a", buffering=1)

    def log(msg):
        stamp = _t.strftime("%H:%M:%S")
        for line in str(msg).split("\n"):
            print(line, flush=True)
            f.write(f"{stamp} {line}\n")
    return log


def cmd_style_anchors_fetch(args):
    import yaml

    from .style import anchor_sources as AS
    cfg = yaml.safe_load(Path(args.config).read_text())
    log = _file_logger(args.log)
    log(f"=== style-anchors-fetch {' '.join(sys.argv[2:])}")
    AS.fetch_anchors(cfg, args.out, args.tmp, files_dir=args.files, only=set(args.only) if args.only else None,
                     max_games=args.max_games, per_game=args.per_game, keep_raw=args.keep_raw, redo=args.redo, log=log)
    print(f"next: chessme style-cohort-analyze --out {args.out} --engine stockfish")


def cmd_style_anchors_games(args):
    import yaml

    from .style import anchor_games as AG
    cfg = yaml.safe_load(Path(args.config).read_text())
    log = _file_logger(args.log)
    log(f"=== style-anchors-games {' '.join(sys.argv[2:])}")
    st = AG.fetch(cfg, args.out, args.tmp, files_dir=args.files, only=set(args.only) if args.only else None, max_games=args.max_games, pause=args.pause,
                  keep_raw=args.keep_raw, log=log)
    log(f"{st['done']} anchors done; missing: {st['missing'] or 'none'}; too few games: {st['short'] or 'none'}")
    print(f"next: chessme style-anchors-games-report --data {args.out}")


def cmd_style_anchors_games_report(args):
    from .style import anchor_games as AG, embed as EM, games_fetch as GF
    anchors = GF.load_players(args.data, min_games=AG.MIN_GAMES)
    if len(anchors) < 8:
        sys.exit(f"only {len(anchors)} anchors in {args.data}: run style-anchors-games first")
    model, norm, _ = EM.load(args.embed)
    cohort = GF.load_players(args.cohort, min_games=30) if args.cohort and (Path(args.cohort) / "games").exists() else None
    res = AG.evaluate(anchors, model, norm, cohort=cohort)
    text = AG.render(res)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)


def cmd_mechess_clock_fit(args):
    from .book import evaluate as EV
    from .mechess import clock as CK
    cfg = config.load_profile(args.profile)
    rows = audit_mod.load(cfg["_raw_dir"].parent / "processed" / "games.jsonl")
    usable = [r for r in rows if r.get("usable")]
    test = [r for i, r in enumerate(usable) if i % args.every == 0]          # every Nth game: all time controls are in the check
    train = [r for i, r in enumerate(usable) if i % args.every]
    from .mechess import agreement as AGR
    model = CK.fit(train)
    print(f"clock model from {model.meta['moves']} of your moves in {len(train)} games; {model.meta['cells']} cells")
    print(AGR.render_clock(AGR.clock_agreement(model, test)))
    CK.fit(rows).save(args.out)                                        # the saved model uses every game
    print(f"written {args.out}; use it with: chessme mechess --clock {args.out}")


def cmd_mechess_agreement(args):
    import random

    from .book import build as BB, evaluate as EV
    from .book.format import write_book
    from .mechess import agreement as AGR, dial, priors
    from .mechess.calibration import Calibration
    from .mechess.controller import BookReader, BookStack, TheoryBands
    from .style import candidates as SC, model as SM
    from .uci_client import UciEngine
    cfg = config.load_profile(args.profile)
    rows = audit_mod.load(cfg["_raw_dir"].parent / "processed" / "games.jsonl")
    train_rows, test_rows = EV.split_by_time(rows, args.holdout)
    with tempfile.TemporaryDirectory() as tmp:
        result = BB.build_book(cfg, train_rows)
        write_book(Path(tmp) / "own.bin", result.entries)
        own, theory = BookReader(Path(tmp) / "own.bin"), TheoryBands(args.theory)
        book = AGR.book_agreement({"personal (older games only)": own, "theory of the rating": theory, "personal then theory": BookStack([own, theory])},
                                  test_rows, max_ply=args.plies)
    print(f"books: {book['games']} held-out games")
    train, test = SC.load(Path(args.style_data) / "train.npz"), SC.load(Path(args.style_data) / "test.npz")
    style = SM.fit(train)                                                  # fitted on the training games only
    SM.save_model(style, Path(args.out).with_suffix(".style.json"))
    positions = [p for p in test if p.platform == 0]
    random.Random(0).shuffle(positions)
    positions = positions[:args.max_positions]
    cal = Calibration.load(args.calibration) if args.calibration else None
    table = cal.table() if cal else None
    engine = UciEngine([args.engine]).start()
    try:
        move = AGR.move_agreement(positions, engine, {"uniform (engine's own ranking)": priors.UniformPrior(),
                                                      "your style": priors.StylePrior(Path(args.out).with_suffix(".style.json"))},
                                  table=table, calibration=cal)
    finally:
        engine.close()
    text = AGR.render(book, move)
    if args.sweep:
        engine = UciEngine([args.engine]).start()
        try:
            rows_ = AGR.sweep(positions, engine, {"uniform": priors.UniformPrior(), "your style": priors.StylePrior(Path(args.out).with_suffix(".style.json"))},
                              [tuple(float(x) for x in v.split(",")) for v in args.sweep], table=table or dial.DEFAULT_TABLE, calibration=cal)
        finally:
            engine.close()
        text += "\n" + AGR.render_sweep([(w, int(k), r) for w, k, r in rows_])
    Path(args.out).with_suffix(".style.json").unlink(missing_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)


def cmd_style_anchors_verify(args):
    import yaml

    from .ingest import http
    from .style import anchor_verify as AV
    log = _file_logger(args.log)
    log(f"=== style-anchors-verify {' '.join(sys.argv[2:])}")
    cfg = yaml.safe_load(Path(args.config).read_text())
    html = http.get(AV.PAGE_URL).text
    AV.verify(cfg, html, args.tmp, only=set(args.only) if args.only else None, log=log)


def cmd_style_anchors_report(args):
    import yaml

    from .style import anchors as SA, candidates as SC, reliability as RL
    anchors = RL.load_cohort(args.out)
    cfg = yaml.safe_load(Path(args.config).read_text())["anchors"]
    hyp = {f"anchor_{k}": v.get("hypothesis", "") for k, v in cfg.items()}
    conf = SA.anchor_confusion(anchors, chunk=args.chunk)
    rank = None
    if args.player:
        train, test = SC.load(Path(args.player) / "train.npz"), SC.load(Path(args.player) / "test.npz")
        rank = SA.rank_anchors(anchors, train, player_test=test)
    text = SA.render(conf, rank, hyp)
    print(text)
    (Path(args.out) / "anchor_report.txt").write_text(text)


def _ladder_args(args):
    from . import openings
    from .match import SearchLimit
    fens = openings.read_openings(args.openings) if args.openings else openings.random_openings(args.random_openings, seed=args.seed)
    return fens, SearchLimit(movetime=args.movetime), dict(
        pairs_per_round=args.pairs, target_se=args.se, min_games=args.min_games, max_games=args.max_games,
        concurrency=args.concurrency)


def cmd_strength(args):
    from . import calibrate
    from .match import EngineSpec
    fens, limit, kw = _ladder_args(args)
    spec = EngineSpec.make(Path(args.engine).name, args.engine, _opts(args.opt))
    r = calibrate.measure(spec, args.opponent, fens, limit, start=args.start, log=lambda m: print(m, flush=True), **kw)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(r, indent=1))
    print(f"\n{r['name']}: {r['elo']:.0f} +/- {r['ci95']:.0f} Elo on the {r['opponent']} UCI_Elo scale "
          f"(movetime {r['limit'].get('movetime')} ms, {r['games']} games, {r['stop']}) -> {args.out}")


def cmd_calibrate(args):
    from . import calibrate
    fens, limit, kw = _ladder_args(args)
    command = calibrate.mechess_command(args.engine, args.prior, args.book, table=args.table, maia3_repo=args.maia3_repo,
                                        maia3_size=args.maia3_size, extra_path=args.extra_path)
    from .mechess import dial
    calibrate.calibrate_dial(args.dial, command, args.opponent, fens, limit, args.out, redo=args.redo, offset=args.offset,
                             table=dial.load_table(args.table) if args.table else dial.DEFAULT_TABLE,
                             log=lambda m: print(m, flush=True), **kw)
    print(f"\ncalibration written to {args.out}; use it with:  chessme mechess --calibration {args.out} --elo <target>")


def cmd_style_summary(args):
    import yaml

    from .style import anchors as SA, candidates as SC, model as SM, reliability as RL, summary as SU
    cohort = RL.load_cohort(args.cohort)
    sh = RL.split_half(cohort, min_usable=args.min_usable)
    train, test = SC.load(Path(args.player) / "train.npz"), SC.load(Path(args.player) / "test.npz")
    mine = [p for p in train if p.platform == 0]          # the reference data are Lichess
    rows, w = SU.me_vs_cohort(mine, sh, n_boot=args.boot)
    axes = SU.axis_table(sh, w)
    shrunk = RL.shrunk_trait_test(cohort, min_usable=args.min_usable)
    population = None
    if args.population:
        base = SC.load(Path(args.population) / "train.npz")
        cmp = SM.compare_to_rating_baseline(mine, base, n_boot=args.boot)
        population = sorted(zip(cmp["names"], cmp["z"]), key=lambda t: -abs(t[1]))
    poles = user_poles = None
    if args.anchors:
        cfg = yaml.safe_load(Path(args.config).read_text())["anchors"]
        pole_of = {f"anchor_{k}": v["pole"] for k, v in cfg.items() if "pole" in v}
        anchors = RL.load_cohort(args.anchors)
        poles = SU.pole_confusion(anchors, pole_of)
        user_poles = SU.user_vs_poles(anchors, pole_of, mine, [p for p in test if p.platform == 0])
    text = SU.render(label=args.label, n_user=len(mine), n_cohort=len(sh["ids"]), me_rows=rows, axes=axes, poles=poles,
                     user_poles=user_poles, population=population, shrunk=shrunk)
    Path(args.out).write_text(text)
    print(text)
    print(f"\nwritten to {args.out}")


def cmd_style_rates(args):
    import json as _json

    from .style import rates as RT
    ratings = {k: v["rating"] for k, v in _json.loads((Path(args.cohort) / "players.json").read_text()).items()}
    rates = RT.cohort_rates(args.cohort, log=lambda m: print(m, flush=True))
    rows, n = RT.reliability(rates, ratings, min_decisions=args.min_decisions)
    text = RT.render(rows, n)
    if args.anchors or args.player:
        import yaml

        cls = profile = None
        if args.anchors:
            cfg = yaml.safe_load(Path(args.config).read_text())["anchors"]
            pole_of = {f"anchor_{k}": v["pole"] for k, v in cfg.items() if "pole" in v}
            cls = RT.anchor_classification(RT.cohort_rates(args.anchors, log=None), pole_of, rows)
        if args.player:
            import numpy as np

            from .style import candidates as SC
            ps = [p for p in SC.load(Path(args.player) / "train.npz") if p.platform == 0]
            feats, _ = RT.item_features(ps)
            profile = RT.player_profile(feats, rows)
        text += "\n" + (RT.render_who(cls, profile) if cls else "\nThe player's habit rates against the cohort (z in cohort SD units):\n"
                         + "\n".join(f"  {n:20s} rate {r:.3f}  cohort {m:.3f}  z {z:+.2f}" for n, r, m, z in profile))
    print(text)
    (Path(args.cohort) / "rates_reliability.txt").write_text(text)


def cmd_calibrate_link(args):
    from . import calibrate
    fens, limit, kw = _ladder_args(args)
    command = calibrate.mechess_command(args.engine, args.prior, args.book, table=args.table, maia3_repo=args.maia3_repo,
                                        maia3_size=args.maia3_size, extra_path=args.extra_path)
    from .mechess import dial
    n = calibrate.link_calibration(args.calibration, command, fens, limit, pairs_per_link=args.link_pairs,
                                   table=dial.load_table(args.table) if args.table else dial.DEFAULT_TABLE,
                                   concurrency=args.concurrency, redo=args.redo, log=lambda m: print(m, flush=True))
    print(f"\n{n} link match(es) played; calibration updated: {args.calibration}")


def cmd_dial_design(args):
    from .mechess import design, dial
    from .mechess.calibration import censored
    src = json.loads(Path(args.from_calibration).read_text())
    anchors = [p for p in src["points"] if not censored(p) and "linked_to" not in p]
    table = design.weak_end_table(tuple(args.labels), weak_label=args.weak_label)
    dial.save_table(table, args.out_table)
    keep = {k: v for k, v in table.items() if k in {p["dial"] for p in anchors} or k < 1800}
    points = design.skeleton(keep, anchors)
    Path(args.out_calibration).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_calibration).write_text(json.dumps({"scale": src.get("scale", "stockfish-UCI_Elo"), "offset": 0.0,
                                                      "meta": src.get("meta", {}), "points": points}, indent=1))
    print(f"table -> {args.out_table}")
    for label, row in sorted(table.items()):
        print(f"  {label:5d}: nodes {row[0]:6d} multipv {row[1]} window {row[2]:3d} T {row[3]:.2f} scale {row[4]:6.1f} book {row[5]:2d} blunder {row[6] if len(row) > 6 else 0:.2f}")
    print(f"calibration skeleton -> {args.out_calibration}\nnext: chessme calibrate-link --calibration {args.out_calibration} --table {args.out_table} --concurrency 3")


def cmd_control(args):
    from . import jobs
    job = args.job
    if args.action == "status":
        f = jobs.flags(args.dir)
        print("control files: " + (", ".join(f) if f else "none (everything runs)"))
        return
    kind = {"pause": "PAUSE", "stop": "STOP"}.get(args.action)
    if kind:
        p = jobs.set_flag(kind, job, args.dir)
        print(f"{args.action} requested for {job or 'all jobs'} ({p}); "
              + ("jobs hold at their next checkpoint and continue when you run `chessme control resume`." if kind == "PAUSE"
                 else "jobs exit at their next checkpoint; rerun the same command to resume, after `chessme control clear`."))
    elif args.action == "resume":
        print("resumed" if jobs.clear_flag("PAUSE", job, args.dir) else "nothing was paused")
    elif args.action == "clear":
        n = sum(jobs.clear_flag(k, job, args.dir) for k in ("PAUSE", "STOP"))
        print(f"cleared {n} control file(s)")


def cmd_style_games_fetch(args):
    from .style import games_fetch as GF
    log = _file_logger(args.log)
    log(f"=== style-games-fetch {' '.join(sys.argv[2:])}")
    stats = GF.run(args.cohort, args.out, n_games=args.games, min_games=args.min_games, pause=args.pause,
                   control_dir=args.control_dir, log=log, limit=args.limit)
    log(f"finished: {stats}")


def cmd_style_games_report(args):
    from .style import gamestats as GS
    from .style import games_fetch as GF
    players = GF.load_players(args.data, min_games=args.min_games)
    if len(players) < args.min_players:
        sys.exit(f"only {len(players)} players with >= {args.min_games} games in {args.data} (need {args.min_players}); fetch more first")
    ids, XT, XA, XB, R = GS.player_matrices(players)
    rows = GS.feature_reliability(XA, XB, R)
    fa = GS.factor_analysis(XA, XB, R, [j for j, r in enumerate(rows) if GS.passes_gate(r)] or [j for j, r in enumerate(rows) if r["coverage"] >= 0.6],
                            seed=args.seed)
    text = GS.render(rows, GS.identification_by_family(XA, XB, rows), GS.identification_by_family(XA, XB, rows, gated_only=True), fa, len(ids),
                    tc_ident=GS.identification(*GS.time_control_profile(players)[:2], list(range(len(GS.time_control_profile(players)[2])))))
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n")


def cmd_report_select(args):
    """Write the newest usable games of a profile (with the player's side) as a PGN for `analyse`."""
    from .analysis import select as SEL
    cfg = config.load_profile(args.profile)
    rows = audit_mod.load(cfg["_raw_dir"].parent / "processed" / "games.jsonl")
    chosen = SEL.choose(rows, n=args.n, platform=args.platform, per_class=args.per_class, time_classes=args.time_classes, since=args.since)
    raw = SEL.raw_games(sorted((cfg["_raw_dir"] / args.platform).glob("*/*.pgn")), args.platform)
    written, missing = SEL.write_pgn(chosen, raw, args.out)
    by = {}
    for r in chosen:
        by[r["time_class"]] = by.get(r["time_class"], 0) + 1
    print(f"{written} games written to {args.out} ({by}); newest {chosen[0]['played_at'][:10] if chosen else '-'}, oldest {chosen[-1]['played_at'][:10] if chosen else '-'}"
          + (f"; {len(missing)} not found in the raw files" if missing else ""))


def cmd_report_leaks(args):
    """Personal report step 2: rank where expected points are lost (opening or phase) and test whether that ranking is stable
    across a split-half of the games, from an `analyse` output directory."""
    from .analysis import leaks as LK
    results = LK.load_results(args.dir)
    if not results:
        sys.exit(f"no analysed games in {args.dir}/games (run `chessme analyse` first)")
    stab = LK.stability(results, by=args.by, min_n=args.min_n)
    text = LK.render(stab)
    if args.english:
        text += "\n" + LK.render_english(stab)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)


def _stoppable(items, ctl):
    """Yield the items, checking the pause / stop controls before each (raises Stopped)."""
    for it in items:
        ctl.checkpoint()
        yield it


def cmd_coach(args):
    """Start the local coach (web page on this computer): go back over the mistakes of a game, find better moves, see why, play on."""
    import webbrowser

    from .coach import server as CS
    from .coach import drills as CD
    backend = CS.EngineBackend(args.engine, nodes=args.nodes)
    data = Path(args.data_dir).expanduser()
    explorer = Path(args.explorer) if args.explorer else None
    if explorer and not explorer.exists():
        print(f"(no opening explorer at {explorer}: opening practice is off; see docs/opening-explorer.md)")
        explorer = None
    tablebase = None
    if args.syzygy and Path(args.syzygy).is_dir():
        import chess.syzygy
        tablebase = chess.syzygy.open_tablebase(args.syzygy)
    elif args.syzygy:
        print(f"(no Syzygy folder at {args.syzygy}: endgame practice is off; see docs/coach.md)")
    app = CS.CoachApp(backend.search, drills=CD.DrillStore(data / "drills.json"), data_dir=data, explorer=explorer, tablebase=tablebase)
    if not args.no_browser:
        import threading
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
    try:
        CS.serve(app, port=args.port)
    finally:
        backend.close()


def cmd_analyse(args):
    """Analyse the games of a PGN file with Stockfish: one JSON file per game (resumable and pausable), then a Markdown report."""
    import io as _io
    import json as _json

    import chess.pgn as _pgn

    from .analysis import runner as AR
    from .jobs import JobControl, Stopped
    log = _file_logger(args.log)
    out = Path(args.out)
    (out / "games").mkdir(parents=True, exist_ok=True)
    text = Path(args.pgn).read_text(errors="replace")
    games = []
    with _io.StringIO(text) as f:
        while (g := _pgn.read_game(f)) is not None:
            games.append(g)
    games = games[: args.limit] if args.limit else games
    ctl = JobControl(args.job, args.control_dir, log=log)
    if sorted(Path(args.openings_dir).glob("*.tsv")) if args.openings_dir else []:
        log(f"Book class from the opening names in {args.openings_dir}")
    else:
        log(f"no opening names in {args.openings_dir} (run `chessme theory-book --download` once): moves in theory are classed by loss like any other")
    log(f"=== analyse {args.pgn}: {len(games)} games, {args.nodes} nodes/position, {args.workers} worker(s), output {out}")
    done = failed = 0
    todo = []
    for i, g in enumerate(games):
        key = AR.game_key(g)
        path = out / "games" / f"{key}.json"
        if path.exists():
            done += 1
        else:
            exp = _io.StringIO()
            print(g, file=exp, end="\n\n")
            todo.append((key, exp.getvalue(), str(path), args.engine, args.nodes, args.openings_dir, args.player))
    stale = [p.name for p in (out / "games").glob("*.json") if re.fullmatch(r"\d{5}(-.*)?\.json", p.name)]
    if stale:
        log(f"WARNING: {len(stale)} files in {out / 'games'} are named by their position in the PGN (older versions, e.g. {stale[0]}); games are now "
            "named by their id, so these are analysed again and would be counted twice: delete the folder's old files (or use a new --out)")
    log(f"{done} already done, {len(todo)} to analyse")
    from .analysis import pool as AP
    from .jobs import run_pool
    t0 = time.time()
    try:
        with ctl.signals():
            if args.workers <= 1:
                results = (AP.analyse_task(t) for t in _stoppable(todo, ctl))
            else:
                results = run_pool(AP.analyse_task, todo, args.workers, ctl)
            for key, plies, err in results:
                if err:
                    failed += 1
                    log(f"  {key}: FAILED {err}")
                    continue
                done += 1
                log(f"  [{done}/{len(games)}] {key}: {plies} plies ({(time.time() - t0) / max(done - (len(games) - len(todo)), 1):.1f} s per game so far)")
    except Stopped as e:
        log(f"stopped: {e} (rerun the same command to resume)")
    finally:
        AP.close()
    wanted = {AR.game_key(g) for g in games}                    # the report covers the games of this PGN, not leftovers of other runs in the folder
    results = [(p.stem, _json.loads(p.read_text())) for p in sorted((out / "games").glob("*.json")) if p.stem in wanted]
    (out / "report.md").write_text(AR.render_report(results, args.player))
    log(f"finished: {done} done, {failed} failed; report {out / 'report.md'}")


def cmd_style_embed_train(args):
    from .jobs import JobControl
    from .style import embed as EM
    from .style import games_fetch as GF
    log = _file_logger(args.log)
    players = GF.load_players(args.data, min_games=args.min_games)
    if len(players) < args.min_players:
        sys.exit(f"only {len(players)} players in {args.data} (need {args.min_players}); fetch more first")
    log(f"=== style-embed-train {' '.join(sys.argv[2:])}: {len(players)} players")
    ctl = JobControl(args.job, args.control_dir, log=log)
    with ctl.signals():
        res = EM.train(players, args.out, steps=args.steps, batch=args.batch, bag=args.bag, dim=args.dim, hidden=args.hidden,
                       lr=args.lr, seed=args.seed, ckpt_every=args.ckpt_every, eval_every=args.eval_every, ctl=ctl, log=log)
    log(f"{'stopped' if res['stopped'] else 'finished'} at step {res['step']}")


def cmd_style_games_quality(args):
    from .style import quality as Q
    log = _file_logger(args.log)
    log(f"=== style-games-quality {' '.join(sys.argv[2:])}")
    print(Q.run(args.data, engine=args.engine, nodes=args.nodes, n_games=args.games, max_players=args.players, seed=args.seed,
                workers=args.workers, control_dir=args.control_dir, log=log))


def cmd_style_quality_report(args):
    from .style import gamestats as GS
    from .style import quality as Q
    players = Q.load_quality(args.data)
    ids, XA, XB, R = GS.quality_matrices(players)
    if len(ids) < args.min_players:
        sys.exit(f"only {len(ids)} players analysed (need {args.min_players}); run style-games-quality first")
    rows = GS.feature_reliability(XA, XB, R, names=list(Q.QUALITY_NAMES))
    good = [j for j, r in enumerate(rows) if GS.passes_gate(r)]
    print(f"Move-quality features: {len(ids)} players (about {len(players[ids[0]][1])} games each), games split into alternating halves")
    print(f"  {'feature':20s} {'cover':>6s} {'r_full':>7s} {'net':>6s} {'rating r':>9s} gate")
    for r in sorted(rows, key=lambda r: -(r['r_full'] if r['r_full'] == r['r_full'] else -9)):
        print(f"  {r['name']:20s} {r['coverage']:6.2f} {r['r_full']:+7.2f} {r['r_net']:+6.2f} {r['rating_corr']:+9.2f} {'KEEP' if GS.passes_gate(r) else ''}")
    print(f"{len(good)} of {len(rows)} pass the gate")
    if good:
        import numpy as np
        A, B = np.nan_to_num(XA), np.nan_to_num(XB)
        res = GS.identification(A, B, good, ratings=R, window=100)
        print(f"identification among rating-matched players from the kept quality features alone: top-1 {100 * res['top1']:.1f}% (chance {100 * res['chance']:.1f}%)")


def cmd_books_fetch(args):
    from .books import fetch as BF
    log = _file_logger(args.log)
    books = BF.load_sources()
    if args.only:
        books = [b for b in books if b["id"] in args.only]
    log(f"=== books-fetch: {len(books)} books -> {args.out}")
    log(str(BF.run(args.out, books, pause=args.pause, log=log)))


def cmd_books_learn(args):
    from .books import learn as BL
    log = _file_logger(args.log)
    log(f"=== books-learn {' '.join(sys.argv[2:])}")
    res = BL.run(args.out, steps=tuple(args.steps), limit_per_source=args.limit_per_source, extra_pgn_dir=args.studies_dir,
                 redo=args.redo, archive=args.archive, no_csv=args.no_csv, no_openings=args.no_openings, no_chessgpt=args.no_chessgpt, max_books=args.max_books,
                 control_dir=args.control_dir, log=log)
    log(str(res))
    if args.slim and not res["stopped"]:
        from . import kaggle as KG
        log(f"slim: {KG.slim_collect(args.out):.0f} MB of raw downloads removed")


def cmd_books_studies(args):
    from .books import studies as BS
    log = _file_logger(args.log)
    users = list(args.users or []) + (Path(args.users_file).read_text().split() if args.users_file else [])
    log(f"=== books-studies: {len(users)} users, {len(args.study_ids or [])} studies")
    log(str(BS.run(args.out, users, args.study_ids or [], pause=args.pause, log=log)))


def cmd_books_pdf(args):
    from .books import pdf as BP
    log = _file_logger(args.log)
    log(str(BP.run(args.inp, args.out, log=log)))


def cmd_books_topics(args):
    from .books import text as BT
    from .books import topics as TP
    paras = []
    for f in sorted(Path(args.texts).glob("*.txt")):
        paras += [p for p in BT.paragraphs(BT.strip_gutenberg(f.read_text(errors="replace"))) if 200 <= len(p) <= 1500]
    print(f"{len(paras)} paragraphs")
    for r in TP.cluster(paras, k=args.k):
        print(f"cluster {r['cluster']:2d} ({r['size']:5d}): {', '.join(r['words'])}")


def cmd_books_nlp_train(args):
    from .books import nlp as NLP
    from .jobs import JobControl
    log = _file_logger(args.log)
    data = Path(args.data)
    log(f"=== books-nlp-train {' '.join(sys.argv[2:])}")
    if args.input_root or args.data_dir:
        from . import kaggle as KG
        KG.prepare_nlp(data, args.input_root or "/kaggle/input", log=log, data_dir=args.data_dir)
    ex = NLP.build_examples(annotated=data / "annotated" / "annotated_moves.jsonl.gz", prose_dir=data, books_dir=data / "books",
                            max_per_kind=args.max_per_source)
    by = {}
    for e in ex:
        by[e["source"]] = by.get(e["source"], 0) + 1
    log(f"{len(ex)} examples: {by}")
    if len(ex) < 200:
        sys.exit("too few examples: run books-learn first")
    missing = NLP.missing_sources(ex)
    if missing and not args.allow_missing_sources:
        sys.exit(f"these sources have no training examples: {missing}. The collection notebook did not finish or its output is incomplete; "
                 "rerun it, or pass --allow-missing-sources to train without them")
    log("sources in the training data: " + ", ".join(f"{k} {v:,}" for k, v in sorted(by.items())))
    ctl = JobControl(args.job, args.control_dir, log=log)
    with ctl.signals():
        res = NLP.train(ex, Path(args.out) if args.out else data / "nlp", backend=args.backend, model_name=args.model, epochs=args.epochs,
                        batch=args.batch, lr=args.lr, dry_run=args.dry_run, deadline_minutes=args.deadline_minutes,
                        ckpt_every=args.ckpt_every, val_every=args.val_every, patience=args.patience, dropout=args.dropout,
                        lab_per_batch=args.lab_per_batch, ctl=ctl, log=log)
    t = res["metrics"].get("test", {})
    if args.dry_run:
        d = res["metrics"].get("dry_run", {})
        log(f"dry-run loss {d.get('first_loss', float('nan')):.3f} -> {d.get('last_loss', float('nan')):.3f}: {'the model can learn' if d.get('learned') else 'NOT LEARNING'}")
        if not d.get("learned"):
            sys.exit("dry-run failed: the loss did not go down on 64 memorisable examples; do not start the long run")
    log(f"{'DRY RUN ' if args.dry_run else ''}{'stopped' if res['stopped'] else 'finished'} at step {res['step']}; test: "
        + json.dumps({k: round(v, 3) for k, v in t.items() if isinstance(v, float)}))
    if args.slim and not args.dry_run:
        from . import kaggle as KG
        KG.slim_nlp(data)



def cmd_books_nlp_report(args):
    m = json.loads((Path(args.model_dir) / "metrics.json").read_text())
    t = m["test"]
    print(f"steps {m['steps']}/{m['total_steps']}  stopped early: {m['stopped']}  device {m['device']}  {m['minutes']} min")
    print(f"model kept: {m.get('selected', 'last')};  early stopped: {m.get('early_stopped', False)};  steps skipped for a non-finite gradient: {m.get('skipped_steps', 0)}")
    if "concepts_model" in m:
        print(f"best concept-only model (step {m['concepts_model']['step']}): concept AP {m['concepts_model']['test'].get('concept_ap_macro', float('nan')):.3f} "
              f"(the kept model: {t.get('concept_ap_macro', float('nan')):.3f}); use `books-nlp-predict --variant concepts`")
    print("examples per source: " + ", ".join(f"{k} {v:,}" for k, v in sorted(m.get("sources", {}).items())))
    for k in ("concept_ap_macro", "concept_ap_baseline", "concept_f1_micro_tuned", "concept_f1_micro_prior", "judgement_f1_macro", "judgement_acc",
              "judgement_acc_majority", "eval_acc", "eval_acc_majority"):
        if k in t:
            print(f"  {k:26s} {t[k]:.3f}")
    print("test set with the keywords visible: concept micro-F1", round(m["test_unmasked"].get("concept_f1_micro_tuned", float("nan")), 3))


def cmd_books_nlp_predict(args):
    from .books import nlp as NLP
    model, cfg = NLP.load(args.model_dir, variant=args.variant)
    for text, r in zip(args.texts, NLP.predict(model, args.texts, cfg)):
        print(f"{text[:80]!r}\n   concepts {r['concepts']}  judgement {r['judgement']}  evaluation {r['evaluation']}")


def cmd_books_nlp_label(args):
    from .books import label as LB, nlp as NLP
    log = _file_logger(args.log)
    out = Path(args.out)
    log(f"=== books-nlp-label {' '.join(sys.argv[2:])}")
    data, model_dir = args.data, args.model_dir
    if args.input_root or args.data_dir:
        from . import kaggle as KG
        r = KG.prepare_label(out.parent, args.input_root or "/kaggle/input", data_dir=args.data_dir, model_dir=model_dir, log=log)
        data, model_dir = data or r["annotated"], r["model"]                 # the resolved model folder (a top folder given by the user is searched)
    if not data or not model_dir:
        sys.exit("give --data (annotated_moves.jsonl.gz or the books-learn folder) and --model-dir, or --input-root / --data-dir on Kaggle")
    data = Path(data)
    if data.is_dir():
        data = data / "annotated" / "annotated_moves.jsonl.gz" if (data / "annotated").exists() else data / "annotated_moves.jsonl.gz"
    if not data.exists():
        sys.exit(f"no annotated moves at {data}")
    model, cfg = NLP.load(model_dir, variant=args.variant)
    log(f"model {model_dir} ({args.variant}), input {data}")
    res = LB.run(data, out, model, cfg, batch=args.batch, limit=args.limit, deadline_minutes=args.deadline_minutes, chunk=args.chunk, log=log, fresh=args.fresh)
    if not res["finished"]:
        sys.exit(3)                                   # paused at the time budget: run the same command again
    stats, pick = LB.summarise(out, sample=args.sample)
    report = out.with_name("label_report.md")
    report.write_text(LB.render(stats, pick), encoding="utf-8")
    out.with_name("label_stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    log(f"{stats['records']} labelled moves; report {report}")


def cmd_books_preflight(args):
    from .books import preflight as PF
    ok = PF.run(args.out, need_gpu=args.need_gpu, need_transformers=args.backend == "transformer", model_name=args.model if args.backend == "transformer" else None,
                min_free_gb=args.min_free_gb, network=not args.no_network)
    sys.exit(0 if ok else 1)


def cmd_theory_book(args):
    from .book import theory as TH
    from .book.format import write_book
    from .books import openings as OP
    log = _file_logger(args.log)
    od = Path(args.openings_dir)
    if not list(od.glob("*.tsv")):
        if not args.download:
            sys.exit(f"no opening files in {od}; rerun with --download (5 small CC0 files from the Lichess chess-openings dataset)")
        OP.download(od)
    lines = TH.load_lines(sorted(od.glob("*.tsv")))
    band = tuple(args.band) if args.band else None
    games = []
    if args.games:
        games = TH.games_from_cohort(args.games, band)
    if args.pgn:
        import itertools
        games = itertools.chain(games, TH.games_from_pgn(args.pgn, band))
    entries, stats = TH.build(lines, games, max_ply=args.max_ply, min_games=args.min_games, min_share=args.min_share,
                              extend_min_games=args.extend_min_games, extend_min_share=args.extend_min_share)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_book(out, entries)
    report = TH.render(stats, band)
    out.with_name(out.stem + "_report.md").write_text(report)
    log(f"theory book {out}: {stats}")
    print(report)


def _ensure_opening_names(directory, log):
    """The explorer database stores opening names: fetch the five small CC0 files when they are missing (a Kaggle run has none)."""
    d = Path(directory)
    if list(d.glob("*.tsv")):
        return
    try:
        from .books import openings as OP
        OP.download(d)
        log(f"downloaded the opening names into {d}")
    except Exception as e:                                   # the explorer works without names: say so instead of failing
        log(f"WARNING: no opening names ({e!r}); the database will have none")


def cmd_explorer_build(args):
    from .book import explorer as EX
    from .jobs import JobControl
    log = _file_logger(args.log)
    edges = tuple(args.bands)
    if args.check:
        r = EX.check(lambda: EX.open_dump(args.source), edges=edges, max_ply=args.max_ply)
        print(f"check OK: read {r['games']} games, {r['usable']} usable, {r['avg_plies']:.1f} plies each; "
              f"{r['with_eval']} with engine evaluations, {r['with_clock']} with clocks")
        return
    log(f"=== explorer-build {' '.join(sys.argv[2:])}")
    _ensure_opening_names(args.openings_dir, log)
    ctl = JobControl(args.job, args.control_dir, log=log)
    with ctl.signals():
        res = EX.run(args.source, args.out, edges=edges, max_ply=args.max_ply, max_per_band=args.max_per_band, max_scan=args.max_scan,
                     holdout=args.holdout, db_min_games=args.db_min_games, db_min_frac=args.db_min_frac, book_min_games=args.book_min_games,
                     book_min_frac=args.book_min_frac, book_min_share=args.book_min_share, eval_margin_cp=args.eval_margin, max_entries=args.max_entries,
                     max_memory_gb=args.max_memory_gb, max_minutes=args.max_minutes, checkpoint_every=args.checkpoint_every,
                     checkpoint_minutes=args.checkpoint_minutes, resume=not args.fresh, resume_glob=args.resume_glob,
                     drop_state_when_finished=args.drop_state_when_finished, openings_dir=args.openings_dir, min_base=args.min_base,
                     should_stop=ctl.stop_requested, log=log)
    print((Path(args.out) / "report.md").read_text())


def cmd_explorer_range_scan(args):
    """Partitioned range-scan: cuts the dump into byte windows (parallel, resumable window by window), instead of one long-lived
    stream that has to restart from byte 0 on every disconnect. See chessme/book/rangescan.py."""
    from .book import explorer as EX
    from .book import rangescan as RS
    log = _file_logger(args.log)
    edges = tuple(args.bands)
    log(f"=== explorer-range-scan {' '.join(sys.argv[2:])}")
    _ensure_opening_names(args.openings_dir, log)
    thresholds = {"db_min_games": args.db_min_games, "db_min_frac": args.db_min_frac, "book_min_games": args.book_min_games,
                  "book_min_frac": args.book_min_frac}
    merged = RS.run(args.source, args.parts, args.out, edges=edges, max_ply=args.max_ply, min_base=args.min_base, max_entries=args.max_entries,
                    holdout=args.holdout, slices=args.slices, thresholds=thresholds, windows_dir=args.windows_dir, workers=args.workers, job=args.job,
                    control_dir=args.control_dir, log=log)
    merged.config = {"edges": list(edges), "max_ply": args.max_ply, "min_base": args.min_base, "holdout": args.holdout, "parts": args.parts,
                     "source": os.path.basename(args.source)}
    state_path = Path(args.out) / "state.pkl.gz"
    EX.save_state(state_path, merged, merged.scanned, merged.config)
    del merged                                                  # rebuild reloads the checkpoint: do not hold two full copies at once
    EX.rebuild(state_path, args.out, db_min_games=args.db_min_games, db_min_frac=args.db_min_frac, book_min_games=args.book_min_games,
              book_min_frac=args.book_min_frac, book_min_share=args.book_min_share, eval_margin_cp=args.eval_margin,
              max_ply=args.max_ply, openings_dir=args.openings_dir, log=log)
    print((Path(args.out) / "report.md").read_text())


def cmd_explorer_rebuild(args):
    from .book import explorer as EX
    log = _file_logger(args.log)
    _ensure_opening_names(args.openings_dir, log)
    EX.rebuild(args.state, args.out, db_min_games=args.db_min_games, db_min_frac=args.db_min_frac, book_min_games=args.book_min_games,
               book_min_frac=args.book_min_frac, book_min_share=args.book_min_share,
               eval_margin_cp=args.eval_margin, max_ply=args.max_ply, openings_dir=args.openings_dir, log=log)
    print((Path(args.out) / "report.md").read_text())


def cmd_explorer_query(args):
    from .book import explorer as EX
    start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    fen = args.fen or start
    name = EX.opening_at(args.db, fen)
    if name:
        print(f"{name[0]} {name[1]}")
    ans = EX.query_position(args.db, fen, rating=args.rating)
    if ans["moves"]:
        print(f"{ans['total']:,} games reached this position")
        print(EX.format_rows(ans["moves"], args.top, other=ans["other"], links=True))
        print("bar: ░ White wins  ▒ draws  █ Black wins")
    else:
        print("no games in the explorer for this position at this rating")


def cmd_style_status(args):
    import time

    from .style import status as ST
    while True:
        text = ST.render(cohort=args.cohort, anchors=args.anchors, target=args.target, logs=args.logs, jobs=ST.running())
        print(("\033[2J\033[H" if args.watch else "") + text, flush=True)
        if not args.watch:
            return
        time.sleep(args.watch)


def cmd_style_judge_compare(args):
    from .style import judges as J
    a, ja = J.load_dir(args.a)
    b, jb = J.load_dir(args.b)
    la, lb = ja or Path(args.a).name, jb or Path(args.b).name
    print(J.render(J.compare(a, b), J.style_agreement(a, b), la, lb))


def cmd_style_report(args):
    from .style import candidates as SC, model as SM
    train, test = SC.load(Path(args.data) / "train.npz"), SC.load(Path(args.data) / "test.npz")
    m = SM.fit(train, l2=args.l2)
    r = SM.evaluate(m, test)
    print(f"held-out choices among approved moves: {r['n']}")
    for k in ("style", "loss_only", "uniform"):
        print(f"  {k:10s} NLL {r[k]['nll']:.3f}  top-1 {100 * r[k]['top1']:.1f}%")
    print(f"strength weight: {m.loss_coef:.2f} per 100 cp lost")
    print("preferences (standardised weight; + = seeks it, - = avoids it):")
    for name, w in SM.profile(m):
        print(f"  {name:22s} {w:+.3f}")
    if not args.baseline:
        return
    from .style import axes as AX, report as SR
    base = SC.load(Path(args.baseline) / "train.npz")
    mine = [p for p in train if p.platform == 0]  # Lichess only: the baseline is on the Lichess rating scale
    cmp = SM.compare_to_rating_baseline(mine, base, n_boot=args.boot, l2=args.l2)
    axes = AX.axis_scores(cmp["names"], cmp["z"])
    print(f"\nvs population ({len(base)} decisions) at rating {cmp['rating']:.0f}, difference in standard errors:")
    for name, z in sorted(zip(cmp["names"], cmp["z"]), key=lambda t: -abs(t[1])):
        print(f"  {name:22s} z {z:+.1f}")
    print("hypothesis axes:", {k: round(v, 2) for k, v in axes.items()})
    lo = min(p.rating for p in base)
    hi = max(p.rating for p in base)
    edges = list(range(lo, hi + 200, 200))
    gains = SM.style_gain_by_band(base, edges)
    for g in gains:
        print("  band %d-%d  n=%d  gain NLL %.3f  top-1 %+.3f" % g)
    text = SR.render(player_label=args.label, n_player=len(mine), n_base=len(base), rating=cmp["rating"],
                     band=(lo, hi), comparison=cmp, axis_scores=axes, gains=gains, held_out=r, loss_coef=m.loss_coef,
                     caveats=["The comparison uses your Lichess games only (the population is on the Lichess rating scale)."])
    Path(args.out).write_text(text)
    print(f"\nreadable report written to {args.out}")


def cmd_style_model_fit(args):
    from .style import candidates as SC, model as SM
    train, test = SC.load(Path(args.data) / "train.npz"), SC.load(Path(args.data) / "test.npz")
    m = SM.fit(train, l2=args.l2)
    r = SM.evaluate(m, test)
    print(f"held-out choices among approved moves: {r['n']}")
    for k in ("style", "loss_only", "uniform"):
        print(f"  {k:10s} NLL {r[k]['nll']:.3f}  top-1 {100 * r[k]['top1']:.1f}%")
    gain = r["loss_only"]["nll"] - r["style"]["nll"]
    print(f"style beats the strength-only model by {gain:+.3f} NLL per decision on held-out games")
    full = SM.fit(train + test, l2=args.l2, standardise=(m.mean, m.std))   # the saved model uses every decision
    SM.save_model(full, args.out, n=len(train) + len(test), judge=SC.judge_of(Path(args.data) / "train.npz"),
                  held_out_nll_gain=round(gain, 4), held_out_n=r["n"])
    print(f"style model ({len(train) + len(test)} decisions) written to {args.out}; use it with: chessme mechess --prior style={args.out}")


def cmd_me_compare(args):
    import gc
    import time

    from .model import compare
    items = _compare_items(args)
    out_path = Path(args.out or f"data/me/compare/{args.set}_{len(items)}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results = json.loads(out_path.read_text()) if out_path.exists() else {}
    print(f"{len(items)} positions ({args.set}); results file {out_path}")
    torch_threads = args.threads
    import torch
    torch.set_num_threads(torch_threads)
    for spec in args.scorer:
        kind, _, arg = spec.partition("=")
        if kind == "ours":
            path, _, label = arg.partition("@")
            name = label or f"ours: {path}"
        elif kind == "maia3":
            arg, _, ckpt = arg.partition("@")
            ckpt, _, label = ckpt.partition("#")
            name = label or (f"Maia-3 {arg.replace('+history', '')}" + (" + history" if arg.endswith("+history") else "")
                             + (" (fine-tuned)" if ckpt else ""))
        elif kind == "maia2":
            name = f"Maia-2 {arg}"
        else:
            raise SystemExit(f"unknown scorer {spec!r} (use ours=PATH[@label], maia3=5m|23m[+history], maia2=blitz|rapid)")
        if name in results and not args.redo:
            print(f"  {name}: cached")
            continue
        t0 = time.time()
        extra = [args.extra_path] if args.extra_path else []
        if kind == "ours":
            scorer = compare.OursScorer(path, name=name)
        elif kind == "maia3":
            size = arg.replace("+history", "")
            scorer = compare.Maia3Scorer(args.maia3_repo, ckpt or Path(args.weights_dir) / f"maia3-{size}.pt", size,
                                         use_history=arg.endswith("+history"), name=name, extra_paths=extra)
        else:
            scorer = compare.Maia2Scorer(args.maia2_repo, Path(args.weights_dir) / f"{arg}_model.pt", name=name, extra_paths=extra)
        results[name] = compare.evaluate_scorer(scorer, items)
        out_path.write_text(json.dumps(results, indent=1))
        a = results[name]["all"]
        print(f"  {name}: top-1 {100 * a['top1']:.1f}%  top-3 {100 * a['top3']:.1f}%  NLL {a['nll']:.3f}   ({time.time() - t0:.0f}s)", flush=True)
        del scorer
        gc.collect()
    print()
    print(compare.format_comparison(results, f"{args.set}: {len(items)} positions"))


def cmd_me_maia3_ft(args):
    import sys

    import torch

    from .book import evaluate as bev
    from .dataset.weights import Weighter
    from .model import maia3_ft as M
    from .model.train import pick_device
    sys.path.insert(0, args.maia3_repo)
    if args.extra_path:
        sys.path.insert(0, args.extra_path)
    from maia3 import uci as mu

    cfg = config.load_profile(args.profile)
    rows = audit_mod.load(cfg["_raw_dir"].parent / "processed" / "games.jsonl")
    weighter = Weighter(cfg, rows)
    usable, _test = bev.split_by_time(rows, 0.1)  # the newest 10% stay untouched
    cut = int(len(usable) * 0.95)
    train, val = M.build_player_data(usable[:cut], weighter), M.build_player_data(usable[cut:], weighter)
    print(f"{len(train):,} training moves, {len(val):,} validation moves")
    device = pick_device(args.device)
    model = mu.load_model(mu.parse_args(["--model", args.model, "--checkpoint-path", args.checkpoint, "--device", str(device),
                                         "--temperature", "0"]))
    hist = M.finetune(model, train, val, args.out, device=device, epochs=args.epochs, batch_size=args.batch_size, lr=args.lr,
                      scope=args.scope, eval_every=args.eval_every, log=lambda m: print(m, flush=True), log_every=25)
    best = min(hist, key=lambda h: h["val_nll"])
    print(f"best validation: step {best['step']}  top-1 {100 * best['val_top1']:.1f}%  nll {best['val_nll']:.3f}  -> {args.out}")


def cmd_humanlike_testset(args):
    from .humanlike import testset as T
    windows = [int(w) for w in args.windows.split(",")]
    manifest = T.build_balanced(args.source, args.parts, windows, args.out, workers=args.workers, cap_per_bin=args.cap_per_bin,
                                shard_dir=args.shard_dir, keep_shards=args.keep_shards, seed=args.seed, log=lambda m: print(m, flush=True),
                                per_game=args.per_game, time_class=args.time_class, allow_bots=args.allow_bots)
    print(json.dumps({k: v for k, v in manifest.items() if not k.startswith("rating_bins")}, indent=1))
    print("positions per rating bin (before -> after the cap):")
    for b, n in manifest["rating_bins_before"].items():
        print(f"  {b:>5}: {n:>9,} -> {manifest['rating_bins_after'].get(b, 0):>9,}")


def cmd_humanlike_allie(args):
    from .humanlike import allie as A
    from .humanlike import testset as T
    positions = list(A.iter_positions(args.file, comparable_only=not args.all))
    meta = {"source": "Allie test set (yimingzhang/allie-data, lichess-2022-blitz-test)", "comparable_only": not args.all,
            "published_positions": A.PUBLISHED_POSITIONS}
    m = T.write_testset(args.out, positions, meta)
    print(json.dumps(m, indent=1))
    if not args.all:
        print(f"{m['positions']:,} positions; the papers report {A.PUBLISHED_POSITIONS:,}" + (" (exact match)" if m["positions"] == A.PUBLISHED_POSITIONS else " (DIFFERENT)"))


def cmd_humanlike_score(args):
    import numpy as np

    from .humanlike import score as S
    from .humanlike import testset as T
    positions = T.read_testset(args.testset)
    manifest = json.loads(Path(str(args.testset) + ".manifest.json").read_text())
    index = np.arange(len(positions))
    if args.limit and args.limit < len(positions):
        index = np.sort(np.random.default_rng(args.seed).permutation(len(positions))[:args.limit])
    chosen = [positions[i] for i in index]
    del positions
    kwargs = dict(spec=args.scorer, maia3_repo=args.maia3_repo, maia2_repo=args.maia2_repo, weights_dir=args.weights_dir,
                  extra_path=args.extra_path, device=args.device, batch=args.batch)
    t0 = time.time()
    scores, name = S.score_items_parallel(kwargs, T.to_items(chosen), workers=args.workers, chunk_items=args.chunk,
                                          progress=lambda d, n: print(f"  {d:,}/{n:,}  {time.time() - t0:.0f}s", flush=True) if d % 20000 < args.chunk or d == n else None)
    scores["index"] = index
    S.save_scores(args.out, scores, name, manifest["sha256"], {"positions_sha": S.positions_hash(chosen), "scorer_spec": args.scorer,
                                                              "seconds": round(time.time() - t0, 1), "device": args.device, "workers": args.workers})
    print(f"{name}: {len(chosen):,} positions in {time.time() - t0:.0f}s -> {args.out}")


def cmd_humanlike_report(args):
    import numpy as np

    from .humanlike import report as R
    from .humanlike import score as S
    from .humanlike import testset as T
    manifest = json.loads(Path(str(args.testset) + ".manifest.json").read_text())
    runs = []
    for path in args.scores:
        scores, meta = S.load_scores(path)
        if meta["testset_sha256"] != manifest["sha256"]:
            raise SystemExit(f"{path} was computed on another test set")
        chosen = T.read_testset(args.testset, scores["index"])
        if meta["positions_sha"] != S.positions_hash(chosen):
            raise SystemExit(f"{path}: the positions do not match the scores")
        runs.append((meta["model"], scores, chosen))
    if len({tuple(r[1]["index"]) for r in runs}) > 1:
        raise SystemExit("the score files cover different positions: score them with the same --limit/--seed")
    arr = R.position_arrays(runs[0][2])
    masks = R.masks(arr, min_ply=args.min_ply, drop_forced=args.drop_forced)
    lines = [f"# Human-likeness report: {Path(args.testset).name}", "",
             f"Test set {manifest['positions']:,} positions (sha256 {manifest['sha256'][:12]}), scored subset {len(runs[0][2]):,}. "
             f"'comparable' = past the first {args.min_ply} plies and not after the first position where either player was under 30 s (the filter of the published Maia-3 / Allie numbers); "
             "'full' = every position. Intervals are 95% game-level bootstrap intervals. **sampled match** = the chance a move sampled from the model equals "
             "the human's move; **top-1** = the same for the model's most probable move.", ""]
    for name, scores, _ in runs:
        lines += [f"## {name}", "", R.table({k: R.summarize(scores, arr, m, n_boot=args.boot) for k, m in masks.items()}), ""]
        for by in ("rating", "phase"):
            lines += [R.table(R.strata(scores, arr, masks["comparable"], by, n_boot=args.boot), f"### {name}: comparable positions by {by}"), ""]
        lines += [R.table(R.strata(scores, arr, masks["full"], "clock", n_boot=args.boot), f"### {name}: all positions by the mover's clock"), ""]
        lines += [R.matched_table(R.matched_overconfidence(scores, arr, masks["full"], n_boot=args.boot),
                                  f"### {name}: overconfidence by clock, raw and matched for difficulty (legal-move count and game phase)"), ""]
    for na, sa, _ in runs[1:]:
        nb, sb = runs[0][0], runs[0][1]
        lines += [f"## {na} minus {nb} (paired, same positions)", "",
                  R.comparison_table({k: R.compare(sa, sb, arr, m, n_boot=args.boot) for k, m in masks.items()}), ""]
    text = "\n".join(lines)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)


def cmd_humanlike_ceiling(args):
    import numpy as np

    from .humanlike import ceiling as C
    from .humanlike import report as R
    from .humanlike import score as S
    from .humanlike import testset as T
    manifest = json.loads(Path(str(args.testset) + ".manifest.json").read_text())
    lines = [f"# Ceiling from repeated positions: {Path(args.testset).name}", "",
             "Positions of the first 24 plies, compared with the opening explorer's exact counts for the game's rating band (leave-one-out: the "
             "position's own game is removed from the counts). The oracle predicts the most played move (top-1) or samples a move from the counts "
             "(sampled match); no model can systematically beat it on a position that many players face. Exact except that moves played fewer than the "
             "band's floor of times are not listed, which only widens the oracle's sampled-match range.", ""]
    runs = []
    for path in args.scores:
        scores, meta = S.load_scores(path)
        if meta["testset_sha256"] != manifest["sha256"]:
            raise SystemExit(f"{path} was computed on another test set")
        chosen = T.read_testset(args.testset, scores["index"])
        runs.append((meta["model"], scores, chosen))
    positions = runs[0][2]
    look = C.lookup(args.explorer, positions)
    orc = C.oracle(look)
    arr = R.position_arrays(positions)
    early = np.array([p.ply < C.MAX_PLY for p in positions])
    lines += [f"{int(early.sum()):,} of {len(positions):,} positions are in the first {C.MAX_PLY} plies; {int(orc['ok'].sum()):,} of them were seen by at least one other game in their band "
              f"(the rest are rarer than the explorer's floor).", ""]
    for name, scores, _ in runs:
        lines += [C.render(C.table(scores, arr, orc, n_boot=args.boot), f"## {name}"), ""]
    text = "\n".join(lines)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)


def cmd_humanlike_judge(args):
    import numpy as np

    from .humanlike import judge as J
    from .humanlike import metrics as M
    from .humanlike import report as R
    from .humanlike import score as S
    from .humanlike import testset as T
    manifest = json.loads(Path(str(args.testset) + ".manifest.json").read_text())
    scores, meta = S.load_scores(args.scores)
    if meta["testset_sha256"] != manifest["sha256"]:
        raise SystemExit("the scores were computed on another test set")
    positions = T.read_testset(args.testset, scores["index"])
    arr = R.position_arrays(positions)
    regime = M.clock_regime(arr["clock"])
    rng = np.random.default_rng(args.seed)
    from .humanlike import adapter as A
    train_m, val_m, test_m = A.game_split(arr["gid"], seed=args.split_seed)          # the same split `humanlike-adapter` uses
    in_split = {"all": np.ones(len(regime), dtype=bool), "train": train_m, "val": val_m, "test": test_m, "trainval": train_m | val_m}[args.split]
    rows = []
    for name in ("30s+", "10-30s", "<10s"):
        ok = np.flatnonzero((regime == name) & (arr["ply"] >= args.min_ply) & (arr["n_legal"] >= 2) & in_split)
        rows += sorted(rng.choice(ok, size=min(args.per_regime, len(ok)), replace=False).tolist())
    rows = np.array(sorted(rows))
    items = [(positions[i].fen, positions[i].played, [m for m in scores["topk_move"][i, :args.candidates] if m]) for i in rows]
    t0 = time.time()
    judged = J.judge_positions(items, engine_path=args.engine, workers=args.workers, nodes_child=args.nodes_child, nodes_root=args.nodes_root, k=args.candidates,
                               progress=lambda d, n: print(f"  {d:,}/{n:,} positions judged ({time.time() - t0:.0f}s)", flush=True))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, rows=rows, meta=np.array(json.dumps({"model": meta["model"], "testset_sha256": manifest["sha256"], "nodes_child": args.nodes_child,
                                                                  "nodes_root": args.nodes_root, "candidates": args.candidates, "seed": args.seed, "per_regime": args.per_regime, "split": args.split, "split_seed": args.split_seed,
                                                                  "positions_sha": S.positions_hash([positions[i] for i in rows])})), **judged)
    print(f"judged {len(rows):,} positions of {meta['model']} in {time.time() - t0:.0f}s -> {out}")


def cmd_humanlike_errors(args):
    import numpy as np

    from .humanlike import errors as E
    from .humanlike import metrics as M
    from .humanlike import report as R
    from .humanlike import score as S
    from .humanlike import testset as T
    manifest = json.loads(Path(str(args.testset) + ".manifest.json").read_text())
    scores, meta = S.load_scores(args.scores)
    with np.load(args.judged, allow_pickle=False) as z:
        jmeta = json.loads(str(z["meta"]))
        rows = z["rows"]
        judged = {k: z[k] for k in ("best_cp", "human_cp", "cand_cp")}
    if jmeta["testset_sha256"] != manifest["sha256"] or jmeta["model"] != meta["model"]:
        raise SystemExit("the judged file belongs to another test set or model")
    chosen = T.read_testset(args.testset, scores["index"][rows])
    if S.positions_hash(chosen) != jmeta["positions_sha"]:
        raise SystemExit("the positions do not match the judged file")
    sub = {k: v[rows] for k, v in scores.items() if k != "index"}
    arr = R.position_arrays(chosen)
    prep = E.prepare(sub, judged)
    regime = M.clock_regime(arr["clock"])
    masks = {"all judged positions": np.ones(len(rows), dtype=bool), **{f"clock {r}": regime == r for r in ("30s+", "10-30s", "<10s")}}
    floor = {k: E.null_halves(prep, arr, m) for k, m in masks.items()}
    stats = E.tail_stats(prep, sub["rank"], regime)
    tail = E.tail_arrays(stats, regime)
    lines = [f"# Error profile (axis A3): {meta['model']}", "",
             f"{len(rows):,} positions of {Path(args.testset).name}, judged by Stockfish at {jmeta['nodes_child']:,} nodes per candidate ({jmeta['nodes_root']:,} at the root). "
             f"Loss = expected points the move gives away (0-1, Lichess curve); values below are x100. The model's probabilities are over its {prep['cand_loss'].shape[1]} most probable moves "
             f"(mean share outside them: {100 * float(prep['tail'].mean()):.1f}%). **model - humans** = the model's expected value minus what the humans did, "
             "paired by position, 95% game-level interval; **gap / noise floor** = that gap divided by the standard deviation of the humans' mean loss between two random halves of the games. "
             "The mass the model puts outside the judged moves is added back at the cost of the moves the humans played outside them (per clock regime: "
             + "; ".join(f"{r}: mean loss {100 * v['mean loss']:.1f}, blunder rate {100 * v['blunder (loss > 0.20)']:.0f}%" for r, v in stats.items()) + ").", ""]
    for tau, label in ((1.0, "the model as is (temperature 1)"), (0.5, "positive control: sharpened (temperature 0.5)"), (2.0, "positive control: flattened (temperature 2)")):
        rows_t = {k: E.compare(prep, arr, m, tau=tau, n_boot=args.boot, tail=tail) for k, m in masks.items()}
        lines += [E.render(rows_t, floor, f"## {label}"), ""]
    lines += [E.render({k: E.compare(prep, arr, m, n_boot=args.boot) for k, m in masks.items()}, title="## sensitivity: the model's mass outside the judged moves dropped (probabilities renormalised over the judged moves)"), ""]
    lines += ["## Error rate (loss > 0.10) against the number of good candidate moves (within 0.02 of the best)", "",
              "| clock | good moves | positions | humans % | model % |", "|---|---|---|---|---|"]
    for k, m in masks.items():
        for d, v in E.by_difficulty(prep, arr, m, tail=tail).items():
            lines.append(f"| {k} | {d} | {v['n']:,} | {100 * v['human']:.1f} | {100 * v['model']:.1f} |")
    text = "\n".join(lines)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)


def cmd_humanlike_adapter(args):
    import numpy as np

    from .humanlike import adapter as A
    from .humanlike import metrics as M
    from .humanlike import report as R
    from .humanlike import score as S
    from .humanlike import testset as T
    manifest = json.loads(Path(str(args.testset) + ".manifest.json").read_text())
    scores, meta = S.load_scores(args.scores)
    if meta["testset_sha256"] != manifest["sha256"]:
        raise SystemExit("the scores were computed on another test set")
    positions = T.read_testset(args.testset, scores["index"])
    arr = R.position_arrays(positions)
    x_all, sl = A.features(arr, scores), A.slots(scores)
    train, val, test = A.game_split(arr["gid"], seed=args.seed)
    print(f"{train.sum():,} training, {val.sum():,} validation, {test.sum():,} test positions (split by game)", flush=True)
    regime_cols = [A.FEATURES.index(n) for n in ("under 10 s", "under 30 s")]
    rating_cols = [A.FEATURES.index(n) for n in ("mover rating", "opponent rating")]
    variants = {"frozen model": None,
                "wrapper: one temperature": ("tau", [A.FEATURES.index("ply")], np.zeros_like(x_all[:, :1])),
                "wrapper: temperature by clock regime and rating": ("tau", regime_cols + rating_cols, None),
                "adapter: clock features, temperature only": ("tau", None, None),
                "adapter: all features, temperature + tail + slot biases": ("full", None, None)}
    fitted = {}
    for name, spec in variants.items():
        if spec is None:
            continue
        mode, cols, override = spec
        x = override if override is not None else (x_all[:, cols] if cols else x_all)
        print(f"fitting {name}", flush=True)
        net, mean, std = A.fit(x, sl, train, val, epochs=args.epochs, mode=mode, seed=args.fit_seed, log=lambda m: None)
        fitted[name] = (A.apply(net, mean, std, x, sl), (net, mean, std, cols, override is not None))
    beh, train_losses = None, None
    if args.judged_train:
        from .humanlike import errors as E
        from .humanlike import judge as J
        with np.load(args.judged_train, allow_pickle=False) as z:
            tmeta = json.loads(str(z["meta"]))
            trows, tj = z["rows"], {k: z[k] for k in ("best_cp", "human_cp", "cand_cp")}
        if tmeta["testset_sha256"] != manifest["sha256"] or tmeta["model"] != meta["model"]:
            raise SystemExit("the judged training file belongs to another test set or model")
        if test[trows].any():
            raise SystemExit("the judged training sample contains positions of test games: judge it with --split trainval and the same split seed")
        k_j = tj["cand_cp"].shape[1]
        c_loss, h_loss = J.losses(tj["best_cp"], tj["cand_cp"][:, :k_j]), J.losses(tj["best_cp"], tj["human_cp"])
        regime_tr = M.clock_regime(arr["clock"][trows])
        beh = A.behaviour_data(trows, c_loss, h_loss, regime_tr, train[trows], scores["rank"][trows])
        train_losses = (c_loss, h_loss, regime_tr)
        print(f"behaviour term on {len(trows):,} judged positions (human targets by regime, in the order {A.REGIMES}: {beh['targets'].round(3).tolist()})", flush=True)
        for lam in (float(v) for v in args.lambdas.split(",")):
            name = f"behaviour-matched adapter (lambda={lam:g})"
            print(f"fitting {name}", flush=True)
            net, mean, std = A.fit(x_all, sl, train, val, epochs=args.epochs, mode="full", behaviour=beh, lam=lam, seed=args.fit_seed, log=lambda m: None)
            fitted[name] = (A.apply(net, mean, std, x_all, sl), (net, mean, std, None, False))
    if args.save_dir:
        import re as _re
        Path(args.save_dir).mkdir(parents=True, exist_ok=True)
        for name, (_, (net, mean, std, cols, const)) in fitted.items():
            if cols is None and not const:
                slug = _re.sub(r"[^a-z0-9.]+", "_", name.lower()).strip("_")
                A.save_adapter(Path(args.save_dir) / f"{slug}.pt", net, mean, std, hidden=32, mode="tau" if "temperature only" in name else "full",
                               meta={"name": name, "base_model": meta["model"], "testset_sha256": manifest["sha256"], "split_seed": args.seed, "epochs": args.epochs})
    masks = {k: v & test for k, v in R.masks(arr).items()}
    lines = [f"# Adapter on a frozen {meta['model']} ({Path(args.testset).name})", "",
             f"Trained on {int(train.sum()):,} positions, early-stopped on {int(val.sum()):,}, evaluated on {int(test.sum()):,} positions of games the adapter never saw. "
             "Every variant gives the probability of the human's actual move, so NLL values are comparable with the frozen model's. "
             "Differences are variant minus frozen model on identical positions, with 95% game-level intervals.", ""]
    base = {k: scores[k] for k in ("p", "top1", "conf", "rank", "entropy", "sq_sum")}
    for name, (out, _) in [("frozen model", (base, None))] + list(fitted.items()):
        rows = {k: R.summarize(out, arr, m, n_boot=args.boot) for k, m in masks.items()}
        lines += [R.table(rows, f"## {name}"), ""]
        if name != "frozen model":
            lines += [R.comparison_table({k: R.compare(out, base, arr, m, n_boot=args.boot) for k, m in masks.items()}, f"### {name} minus frozen model (paired)"), ""]
        lines += [R.matched_table(R.matched_overconfidence(out, arr, masks["full"], n_boot=min(args.boot, 200)), f"### {name}: confidence - accuracy by clock, raw and matched"), ""]
    full_name, wrap_name = "adapter: all features, temperature + tail + slot biases", "wrapper: temperature by clock regime and rating"
    if full_name in fitted and wrap_name in fitted:
        lines += [R.comparison_table({k: R.compare(fitted[full_name][0], fitted[wrap_name][0], arr, m, n_boot=args.boot) for k, m in masks.items()},
                                     f"## {full_name} minus {wrap_name} (paired): what the adapter adds over the best calibration wrapper"), ""]
    if args.judged:
        from .humanlike import errors as E
        with np.load(args.judged, allow_pickle=False) as z:
            jmeta = json.loads(str(z["meta"]))
            jrows = z["rows"]
            judged = {k: z[k] for k in ("best_cp", "human_cp", "cand_cp")}
        if jmeta["testset_sha256"] != manifest["sha256"] or jmeta["model"] != meta["model"]:
            raise SystemExit("the judged file belongs to another test set or model")
        k_judged = judged["cand_cp"].shape[1]
        keep = test[jrows]                                               # only judged positions from games the adapter never saw
        sub_judged = {k: v[keep] for k, v in judged.items()}
        regime = M.clock_regime(arr["clock"][jrows])[keep]
        sub_arr = {k: v[jrows][keep] for k, v in arr.items()}
        jmasks = {"all judged test positions": np.ones(int(keep.sum()), dtype=bool), **{f"clock {r}": regime == r for r in ("30s+", "10-30s", "<10s")}}
        lines += [f"## Sampled-play errors of the adapted models (axis A3) on the {int(keep.sum()):,} judged positions from test games", "",
                  f"Same engine losses as `humanlike-errors`. Each model's probabilities over the frozen model's {k_judged} judged candidates are renormalised; the mass it puts OUTSIDE "
                  f"those {k_judged} moves is added back at the cost of the moves humans played outside them (per regime, from other games when a judged training sample is given) and "
                  "reported below each table.", ""]
        if beh is not None:                                              # the tail stand-in comes from other games than the ones evaluated
            tprep = E.prepare({"topk_p": scores["topk_p"][trows][:, :A.K]}, {"best_cp": tj["best_cp"], "human_cp": tj["human_cp"], "cand_cp": tj["cand_cp"]})
            tstats = E.tail_stats(tprep, scores["rank"][trows], train_losses[2])
        else:
            tstats = None
        for name, out in [("frozen model", {"probs": scores["topk_p"][:, :A.K]})] + [(n, o) for n, (o, _) in fitted.items()]:
            prep = E.prepare({"topk_p": np.asarray(out["probs"])[jrows][keep]}, sub_judged)
            if tstats is None:
                tstats_here = E.tail_stats(prep, scores["rank"][jrows][keep], regime)
            else:
                tstats_here = tstats
            tail = E.tail_arrays(tstats_here, regime)
            cmp_rows = {k: E.compare(prep, sub_arr, m, n_boot=args.boot, tail=tail) for k, m in jmasks.items()}
            unj = {k: float(1.0 - np.asarray(out["probs"])[jrows][keep][m][:, :k_judged].sum(axis=1).mean()) for k, m in jmasks.items()}
            lines += [E.render(cmp_rows, title=f"### {name}"), "", f"Mass outside the {k_judged} judged candidates: " + ", ".join(f"{k} {100 * v:.1f}%" for k, v in unj.items()), ""]
            diff_rows = [(k, d, v) for k, m in jmasks.items() if k != "all judged test positions" for d, v in E.by_difficulty(prep, sub_arr, m, tail=tail).items()]
            lines += ["Error rate (loss > 0.10) by the number of good moves (humans / model, %): " + "; ".join(f"{k} {d} good: {100 * v['human']:.1f} / {100 * v['model']:.1f}" for k, d, v in diff_rows), ""]
    if args.eval_testset:
        m2 = json.loads(Path(str(args.eval_testset) + ".manifest.json").read_text())
        s2, meta2 = S.load_scores(args.eval_scores)
        if meta2["testset_sha256"] != m2["sha256"] or meta2["model"] != meta["model"]:
            raise SystemExit("the evaluation scores belong to another test set or model")
        del positions, arr
        p2 = T.read_testset(args.eval_testset, s2["index"])
        a2 = R.position_arrays(p2)
        x2, sl2 = A.features(a2, s2), A.slots(s2)
        base2 = {k: s2[k] for k in ("p", "top1", "conf", "rank", "entropy", "sq_sum")}
        full2 = np.ones(len(p2), dtype=bool)
        lines += [f"## Independent check on {Path(args.eval_testset).name} (other games; the published Maia-3 / Allie filter: every position has at least 30 s on both clocks)", ""]
        for name, (_, (net, mean, std, cols, const)) in fitted.items():
            x = np.zeros_like(x2[:, :1]) if const else (x2[:, cols] if cols else x2)
            out2 = A.apply(net, mean, std, x, sl2)
            lines += [R.comparison_table({"all positions": R.compare(out2, base2, a2, full2, n_boot=args.boot)}, f"### {name} minus frozen model"), ""]
    text = "\n".join(lines)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)


def cmd_humanlike_selfplay(args):
    import chess
    import numpy as np

    from .humanlike import adapter as A
    from .humanlike import models as MD
    from .humanlike import play as P
    from .humanlike import testset as T
    manifest = json.loads(Path(str(args.testset) + ".manifest.json").read_text())
    print("fitting the time model and choosing the starting positions", flush=True)
    candidates = []

    from .humanlike import adapter as _A
    keep_split = {"all": None, "train": 0, "val": 1, "test": 2}[args.split]

    def in_split(gid):
        return keep_split is None or bool(_A.game_split(np.array([gid]), seed=args.split_seed)[keep_split][0])

    def stream():
        for p in T.iter_testset(args.testset):
            if P.is_start_candidate(p, args.min_start_ply, args.max_start_ply, args.min_clock) and in_split(p.gid):
                candidates.append(p)
            yield p
    tm = P.TimeModel.fit(stream(), seed=args.seed)
    rng = np.random.default_rng(args.seed)
    if args.starts_from:                                              # the starting positions of an earlier run (or of the human games): same games to compare
        wanted = [r["gid"] for r in map(json.loads, Path(args.starts_from).read_text().splitlines()) if r.get("gid")]
        by_key = {f"{p.gid}@{p.ply}": p for p in candidates}
        chosen = [by_key[k] for k in wanted if k in by_key][:args.games]
        print(f"{len(chosen):,} of the {len(wanted):,} starting positions of {Path(args.starts_from).name} found among the candidates", flush=True)
    else:
        chosen = [candidates[i] for i in sorted(rng.choice(len(candidates), size=min(args.games, len(candidates)), replace=False))]
    del candidates
    kw = dict(maia3_repo=args.maia3_repo, maia2_repo=args.maia2_repo, weights_dir=args.weights_dir, extra_path=args.extra_path, device=args.device, batch=args.batch)

    def build(spec, adapter):
        scorer = MD.make_scorer(spec, **kw)
        scorer = P.AdaptedScorer(scorer, A.load_adapter(adapter), name=f"{scorer.name} + {Path(adapter).stem}") if adapter else scorer
        return P.TemperatureScorer(scorer, args.temperature) if args.temperature != 1.0 else scorer
    args.black = args.black or args.white
    white = build(args.white, args.white_adapter)
    black = white if (args.black == args.white and args.black_adapter == args.white_adapter) else build(args.black, args.black_adapter)
    games = [P.game_from_position(p, {chess.WHITE: white, chess.BLACK: black}) for p in chosen]
    t0 = time.time()
    P.play_games(games, tm, seed=args.seed, max_plies=args.max_plies, batch=args.play_batch,
                 progress=lambda d, n: print(f"  {d:,}/{n:,} games finished  {time.time() - t0:.0f}s", flush=True))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for g in games:
            f.write(json.dumps(P.game_record(g), separators=(",", ":")) + "\n")
    from collections import Counter
    print(f"{len(games):,} games ({white.name} vs {black.name}) in {time.time() - t0:.0f}s -> {out}; results {dict(Counter(g.result for g in games))}, "
          f"terminations {dict(Counter(g.termination for g in games))}")


def cmd_humanlike_gamestats(args):
    from .humanlike import gamestats as GS
    sets = {}
    for spec in args.games:
        name, _, path = spec.partition("=")
        sets[name] = GS.read_games(path)
    lines = []
    if args.real:
        real_by_id = {}
        with open(args.real, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    g = json.loads(line)
                    real_by_id[g["id"]] = g
        first = next(iter(sets.values()))
        real = {}
        for r in first:
            gid, _, ply = r["gid"].partition("@")
            if gid in real_by_id and ply.isdigit():
                real[r["gid"]] = GS.real_continuation(real_by_id[gid], int(ply), r["gid"])
        keys = [k for k in real if real[k]["moves"]]
        lines.append(f"{len(keys):,} starting positions with the real continuation. Per-move rows compare the same stretch of each game (the generated games are cut where the real game ended: "
                     f"humans resign, generated games are played out); how a game ends is only comparable in the whole-game table.\n")
        by_gid = {name: {r["gid"]: r for r in rs} for name, rs in sets.items()}
        matched = {"real": GS.summarize([real[k] for k in keys])}
        for name, rs in by_gid.items():
            matched[name] = GS.summarize([GS.truncate(rs[k], real[k]["plies"]) for k in keys if k in rs])
        lines += ["### matched stretches (per-move statistics)", GS.table(matched, per_move_only=True), ""]
        sets = {"real": [real[k] for k in keys], **sets}
    lines += ["### whole games", GS.table({name: GS.summarize(rs) for name, rs in sets.items()})]
    text = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)


def cmd_humanlike_humangames(args):
    import numpy as np

    from .humanlike import adapter as _A
    from .humanlike import gamestats as GS
    from .humanlike import lichess_games as LG
    from .humanlike import play as P
    from .humanlike import testset as T
    keep_split = {"all": None, "train": 0, "val": 1, "test": 2}[args.split]
    candidates = [p for p in T.iter_testset(args.testset) if P.is_start_candidate(p, args.min_start_ply, args.max_start_ply, args.min_clock)]
    if keep_split is not None:
        gids = np.array(sorted({p.gid for p in candidates}))
        member = set(gids[_A.game_split(gids, seed=args.split_seed)[keep_split]])
        candidates = [p for p in candidates if p.gid in member]
    chosen = P.choose_starts(candidates, args.games, seed=args.seed)
    print(f"{len(candidates):,} candidate positions; {len(chosen):,} chosen (one per game)", flush=True)
    games = {g["id"]: g for g in LG.fetch_games([p.gid for p in chosen], pause=args.pause)}
    dropped = {"not returned": 0, "unreadable": 0, "history differs": 0, "no moves after the start": 0}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    kept = 0
    with open(out, "w", encoding="utf-8") as f:
        for p in chosen:
            g = games.get(p.gid)
            if g is None:
                dropped["not returned"] += 1
                continue
            try:
                rec = GS.real_continuation(g, p.ply, f"{p.gid}@{p.ply}")
            except (ValueError, KeyError):
                dropped["unreadable"] += 1
                continue
            if rec["start"] != p.moves:
                dropped["history differs"] += 1
            elif not rec["moves"]:
                dropped["no moves after the start"] += 1
            else:
                f.write(json.dumps({**rec, "models": {"white": "human", "black": "human"}}, separators=(",", ":")) + "\n")
                kept += 1
    manifest = {"games": kept, "chosen": len(chosen), "dropped": dropped, "split": args.split, "seed": args.seed, "testset": Path(args.testset).name}
    Path(str(out) + ".manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"{kept:,} human games from {len(chosen):,} chosen starts -> {out}; dropped {dropped}")


def cmd_humanlike_quality(args):
    from .humanlike import gamestats as GS
    from .humanlike import quality as Q
    records = GS.read_games(args.games)
    if args.limit:
        records = records[:args.limit]
    done = Q.annotate_games(records, engine_path=args.engine, workers=args.workers, max_moves=args.max_moves, nodes=args.nodes,
                            progress=lambda i, n: print(f"  {i:,} / {n:,} games", flush=True))
    Q.write(args.out, done)
    print(f"wrote {len(done):,} games to {args.out}")


def cmd_humanlike_stimuli(args):
    from .humanlike import gamestats as GS
    from .humanlike import stimuli as ST
    human = GS.read_games(args.human)
    generated = {}
    for spec in args.games:
        name, _, path = spec.partition("=")
        generated[name] = GS.read_games(path)
    conditions = args.conditions or list(generated)
    try:
        stim, key = ST.build(human, generated, conditions, blocks=args.blocks, per_condition=args.per_condition, checks=args.checks,
                             fragment_plies=args.fragment_plies, min_plies=args.min_plies, seed=args.seed)
    except ValueError as e:
        raise SystemExit(str(e))
    problems = ST.audit(stim, key)
    if problems:
        raise SystemExit("audit failed: " + "; ".join(problems[:5]))
    stim["seed"] = args.seed
    Path(args.out).write_text(json.dumps(stim, separators=(",", ":")))
    Path(args.key).write_text(json.dumps({"seed": args.seed, "conditions": conditions, "trials": key}, indent=0))
    print(f"{len(stim['blocks'])} blocks of {len(stim['blocks'][0]['trials'])} trials ({args.per_condition} per condition {conditions}, {args.checks} checks) -> {args.out}; "
          f"answer key -> {args.key} (keep it away from the participants)")


def cmd_humanlike_scaling(args):
    import numpy as np

    from .humanlike import metrics as M
    from .humanlike import report as R
    from .humanlike import scaling as SC
    from .humanlike import score as S
    from .humanlike import testset as T
    manifest = json.loads(Path(str(args.testset) + ".manifest.json").read_text())
    params = {}
    for spec in args.params:
        name, _, v = spec.partition("=")
        params[name] = float(v)
    per, arr, rows0, regime, sizes = {}, None, None, None, []
    for spec in args.models:
        name, _, rest = spec.partition("=")
        spath, _, jpath = rest.partition(",")
        scores, meta = S.load_scores(spath)
        with np.load(jpath, allow_pickle=False) as z:
            jmeta, rows = json.loads(str(z["meta"])), z["rows"]
            judged = {k: z[k] for k in ("best_cp", "human_cp", "cand_cp")}
        if jmeta["testset_sha256"] != manifest["sha256"] or jmeta["model"] != meta["model"]:
            raise SystemExit(f"{name}: the judged file belongs to another test set or model")
        if rows0 is None:
            rows0 = rows
            chosen = T.read_testset(args.testset, scores["index"][rows])
            arr = R.position_arrays(chosen)
            regime = M.clock_regime(arr["clock"])
        elif not np.array_equal(rows, rows0):
            raise SystemExit(f"{name}: judged on other positions than the first model; sizes must be compared on identical positions")
        sub = {k: v[rows] for k, v in scores.items() if k != "index"}
        per[name], _ = SC.prepared(sub, judged, regime)
        sizes.append(name)
    masks = {"all judged positions": np.ones(len(rows0), dtype=bool), **{f"clock {r}": regime == r for r in ("30s+", "10-30s", "<10s")}}
    lines = [f"# Gap between model and humans by model size (axis A3, same {len(rows0):,} positions for every size)", "",
             "Gap = the model's expected value minus what the humans did, in points (x100), positions of the clock regime; 95% intervals resample whole games; "
             "differences are larger minus smaller size on identical positions; slope = change of the gap per doubling of the parameters (least squares over the sizes).", ""]
    for measure in ("blunder (loss > 0.20)", "error (loss > 0.10)", "mean loss"):
        lines += [f"## {measure}", "", "| positions | " + " | ".join(sizes) + " | " + " | ".join(f"{b} - {a}" for (b, a) in [(sizes[-1], sizes[0])] + ([(sizes[-1], sizes[-2])] if len(sizes) > 2 else [])) + " | slope per doubling |",
                  "|---|" + "---|" * (len(sizes) + 1 + (1 if len(sizes) > 2 else 0) + 1)]
        for label, m in masks.items():
            r = SC.gaps({n: per[n][measure] for n in sizes}, params, arr["gid"], m, measure, n_boot=args.boot)
            f = lambda t: f"{100 * t[0]:+.2f} [{100 * t[1]:+.2f}, {100 * t[2]:+.2f}]"
            pairs = [(sizes[-1], sizes[0])] + ([(sizes[-1], sizes[-2])] if len(sizes) > 2 else [])
            lines.append(f"| {label} ({r['positions']:,}) | " + " | ".join(f(r["gap"][n]) for n in sizes) + " | " + " | ".join(f(r["diff"][p]) for p in pairs) + f" | {f(r['slope'])} |")
        lines.append("")
    text = "\n".join(lines)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)


def cmd_humanlike_frontier(args):
    import numpy as np

    from .humanlike import errors as E
    from .humanlike import frontier as FR
    from .humanlike import metrics as M
    from .humanlike import report as R
    from .humanlike import score as S
    from .humanlike import testset as T
    manifest = json.loads(Path(str(args.testset) + ".manifest.json").read_text())
    scores, meta = S.load_scores(args.scores)
    with np.load(args.judged, allow_pickle=False) as z:
        jmeta, rows = json.loads(str(z["meta"])), z["rows"]
        judged = {k: z[k] for k in ("best_cp", "human_cp", "cand_cp")}
    if jmeta["testset_sha256"] != manifest["sha256"] or jmeta["model"] != meta["model"]:
        raise SystemExit("the judged file belongs to another test set or model")
    arr = R.position_arrays(T.read_testset(args.testset, scores["index"][rows]))
    sub = {k: v[rows] for k, v in scores.items() if k != "index"}
    prep = E.prepare(sub, judged)
    regime = M.clock_regime(arr["clock"])
    settings = [("engine-reweighted", float(b)) for b in args.betas.split(",")] + [("temperature", float(v)) for v in args.taus.split(",")] + \
               [("mixture", float(v)) for v in args.alphas.split(",")]
    lines = [f"# Strength against human-likeness: {meta['model']} ({len(rows):,} judged positions, {prep['cand_loss'].shape[1]} candidates)", "",
             "Expected loss = points given away per move by the policy (lower = stronger); NLL of the human's move = human-likeness (lower = more human-like), only over positions where "
             "the human's move is among the judged candidates; policies are renormalised over the judged candidates. 95% game-level intervals.", ""]
    for label, mask in (("all judged positions", np.ones(len(rows), dtype=bool)), *((f"clock {r}", regime == r) for r in ("30s+", "10-30s", "<10s"))):
        out = FR.sweep(prep, sub["rank"], arr["gid"], mask, settings, n_boot=args.boot)
        lines += [FR.render(out, f"## {label} ({int(mask.sum()):,} positions, human move among the candidates in {100 * out[0]['covered']:.1f}%)"), "",
                  FR.render_equal_strength(out, f"### {label}: human-likeness at equal strength"), ""]
    text = "\n".join(lines)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)


def cmd_humanlike_arena(args):
    import hashlib
    import time

    import chess

    from .humanlike import arena as AR
    from .humanlike import elo as EL
    from .humanlike import gamestats as GS
    from .humanlike import models as MD
    from .humanlike import play as P
    import shutil
    engine = args.engine or shutil.which("stockfish")
    if not engine:
        raise SystemExit("Stockfish not found: pass --engine")
    for spec in args.players:                                                          # a bad spec must fail before any engine is started
        if spec.partition("=")[2].partition(":")[0] not in ("sf", "bot"):
            raise SystemExit(f"unknown player {spec!r} (use NAME=sf:nodes=N or NAME=bot:maia3=23m+history:beta=B[:rating=R][:nodes=N])")
    pool = AR.EnginePool(engine, workers=args.workers)
    ref_pool = AR.EnginePool(engine, workers=max(1, args.workers // 2))
    try:
        _arena(args, AR, EL, GS, MD, P, pool, ref_pool, chess, json, hashlib, time)
    finally:
        pool.close()
        ref_pool.close()


def _arena(args, AR, EL, GS, MD, P, pool, ref_pool, chess, json, hashlib, time):
    players, groups, bases = {}, {}, {}
    for spec in args.players:
        name, _, rest = spec.partition("=")
        kind, _, opts = rest.partition(":")
        if kind == "sf":
            kv = dict(o.split("=") for o in opts.split(":"))
            players[name], groups[name] = AR.StockfishScorer(pool, int(kv["nodes"]), name=name), "ladder"
        elif kind == "bot":
            first, *more = opts.split(":")
            kv = dict(o.split("=") for o in more)
            if first not in bases:
                bases[first] = MD.make_scorer(first, maia3_repo=args.maia3_repo, maia2_repo=args.maia2_repo, weights_dir=args.weights_dir, extra_path=args.extra_path,
                                              device=args.device, batch=args.batch)
            players[name], groups[name] = AR.ReweightedScorer(bases[first], pool, float(kv.get("beta", 0)), nodes_child=int(kv.get("nodes", 10000)),
                                                              nodes_root=int(kv.get("root", 20000)), rating=int(kv["rating"]) if "rating" in kv else None, name=name), "bot"
        else:
            raise SystemExit(f"unknown player {spec!r} (use NAME=sf:nodes=N or NAME=bot:maia3=23m+history:beta=B[:rating=R][:nodes=N])")
    starts = []
    seen = set()
    for r in GS.read_games(args.starts_from):
        if r["start"] not in seen:
            seen.add(r["start"])
            starts.append(r["start"])
    starts = sorted(starts, key=lambda s: hashlib.sha256(f"{args.seed}:{s}".encode()).hexdigest())[:args.starts]
    names = list(players)
    todo = AR.schedule(players, AR.pairings(names, groups, bot_vs_bot=args.bot_vs_bot), starts)
    todo.sort(key=lambda g: (g[3], g[0]))
    out = Path(args.games_out)
    done = {}
    if out.exists():
        for line in out.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                done[d["gid"]] = d
    todo = [g for g in todo if g[0] not in done]
    print(f"{len(players)} players, {len(starts)} openings, {len(done):,} games done, {len(todo):,} to play", flush=True)
    referee = AR.Referee(ref_pool, nodes=args.referee_nodes)
    t0 = time.time()
    for i in range(0, len(todo), args.chunk):
        part = todo[i:i + args.chunk]
        games = [AR.game_from_start(s, {chess.WHITE: players[w], chess.BLACK: players[b]}, gid) for gid, w, b, _, s in part]
        P.play_games(games, AR.NoTime(), max_plies=args.max_plies, referee=referee)
        with open(out, "a", encoding="utf-8") as f:
            for (gid, w, b, k, s), g in zip(part, games):
                d = {"gid": gid, "white": w, "black": b, "opening": k, "result": g.result, "termination": g.termination, "plies": g.ply, "start": s, "moves": " ".join(g.moves)}
                done[gid] = d
                f.write(json.dumps(d, separators=(",", ":")) + "\n")
        print(f"  {len(done):,} games  {time.time() - t0:.0f}s", flush=True)
    results = [(d["white"], d["black"], AR.result_for(d["white"], d["black"], d["result"], d["white"], d["black"]), d["opening"]) for d in done.values()
               if d["white"] in players and d["black"] in players]
    anchor = args.anchor or next(n for n in names if groups[n] == "ladder")
    rating = EL.fit(names, results, anchor=anchor)
    ci = EL.bootstrap(names, results, anchor=anchor, boot=args.boot)
    tally = {n: [0.0, 0] for n in names}
    for a, b, s, _ in results:
        tally[a][0] += s; tally[a][1] += 1
        tally[b][0] += 1 - s; tally[b][1] += 1
    from collections import Counter
    ends = Counter(d["termination"] for d in done.values())
    lines = [f"# Match results: {len(done):,} games, {len(starts)} openings, both colours", "",
             f"Elo relative to {anchor} (0), 95% intervals resample openings. Games are adjudicated by a referee engine ({args.referee_nodes} nodes). Endings: " + ", ".join(f"{k} {v}" for k, v in ends.most_common()) + ".", "",
             "| player | kind | Elo | 95% interval | games | score % |", "|---|---|---|---|---|---|"]
    for n in sorted(names, key=lambda n: -rating[n]):
        lines.append(f"| {n} | {groups[n]} | {rating[n]:+.0f} | [{ci[n][0]:+.0f}, {ci[n][1]:+.0f}] | {tally[n][1]} | {100 * tally[n][0] / max(tally[n][1], 1):.1f} |")
    text = "\n".join(lines)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)


def _model_variants(scores, arr, meta, adapters_dir, lambdas):
    """(base statistics, {name: (probabilities over the 16 stored slots, adapter meta)}): the frozen model and the saved adapters (likelihood adapter and the
    behaviour-matched ones for the given weights), applied without refitting."""
    from .humanlike import adapter as A
    base = {k: scores[k] for k in ("p", "top1", "conf", "rank", "entropy", "sq_sum")}
    outs = {"frozen model": ({**base, "probs": scores["topk_p"][:, :A.K]}, None)}
    x, sl = (A.features(arr, scores), A.slots(scores)) if adapters_dir else (None, None)
    adapters = {"likelihood adapter": "adapter_all_features_temperature_tail_slot_biases.pt"} if adapters_dir else {}
    for lam in (lambdas.split(",") if adapters_dir and lambdas else []):
        adapters[f"behaviour-matched adapter (lambda={float(lam):g})"] = f"behaviour_matched_adapter_lambda_{float(lam):g}.pt"
    for name, fname in adapters.items():
        net, mean, std, ameta = A.load_adapter(Path(adapters_dir) / fname)
        if ameta.get("base_model") not in (None, meta["model"]):
            raise SystemExit(f"{fname} was trained on {ameta.get('base_model')}, not {meta['model']}")
        outs[name] = (A.apply(net, mean, std, x, sl), ameta)
    return base, outs


def cmd_humanlike_confirm(args):
    """The confirmation split: trained adapters (not refitted) and the frozen model on a NEW test set, judged by the engine. Nothing is tuned here."""
    import numpy as np

    from .humanlike import adapter as A
    from .humanlike import errors as E
    from .humanlike import metrics as M
    from .humanlike import report as R
    from .humanlike import score as S
    from .humanlike import testset as T
    manifest = json.loads(Path(str(args.testset) + ".manifest.json").read_text())
    scores, meta = S.load_scores(args.scores)
    with np.load(args.judged, allow_pickle=False) as z:
        jmeta, jrows = json.loads(str(z["meta"])), z["rows"]
        judged = {k: z[k] for k in ("best_cp", "human_cp", "cand_cp")}
    if meta["testset_sha256"] != manifest["sha256"] or jmeta["testset_sha256"] != manifest["sha256"] or jmeta["model"] != meta["model"]:
        raise SystemExit("the scores or the judged file belong to another test set or model")
    if len(jrows) == 0 or jrows.max() >= len(scores["index"]):
        raise SystemExit("the judged file does not match these scores (other positions)")
    chosen = T.read_testset(args.testset, scores["index"][jrows])
    if S.positions_hash(chosen) != jmeta["positions_sha"]:
        raise SystemExit("the positions do not match the judged file")
    arr = R.position_arrays(T.read_testset(args.testset, scores["index"]))
    arr_j = R.position_arrays(chosen)
    regime_j = M.clock_regime(arr_j["clock"])
    # the stand-in cost of the moves outside the judged candidates comes from the TRAINING games' judged sample, as when the adapters were trained
    tman = json.loads(Path(str(args.train_testset) + ".manifest.json").read_text())
    tscores, tmeta = S.load_scores(args.train_scores)
    with np.load(args.judged_train, allow_pickle=False) as z:
        trmeta, trows = json.loads(str(z["meta"])), z["rows"]
        tj = {k: z[k] for k in ("best_cp", "human_cp", "cand_cp")}
    if tmeta["testset_sha256"] != tman["sha256"] or trmeta["testset_sha256"] != tman["sha256"] or tmeta["model"] != meta["model"]:
        raise SystemExit("the training scores or judged sample belong to another test set or model")
    tarr = R.position_arrays(T.read_testset(args.train_testset, tscores["index"][trows]))
    tprep = E.prepare({"topk_p": tscores["topk_p"][trows][:, :A.K]}, tj)
    tail = E.tail_arrays(E.tail_stats(tprep, tscores["rank"][trows], M.clock_regime(tarr["clock"])), regime_j)
    base, outs = _model_variants(scores, arr, meta, args.adapters_dir, args.lambdas)
    masks = R.masks(arr)
    jmasks = {"all judged positions": np.ones(len(jrows), dtype=bool), **{f"clock {r}": regime_j == r for r in ("30s+", "10-30s", "<10s")}}
    lines = [f"# Confirmation split: {meta['model']} on {Path(args.testset).name} ({len(arr['ply']):,} positions, {len(jrows):,} judged)", "",
             "Frozen model and adapters trained on OTHER games (not refitted, nothing tuned here). Blunder-rate gap = model minus humans, points x100, 95% game-level intervals; "
             "the mass outside the 16 judged candidates is added back at the humans' cost of such moves, taken from the training games' judged sample.", ""]
    summary = ["| model | blunder gap <10 s | 10-30 s | 30 s+ | all | NLL change <10 s | 10-30 s | 30 s+ | overall |", "|---|---|---|---|---|---|---|---|---|"]
    details = []
    for name, (out, _) in outs.items():
        prep = E.prepare({"topk_p": np.asarray(out["probs"])[jrows]}, judged)
        cmp_rows = {k: E.compare(prep, arr_j, m, n_boot=args.boot, tail=tail) for k, m in jmasks.items()}
        b = lambda k: "{:+.2f} [{:+.2f}, {:+.2f}]".format(*(100 * v for v in cmp_rows[k]["blunder (loss > 0.20)"]["diff"]))
        if name == "frozen model":
            nll = ["-"] * 4
        else:
            nll = ["{:+.4f} [{:+.4f}, {:+.4f}]".format(*R.compare(out, base, arr, masks[k], n_boot=args.boot)["nll"]) for k in ("clock <10s", "clock 10-30s", "clock 30s+", "full")]
        summary.append(f"| {name} | {b('clock <10s')} | {b('clock 10-30s')} | {b('clock 30s+')} | {b('all judged positions')} | " + " | ".join(nll) + " |")
        details += [E.render(cmp_rows, title=f"### {name}"), ""]
    lines += ["## Summary", ""] + summary + ["", "## Error profile by clock regime", ""] + details
    text = "\n".join(lines)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)


def _implied_blunder(prep, tail):
    """The model's probability of a blunder per position, with the mass outside the judged candidates added back at the humans' blunder rate for such moves; where that
    rate is unknown (a regime with too few positions) the probabilities over the judged candidates are renormalised instead."""
    import numpy as np

    from .humanlike import errors as E
    name = "blunder (loss > 0.20)"
    q = E.model_values(prep, 1.0, tail)[name]
    return np.where(np.isnan(q), E.model_values(prep, 1.0, None)[name], q)


def cmd_humanlike_diagnose(args):
    """Two diagnostics on judged positions: the MIX of blunder types (humans against the model and the saved adapters) and whether the blunder probability the
    model implies in each position is calibrated and informative (discrimination, Brier, slope). Nothing is fitted here."""
    import numpy as np

    from .humanlike import blunders as BL
    from .humanlike import calibration as CA
    from .humanlike import errors as E
    from .humanlike import metrics as M
    from .humanlike import report as R
    from .humanlike import score as S
    from .humanlike import testset as T
    manifest = json.loads(Path(str(args.testset) + ".manifest.json").read_text())
    scores, meta = S.load_scores(args.scores)
    with np.load(args.judged, allow_pickle=False) as z:
        jmeta, jrows = json.loads(str(z["meta"])), z["rows"]
        judged = {k: z[k] for k in ("best_cp", "human_cp", "cand_cp")}
    if meta["testset_sha256"] != manifest["sha256"] or jmeta["testset_sha256"] != manifest["sha256"] or jmeta["model"] != meta["model"]:
        raise SystemExit("the scores or the judged file belong to another test set or model")
    chosen = T.read_testset(args.testset, scores["index"][jrows])
    if S.positions_hash(chosen) != jmeta["positions_sha"]:
        raise SystemExit("the positions do not match the judged file")
    arr = R.position_arrays(T.read_testset(args.testset, scores["index"])) if args.adapters_dir else None
    arr_j = R.position_arrays(chosen)
    regime = M.clock_regime(arr_j["clock"])
    _, outs = _model_variants(scores, arr, meta, args.adapters_dir, args.lambdas)
    masks = {"all judged positions": np.ones(len(jrows), dtype=bool), **{f"clock {r}": regime == r for r in ("30s+", "10-30s", "<10s")}}
    rank = scores["rank"][jrows]
    k = judged["cand_cp"].shape[1]
    preps = {name: E.prepare({"topk_p": np.asarray(out["probs"])[jrows]}, judged) for name, (out, _) in outs.items()}
    first = next(iter(preps.values()))
    print(f"classifying the blunders of {len(jrows):,} positions", flush=True)
    human_type, cand_type, _ = BL.type_arrays([p.fen for p in chosen], [p.played for p in chosen], scores["topk_move"][jrows][:, :k].tolist(), first["cand_loss"],
                                              first["human_loss"])
    tail_t = BL.tail_type_rates(human_type, rank, regime, k)
    tail_b = E.tail_arrays(E.tail_stats(first, rank, regime), regime)
    lines = [f"# Blunder types and per-position calibration: {meta['model']} on {Path(args.testset).name} ({len(jrows):,} judged positions)", "",
             "Blunder = the move loses more than 0.20 expected points (Stockfish, the judging of `humanlike-judge`). Types are rules on the position and the move alone: "
             "**mate in 1** (the opponent can mate next move), **ignores a threat** (the opponent could win two pawns or more by a capture before the move and still can), "
             "**walks into a capture** (the move allows such a capture that was not there before), **deeper** (none of these: not visible at one move). Rates are per position, x100. "
             "The model's mass outside the judged candidates is added back at the humans' rates for moves outside them (same clock regime). Intervals resample games.", ""]
    lines += ["## 1. Mix of blunder types, humans against the model", ""]
    for name, prep in preps.items():
        model, human = BL.type_rates(prep, cand_type, human_type, regime, tail=tail_t)
        rows = {label: BL.compare_types(model, human, arr_j, m, n_boot=args.boot) for label, m in masks.items() if m.sum() >= 5}
        lines += [BL.render_types(rows, f"### {name}"), ""]
    lines += ["## 2. Does the model know where humans blunder? Implied blunder probability against what the human did", "",
              "Per position the model's implied probability of a blunder (its probability on moves losing more than 0.20) against whether the human blundered there. "
              "**AUC** 0.5 = no information inside the subset; **skill vs base rate** > 0 = better than predicting the subset's blunder rate; **skill vs difficulty-only** = the same against "
              "the base rate by number of good moves (within 0.02 of the best); **slope** = slope of the outcome on the logit of the implied probability (1 = calibrated spread). "
              "One human move per position is a noisy outcome: compare models on the same positions rather than reading the absolute values.", ""]
    y = (first["human_loss"] > BL.BLUNDER).astype(float)
    rows = {}
    for label, m in masks.items():
        if (m & ~np.isnan(first["human_loss"])).sum() < 5:
            continue
        qs = {name: _implied_blunder(prep, tail_b) for name, prep in preps.items()}
        rows[label] = CA.bootstrap(qs, y, arr_j["gid"], m & ~np.isnan(first["human_loss"]), n_boot=args.boot, difficulty=first["n_good"])
    lines += [CA.render(rows), ""]
    for label in rows:
        name = next(iter(preps))
        rel = CA.reliability(_implied_blunder(preps[name], tail_b)[masks[label]], y[masks[label]], np.ones(masks[label].sum()), bins=8)
        lines += [f"Reliability, {name}, {label}: " + "; ".join(f"model {100 * a:.1f}% -> humans {100 * b:.1f}%" for a, b, _ in rel), ""]
    text = "\n".join(lines)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)


def cmd_humanlike_c2st(args):
    from .humanlike import c2st as C
    from .humanlike import gamestats as GS
    human = GS.read_games(args.human)
    generated = {}
    for spec in args.games:
        name, _, path = spec.partition("=")
        generated[name] = GS.read_games(path)
    if args.limit:
        human = human[:args.limit]
    quality = None
    if args.quality:
        from .humanlike import quality as Q
        quality = {}
        for spec in args.quality:
            name, _, path = spec.partition("=")
            quality[name] = Q.read(path)
        missing = ({"human"} | set(generated)) - set(quality)
        if missing:
            raise SystemExit(f"--quality needs a file for {', '.join(sorted(missing))} (NAME=FILE, with 'human' for the human games)")
    result = C.run(human, generated, folds=args.folds, seed=args.seed, boot=args.boot, hidden=args.hidden, epochs=args.epochs, quality=quality, max_moves=args.max_moves)
    text = C.report(result)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)


def cmd_mechess(args):
    from .mechess import priors
    from .mechess.controller import MeChess, load_books
    from .mechess.uci import MechessUci
    from .uci_client import UciEngine

    kind, _, path = args.prior.partition("=")
    if kind == "ours":
        prior = priors.OursPrior(path)
    elif kind == "maia3":
        prior = priors.Maia3Prior(args.maia3_repo, path, args.maia3_size, extra_paths=[args.extra_path] if args.extra_path else [])
    elif kind == "style":
        prior = priors.StylePrior(path, strength=args.style_strength)
    elif kind == "uniform":
        prior = priors.UniformPrior()
    else:
        raise SystemExit("--prior must be uniform, ours=CHECKPOINT, maia3=CHECKPOINT or style=MODEL.json")
    engine = UciEngine([args.engine]).start()
    try:
        book = load_books(args.book) if args.book else None
        from .mechess.calibration import Calibration
        cal = Calibration.load(args.calibration) if args.calibration else None
        from .mechess import dial
        table = dial.load_table(args.table) if args.table else (cal.table() if cal else None)   # a calibration brings its own table
        mc = MeChess(engine, prior, book, table=table, seed=args.seed or None, calibration=cal)
        clock = None
        if args.clock:
            from .mechess.clock import ClockModel
            clock = ClockModel.load(args.clock)
        MechessUci(mc, elo=args.elo, clock=clock, clock_strength=args.clock_strength).run()
    finally:
        engine.close()


def main():
    p = argparse.ArgumentParser(prog="chessme")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download games for the accounts in a profile")
    f.add_argument("--profile", default=DEFAULT_PROFILE)
    f.add_argument("--only", nargs="*", help="limit to these usernames")
    f.set_defaults(func=cmd_fetch)
    for name, fn, helptext in [("ingest", cmd_ingest, "normalise raw games into data/processed/games.jsonl"),
                               ("audit", cmd_audit, "print a data audit report")]:
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--profile", default=DEFAULT_PROFILE)
        sp.set_defaults(func=fn)

    o = sub.add_parser("openings", help="build an opening-position file from your games (or random)")
    o.add_argument("--profile", default=DEFAULT_PROFILE)
    o.add_argument("--out", required=True)
    o.add_argument("--plies", type=int, default=8)
    o.add_argument("--n", type=int, default=None, help="keep at most this many")
    o.add_argument("--seed", type=int, default=1)
    o.add_argument("--random", type=int, default=0, help="generate this many random openings instead")
    o.add_argument("--balance-engine", help="keep only openings this engine rates within --balance-cp")
    o.add_argument("--balance-cp", type=int, default=100)
    o.add_argument("--balance-depth", type=int, default=6)
    o.set_defaults(func=cmd_openings)

    def add_limit(sp):
        sp.add_argument("--nodes", type=int)
        sp.add_argument("--depth", type=int)
        sp.add_argument("--movetime", type=int, help="milliseconds per move")
        sp.add_argument("--concurrency", type=int, default=1)
        sp.add_argument("--no-adjudicate", action="store_true")

    m = sub.add_parser("match", help="play engine A against engine B (paired openings, optional SPRT)")
    m.add_argument("--a", required=True); m.add_argument("--a-name"); m.add_argument("--a-opt", action="append")
    m.add_argument("--b", required=True); m.add_argument("--b-name"); m.add_argument("--b-opt", action="append")
    m.add_argument("--openings", required=True)
    m.add_argument("--pairs", type=int, help="max opening pairs (2 games each)")
    m.add_argument("--sprt", type=float, nargs=2, metavar=("ELO0", "ELO1"))
    m.add_argument("--pgn")
    add_limit(m)
    m.set_defaults(func=cmd_match)

    sp = sub.add_parser("selfplay", help="generate 'FEN | result' tuning data by engine self-play")
    sp.add_argument("--engine", required=True); sp.add_argument("--opt", action="append")
    sp.add_argument("--openings", required=True)
    sp.add_argument("--games", type=int, required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--seed", type=int, default=1)
    sp.add_argument("--keep-prob", type=float, default=0.35)
    add_limit(sp)
    sp.set_defaults(func=cmd_selfplay)

    t = sub.add_parser("texel-data", help="tuning positions from your own games (weighted by the profile filters)")
    t.add_argument("--profile", default=DEFAULT_PROFILE)
    t.add_argument("--out", required=True)
    t.add_argument("--keep-prob", type=float, default=0.2)
    t.add_argument("--weight-scale", type=float, default=0.3)
    t.add_argument("--seed", type=int, default=1)
    t.set_defaults(func=cmd_texel_data)

    tu = sub.add_parser("tune", help="fit evaluation parameters (runs the C++ texel tuner)")
    tu.add_argument("--data", nargs="+", required=True)
    tu.add_argument("--out", required=True)
    tu.add_argument("--params-in")
    tu.add_argument("--epochs", type=int, default=300)
    tu.add_argument("--lr", type=float, default=1.0)
    tu.add_argument("--l2", type=float, default=1e-8)
    tu.add_argument("--val", type=float, default=0.1)
    tu.add_argument("--max-positions", type=int, default=0)
    tu.add_argument("--freeze", help="comma-separated parameter groups to keep fixed")
    tu.set_defaults(func=cmd_tune)
    b = sub.add_parser("book", help="build an opening book from your games")
    b.add_argument("--profile", default=DEFAULT_PROFILE)
    b.add_argument("--out", help="default: profiles/<profile>/book.bin")
    b.add_argument("--max-ply", type=int)
    b.add_argument("--min-games", type=int)
    b.add_argument("--min-position-games", type=int)
    b.add_argument("--min-share", type=float)
    b.add_argument("--holdout", type=float, help="also report how well a book built from older games predicts "
                                                 "the newest FRACTION of your games")
    b.add_argument("--sanity-engine", help="UCI engine used to drop book moves that lose material")
    b.set_defaults(func=cmd_book)
    md = sub.add_parser("me-data", help="build training shards for the 'me' model")
    md.add_argument("source", help="'user' (your own games, needs --profile) or a Lichess .pgn.zst URL / file")
    md.add_argument("--out", required=True)
    md.add_argument("--profile", default=DEFAULT_PROFILE)
    md.add_argument("--samples-per-bin", type=int, default=20000)
    md.add_argument("--rating-min", type=int, default=1100)
    md.add_argument("--rating-max", type=int, default=2600)
    md.add_argument("--bin-width", type=int, default=100)
    md.add_argument("--keep-prob", type=float, default=0.2)
    md.add_argument("--min-ply", type=int, default=10)
    md.add_argument("--min-clock", type=float, default=30)
    md.add_argument("--budget-mb", type=float, help="stop after reading this many compressed MB of the stream")
    md.add_argument("--workers", type=int, default=1)
    md.add_argument("--seed", type=int, default=1)
    md.add_argument("--test-fraction", type=float, default=0.1)
    md.add_argument("--time-classes", default="blitz,rapid,classical", help="Lichess time controls to keep (comma-separated)")
    md.add_argument("--train-time-classes", help="user data: train only on these time controls (val / test unchanged)")
    md.set_defaults(func=cmd_me_data)

    mt = sub.add_parser("me-train", help="train (or fine-tune) the 'me' network")
    mt.add_argument("--data", required=True, help="folder with train*.npz")
    mt.add_argument("--val-data", help="folder with val.npz (default: --data)")
    mt.add_argument("--out", required=True)
    mt.add_argument("--blocks", type=int, default=6); mt.add_argument("--channels", type=int, default=64)
    mt.add_argument("--policy-dim", type=int, default=32)
    mt.add_argument("--batch-size", type=int, default=1024); mt.add_argument("--lr", type=float, default=2e-3)
    mt.add_argument("--weight-decay", type=float, default=1e-4); mt.add_argument("--warmup-steps", type=int, default=200)
    mt.add_argument("--epochs", type=float, default=1.0); mt.add_argument("--max-steps", type=int, default=0)
    mt.add_argument("--eval-every", type=int, default=1000); mt.add_argument("--patience", type=int, default=0)
    mt.add_argument("--device", default="auto"); mt.add_argument("--seed", type=int, default=1)
    mt.add_argument("--init-from"); mt.add_argument("--freeze-body", action="store_true")
    mt.set_defaults(func=cmd_me_train)

    me = sub.add_parser("me-eval", help="evaluate a checkpoint on a val/test shard")
    me.add_argument("--ckpt", required=True); me.add_argument("--data", required=True)
    me.add_argument("--split", default="test"); me.add_argument("--limit", type=int)
    me.add_argument("--device", default="auto")
    me.set_defaults(func=cmd_me_eval)
    mb = sub.add_parser("me-baseline", help="how often the engine's best move equals the human move")
    mb.add_argument("--engine", required=True); mb.add_argument("--data", required=True)
    mb.add_argument("--split", default="test"); mb.add_argument("--nodes", type=int, default=5000)
    mb.add_argument("--limit", type=int, default=2000)
    mb.set_defaults(func=cmd_me_baseline)
    fx = sub.add_parser("me-fix-ep", help="apply the en-passant encoding rule to shards built with the old rule")
    fx.add_argument("--data", required=True)
    fx.set_defaults(func=cmd_me_fix_ep)
    mm = sub.add_parser("me-merge", help="combine several me-data folders into one (train shards are symlinked)")
    mm.add_argument("sources", nargs="+")
    mm.add_argument("--out", required=True)
    mm.set_defaults(func=cmd_me_merge)
    mc = sub.add_parser("me-compare", help="compare our model with Maia-3 / Maia-2 on identical positions")
    mc.add_argument("--set", choices=["user-test", "user-val", "lichess-test"], required=True)
    mc.add_argument("--profile", default=DEFAULT_PROFILE); mc.add_argument("--data", default="data/me/lichess_1100_2600")
    mc.add_argument("--limit", type=int); mc.add_argument("--seed", type=int, default=1)
    mc.add_argument("--scorer", action="append", required=True, help="ours=PATH[@label] | maia3=5m|23m[+history] | maia2=blitz|rapid")
    mc.add_argument("--maia3-repo"); mc.add_argument("--maia2-repo"); mc.add_argument("--weights-dir")
    mc.add_argument("--extra-path", help="folder with extra python packages the Maia code needs")
    mc.add_argument("--threads", type=int, default=3, help="CPU threads (kept low to leave memory / CPU for other jobs)")
    mc.add_argument("--out"); mc.add_argument("--redo", action="store_true")
    mc.set_defaults(func=cmd_me_compare)

    mf = sub.add_parser("me-maia3-ft", help="personalise a Maia-3 model on your games (needs a local Maia-3 checkout)")
    mf.add_argument("--profile", default=DEFAULT_PROFILE); mf.add_argument("--maia3-repo", required=True)
    mf.add_argument("--extra-path"); mf.add_argument("--model", default="5m")
    mf.add_argument("--checkpoint", required=True, help="the downloaded Maia-3 .pt file")
    mf.add_argument("--out", required=True)
    mf.add_argument("--epochs", type=float, default=3); mf.add_argument("--batch-size", type=int, default=256)
    mf.add_argument("--lr", type=float, default=1e-4); mf.add_argument("--scope", choices=["all", "heads"], default="all")
    mf.add_argument("--eval-every", type=int, default=250); mf.add_argument("--device", default="auto")
    mf.set_defaults(func=cmd_me_maia3_ft)
    sd = sub.add_parser("style-data", help="build the choice-level style dataset (engine candidates + move features)")
    sd.add_argument("--profile", default=DEFAULT_PROFILE); sd.add_argument("--engine", default=str(ENGINE_BIN))
    sd.add_argument("--nodes", type=int, default=20000); sd.add_argument("--multipv", type=int, default=8)
    sd.add_argument("--window", type=int, default=60, help="approved = within this many centipawns of the best move")
    sd.add_argument("--limit", type=int, default=6000, help="training positions (test gets a quarter)")
    sd.add_argument("--seed", type=int, default=1); sd.add_argument("--out", default="data/style/example")
    sd.set_defaults(func=cmd_style_data)
    cf = sub.add_parser("style-cohort-fetch", help="collect a cohort of individual players (about 50 recent games each) for style variation")
    cf.add_argument("source", help="Lichess .pgn.zst URL / file used only to pick candidate players per rating bin")
    cf.add_argument("--out", default="data/style/cohort")
    cf.add_argument("--players", type=int, default=200); cf.add_argument("--games", type=int, default=50)
    cf.add_argument("--per-game", type=int, default=10); cf.add_argument("--min-games", type=int, default=30)
    cf.add_argument("--rating-lo", type=int, default=1500); cf.add_argument("--rating-hi", type=int, default=2600)
    cf.add_argument("--oversample", type=int, default=4, help="candidates per wanted player (many are not active enough)")
    cf.add_argument("--budget-mb", type=float, default=300); cf.add_argument("--pause", type=float, default=1.0,
                    help="seconds between API requests (be polite)")
    cf.set_defaults(func=cmd_style_cohort_fetch)
    ca = sub.add_parser("style-cohort-analyze", help="run the engine over the fetched cohort (parallel, resumable)")
    ca.add_argument("--out", default="data/style/cohort"); ca.add_argument("--engine", default=str(ENGINE_BIN))
    ca.add_argument("--workers", type=int, default=4); ca.add_argument("--nodes", type=int, default=20000)
    ca.add_argument("--multipv", type=int, default=8); ca.add_argument("--window", type=int, default=60)
    ca.set_defaults(func=cmd_style_cohort_analyze)
    cr = sub.add_parser("style-cohort-report", help="split-half reliability and personal-vs-population test on the cohort")
    cr.add_argument("--out", default="data/style/cohort"); cr.add_argument("--min-usable", type=int, default=60)
    cr.set_defaults(func=cmd_style_cohort_report)
    sp = sub.add_parser("style-pop-data", help="sample a rating-matched population from a Lichess dump and build its candidate dataset")
    sp.add_argument("source", help="Lichess .pgn.zst URL / file")
    sp.add_argument("--rating-lo", type=int, default=1500); sp.add_argument("--rating-hi", type=int, default=2600)
    sp.add_argument("--per-bin", type=int, default=1200, help="decisions per rating bin (balanced across ratings)")
    sp.add_argument("--bin-width", type=int, default=100); sp.add_argument("--per-game", type=int, default=4)
    sp.add_argument("--time-classes", nargs="+", default=["blitz", "rapid"])
    sp.add_argument("--budget-mb", type=float, default=1000, help="stop reading the compressed stream after this many MB (nothing is stored)")
    sp.add_argument("--engine", default=str(ENGINE_BIN)); sp.add_argument("--nodes", type=int, default=20000)
    sp.add_argument("--multipv", type=int, default=8); sp.add_argument("--window", type=int, default=60)
    sp.add_argument("--seed", type=int, default=1); sp.add_argument("--out", default="data/style/pop_1500_2600")
    sp.set_defaults(func=cmd_style_pop_data)
    ab = sub.add_parser("style-anchors-build", help="sample decisions of famous players from game files you supply")
    ab.add_argument("--files", required=True, help="folder with <name>.pgn / .zip files (e.g. tal.pgn)")
    ab.add_argument("--config", default="configs/anchors.yaml"); ab.add_argument("--out", default="data/style/anchors")
    ab.add_argument("--max-games", type=int, default=100); ab.add_argument("--per-game", type=int, default=10)
    ab.add_argument("--all", action="store_true", help="include unselected anchors")
    ab.set_defaults(func=cmd_style_anchors_build)
    af = sub.add_parser("style-anchors-fetch", help="download each anchor's archive, sample decisions from their peak years, delete the archive")
    af.add_argument("--config", default="configs/anchors.yaml"); af.add_argument("--out", default="data/style/anchors")
    af.add_argument("--tmp", default="data/anchors_raw", help="temporary download folder (archives are deleted after sampling)")
    af.add_argument("--files", help="folder with your own <key>.pgn / .zip files; used instead of a download")
    af.add_argument("--only", nargs="+", help="only these anchor keys"); af.add_argument("--keep-raw", action="store_true")
    af.add_argument("--max-games", type=int, default=100); af.add_argument("--per-game", type=int, default=10)
    af.add_argument("--redo", action="store_true")
    af.add_argument("--log", default="data/style/logs/anchors_fetch.log", help="log file (also printed to the terminal)")
    af.set_defaults(func=cmd_style_anchors_fetch)
    av = sub.add_parser("style-anchors-verify", help="check every anchor's aliases against the PGN Mentor page and archives")
    av.add_argument("--config", default="configs/anchors.yaml"); av.add_argument("--tmp", default="data/anchors_raw")
    av.add_argument("--only", nargs="+"); av.add_argument("--log", default="data/style/logs/anchors_verify.log")
    av.set_defaults(func=cmd_style_anchors_verify)
    ar = sub.add_parser("style-anchors-report", help="can the features tell the anchors apart? which anchor is closest to a player?")
    ar.add_argument("--out", default="data/style/anchors"); ar.add_argument("--config", default="configs/anchors.yaml")
    ar.add_argument("--player", help="dataset folder (train.npz / test.npz) of the player to rank against the anchors")
    ar.add_argument("--chunk", type=int, default=30)
    ar.set_defaults(func=cmd_style_anchors_report)
    stg = sub.add_parser("strength", help="measure an engine's strength by an adaptive ladder against Stockfish UCI_Elo")
    stg.add_argument("--engine", default=str(ENGINE_BIN)); stg.add_argument("--opt", action="append", default=[])
    stg.add_argument("--start", type=int, help="first guess of the engine's Elo"); stg.add_argument("--out", default="data/calibration/engine_strength.json")
    cal = sub.add_parser("calibrate", help="measure MeChess at several dial settings against Stockfish and write a calibration file")
    cal.add_argument("--engine", default=str(ENGINE_BIN)); cal.add_argument("--book"); cal.add_argument("--prior", default="uniform")
    cal.add_argument("--table", help="dial table file to calibrate (default: the built-in table)")
    cal.add_argument("--maia3-repo"); cal.add_argument("--maia3-size", default="5m"); cal.add_argument("--extra-path")
    cal.add_argument("--dial", type=int, nargs="+", default=[1200, 1500, 1800, 2100, 2400])
    cal.add_argument("--out", default="data/calibration/dial.json"); cal.add_argument("--redo", action="store_true")
    cal.add_argument("--offset", type=float, default=0.0, help="shift measured Elo to another scale (only after validating it)")
    for lp in (stg, cal):
        lp.add_argument("--opponent", default="stockfish", help="UCI engine with UCI_Elo support used as the ladder")
        lp.add_argument("--openings", help="file of opening FENs (default: random 6-ply openings)")
        lp.add_argument("--random-openings", type=int, default=200); lp.add_argument("--seed", type=int, default=1)
        lp.add_argument("--movetime", type=int, default=100, help="milliseconds per move for both sides")
        lp.add_argument("--pairs", type=int, default=5, help="opening pairs (2 games each) per ladder round")
        lp.add_argument("--se", type=float, default=35.0, help="stop when the standard error is this small (95%% CI = 1.96 x)")
        lp.add_argument("--min-games", type=int, default=40); lp.add_argument("--max-games", type=int, default=400)
        lp.add_argument("--concurrency", type=int, default=1)
    stg.set_defaults(func=cmd_strength)
    cal.set_defaults(func=cmd_calibrate)
    ss = sub.add_parser("style-summary", help="one player against the cohort, axes, anchors (poles) and population: what is reliably personal")
    ss.add_argument("--cohort", default="data/style/cohort"); ss.add_argument("--anchors", default="data/style/anchors")
    ss.add_argument("--config", default="configs/anchors.yaml"); ss.add_argument("--player", required=True, help="dataset folder of the player (train.npz, test.npz)")
    ss.add_argument("--population", help="population folder from style-pop-data (adds the population comparison)")
    ss.add_argument("--label", default="you"); ss.add_argument("--boot", type=int, default=20); ss.add_argument("--min-usable", type=int, default=60)
    ss.add_argument("--out", default="data/style/summary.md")
    ss.set_defaults(func=cmd_style_summary)
    sx = sub.add_parser("style-rates", help="reliability across players of plain habit rates (no engine, no move-quality filter)")
    sx.add_argument("--cohort", default="data/style/cohort"); sx.add_argument("--min-decisions", type=int, default=100)
    sx.add_argument("--anchors", help="anchors folder: can habit rates tell the anchors apart?")
    sx.add_argument("--config", default="configs/anchors.yaml"); sx.add_argument("--player", help="dataset folder of a player: their habit profile")
    sx.set_defaults(func=cmd_style_rates)
    lk = sub.add_parser("calibrate-link", help="measure dial settings below/above Stockfish's UCI_Elo range by playing them against the next dial setting")
    lk.add_argument("--calibration", default="data/calibration/dial.json"); lk.add_argument("--engine", default=str(ENGINE_BIN))
    lk.add_argument("--book"); lk.add_argument("--prior", default="uniform")
    lk.add_argument("--table", help="dial table file to calibrate (default: the built-in table)")
    lk.add_argument("--maia3-repo"); lk.add_argument("--maia3-size", default="5m"); lk.add_argument("--extra-path")
    lk.add_argument("--link-pairs", type=int, default=40, help="opening pairs (2 games each) per link"); lk.add_argument("--redo", action="store_true")
    for lp in (lk,):
        lp.add_argument("--openings"); lp.add_argument("--random-openings", type=int, default=200); lp.add_argument("--seed", type=int, default=1)
        lp.add_argument("--movetime", type=int, default=100); lp.add_argument("--pairs", type=int, default=5)
        lp.add_argument("--se", type=float, default=35.0); lp.add_argument("--min-games", type=int, default=40)
        lp.add_argument("--max-games", type=int, default=400); lp.add_argument("--concurrency", type=int, default=1)
    lk.set_defaults(func=cmd_calibrate_link)
    dd = sub.add_parser("dial-design", help="design the weak end of the dial: a table of settings plus a calibration skeleton to link")
    dd.add_argument("--from-calibration", default="data/calibration/dial.json", help="calibration with the absolute measurements to anchor on")
    dd.add_argument("--labels", type=int, nargs="+", default=list(range(400, 1601, 200)))
    dd.add_argument("--weak-label", type=int, default=400, help="label of the weakest row of the path (rows for other labels follow from it)")
    dd.add_argument("--out-table", default="data/calibration/weak_table.json"); dd.add_argument("--out-calibration", default="data/calibration/weak_cal.json")
    dd.set_defaults(func=cmd_dial_design)
    ctl = sub.add_parser("control", help="pause, resume or stop long jobs (they check a control folder between units of work)")
    ctl.add_argument("action", choices=["pause", "resume", "stop", "clear", "status"])
    ctl.add_argument("job", nargs="?", help="job name (e.g. fetch, features, train); default: all jobs")
    ctl.add_argument("--dir", default="data/control")
    ctl.set_defaults(func=cmd_control)
    gf = sub.add_parser("style-games-fetch", help="refetch the cohort's games with clocks and openings; compute game-level style features (resumable, pausable)")
    gf.add_argument("--cohort", default="data/style/cohort", help="the v1 cohort folder (players.json, candidates.json, salt)")
    gf.add_argument("--out", default="data/style/cohort2"); gf.add_argument("--games", type=int, default=50)
    gf.add_argument("--min-games", type=int, default=30); gf.add_argument("--pause", type=float, default=1.0, help="seconds between requests")
    gf.add_argument("--limit", type=int, help="only this many players (for a trial)"); gf.add_argument("--control-dir", default="data/control")
    gf.add_argument("--log", default="data/style/logs/games_fetch.log")
    gf.set_defaults(func=cmd_style_games_fetch)
    bk = sub.add_parser("books-fetch", help="download the public-domain chess books in books/sources.json and extract game lines and concept counts")
    bk.add_argument("--out", default="data/books"); bk.add_argument("--only", nargs="*", help="book ids"); bk.add_argument("--pause", type=float, default=3.0)
    bk.add_argument("--log", default="data/books/books.log")
    bk.set_defaults(func=cmd_books_fetch)
    eb = sub.add_parser("explorer-build", help="build an opening explorer (SQLite) and per-band theory books from the Lichess database (streamed, CC0; exact counts)")
    eb.add_argument("--source", default="https://database.lichess.org/standard/lichess_db_standard_rated_2026-06.pgn.zst", help="a .pgn.zst URL or path (or plain .pgn)")
    eb.add_argument("--out", default="data/explorer"); eb.add_argument("--bands", nargs="+", type=int, default=[0, 800, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 4000],
                                                                      help="rating band edges (default: every range, 0 to 4000)")
    eb.add_argument("--max-ply", type=int, default=24)
    eb.add_argument("--max-per-band", type=int, default=1_000_000, help="a band stops collecting at this many games; rare bands collect over the whole scan (exact counts, no sampling)")
    eb.add_argument("--max-scan", type=int, default=100_000_000, help="games to scan at most (a month is about 100 million)"); eb.add_argument("--holdout", type=int, default=1000, help="games per band kept aside for the coverage test (counted afterwards)")
    eb.add_argument("--db-min-games", type=int, default=5); eb.add_argument("--db-min-frac", type=float, default=1e-5, help="database keeps moves with at least max(db-min-games, this fraction of the band's games)")
    eb.add_argument("--book-min-games", type=int, default=20); eb.add_argument("--book-min-frac", type=float, default=5e-5); eb.add_argument("--book-min-share", type=float, default=0.03)
    eb.add_argument("--max-entries", type=int, default=60_000_000); eb.add_argument("--max-minutes", type=float, help="stop counting after this long and still write the outputs")
    eb.add_argument("--max-memory-gb", type=float, default=20.0, help="prune the rarest entries when the process grows past this (recorded in the report)")
    eb.add_argument("--checkpoint-every", type=int, default=1_000_000, help="games between checkpoints"); eb.add_argument("--checkpoint-minutes", type=float, default=15, help="and at least this often")
    eb.add_argument("--fresh", action="store_true", help="ignore an earlier checkpoint"); eb.add_argument("--resume-glob", help="search this glob (e.g. an earlier run mounted as an input) for a checkpoint when the output folder has none")
    eb.add_argument("--drop-state-when-finished", action="store_true", help="delete the checkpoint after a complete run (a stopped run keeps it)")
    eb.add_argument("--min-base", type=int, default=30, help="skip games with a base time under this many seconds (ultra-bullet); bullet and above are all counted")
    eb.add_argument("--eval-margin", type=float, help="also drop book moves whose average engine evaluation is worse than the best sibling's by more than this many centipawns")
    eb.add_argument("--openings-dir", default="data/opening_names", help="Lichess opening names, stored in the explorer database (from `theory-book --download`)")
    eb.add_argument("--job", default="explorer"); eb.add_argument("--control-dir", default="data/control")
    eb.add_argument("--check", action="store_true", help="read a few hundred games and exit: tests the URL, decompression and parsing in seconds")
    eb.add_argument("--log", default="data/explorer/explorer.log")

    eb.set_defaults(func=cmd_explorer_build)

    rg = sub.add_parser("explorer-range-scan", help="opening explorer via a partitioned byte-range scan of the dump (parallel, exact, resumable window by "
                        "window - no 17-minute reconnect-from-byte-0 problem); see chessme/book/rangescan.py")
    rg.add_argument("--source", default="https://database.lichess.org/standard/lichess_db_standard_rated_2026-06.pgn.zst",
                    help="a .pgn.zst URL (must support HTTP range requests) or the path of a downloaded .pgn.zst")
    rg.add_argument("--out", default="data/explorer_range", help="not data/explorer: a finished explorer-build run lives there and would be overwritten")
    rg.add_argument("--bands", nargs="+", type=int, default=[0, 800, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 4000])
    rg.add_argument("--max-ply", type=int, default=24); rg.add_argument("--min-base", type=int, default=30)
    rg.add_argument("--parts", type=int, default=700, help="byte windows to cut the dump into (about 40 MB each for the real dump); a rerun must use the same number")
    rg.add_argument("--workers", type=int, default=4, help="windows scanned at the same time")
    rg.add_argument("--max-entries", type=int, default=5_000_000, help="a window whose tables pass this many entries stops the scan (never pruned): use more --parts")
    rg.add_argument("--windows-dir", help="where the scanned windows are kept (about 45 MB each, ~31 GB for the real dump); default <out>/windows_<parts>. "
                    "On Kaggle use scratch space (/kaggle/temp): /kaggle/working is limited to 20 GB")
    rg.add_argument("--slices", type=int, default=64, help="each window is saved in this many slices and the merge handles one slice at a time (peak memory)")
    rg.add_argument("--holdout", type=int, default=1000, help="games per band kept aside for the coverage test (spread over the windows)")
    rg.add_argument("--db-min-games", type=int, default=5); rg.add_argument("--db-min-frac", type=float, default=1e-5)
    rg.add_argument("--book-min-games", type=int, default=20); rg.add_argument("--book-min-frac", type=float, default=5e-5); rg.add_argument("--book-min-share", type=float, default=0.03)
    rg.add_argument("--eval-margin", type=float)
    rg.add_argument("--openings-dir", default="data/opening_names")
    rg.add_argument("--job", default="explorer-range"); rg.add_argument("--control-dir", default="data/control")
    rg.add_argument("--log", default="data/explorer_range/explorer_range.log")
    rg.set_defaults(func=cmd_explorer_range_scan)
    er = sub.add_parser("explorer-rebuild", help="rebuild explorer.db, the books and the report from a saved checkpoint with other thresholds (no streaming)")
    er.add_argument("state", help="state.pkl.gz written by explorer-build"); er.add_argument("--out", default="data/explorer")
    er.add_argument("--db-min-games", type=int, default=5); er.add_argument("--db-min-frac", type=float, default=1e-5)
    er.add_argument("--book-min-games", type=int, default=20); er.add_argument("--book-min-frac", type=float, default=5e-5); er.add_argument("--book-min-share", type=float, default=0.03)
    er.add_argument("--eval-margin", type=float, help="drop book moves whose average engine evaluation is worse than the best sibling's by more than this (centipawns)")
    er.add_argument("--max-ply", type=int, help="a shallower book than the counts allow"); er.add_argument("--openings-dir", default="data/opening_names")
    er.add_argument("--log", default="data/explorer/explorer.log")
    er.set_defaults(func=cmd_explorer_rebuild)
    eq = sub.add_parser("explorer-query", help="look a position up in the explorer database")
    eq.add_argument("db"); eq.add_argument("--fen"); eq.add_argument("--rating", type=int, default=1500); eq.add_argument("--top", type=int, default=10)
    eq.set_defaults(func=cmd_explorer_query)
    tb = sub.add_parser("theory-book", help="build an opening book of known theory (both colours), weighted by what players at a rating band play")
    tb.add_argument("--out", required=True); tb.add_argument("--openings-dir", default="data/opening_names"); tb.add_argument("--download", action="store_true", help="fetch the CC0 opening list if missing")
    tb.add_argument("--games", help="cohort folder with games/ (style-games-fetch output) for popularity"); tb.add_argument("--pgn", nargs="*", help="extra PGN files for popularity")
    tb.add_argument("--band", nargs=2, type=int, metavar=("LO", "HI"), help="only games of players rated in this range")
    tb.add_argument("--max-ply", type=int, default=20); tb.add_argument("--min-games", type=int, default=2); tb.add_argument("--min-share", type=float, default=0.03)
    tb.add_argument("--extend-min-games", type=int, default=15, help="also follow popular moves beyond the opening names (0: named lines only)")
    tb.add_argument("--extend-min-share", type=float, default=0.08)
    tb.add_argument("--log", default="data/book/theory.log")
    tb.set_defaults(func=cmd_theory_book)
    bl = sub.add_parser("books-learn", help="everything from books and annotated games in one command: books, concept-line pairs, annotated archive, report (resumable)")
    bl.add_argument("--out", default="data/books_learn"); bl.add_argument("--steps", nargs="+", default=["books", "pairs", "annotated", "prose", "report"],
                                                                        choices=["books", "pairs", "annotated", "prose", "report"])
    bl.add_argument("--limit-per-source", type=int, help="at most this many games per annotated source (a trial)")
    bl.add_argument("--studies-dir", help="folder with extra PGN files, e.g. from books-studies"); bl.add_argument("--archive", help="an already downloaded annotated_pgn_free.tar.gz")
    bl.add_argument("--max-books", type=int, help="only the first N books (a trial)")
    bl.add_argument("--no-chessgpt", action="store_true", help="skip the large ChessGPT annotated-PGN shards (175 MB)")
    bl.add_argument("--no-csv", action="store_true", help="skip the extra CC0 studies dataset"); bl.add_argument("--no-openings", action="store_true", help="skip opening names")
    bl.add_argument("--slim", action="store_true", help="after a complete run, delete the raw downloads and keep only the results")
    bl.add_argument("--redo", action="store_true"); bl.add_argument("--control-dir", default="data/control"); bl.add_argument("--log", default="data/books_learn/learn.log")
    bl.set_defaults(func=cmd_books_learn)
    nt = sub.add_parser("books-nlp-train", help="train the chess-text language model (concepts, move judgement, evaluation) on the books-learn output")
    nt.add_argument("--data", default="data/books_learn"); nt.add_argument("--out"); nt.add_argument("--backend", choices=["bow", "transformer"], default="bow")
    nt.add_argument("--model", default="distilroberta-base", help="Hugging Face encoder for --backend transformer")
    nt.add_argument("--epochs", type=int, default=3); nt.add_argument("--batch", type=int, default=64); nt.add_argument("--lr", type=float)
    nt.add_argument("--max-per-source", type=int, help="cap examples per source (a trial)")
    nt.add_argument("--dry-run", action="store_true", help="a few seconds on a few hundred examples: checks the whole path, writes nothing")
    nt.add_argument("--deadline-minutes", type=float, help="stop cleanly with a checkpoint after this many minutes (Kaggle: below 12 h)")
    nt.add_argument("--data-dir", help="the collection notebook's output folder (searched recursively), e.g. /kaggle/input/notebooks/<user>/<notebook>")
    nt.add_argument("--allow-missing-sources", action="store_true", help="train even if some expected source has no examples")
    nt.add_argument("--input-root", help="Kaggle: link the data and restore an earlier checkpoint from the inputs under this folder (e.g. /kaggle/input)")
    nt.add_argument("--slim", action="store_true", help="after training, remove the linked data and the dry-run folder")
    nt.add_argument("--patience", type=int, default=4, help="stop after this many validations without a new best model (0: never)")
    nt.add_argument("--dropout", type=float, default=0.2, help="dropout before the heads")
    nt.add_argument("--lab-per-batch", type=int, default=4, help="glyph-labelled examples in every batch (fewer: less memorising of the rare labelled examples)")
    nt.add_argument("--val-every", type=int, default=1000, help="log a validation check (concept AP, judgement / evaluation accuracy vs the majority guess) every N steps")
    nt.add_argument("--ckpt-every", type=int, default=500); nt.add_argument("--job", default="nlp"); nt.add_argument("--control-dir", default="data/control")
    nt.add_argument("--log", default="data/books_learn/nlp.log")
    nt.set_defaults(func=cmd_books_nlp_train)
    nr = sub.add_parser("books-nlp-report", help="print the held-out metrics of a trained chess-text model")
    nr.add_argument("model_dir"); nr.set_defaults(func=cmd_books_nlp_report)
    npd = sub.add_parser("books-nlp-predict", help="read comments with a trained chess-text model")
    npd.add_argument("model_dir"); npd.add_argument("texts", nargs="+")
    npd.add_argument("--variant", choices=["composite", "concepts"], default="composite", help="the model selected on all three heads, or the best on concepts alone")
    npd.set_defaults(func=cmd_books_nlp_predict)
    nl = sub.add_parser("books-nlp-label", help="label every annotated move's comment with the trained text model (concepts, verdict, evaluation): training data for a position model")
    nl.add_argument("--data", help="annotated_moves.jsonl.gz, or the books-learn folder that holds annotated/annotated_moves.jsonl.gz")
    nl.add_argument("--model-dir", help="a trained model folder (config.json, model.pt); on Kaggle found under --input-root")
    nl.add_argument("--variant", choices=["composite", "concepts"], default="composite", help="the model kept on all three heads, or the one best on concepts alone (labels are mostly concepts)")
    nl.add_argument("--out", default="data/books_learn/labelled/labelled.jsonl.gz")
    nl.add_argument("--batch", type=int, default=128); nl.add_argument("--chunk", type=int, default=2048, help="records per saved step (a resume restarts at the last one)")
    nl.add_argument("--limit", type=int, help="label only the first N records (a trial)")
    nl.add_argument("--sample", type=int, default=60, help="records with model-only concepts to list in the report for checking by eye")
    nl.add_argument("--deadline-minutes", type=float, help="stop cleanly after this many minutes (exit code 3); run the same command to continue")
    nl.add_argument("--fresh", action="store_true", help="ignore a partial earlier run")
    nl.add_argument("--data-dir", help="Kaggle: the collection notebook's output folder (searched recursively)")
    nl.add_argument("--input-root", help="Kaggle: find the data and the model, and restore an interrupted run, under this folder (e.g. /kaggle/input)")
    nl.add_argument("--log", default="data/books_learn/labelled/label.log")
    nl.set_defaults(func=cmd_books_nlp_label)
    pf = sub.add_parser("books-preflight", help="check dependencies, disk, network and GPU before a long run (exit code 1 on failure)")
    pf.add_argument("--out", default="data/books_learn"); pf.add_argument("--need-gpu", action="store_true"); pf.add_argument("--backend", choices=["bow", "transformer"], default="bow")
    pf.add_argument("--model", default="distilroberta-base"); pf.add_argument("--min-free-gb", type=float, default=3.0); pf.add_argument("--no-network", action="store_true")
    pf.set_defaults(func=cmd_books_preflight)
    bs = sub.add_parser("books-studies", help="export public Lichess studies of users or by study id (one request at a time)")
    bs.add_argument("--out", default="data/books_learn/studies"); bs.add_argument("--users", nargs="*"); bs.add_argument("--users-file")
    bs.add_argument("--study-ids", nargs="*"); bs.add_argument("--pause", type=float, default=2.0); bs.add_argument("--log", default="data/books_learn/studies.log")
    bs.set_defaults(func=cmd_books_studies)
    bp = sub.add_parser("books-pdf", help="read PDFs you own (text layer) with the book reader")
    bp.add_argument("inp"); bp.add_argument("--out", default="data/books_learn/private"); bp.add_argument("--log", default="data/books_learn/pdf.log")
    bp.set_defaults(func=cmd_books_pdf)
    bt = sub.add_parser("books-topics", help="cluster book paragraphs into topics (needs sentence-transformers)")
    bt.add_argument("texts", help="folder with .txt books"); bt.add_argument("--k", type=int, default=25)
    bt.set_defaults(func=cmd_books_topics)
    sq = sub.add_parser("style-games-quality", help="engine move-quality features (accuracy, class rates, conversion...) for a sample of the cohort (resumable, pausable)")
    sq.add_argument("--data", default="data/style/cohort2"); sq.add_argument("--engine", default="stockfish")
    sq.add_argument("--nodes", type=int, default=25000); sq.add_argument("--games", type=int, default=10); sq.add_argument("--players", type=int, default=400)
    sq.add_argument("--seed", type=int, default=0); sq.add_argument("--workers", type=int, default=3)
    sq.add_argument("--control-dir", default="data/control"); sq.add_argument("--log", default="data/style/logs/quality.log")
    sq.set_defaults(func=cmd_style_games_quality)
    qr = sub.add_parser("style-quality-report", help="reliability and gate of the move-quality features")
    qr.add_argument("--data", default="data/style/cohort2"); qr.add_argument("--min-players", type=int, default=40)
    qr.set_defaults(func=cmd_style_quality_report)
    et = sub.add_parser("style-embed-train", help="train the contrastive player embedding on the game-level features (resumable, pausable)")
    et.add_argument("--data", default="data/style/cohort2"); et.add_argument("--out", default="data/style/embed")
    et.add_argument("--min-games", type=int, default=30); et.add_argument("--min-players", type=int, default=60)
    et.add_argument("--steps", type=int, default=2000); et.add_argument("--batch", type=int, default=64); et.add_argument("--bag", type=int, default=20)
    et.add_argument("--dim", type=int, default=32); et.add_argument("--hidden", type=int, default=128); et.add_argument("--lr", type=float, default=2e-3)
    et.add_argument("--seed", type=int, default=0); et.add_argument("--ckpt-every", type=int, default=100); et.add_argument("--eval-every", type=int, default=500)
    et.add_argument("--job", default="embed"); et.add_argument("--control-dir", default="data/control"); et.add_argument("--log", default="data/style/logs/embed.log")
    et.set_defaults(func=cmd_style_embed_train)
    an = sub.add_parser("analyse", help="analyse the games of a PGN file with Stockfish: move classes, accuracy, report (resumable, pausable)")
    an.add_argument("pgn"); an.add_argument("--out", default="data/analysis"); an.add_argument("--player", help="report on this player's side (PGN name)")
    an.add_argument("--engine", default="stockfish"); an.add_argument("--nodes", type=int, default=200000, help="nodes per position (fixed, machine independent)")
    an.add_argument("--openings-dir", default="data/opening_names", help="Lichess opening names (from `theory-book --download`): moves in named theory are classed Book")
    an.add_argument("--workers", type=int, default=1, help="games analysed at the same time (one Stockfish each)")
    an.add_argument("--limit", type=int); an.add_argument("--job", default="analyse"); an.add_argument("--control-dir", default="data/control")
    an.add_argument("--log", default="data/analysis/analyse.log")
    an.set_defaults(func=cmd_analyse)
    rs = sub.add_parser("report-select", help="choose the newest usable games of your profile for a personal report and write them as a PGN (with your side)")
    rs.add_argument("--profile", default=DEFAULT_PROFILE); rs.add_argument("--platform", default="lichess"); rs.add_argument("--n", type=int, default=20)
    rs.add_argument("--per-class", type=int, help="this many newest games of each time class instead of --n overall")
    rs.add_argument("--time-classes", nargs="+"); rs.add_argument("--since", help="only games from this ISO date on"); rs.add_argument("--out", default="data/analysis/games.pgn")
    rs.set_defaults(func=cmd_report_select)
    rl = sub.add_parser("report-leaks", help="personal report step 2: rank where expected points are lost (opening/phase) and test the ranking's split-half stability")
    rl.add_argument("--dir", default="data/analysis", help="an `analyse` output directory (reads dir/games/*.json)")
    rl.add_argument("--by", choices=["opening", "phase"], default="opening")
    rl.add_argument("--min-n", type=int, default=8, help="a bucket needs at least this many of your moves to be ranked")
    rl.add_argument("--out", help="also write the report text here")
    rl.add_argument("--english", action="store_true", help="also print a plain-English paragraph (templated, not a model - no claim beyond the numbers)")
    rl.set_defaults(func=cmd_report_leaks)
    gr = sub.add_parser("style-games-report", help="reliability, quality gate, identification and factors of the game-level features")
    gr.add_argument("--data", default="data/style/cohort2"); gr.add_argument("--min-games", type=int, default=30)
    gr.add_argument("--min-players", type=int, default=40); gr.add_argument("--seed", type=int, default=0)
    gr.add_argument("--out", default="data/style/games_report.md")
    gr.set_defaults(func=cmd_style_games_report)
    st = sub.add_parser("style-status", help="one-screen status of the long style jobs (progress, ETA, latest log lines)")
    st.add_argument("--cohort", default="data/style/cohort"); st.add_argument("--anchors", default="data/style/anchors")
    st.add_argument("--target", type=int, default=1000, help="players wanted in the cohort")
    st.add_argument("--logs", default="data/style/logs"); st.add_argument("--watch", type=float, help="refresh every N seconds")
    st.set_defaults(func=cmd_style_status)
    sj = sub.add_parser("style-judge-compare", help="how much does the judge engine change the style data? (two dataset folders)")
    sj.add_argument("a"); sj.add_argument("b")
    sj.set_defaults(func=cmd_style_judge_compare)
    sm = sub.add_parser("style-model-fit", help="fit your style model on a style-data folder and save it for the bot (mechess --prior style=FILE)")
    sm.add_argument("--data", required=True, help="folder from style-data (train.npz, test.npz)")
    sm.add_argument("--out", required=True)
    sm.add_argument("--l2", type=float, default=1.0)
    sm.set_defaults(func=cmd_style_model_fit)
    mc = sub.add_parser("mechess-clock-fit", help="learn how long you think (per time control, stage and move type) for the bot's waiting; prints a held-out check")
    mc.add_argument("--profile", default=DEFAULT_PROFILE); mc.add_argument("--out", default="data/style/clock_model.json")
    mc.add_argument("--every", type=int, default=7, help="every Nth game is kept out of the fit for the check")
    mc.set_defaults(func=cmd_mechess_clock_fit)
    ma = sub.add_parser("mechess-agreement", help="held-out check: how much probability do the books and the style prior give the moves you actually played?")
    ma.add_argument("--profile", default=DEFAULT_PROFILE); ma.add_argument("--style-data", required=True, help="a style-data folder (train.npz, test.npz)")
    ma.add_argument("--theory", default="data/explorer", help="folder of theory books (theory_LO_HI.bin)"); ma.add_argument("--calibration")
    ma.add_argument("--engine", default=str(ENGINE_BIN)); ma.add_argument("--holdout", type=float, default=0.15, help="the newest share of games kept out of the personal book")
    ma.add_argument("--plies", type=int, default=20); ma.add_argument("--max-positions", type=int, default=800)
    ma.add_argument("--sweep", nargs="*", metavar="SCALE,LINES", help="also try wider candidate windows, e.g. 1.5,1 2,2 3,4 (window scale, extra MultiPV lines)")
    ma.add_argument("--out", default="data/style/agreement.md"); ma.set_defaults(func=cmd_mechess_agreement)
    ag = sub.add_parser("style-anchors-games", help="game-level features (openings, game shape) of the anchors' peak-year games; resumable, one anchor at a time, archives deleted")
    ag.add_argument("--config", default="configs/anchors.yaml"); ag.add_argument("--out", default="data/style/anchors_games")
    ag.add_argument("--tmp", default="data/anchors_raw"); ag.add_argument("--files", help="folder with your own <key>.pgn / .zip files, used instead of a download")
    ag.add_argument("--only", nargs="+"); ag.add_argument("--max-games", type=int, default=100); ag.add_argument("--pause", type=float, default=1.0)
    ag.add_argument("--keep-raw", action="store_true"); ag.add_argument("--log", default="data/style/logs/anchors_games.log")
    ag.set_defaults(func=cmd_style_anchors_games)
    agr = sub.add_parser("style-anchors-games-report", help="can the game-level features and the trained embedding tell the anchors apart? (and do they see era, not style?)")
    agr.add_argument("--data", default="data/style/anchors_games"); agr.add_argument("--embed", default="data/style/embed")
    agr.add_argument("--cohort", default="data/style/cohort2", help="the online cohort's game-level folder (adds the format comparison)")
    agr.add_argument("--out", default="data/style/anchors_games_report.md")
    agr.set_defaults(func=cmd_style_anchors_games_report)
    sr = sub.add_parser("style-report", help="fit the style model on the training positions, evaluate on the test ones")
    sr.add_argument("--data", default="data/style/example"); sr.add_argument("--l2", type=float, default=1.0)
    sr.add_argument("--baseline", help="folder from style-pop-data: report the player's weights relative to it")
    sr.add_argument("--boot", type=int, default=30, help="bootstrap resamples for the standard errors")
    sr.add_argument("--label", default="you"); sr.add_argument("--out", default="data/style/style_report.md")
    sr.set_defaults(func=cmd_style_report)
    ht = sub.add_parser("humanlike-testset", help="build a fixed test set of positions (with clocks, history, ratings) from byte windows of a Lichess dump")
    ht.add_argument("--source", default="https://database.lichess.org/standard/lichess_db_standard_rated_2026-06.pgn.zst")
    ht.add_argument("--parts", type=int, default=700); ht.add_argument("--windows", required=True, help="comma-separated window numbers (0 to parts-1)")
    ht.add_argument("--per-game", type=int, default=4); ht.add_argument("--seed", type=int, default=2026)
    ht.add_argument("--time-class", default="blitz"); ht.add_argument("--allow-bots", action="store_true")
    ht.add_argument("--workers", type=int, default=1, help="windows parsed at the same time (about 100 games/s per worker)")
    ht.add_argument("--cap-per-bin", type=int, help="thin each 100-point rating bin to at most this many positions (a natural month is thin at the extremes)")
    ht.add_argument("--shard-dir"); ht.add_argument("--keep-shards", action="store_true")
    ht.add_argument("--out", required=True)
    ht.set_defaults(func=cmd_humanlike_testset)
    ha = sub.add_parser("humanlike-allie", help="turn the published Allie test set (jsonl) into a test set of ours; by default only the positions the papers evaluate")
    ha.add_argument("--file", required=True, help="2022-test-annotated.jsonl from the Hugging Face dataset yimingzhang/allie-data")
    ha.add_argument("--all", action="store_true", help="keep every position (the filters then only set the `late` flag)"); ha.add_argument("--out", required=True)
    ha.set_defaults(func=cmd_humanlike_allie)
    hs = sub.add_parser("humanlike-score", help="score a move model (Maia-3, Maia-2, ours) over a test set; one record per position")
    hs.add_argument("--testset", required=True); hs.add_argument("--scorer", required=True, help="maia3=5m|23m|79m[+history] | maia2=blitz|rapid | ours=CHECKPOINT")
    hs.add_argument("--maia3-repo"); hs.add_argument("--maia2-repo"); hs.add_argument("--weights-dir"); hs.add_argument("--extra-path")
    hs.add_argument("--limit", type=int, help="score a random subset (seeded); every model to be compared must use the same --limit and --seed")
    hs.add_argument("--seed", type=int, default=1); hs.add_argument("--batch", type=int, default=64); hs.add_argument("--out", required=True)
    hs.add_argument("--device", default="cpu", help="cpu or cuda"); hs.add_argument("--workers", type=int, default=1, help="processes (each loads the model); the cost is mostly Python-side board encoding")
    hs.add_argument("--chunk", type=int, default=4000, help="positions handed to a worker at a time")
    hs.set_defaults(func=cmd_humanlike_score)
    hc = sub.add_parser("humanlike-ceiling", help="how much room there is above a model on positions many players have faced: the explorer's counts as an oracle (leave-one-out)")
    hc.add_argument("--testset", required=True); hc.add_argument("--scores", nargs="+", required=True)
    hc.add_argument("--explorer", default="data/explorer/explorer.db"); hc.add_argument("--boot", type=int, default=500); hc.add_argument("--out", default="data/humanlike/ceiling.md")
    hc.set_defaults(func=cmd_humanlike_ceiling)
    hj = sub.add_parser("humanlike-judge", help="Stockfish losses of the human's move and the model's most probable moves on a sample of a scored test set, per clock regime")
    hj.add_argument("--testset", required=True); hj.add_argument("--scores", required=True); hj.add_argument("--out", default="data/humanlike/judged.npz")
    hj.add_argument("--per-regime", type=int, default=4000); hj.add_argument("--min-ply", type=int, default=10); hj.add_argument("--seed", type=int, default=0)
    hj.add_argument("--workers", type=int, default=3); hj.add_argument("--engine"); hj.add_argument("--nodes-child", type=int, default=10000)
    hj.add_argument("--nodes-root", type=int, default=20000); hj.add_argument("--candidates", type=int, default=8, choices=range(1, 17), metavar="1-16", help="how many of the model's most probable moves are judged next to the human's")
    hj.add_argument("--split", choices=("all", "train", "val", "test", "trainval"), default="all", help="judge only positions of games in this part of the adapter's game split")
    hj.add_argument("--split-seed", type=int, default=0)
    hj.set_defaults(func=cmd_humanlike_judge)
    he = sub.add_parser("humanlike-errors", help="error profile (A3): the errors a model would make when sampling its moves against the errors humans made, with positive controls and a noise floor")
    he.add_argument("--testset", required=True); he.add_argument("--scores", required=True); he.add_argument("--judged", required=True)
    he.add_argument("--boot", type=int, default=500); he.add_argument("--out", default="data/humanlike/errors.md")
    he.set_defaults(func=cmd_humanlike_errors)
    ha = sub.add_parser("humanlike-adapter", help="train a small adapter (clock, ratings, the model's confidence) on a frozen model's stored top moves and compare it with the frozen model and with calibration wrappers on games it never saw")
    ha.add_argument("--testset", required=True); ha.add_argument("--scores", required=True)
    ha.add_argument("--eval-testset"); ha.add_argument("--eval-scores"); ha.add_argument("--judged", help="judged positions (humanlike-judge) for the sampled-play error check")
    ha.add_argument("--judged-train", help="judged positions of the TRAINING games (humanlike-judge --split trainval): adds the behaviour-matched adapters")
    ha.add_argument("--lambdas", default="1,3,10", help="weights of the behaviour term to try")
    ha.add_argument("--save-dir", help="write each trained adapter (all-features and behaviour-matched ones) here, to be used by humanlike-selfplay")
    ha.add_argument("--epochs", type=int, default=20); ha.add_argument("--boot", type=int, default=500); ha.add_argument("--seed", type=int, default=0, help="seed of the split into training, validation and test games")
    ha.add_argument("--fit-seed", type=int, default=0, help="seed of the training (initial weights, batch order): vary it to see how much the results move from training noise alone")
    ha.add_argument("--out", default="data/humanlike/adapter.md")
    ha.set_defaults(func=cmd_humanlike_adapter)
    hp = sub.add_parser("humanlike-selfplay", help="let models play games from the positions, clocks and ratings of real games: moves are sampled from the model's probabilities, thinking time from what humans spent")
    hp.add_argument("--testset", required=True); hp.add_argument("--out", required=True)
    hp.add_argument("--white", required=True, help="scorer spec, as for humanlike-score"); hp.add_argument("--black"); hp.add_argument("--white-adapter"); hp.add_argument("--black-adapter")
    hp.add_argument("--temperature", type=float, default=1.0, help="sharpen (below 1) or flatten (above 1) both players' probabilities: a dose-response control for the classifier test")
    hp.add_argument("--maia3-repo"); hp.add_argument("--maia2-repo"); hp.add_argument("--weights-dir"); hp.add_argument("--extra-path")
    hp.add_argument("--games", type=int, default=1000); hp.add_argument("--seed", type=int, default=0); hp.add_argument("--max-plies", type=int, default=300)
    hp.add_argument("--min-start-ply", type=int, default=8); hp.add_argument("--max-start-ply", type=int, default=14); hp.add_argument("--min-clock", type=float, default=60.0)
    hp.add_argument("--device", default="cpu"); hp.add_argument("--batch", type=int, default=64); hp.add_argument("--play-batch", type=int, default=256)
    hp.add_argument("--split", choices=("all", "train", "val", "test"), default="all", help="start only from games of this part of the adapter's game split"); hp.add_argument("--split-seed", type=int, default=0)
    hp.add_argument("--starts-from", help="a games file (selfplay or humanlike-humangames output): start from exactly its positions, in its order, instead of choosing at random")
    hp.set_defaults(func=cmd_humanlike_selfplay)
    hh = sub.add_parser("humanlike-humangames", help="the real continuations (moves, clocks) of starting positions of a test set, fetched by game id from Lichess: the human side of a comparison with generated games")
    hh.add_argument("--testset", required=True); hh.add_argument("--out", required=True)
    hh.add_argument("--games", type=int, default=20000); hh.add_argument("--seed", type=int, default=0)
    hh.add_argument("--min-start-ply", type=int, default=8); hh.add_argument("--max-start-ply", type=int, default=14); hh.add_argument("--min-clock", type=float, default=60.0)
    hh.add_argument("--split", choices=("all", "train", "val", "test"), default="test"); hh.add_argument("--split-seed", type=int, default=0)
    hh.add_argument("--pause", type=float, default=5.0, help="seconds between requests")
    hh.set_defaults(func=cmd_humanlike_humangames)
    hc = sub.add_parser("humanlike-c2st", help="classifier two-sample test: can a classifier tell human games from generated ones from the same starts, given only the moves (AUC 0.5 = not at all)")
    hc.add_argument("--human", required=True, help="games of humanlike-humangames"); hc.add_argument("--games", nargs="+", required=True, help="NAME=FILE of games of humanlike-selfplay from the same starts")
    hc.add_argument("--folds", type=int, default=5); hc.add_argument("--boot", type=int, default=500); hc.add_argument("--seed", type=int, default=0)
    hc.add_argument("--hidden", type=int, default=32, help="units of the network's hidden layer"); hc.add_argument("--epochs", type=int, default=60)
    hc.add_argument("--limit", type=int, help="use only the first N starts of the human games"); hc.add_argument("--out")
    hc.add_argument("--quality", nargs="+", metavar="NAME=FILE", help="engine-judged move quality (humanlike-quality) for 'human' and for every generated set: adds evaluation lost, error, blunder, engine's first choice as features")
    hc.add_argument("--max-moves", type=int, help="cut every game after this many moves following the start (the stimuli of the forced-choice study use 20 moves = 40 half-moves)")
    hc.set_defaults(func=cmd_humanlike_c2st)
    hs = sub.add_parser("humanlike-stimuli", help="stimuli of the forced-choice study: blocks of trials (a start and two fragments, the human one and a generated one), no clocks or ids, with a separate answer key")
    hs.add_argument("--human", required=True, help="games of humanlike-humangames"); hs.add_argument("--games", nargs="+", required=True, help="NAME=FILE of generated games from the same starts")
    hs.add_argument("--conditions", nargs="+", help="names of the generated sets that form the conditions 'human vs NAME' (default: all)")
    hs.add_argument("--blocks", type=int, default=30, help="one block per participant (with spares)"); hs.add_argument("--per-condition", type=int, default=60)
    hs.add_argument("--checks", type=int, default=4, help="attention checks per block: a human fragment against random legal moves")
    hs.add_argument("--fragment-plies", type=int, default=40, help="half-moves per fragment (fewer when a game ends earlier)"); hs.add_argument("--min-plies", type=int, default=24, help="shortest fragment allowed")
    hs.add_argument("--seed", type=int, required=True)
    hs.add_argument("--out", required=True); hs.add_argument("--key", required=True, help="the answer key (human side, condition, game id per trial)")
    hs.set_defaults(func=cmd_humanlike_stimuli)
    hz = sub.add_parser("humanlike-scaling", help="does the gap between a model and the humans (error profile, same judged positions) change with the model's size? gaps, differences and the slope with game-level intervals")
    hz.add_argument("--testset", required=True); hz.add_argument("--models", nargs="+", required=True, metavar="NAME=SCORES.npz,JUDGED.npz", help="in increasing order of size")
    hz.add_argument("--params", nargs="+", required=True, metavar="NAME=MILLIONS"); hz.add_argument("--boot", type=int, default=2000); hz.add_argument("--out", required=True)
    hz.set_defaults(func=cmd_humanlike_scaling)
    hf = sub.add_parser("humanlike-frontier", help="strength against human-likeness on judged positions: policies built from the human prior and the engine's losses (engine-reweighted, temperature, mixture), expected loss against the likelihood of the human's move")
    hf.add_argument("--testset", required=True); hf.add_argument("--scores", required=True); hf.add_argument("--judged", required=True)
    hf.add_argument("--betas", default="-10,0,1,2,3,5,7,10,15,20,30,50,100,1000", help="weights of the engine's loss in the reweighted policy (0 = the prior)")
    hf.add_argument("--taus", default="0.2,0.3,0.4,0.5,0.6,0.7,0.85,1.0,1.5", help="temperatures of the sharpened/flattened prior"); hf.add_argument("--alphas", default="0.05,0.1,0.2,0.3,0.45,0.6,0.8,1.0", help="shares of the engine's best candidate in the mixture")
    hf.add_argument("--boot", type=int, default=300); hf.add_argument("--out", required=True); hf.set_defaults(func=cmd_humanlike_frontier)
    hr = sub.add_parser("humanlike-arena", help="matches between Stockfish at node limits (the ladder) and the human-like bot (Maia-3 prior reweighted by the engine's losses), from the opening moves of real games, adjudicated by a referee engine; Elo with intervals (resumable)")
    hr.add_argument("--engine", help="Stockfish path"); hr.add_argument("--workers", type=int, default=4)
    hr.add_argument("--players", nargs="+", required=True, metavar="NAME=SPEC", help="NAME=sf:nodes=N (ladder) or NAME=bot:maia3=23m+history:beta=B[:rating=R][:nodes=N][:root=N]")
    hr.add_argument("--starts-from", required=True, help="human games (humanlike-humangames) whose opening moves are used"); hr.add_argument("--starts", type=int, default=24)
    hr.add_argument("--games-out", required=True, help="games (appended; finished games are skipped on a restart)"); hr.add_argument("--out", required=True)
    hr.add_argument("--chunk", type=int, default=200); hr.add_argument("--max-plies", type=int, default=240); hr.add_argument("--referee-nodes", type=int, default=1000)
    hr.add_argument("--bot-vs-bot", action="store_true"); hr.add_argument("--anchor"); hr.add_argument("--boot", type=int, default=200); hr.add_argument("--seed", type=int, default=0)
    hr.add_argument("--maia3-repo"); hr.add_argument("--maia2-repo"); hr.add_argument("--weights-dir"); hr.add_argument("--extra-path"); hr.add_argument("--device", default="cpu")
    hr.add_argument("--batch", type=int, default=64); hr.set_defaults(func=cmd_humanlike_arena)
    hk = sub.add_parser("humanlike-confirm", help="confirmation split: the frozen model and already trained adapters (not refitted) on a NEW test set judged by the engine: blunder gaps by clock regime and likelihood changes")
    hk.add_argument("--testset", required=True); hk.add_argument("--scores", required=True); hk.add_argument("--judged", required=True)
    hk.add_argument("--adapters-dir", required=True, help="the --save-dir of humanlike-adapter"); hk.add_argument("--lambdas", default="0.1,0.5", help="behaviour weights whose adapters were saved")
    hk.add_argument("--train-testset", required=True); hk.add_argument("--train-scores", required=True); hk.add_argument("--judged-train", required=True, help="judged sample of the TRAINING games (for the tail stand-in)")
    hk.add_argument("--boot", type=int, default=500); hk.add_argument("--out", required=True); hk.set_defaults(func=cmd_humanlike_confirm)
    hd = sub.add_parser("humanlike-diagnose", help="blunder types (humans against the model, by clock regime) and per-position calibration of the blunder probability the model implies, on judged positions")
    hd.add_argument("--testset", required=True); hd.add_argument("--scores", required=True); hd.add_argument("--judged", required=True)
    hd.add_argument("--adapters-dir", help="the --save-dir of humanlike-adapter: also diagnose the saved adapters (not refitted)"); hd.add_argument("--lambdas", default="0.1,0.5")
    hd.add_argument("--boot", type=int, default=500); hd.add_argument("--out", required=True); hd.set_defaults(func=cmd_humanlike_diagnose)
    co = sub.add_parser("coach", help="start the local coach: a web page on this computer to go back over the mistakes of a game, find better moves, see why they are better and play on (needs Stockfish)")
    co.add_argument("--engine", help="path to Stockfish (default: stockfish on the PATH)"); co.add_argument("--nodes", type=int, default=100000, help="search budget per position (more is slower and stronger)")
    co.add_argument("--data-dir", default="~/.mechess-coach", help="where your drills and reviewed games are kept (small JSON files on this computer; nothing is sent anywhere)")
    co.add_argument("--explorer", default="data/explorer/explorer.db", help="the opening explorer database (opening practice needs it)")
    co.add_argument("--syzygy", default="data/syzygy", help="folder with Syzygy tablebase files (endgame practice needs them; the 3 to 5 piece set is about 1 GB)")
    co.add_argument("--port", type=int, default=8765); co.add_argument("--no-browser", action="store_true"); co.set_defaults(func=cmd_coach)
    hq = sub.add_parser("humanlike-quality", help="Stockfish judges every move of the first N half-moves of each game (evaluation lost, error, blunder, engine's first choice) for the classifier test")
    hq.add_argument("--games", required=True, help="games of humanlike-humangames or humanlike-selfplay"); hq.add_argument("--out", required=True)
    hq.add_argument("--engine", help="path to Stockfish (default: stockfish on the PATH)"); hq.add_argument("--workers", type=int, default=1)
    hq.add_argument("--max-moves", type=int, default=40, help="half-moves after the start that are judged"); hq.add_argument("--nodes", type=int, default=20000, help="search budget per position")
    hq.add_argument("--limit", type=int, help="judge only the first N games"); hq.set_defaults(func=cmd_humanlike_quality)
    hg = sub.add_parser("humanlike-gamestats", help="statistics of generated games (results, endings, length, captures, checks, time use), optionally against the real continuations of the same starting positions")
    hg.add_argument("--games", nargs="+", required=True, help="NAME=FILE of games written by humanlike-selfplay")
    hg.add_argument("--real", help="Lichess games export (ndjson, with clocks and moves) of the games the starting positions come from")
    hg.add_argument("--out")
    hg.set_defaults(func=cmd_humanlike_gamestats)
    hr = sub.add_parser("humanlike-report", help="tables from score files: per model, by rating / phase / clock, and each later model's paired difference from the first")
    hr.add_argument("--testset", required=True); hr.add_argument("--scores", nargs="+", required=True)
    hr.add_argument("--min-ply", type=int, default=10, help="'comparable' drops the first N plies")
    hr.add_argument("--drop-forced", action="store_true", help="also leave out positions with a single legal move")
    hr.add_argument("--boot", type=int, default=300, help="bootstrap resamples"); hr.add_argument("--out", default="data/humanlike/report.md")
    hr.set_defaults(func=cmd_humanlike_report)
    mch = sub.add_parser("mechess", help="run MeChess as a UCI engine (book + engine candidates + prior + rating dial)")
    mch.add_argument("--table", help="dial table file (JSON {elo: [nodes, multipv, window, temperature, cp_scale, book_plies, blunder_rate, depth]})")
    mch.add_argument("--calibration", help="calibration file from `chessme calibrate`: --elo / the Elo option then mean the measured Elo")
    mch.add_argument("--engine", default=str(ENGINE_BIN)); mch.add_argument("--book", help="opening books in priority order, comma-separated; a folder holds one theory book per rating band "
                                                                 "(e.g. your own book.bin,data/explorer)")
    mch.add_argument("--prior", default="uniform", help="uniform | ours=CHECKPOINT | maia3=CHECKPOINT | style=MODEL.json (from style-model-fit)")
    mch.add_argument("--clock", help="clock model from mechess-clock-fit: the bot waits the way you would have thought (needs the GUI's clocks in `go`)")
    mch.add_argument("--clock-strength", type=float, default=1.0, help="scales the waiting: 0 = never wait, 1 = as you do")
    mch.add_argument("--style-strength", type=float, default=1.0, help="how strongly the style prior counts: 0 = none, 1 = as fitted")
    mch.add_argument("--maia3-repo"); mch.add_argument("--maia3-size", default="5m"); mch.add_argument("--extra-path")
    mch.add_argument("--elo", type=int, default=1800); mch.add_argument("--seed", type=int, default=0)
    mch.set_defaults(func=cmd_mechess)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
