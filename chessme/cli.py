import argparse
import json
import os
import subprocess
import sys
import tempfile
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


def cmd_analyse(args):
    """Analyse the games of a PGN file with Stockfish: one JSON file per game (resumable and pausable), then a Markdown report."""
    import io as _io
    import json as _json

    import chess.pgn as _pgn

    from .analysis import runner as AR
    from .jobs import JobControl, Stopped
    from .uci_client import UciEngine
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
    log(f"=== analyse {args.pgn}: {len(games)} games, {args.nodes} nodes/position, output {out}")
    done = failed = 0
    with UciEngine([args.engine], options={"Threads": 1, "Hash": 64}) as eng, ctl.signals():
        search = AR.engine_search(eng, nodes=args.nodes, multipv=2)
        try:
            for i, g in enumerate(games):
                ctl.checkpoint()
                key = AR.game_key(g, i)
                path = out / "games" / f"{key}.json"
                if path.exists():
                    done += 1
                    continue
                try:
                    res = AR.analyse_game(g, search)
                except Exception as e:      # a game the engine cannot finish must not stop the batch
                    failed += 1
                    log(f"  {key}: FAILED {e!r}")
                    continue
                res["player_color"] = AR.side_of(g, args.player)
                res["headers"] = {k: g.headers.get(k, "") for k in ("White", "Black", "Result", "Date", "Site", "Opening")}
                path.with_suffix(".tmp").write_text(_json.dumps(res))
                path.with_suffix(".tmp").replace(path)
                done += 1
                log(f"  [{done}/{len(games)}] {key}: {len(res['moves'])} plies")
        except Stopped as e:
            log(f"stopped: {e} (rerun the same command to resume)")
    results = [(p.stem, _json.loads(p.read_text())) for p in sorted((out / "games").glob("*.json"))]
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
    ex = NLP.build_examples(annotated=data / "annotated" / "annotated_moves.jsonl.gz", prose_dir=data, books_dir=data / "books",
                            max_per_kind=args.max_per_source)
    by = {}
    for e in ex:
        by[e["source"]] = by.get(e["source"], 0) + 1
    log(f"{len(ex)} examples: {by}")
    if len(ex) < 200:
        sys.exit("too few examples: run books-learn first")
    ctl = JobControl(args.job, args.control_dir, log=log)
    with ctl.signals():
        res = NLP.train(ex, Path(args.out) if args.out else data / "nlp", backend=args.backend, model_name=args.model, epochs=args.epochs,
                        batch=args.batch, lr=args.lr, dry_run=args.dry_run, deadline_minutes=args.deadline_minutes,
                        ckpt_every=args.ckpt_every, ctl=ctl, log=log)
    t = res["metrics"].get("test", {})
    log(f"{'DRY RUN ' if args.dry_run else ''}{'stopped' if res['stopped'] else 'finished'} at step {res['step']}; test: "
        + json.dumps({k: round(v, 3) for k, v in t.items() if isinstance(v, float)}))


def cmd_books_nlp_predict(args):
    from .books import nlp as NLP
    model, cfg = NLP.load(args.model_dir)
    for text, r in zip(args.texts, NLP.predict(model, args.texts, cfg)):
        print(f"{text[:80]!r}\n   concepts {r['concepts']}  judgement {r['judgement']}  evaluation {r['evaluation']}")


def cmd_books_preflight(args):
    from .books import preflight as PF
    ok = PF.run(args.out, need_gpu=args.need_gpu, need_transformers=args.backend == "transformer", model_name=args.model if args.backend == "transformer" else None,
                min_free_gb=args.min_free_gb, network=not args.no_network)
    sys.exit(0 if ok else 1)


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


def cmd_mechess(args):
    from .mechess import priors
    from .mechess.controller import BookReader, MeChess
    from .mechess.uci import MechessUci
    from .uci_client import UciEngine

    kind, _, path = args.prior.partition("=")
    if kind == "ours":
        prior = priors.OursPrior(path)
    elif kind == "maia3":
        prior = priors.Maia3Prior(args.maia3_repo, path, args.maia3_size, extra_paths=[args.extra_path] if args.extra_path else [])
    elif kind == "uniform":
        prior = priors.UniformPrior()
    else:
        raise SystemExit("--prior must be uniform, ours=CHECKPOINT or maia3=CHECKPOINT")
    engine = UciEngine([args.engine]).start()
    try:
        book = BookReader(args.book) if args.book else None
        from .mechess.calibration import Calibration
        cal = Calibration.load(args.calibration) if args.calibration else None
        from .mechess import dial
        table = dial.load_table(args.table) if args.table else (cal.table() if cal else None)   # a calibration brings its own table
        mc = MeChess(engine, prior, book, table=table, seed=args.seed or None, calibration=cal)
        MechessUci(mc, elo=args.elo).run()
    finally:
        engine.close()


