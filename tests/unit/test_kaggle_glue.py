import os

import pytest

from chessme import kaggle as K


def make_collection(root):
    d = root / "nb1" / "learn"
    (d / "annotated").mkdir(parents=True)
    (d / "annotated" / "annotated_moves.jsonl.gz").write_bytes(b"x")
    (d / "prose").mkdir()
    (d / "books").mkdir()
    return d


def test_prepare_nlp_links_the_collected_data_and_restores_an_earlier_checkpoint(tmp_path):
    inp = tmp_path / "input"
    d = make_collection(inp)
    (inp / "earlier" / "learn" / "nlp").mkdir(parents=True)
    for n in ("ckpt.pt", "config.json", "thresholds.json"):
        (inp / "earlier" / "learn" / "nlp" / n).write_text(n)
    out = tmp_path / "work"
    res = K.prepare_nlp(out, inp, log=lambda *_: None)
    assert res["data"] == str(d) and res["resumed_from"].endswith("ckpt.pt")
    assert (out / "annotated").is_symlink() and (out / "annotated" / "annotated_moves.jsonl.gz").exists() and (out / "books").is_symlink()
    assert sorted(p.name for p in (out / "nlp").iterdir()) == ["ckpt.pt", "config.json", "thresholds.json"]
    K.prepare_nlp(out, inp, log=lambda *_: None)                                       # idempotent: nothing is overwritten or duplicated
    assert (out / "nlp" / "ckpt.pt").read_text() == "ckpt.pt"


def test_prepare_nlp_without_data_fails_before_any_work_with_a_clear_message(tmp_path):
    with pytest.raises(FileNotFoundError, match="Add Input"):
        K.prepare_nlp(tmp_path / "work", tmp_path / "empty", log=lambda *_: None)


def test_an_existing_local_checkpoint_is_not_replaced(tmp_path):
    inp = tmp_path / "input"
    make_collection(inp)
    (inp / "earlier" / "nlp").mkdir(parents=True)
    (inp / "earlier" / "nlp" / "ckpt.pt").write_text("old")
    out = tmp_path / "work"
    (out / "nlp").mkdir(parents=True)
    (out / "nlp" / "ckpt.pt").write_text("mine")
    assert K.prepare_nlp(out, inp, log=lambda *_: None)["resumed_from"] is None and (out / "nlp" / "ckpt.pt").read_text() == "mine"


def test_slim_removes_raw_downloads_and_links_but_keeps_results(tmp_path):
    out = tmp_path / "learn"
    (out / "annotated" / "chessgpt").mkdir(parents=True)
    (out / "annotated" / "chessgpt" / "big").write_bytes(b"x" * 2_000_000)
    (out / "annotated" / "annotated_pgn_free.tar.gz").write_bytes(b"x" * 1_000_000)
    (out / "annotated" / "annotated_moves.jsonl.gz").write_bytes(b"keep")
    (out / "prose" / "raw").mkdir(parents=True)
    (out / "prose" / "raw" / "se.jsonl").write_bytes(b"x" * 1_000_000)
    (out / "prose" / "stackexchange.jsonl.gz").write_bytes(b"keep")
    assert abs(K.slim_collect(out) - 4.0) < 0.01
    assert (out / "annotated" / "annotated_moves.jsonl.gz").exists() and (out / "prose" / "stackexchange.jsonl.gz").exists() and not (out / "prose" / "raw").exists()
    src = tmp_path / "src"
    src.mkdir()
    work = tmp_path / "work"
    (work / "nlp").mkdir(parents=True)
    (work / "nlp_dry").mkdir()
    os.symlink(src, work / "annotated")
    K.slim_nlp(work)
    assert not (work / "annotated").exists() and src.exists() and not (work / "nlp_dry").exists() and (work / "nlp").exists()
