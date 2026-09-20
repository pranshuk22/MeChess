from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_profile(name):
    path = ROOT / "configs" / "profiles" / f"{name}.yaml"
    if not path.exists():
        raise SystemExit(f"No such profile: {path}")
    cfg = yaml.safe_load(path.read_text())
    cfg["_raw_dir"] = ROOT / cfg.get("paths", {}).get("raw", "data/raw")
    return cfg
