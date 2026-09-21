import gzip
import json
import subprocess
import sys

import pytest

from chessme import kaggle as KG
from chessme.books import label as LB, nlp as N
from tests.unit.test_books_nlp import CONTEXT, synth


@pytest.fixture(autouse=True)
def tiny_embedding_table(monkeypatch):
    monkeypatch.setattr(N, "BOW_BUCKETS", 1 << 12)


@pytest.fixture(scope="module")
def model_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("model")
    N.BOW_BUCKETS = 1 << 12
    N.train(synth(600), d, backend="bow", epochs=6, batch=32, dim=64, lr=3e-3, log=lambda *_: None)
    return d


def rec(i, comment, concepts=None, glyph=None):
    return {"ply": i, "color": "white", "fen": "8/8/8/8/8/8/8/K1k5 w - - 0 1", "uci": "a1a2", "san": "Ka2", "glyph": glyph, "eval": None,
            "comment": comment, "concepts": concepts or {}, "source": "unit", "game": i // 3}


def records(n=40):
    out = []
    for i in range(n):
        if i % 10 == 3:
            out.append(rec(i, "ok"))                                             # too short
        elif i % 10 == 7:
            out.append(rec(i, "ъъъ ыыы эээ " * 6))                               # not English
        elif i % 4 == 0:
            out.append(rec(i, "the position is in zugzwang and " + CONTEXT["zugzwang"], {"zugzwang": 1}, glyph="?" if i % 8 == 0 else None))
        else:
            out.append(rec(i, CONTEXT["open_file"] + " and white plays carefully here", {}))
    return out


def write(path, recs):
    with gzip.open(path, "wt") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")


def test_only_readable_comments_are_labelled_with_every_field(model_dir):
    model, cfg = N.load(model_dir, device="cpu")
    recs = records()
    out = LB.label_chunk(model, cfg, recs)
    assert len(out) == sum(LB.usable(r) for r in recs) and 0 < len(out) < len(recs)
    r = out[0]
    assert set(r) >= {"fen", "uci", "san", "comment", "concepts", "concepts_lexicon", "concepts_model", "model_only", "judgement", "judgement_conf",
                      "evaluation", "concept_scores", "game", "source"}
    assert r["judgement"] in N.JUDGEMENT and r["evaluation"] in N.EVAL_CLASSES and 0 < r["judgement_conf"] <= 1


def test_concepts_are_the_union_and_model_only_excludes_the_lexicon(model_dir):
    model, cfg = N.load(model_dir, device="cpu")
    out = LB.label_chunk(model, cfg, records())
    for r in out:
        assert set(r["concepts"]) == set(r["concepts_lexicon"]) | set(r["concepts_model"])
        assert set(r["model_only"]) == set(r["concepts_model"]) - set(r["concepts_lexicon"])
    assert any(r["concepts_lexicon"] == ["zugzwang"] for r in out)


def test_the_model_is_fed_the_comment_with_keywords_hidden(model_dir, monkeypatch):
    model, cfg = N.load(model_dir, device="cpu")
    seen = []
    real = N.predict_batches
    monkeypatch.setattr(N, "predict_batches", lambda m, texts, batch=64: (seen.extend(texts), real(m, texts, batch))[1])
    LB.label_chunk(model, cfg, [rec(0, "the position is in zugzwang and white plays carefully here and black answers in the natural way")])
    assert seen and all("zugzwang" not in t for t in seen) and N.MASK in seen[0]


def test_labels_do_not_depend_on_batching_or_order(model_dir):
    model, cfg = N.load(model_dir, device="cpu")
    recs = [r for r in records() if LB.usable(r)]
    a = LB.label_chunk(model, cfg, recs, batch=3)
    b = LB.label_chunk(model, cfg, recs, batch=64)
    assert [r["concepts"] for r in a] == [r["concepts"] for r in b] and [r["judgement"] for r in a] == [r["judgement"] for r in b]


def read(path):
    return [json.loads(l) for l in gzip.open(path, "rt")]


def test_run_writes_the_gzip_and_removes_the_partial_files(model_dir, tmp_path):
    model, cfg = N.load(model_dir, device="cpu")
    write(tmp_path / "in.jsonl.gz", records())
    res = LB.run(tmp_path / "in.jsonl.gz", tmp_path / "out.jsonl.gz", model, cfg, chunk=7, log=lambda *_: None)
    assert res["finished"] and res["read"] == 40
    assert len(read(tmp_path / "out.jsonl.gz")) == res["labelled"]
    assert not (tmp_path / "out.jsonl.gz.part").exists() and not (tmp_path / "out.jsonl.gz.progress").exists()


def test_an_interrupted_run_continues_to_exactly_the_same_result(model_dir, tmp_path):
    model, cfg = N.load(model_dir, device="cpu")
    write(tmp_path / "in.jsonl.gz", records())
    LB.run(tmp_path / "in.jsonl.gz", tmp_path / "whole.jsonl.gz", model, cfg, chunk=7, log=lambda *_: None)
    first = LB.run(tmp_path / "in.jsonl.gz", tmp_path / "cut.jsonl.gz", model, cfg, chunk=7, deadline_minutes=0, log=lambda *_: None)
    assert not first["finished"] and first["read"] == 7
    part = tmp_path / "cut.jsonl.gz.part"
    with open(part, "ab") as f:
        f.write(b'{"torn": tru')                                                  # a write cut off by the interruption
    second = LB.run(tmp_path / "in.jsonl.gz", tmp_path / "cut.jsonl.gz", model, cfg, chunk=7, log=lambda *_: None)
    assert second["finished"] and second["read"] == 40
    assert read(tmp_path / "cut.jsonl.gz") == read(tmp_path / "whole.jsonl.gz")


def test_limit_and_fresh(model_dir, tmp_path):
    model, cfg = N.load(model_dir, device="cpu")
    write(tmp_path / "in.jsonl.gz", records())
    res = LB.run(tmp_path / "in.jsonl.gz", tmp_path / "o.jsonl.gz", model, cfg, limit=10, chunk=4, log=lambda *_: None)
    assert res["read"] == 10 and res["finished"]
    LB.run(tmp_path / "in.jsonl.gz", tmp_path / "p.jsonl.gz", model, cfg, chunk=7, deadline_minutes=0, log=lambda *_: None)
    res = LB.run(tmp_path / "in.jsonl.gz", tmp_path / "p.jsonl.gz", model, cfg, chunk=7, fresh=True, log=lambda *_: None)
    assert res["read"] == 40


def test_summary_and_report(model_dir, tmp_path):
    model, cfg = N.load(model_dir, device="cpu")
    write(tmp_path / "in.jsonl.gz", records())
    LB.run(tmp_path / "in.jsonl.gz", tmp_path / "o.jsonl.gz", model, cfg, chunk=9, log=lambda *_: None)
    stats, pick = LB.summarise(tmp_path / "o.jsonl.gz", sample=5)
    assert stats["records"] == len(read(tmp_path / "o.jsonl.gz")) and stats["glyph_labelled"] > 0
    assert 0 <= stats["judgement_matches_glyph"] <= 1
    assert len(pick) <= 5 and all(r["model_only"] for r in pick)
    text = LB.render(stats, pick)
    assert "| concept |" in text and ("check these by eye" in text) == bool(pick)


def test_kaggle_finds_the_model_and_the_data_and_refuses_when_missing(tmp_path):
    root = tmp_path / "input"
    (root / "a" / "annotated").mkdir(parents=True)
    (root / "a" / "annotated" / "annotated_moves.jsonl.gz").write_bytes(b"")
    with pytest.raises(FileNotFoundError, match="no trained model"):
        KG.prepare_label(tmp_path / "out", root, log=lambda *_: None)
    (root / "b" / "learn" / "nlp").mkdir(parents=True)
    (root / "b" / "learn" / "nlp" / "model.pt").write_bytes(b"x")
    with pytest.raises(FileNotFoundError, match="no trained model"):
        KG.prepare_label(tmp_path / "out", root, log=lambda *_: None)                # config.json is missing too
    (root / "b" / "learn" / "nlp" / "config.json").write_text("{}")
    r = KG.prepare_label(tmp_path / "out", root, log=lambda *_: None)
    assert r["model"].endswith("learn/nlp") and r["annotated"].endswith("annotated_moves.jsonl.gz") and r["resumed_from"] is None
    with pytest.raises(FileNotFoundError, match="annotated_moves"):
        KG.prepare_label(tmp_path / "out", tmp_path / "empty", log=lambda *_: None)


def test_kaggle_restores_an_interrupted_labelling_run(tmp_path):
    root = tmp_path / "input"
    (root / "a" / "annotated").mkdir(parents=True)
    (root / "a" / "annotated" / "annotated_moves.jsonl.gz").write_bytes(b"")
    (root / "m" / "nlp").mkdir(parents=True)
    (root / "m" / "nlp" / "model.pt").write_bytes(b"x")
    (root / "m" / "nlp" / "config.json").write_text("{}")
    (root / "prev" / "labelled").mkdir(parents=True)
    (root / "prev" / "labelled" / "labelled.jsonl.gz.part").write_bytes(b"line\n")
    (root / "prev" / "labelled" / "labelled.jsonl.gz.progress").write_text('{"read": 3, "bytes": 5}')
    out = tmp_path / "out"
    r = KG.prepare_label(out, root, log=lambda *_: None)
    assert r["resumed_from"] and (out / "labelled.jsonl.gz.part").read_bytes() == b"line\n"
    assert json.loads((out / "labelled.jsonl.gz.progress").read_text())["read"] == 3


def test_cli_end_to_end_and_pause_exit_code(model_dir, tmp_path):
    write(tmp_path / "in.jsonl.gz", records())
    cmd = [sys.executable, "-m", "chessme", "books-nlp-label", "--data", str(tmp_path / "in.jsonl.gz"), "--model-dir", str(model_dir),
           "--out", str(tmp_path / "lab" / "l.jsonl.gz"), "--log", str(tmp_path / "l.log"), "--chunk", "7", "--sample", "3"]
    paused = subprocess.run(cmd + ["--deadline-minutes", "0"], capture_output=True, text=True)
    assert paused.returncode == 3 and (tmp_path / "lab" / "l.jsonl.gz.part").exists()
    done = subprocess.run(cmd, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-800:]
    assert (tmp_path / "lab" / "l.jsonl.gz").exists() and (tmp_path / "lab" / "label_report.md").exists()
    assert json.loads((tmp_path / "lab" / "label_stats.json").read_text())["records"] > 0


def test_a_missing_transformers_package_gives_a_clear_message(monkeypatch):
    monkeypatch.setitem(sys.modules, "transformers", None)                          # makes `import transformers` fail
    with pytest.raises(ImportError, match="pip install transformers"):
        N.TransformerEncoder("any-model")


def test_a_model_dir_may_be_the_outputs_top_folder_or_the_model_folder(tmp_path):
    top = tmp_path / "input" / "train-output"
    (top / "learn" / "nlp").mkdir(parents=True)
    (top / "learn" / "nlp" / "model.pt").write_bytes(b"x")
    (top / "learn" / "nlp" / "config.json").write_text("{}")
    (top / "MeChess").mkdir()
    assert KG.resolve_model(top) == top / "learn" / "nlp"                       # the folder named in the failed Kaggle run
    assert KG.resolve_model(top / "learn" / "nlp") == top / "learn" / "nlp"
    assert KG.resolve_model(tmp_path / "nothing") is None
    (top / "learn" / "nlp" / "config.json").unlink()
    assert KG.resolve_model(top) is None                                        # a model.pt without its config is not a model


def test_prepare_label_accepts_the_top_folder_and_names_what_it_found_when_it_fails(tmp_path):
    root = tmp_path / "input"
    (root / "data" / "annotated").mkdir(parents=True)
    (root / "data" / "annotated" / "annotated_moves.jsonl.gz").write_bytes(b"")
    top = root / "train-output"
    (top / "learn" / "nlp").mkdir(parents=True)
    (top / "learn" / "nlp" / "model.pt").write_bytes(b"x")
    with pytest.raises(FileNotFoundError, match=r"\.pt files found there: \['learn/nlp/model.pt'\]"):
        KG.prepare_label(tmp_path / "out", root, data_dir=str(root / "data"), model_dir=str(top), log=lambda *_: None)      # no config.json yet
    (top / "learn" / "nlp" / "config.json").write_text("{}")
    r = KG.prepare_label(tmp_path / "out", root, data_dir=str(root / "data"), model_dir=str(top), log=lambda *_: None)
    assert r["model"] == str(top / "learn" / "nlp")


def test_cli_with_kaggle_style_inputs_and_the_training_outputs_top_folder(model_dir, tmp_path):
    """What the Kaggle notebook runs: --input-root, --data-dir, and --model-dir naming the top folder of the training output (the model is in learn/nlp)."""
    import shutil
    root = tmp_path / "input"
    (root / "data" / "annotated").mkdir(parents=True)
    write(root / "data" / "annotated" / "annotated_moves.jsonl.gz", records())
    top = root / "train-output"
    shutil.copytree(model_dir, top / "learn" / "nlp")
    (top / "MeChess").mkdir()
    cmd = [sys.executable, "-m", "chessme", "books-nlp-label", "--input-root", str(root), "--data-dir", str(root / "data"), "--model-dir", str(top),
           "--out", str(tmp_path / "out" / "labelled" / "l.jsonl.gz"), "--log", str(tmp_path / "l.log"), "--sample", "3"]
    done = subprocess.run(cmd, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-800:]
    assert len(read(tmp_path / "out" / "labelled" / "l.jsonl.gz")) > 0