def main():
    p = argparse.ArgumentParser(prog="chessme")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download games for the accounts in a profile")
    f.add_argument("--profile", required=True)
    f.add_argument("--only", nargs="*", help="limit to these usernames")
    f.set_defaults(func=cmd_fetch)
    for name, fn, helptext in [("ingest", cmd_ingest, "normalise raw games into data/processed/games.jsonl"),
                               ("audit", cmd_audit, "print a data audit report")]:
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--profile", required=True)
        sp.set_defaults(func=fn)

    o = sub.add_parser("openings", help="build an opening-position file from your games (or random)")
    o.add_argument("--profile", required=True)
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
    t.add_argument("--profile", required=True)
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
    b.add_argument("--profile", required=True)
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
    md.add_argument("--profile")
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
    bl = sub.add_parser("books-learn", help="everything from books and annotated games in one command: books, concept-line pairs, annotated archive, report (resumable)")
    bl.add_argument("--out", default="data/books_learn"); bl.add_argument("--steps", nargs="+", default=["books", "pairs", "annotated", "prose", "report"],
                                                                        choices=["books", "pairs", "annotated", "prose", "report"])
    bl.add_argument("--limit-per-source", type=int, help="at most this many games per annotated source (a trial)")
    bl.add_argument("--studies-dir", help="folder with extra PGN files, e.g. from books-studies"); bl.add_argument("--archive", help="an already downloaded annotated_pgn_free.tar.gz")
    bl.add_argument("--max-books", type=int, help="only the first N books (a trial)")
    bl.add_argument("--no-chessgpt", action="store_true", help="skip the large ChessGPT annotated-PGN shards (175 MB)")
    bl.add_argument("--no-csv", action="store_true", help="skip the extra CC0 studies dataset"); bl.add_argument("--no-openings", action="store_true", help="skip opening names")
    bl.add_argument("--redo", action="store_true"); bl.add_argument("--control-dir", default="data/control"); bl.add_argument("--log", default="data/books_learn/learn.log")
    bl.set_defaults(func=cmd_books_learn)
    nt = sub.add_parser("books-nlp-train", help="train the chess-text language model (concepts, move judgement, evaluation) on the books-learn output")
    nt.add_argument("--data", default="data/books_learn"); nt.add_argument("--out"); nt.add_argument("--backend", choices=["bow", "transformer"], default="bow")
    nt.add_argument("--model", default="distilroberta-base", help="Hugging Face encoder for --backend transformer")
    nt.add_argument("--epochs", type=int, default=3); nt.add_argument("--batch", type=int, default=64); nt.add_argument("--lr", type=float)
    nt.add_argument("--max-per-source", type=int, help="cap examples per source (a trial)")
    nt.add_argument("--dry-run", action="store_true", help="a few seconds on a few hundred examples: checks the whole path, writes nothing")
    nt.add_argument("--deadline-minutes", type=float, help="stop cleanly with a checkpoint after this many minutes (Kaggle: below 12 h)")
    nt.add_argument("--ckpt-every", type=int, default=500); nt.add_argument("--job", default="nlp"); nt.add_argument("--control-dir", default="data/control")
    nt.add_argument("--log", default="data/books_learn/nlp.log")
    nt.set_defaults(func=cmd_books_nlp_train)
    npd = sub.add_parser("books-nlp-predict", help="read comments with a trained chess-text model")
    npd.add_argument("model_dir"); npd.add_argument("texts", nargs="+")
    npd.set_defaults(func=cmd_books_nlp_predict)
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
    an.add_argument("--limit", type=int); an.add_argument("--job", default="analyse"); an.add_argument("--control-dir", default="data/control")
    an.add_argument("--log", default="data/analysis/analyse.log")
    an.set_defaults(func=cmd_analyse)
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
    sr = sub.add_parser("style-report", help="fit the style model on the training positions, evaluate on the test ones")
    sr.add_argument("--data", default="data/style/example"); sr.add_argument("--l2", type=float, default=1.0)
    sr.add_argument("--baseline", help="folder from style-pop-data: report the player's weights relative to it")
    sr.add_argument("--boot", type=int, default=30, help="bootstrap resamples for the standard errors")
    sr.add_argument("--label", default="you"); sr.add_argument("--out", default="data/style/style_report.md")
    sr.set_defaults(func=cmd_style_report)
    mch = sub.add_parser("mechess", help="run MeChess as a UCI engine (book + engine candidates + prior + rating dial)")
    mch.add_argument("--table", help="dial table file (JSON {elo: [nodes, multipv, window, temperature, cp_scale, book_plies, blunder_rate, depth]})")
    mch.add_argument("--calibration", help="calibration file from `chessme calibrate`: --elo / the Elo option then mean the measured Elo")
    mch.add_argument("--engine", default=str(ENGINE_BIN)); mch.add_argument("--book")
    mch.add_argument("--prior", default="uniform", help="uniform | ours=CHECKPOINT | maia3=CHECKPOINT")
    mch.add_argument("--maia3-repo"); mch.add_argument("--maia3-size", default="5m"); mch.add_argument("--extra-path")
    mch.add_argument("--elo", type=int, default=1800); mch.add_argument("--seed", type=int, default=0)
    mch.set_defaults(func=cmd_mechess)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
