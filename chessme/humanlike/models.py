"""Build a scorer (a model that gives a probability to every legal move) from a short spec such as `maia3=23m+history`."""
from pathlib import Path


def make_scorer(spec, *, maia3_repo=None, maia2_repo=None, weights_dir=None, extra_path=None, device="cpu", batch=64):
    """`maia3=5m|23m|79m[+history]` (needs `maia3_repo` and `weights_dir/maia3-<size>.pt`), `maia2=blitz|rapid` (`maia2_repo`,
    `weights_dir/<kind>_model.pt`), or `ours=CHECKPOINT`. The Maia checkouts are separate, AGPL-licensed downloads."""
    from ..model import compare
    kind, _, arg = spec.partition("=")
    extra = [extra_path] if extra_path else []
    if kind == "maia3":
        size = arg.replace("+history", "")
        return compare.Maia3Scorer(maia3_repo, Path(weights_dir) / f"maia3-{size}.pt", size, use_history=arg.endswith("+history"), device=device,
                                   extra_paths=extra, batch_size=batch)
    if kind == "maia2":
        return compare.Maia2Scorer(maia2_repo, Path(weights_dir) / f"{arg}_model.pt", device=device, extra_paths=extra, batch_size=batch)
    if kind == "ours":
        return compare.OursScorer(arg, device=device, batch_size=batch)
    raise SystemExit(f"unknown scorer {spec!r} (use maia3=5m|23m|79m[+history], maia2=blitz|rapid, ours=CHECKPOINT)")
