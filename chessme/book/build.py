"""Build a book from normalised games and a profile config."""
from dataclasses import dataclass
from pathlib import Path

from ..dataset.weights import Weighter
from . import report, sanity
from .format import write_book
from .tree import BookTree

DEFAULTS = {"max_ply": 30, "min_games": 2, "min_position_games": 3, "min_share": 0.05}


@dataclass
class BuildResult:
    tree: BookTree
    entries: list
    dropped_stats: object
    sanity_dropped: list
    params: dict
    report_text: str


def book_params(cfg, overrides=None):
    params = dict(DEFAULTS)
    params.update({k: v for k, v in cfg.get("book", {}).items() if k in DEFAULTS})
    params.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return params


def build_book(cfg, rows, overrides=None, sanity_engine=None):
    """`sanity_engine`: a started UciEngine to drop book moves that lose material (optional)."""
    params = book_params(cfg, overrides)
    weighter = Weighter(cfg, rows)
    tree = BookTree(params["max_ply"])
    for row in rows:
        tree.add_game(row, weighter)
    entries, dropped_stats = tree.entries(params["min_games"], params["min_position_games"], params["min_share"])
    sanity_dropped = None
    if sanity_engine is not None:
        s = cfg.get("book", {}).get("sanity", {})
        entries, sanity_dropped = sanity.sanity_filter(tree, entries, sanity_engine, depth=s.get("depth", 10),
                                                       max_cp_loss=s.get("max_cp_loss", 80))
    text = report.build_report(tree, entries, dropped_stats, rows, weighter, params, sanity_dropped)
    return BuildResult(tree, entries, dropped_stats, sanity_dropped, params, text)


def save(result, out_path):
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_book(out, result.entries)
    report_path = out.with_name(out.stem + "_report.md")
    report_path.write_text(result.report_text)
    return out, report_path
