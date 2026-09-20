"""Kaggle glue, kept out of the notebooks: the notebooks only clone the repository and call `chessme` commands, and everything that
depends on where Kaggle puts files lives here, where it is tested and also usable elsewhere.

  prepare_nlp   find the data written by the collection notebook (an input) and link it into the working folder; restore the checkpoint
                of an earlier training run (also an input) so a new session continues where the old one stopped
  slim_collect  drop the raw downloads after a collection run (the outputs are what the next notebook needs)
  slim_nlp      drop the linked data and the dry-run folder after training (only the model, metrics and logs are kept)"""
import glob
import os
import shutil
from pathlib import Path

DATA_DIRS = ("annotated", "prose", "books")
RAW_DOWNLOADS = ("annotated/annotated_pgn_free.tar.gz", "annotated/chessgpt", "annotated/lichess_studies.csv", "annotated/others.csv", "prose/raw")


def find_data(input_root):
    """The folder that holds annotated/, prose/ and books/ from a collection run mounted under `input_root`, or None."""
    found = sorted(glob.glob(os.path.join(str(input_root), "**", "annotated_moves.jsonl.gz"), recursive=True))
    return Path(found[0]).parent.parent if found else None


def prepare_nlp(out, input_root="/kaggle/input", log=print):
    """Link the collected data into `out` and restore an earlier training checkpoint. Raises when no data is found (before any GPU time
    is spent). Returns {"data": path, "resumed_from": path or None}."""
    out = Path(out)
    data = find_data(input_root)
    if data is None:
        raise FileNotFoundError(f"no annotated_moves.jsonl.gz under {input_root}: add the output of the collection notebook as an input "
                                "(Add Input -> Notebook output files)")
    out.mkdir(parents=True, exist_ok=True)
    for name in DATA_DIRS:
        src, dst = data / name, out / name
        if src.exists() and not (dst.exists() or dst.is_symlink()):
            os.symlink(src, dst)
    resumed = None
    prev = sorted(glob.glob(os.path.join(str(input_root), "**", "nlp", "ckpt.pt"), recursive=True))
    if prev and not (out / "nlp" / "ckpt.pt").exists():
        (out / "nlp").mkdir(exist_ok=True)
        for f in Path(prev[0]).parent.iterdir():
            if f.is_file():
                shutil.copy(f, out / "nlp" / f.name)
        resumed = prev[0]
        log(f"restored the checkpoint of an earlier run: {resumed}")
    log(f"data: {data}")
    return {"data": str(data), "resumed_from": resumed}


def slim_collect(out):
    """Delete the raw downloads of a collection run; returns the number of megabytes freed."""
    freed = 0
    for rel in RAW_DOWNLOADS:
        p = Path(out) / rel
        if p.is_dir():
            freed += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            freed += p.stat().st_size
            p.unlink()
    return freed / 1e6


def slim_nlp(out):
    """Remove the linked data and the dry-run folder after training."""
    for name in DATA_DIRS + ("nlp_dry",):
        p = Path(out) / name
        if p.is_symlink():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
