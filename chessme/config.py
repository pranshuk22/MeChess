import os
from pathlib import Path

import yaml


def find_root():
    """The project folder: where configs/, profiles/, data/ and engine/build live. `$CHESSME_ROOT` if set; else the source checkout this package
    sits in (an editable install or a plain clone); else the current folder (a normal `pip install`, where the package lives in site-packages
    and its parent folder is not the project)."""
    env = os.environ.get("CHESSME_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    source = Path(__file__).resolve().parent.parent
    if (source / "configs").is_dir() and (source / "engine").is_dir():
        return source
    return Path.cwd()


ROOT = find_root()


def load_profile(name):
    path = ROOT / "configs" / "profiles" / f"{name}.yaml"
    if not path.exists():
        raise SystemExit(f"No such profile: {path}")
    cfg = yaml.safe_load(path.read_text())
    cfg["_raw_dir"] = ROOT / cfg.get("paths", {}).get("raw", "data/raw")
    return cfg
