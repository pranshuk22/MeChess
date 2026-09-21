"""Kaggle glue, kept out of the notebooks: the notebooks only clone the repository and call `chessme` commands, and everything that
depends on where Kaggle puts files lives here, where it is tested and also usable elsewhere.

  prepare_nlp   find the data written by the collection notebook (an input) and link it into the working folder; restore the checkpoint
                of an earlier training run (also an input) so a new session continues where the old one stopped
  slim_collect  drop the raw downloads after a collection run (the outputs are what the next notebook needs)
  slim_nlp      drop the linked data and the dry-run folder after training (only the model, metrics and logs are kept)
  find_model    the trained chess-text model (an earlier training run's output) mounted under the inputs
  prepare_label find the data and the model for the labelling run and restore an interrupted labelling run's partial output"""
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


def inventory(data):
    """What the collected data folder holds: [(name, size in MB or item count)] and a printable text."""
    d = Path(data)
    rows = []
    for rel in ("annotated/annotated_moves.jsonl.gz", "prose/stackexchange.jsonl.gz", "prose/wikipedia.jsonl.gz", "concept_line_pairs.jsonl", "report.md"):
        p = d / rel
        rows.append((rel, f"{p.stat().st_size / 1e6:.1f} MB" if p.exists() else "MISSING"))
    books = list((d / "books").glob("*.txt")) if (d / "books").exists() else []
    rows.append(("books/*.txt", f"{len(books)} books, {sum(f.stat().st_size for f in books) / 1e6:.1f} MB" if books else "MISSING"))
    return rows, "\n".join(f"  {n:42s} {v}" for n, v in rows)


def prepare_nlp(out, input_root="/kaggle/input", log=print, data_dir=None):
    """Link the collected data into `out` and restore an earlier training checkpoint. `data_dir` names the collection notebook's output folder
    explicitly (searched recursively); otherwise everything under `input_root` is searched. Raises when no data is found (before any GPU time
    is spent), listing what is there. Returns {"data": path, "resumed_from": path or None}."""
    out = Path(out)
    root = data_dir or input_root
    data = find_data(root)
    if data is None:
        seen = sorted(p.name for p in Path(root).glob("*"))[:20] if Path(root).exists() else []
        raise FileNotFoundError(f"no annotated_moves.jsonl.gz under {root} (found there: {seen or 'nothing'}): add the output of the collection notebook "
                                "as an input (Add Input -> Notebook output files) or set DATA_DIR to its folder")
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
    log(inventory(data)[1])
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


def find_model(input_root):
    """The folder of a trained chess-text model (holds config.json and model.pt) under `input_root`, or None. When several are mounted the
    first in name order is returned; name the folder explicitly (--model-dir) to choose."""
    found = sorted(glob.glob(os.path.join(str(input_root), "**", "nlp", "model.pt"), recursive=True))
    found = [f for f in found if (Path(f).parent / "config.json").exists()]
    return Path(found[0]).parent if found else None


def prepare_label(out, input_root="/kaggle/input", data_dir=None, model_dir=None, log=print):
    """Locate the annotated moves and the trained model for `books-nlp-label`, and restore the partial output of an interrupted run found among
    the inputs. Raises before any GPU time is spent when something is missing. Returns {"annotated", "model", "resumed_from"}."""
    root = data_dir or input_root
    data = find_data(root)
    if data is None:
        raise FileNotFoundError(f"no annotated_moves.jsonl.gz under {root}: add the collection notebook's output as an input (or set DATA_DIR)")
    model = Path(model_dir) if model_dir else find_model(input_root)
    if model is None or not (Path(model) / "model.pt").exists():
        raise FileNotFoundError(f"no trained model (nlp/model.pt with config.json) under {input_root}: add the training notebook's output as an input (or set MODEL_DIR)")
    out = Path(out)
    resumed = None
    have = (out / "labelled.jsonl.gz.part").exists() or (out / "labelled.jsonl.gz").exists()
    for part in sorted(glob.glob(os.path.join(str(input_root), "**", "labelled.jsonl.gz.part"), recursive=True)):
        progress = part[:-len(".part")] + ".progress"
        if not have and os.path.exists(progress):
            out.mkdir(parents=True, exist_ok=True)
            shutil.copy(part, out / "labelled.jsonl.gz.part")
            shutil.copy(progress, out / "labelled.jsonl.gz.progress")
            resumed = part
            log(f"restored an interrupted labelling run: {part}")
            break
    log(f"annotated moves: {data / 'annotated' / 'annotated_moves.jsonl.gz'}\nmodel: {model}")
    return {"annotated": str(data / "annotated" / "annotated_moves.jsonl.gz"), "model": str(model), "resumed_from": resumed}
