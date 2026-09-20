import gzip
import json

import numpy as np
import pytest
import torch

from chessme.books import nlp as N

CONTEXT = {  # a concept implied by its context, with the keyword itself absent or masked
    "outpost": "the knight sits on d5 where no enemy pawn can ever attack it and so it stays there for good",
    "zugzwang": "every move he makes now only worsens his position and he would gladly pass if the rules allowed it",
    "open_file": "the rook takes the file that has no pawns on it and pressures the back rank at once",
}
FILLER = "white plays carefully here and black answers in the natural way while the game goes on".split()


def synth(n=900, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    keys = list(CONTEXT)
    for i in range(n):
        k = keys[i % len(keys)]
        bad = i % 5 == 0
        text = CONTEXT[k].replace("outpost", "").strip() + " " + " ".join(rng.choice(FILLER, 6))
        if bad:
            text += " what a terrible blunder that was, a complete disaster"
        if k == "zugzwang":
            text = "the position is in " + ("zugzwang" if i % 2 else "a bind") + ". " + text          # keyword present in half of them
        out.append(N._example(text, f"g{i // 3}", "synthetic", judgement=5 if bad else (1 if i % 7 == 0 else -1),
                              evaluation=3 if k == "open_file" and i % 2 else -1))
    return out


def test_masking_removes_every_keyword_but_keeps_the_context():
    t = "The knight on an outpost; a bad bishop and the seventh rank. Zugzwang!"
    m = N.mask_keywords(t)
    assert "outpost" not in m.lower() and "zugzwang" not in m.lower() and "seventh rank" not in m.lower()
    assert m.count("unk") >= 4 and "knight" in m and "bishop" in m or "unk" in m and "knight" in m
    assert N.concept_vector(t)[N.CONCEPTS.index("outpost")] == 1.0


def test_class_mappings_from_glyph_numbers():
    assert N.judgement_class([1]) == N.JUDGEMENT.index("!") and N.judgement_class([4]) == N.JUDGEMENT.index("??") and N.judgement_class([16]) == -1
    assert N.eval_class([10]) == 0 and N.eval_class([14]) == 1 and N.eval_class([19]) == 6 and N.eval_class([13]) == -1 and N.eval_class([1]) == -1


def test_english_filter_and_split_stability():
    assert N.looks_english("White plays the move and it is not a mistake for black")
    assert not N.looks_english("Ein sehr guter Zug, der Springer steht nun stark im Zentrum")
    assert N.split_of("game:1") == N.split_of("game:1")
    parts = [N.split_of(f"g{i}") for i in range(2000)]
    assert 0.7 < parts.count("train") / 2000 < 0.9 and parts.count("test") > 100 and parts.count("val") > 100


def test_build_examples_from_annotated_prose_and_books(tmp_path):
    ann = tmp_path / "a.jsonl.gz"
    rows = [{"source": "gameknot", "game": 1, "comment": "White has a strong outpost on d5 and the bad bishop is passive here.", "nags": [1, 16]},
            {"source": "gameknot", "game": 1, "comment": "", "nags": [2]}, {"source": "gameknot", "game": 2, "comment": "Ja das ist sehr gut", "nags": []},
            {"source": "gameknot", "game": 2, "comment": "White has a strong outpost on d5 and the bad bishop is passive here.", "nags": []}]
    with gzip.open(ann, "wt") as f:
        f.write("\n".join(json.dumps(r) for r in rows))
    (tmp_path / "prose").mkdir()
    with gzip.open(tmp_path / "prose" / "stackexchange.jsonl.gz", "wt") as f:
        f.write(json.dumps({"question": "q", "answers": ["It is the point of the plan that white can win the exchange and it is not simple."]}) + "\n")
    (tmp_path / "books").mkdir()
    (tmp_path / "books" / "b.txt").write_text("A blockade is the way to stop a passed pawn and it is the plan of the side that is behind.\n\nshort")
    ex = N.build_examples(annotated=ann, prose_dir=tmp_path, books_dir=tmp_path / "books")
    by = {e["source"]: e for e in ex}
    assert set(by) == {"gameknot", "stackexchange", "books"} and len(ex) == 3                # duplicate, empty, German and short ones dropped
    g = by["gameknot"]
    assert g["judgement"] == N.JUDGEMENT.index("!") and g["eval"] == 2 and g["concepts"][N.CONCEPTS.index("outpost")] == 1.0
    assert by["stackexchange"]["judgement"] == -1 and by["books"]["concepts"][N.CONCEPTS.index("blockade")] == 1.0


def test_training_learns_from_context_and_beats_the_baselines(tmp_path):
    res = N.train(synth(), tmp_path, backend="bow", epochs=12, batch=32, dim=64, lr=3e-3, log=lambda *_: None)
    m = res["metrics"]["test"]
    assert m["concept_f1_micro"] > m["concept_f1_micro_prior"] + 0.15                        # keywords are masked: this is context
    assert m["judgement_f1_macro"] > 0.5 and m["judgement_acc"] > m["judgement_acc_majority"] - 0.01
    assert (tmp_path / "metrics.json").exists() and res["metrics"]["test_unmasked"]["n"] == m["n"]


def test_stop_at_deadline_then_resume_matches_an_uninterrupted_run(tmp_path):
    ex = synth(300)
    kw = dict(backend="bow", epochs=2, batch=32, dim=32, ckpt_every=3, log=lambda *_: None)
    full = N.train(ex, tmp_path / "full", **kw)
    class StopAfter:
        def __init__(self, n): self.n = n
        def checkpoint(self):
            if self.n <= 0:
                from chessme.jobs import Stopped
                raise Stopped("test")
            self.n -= 1
    first = N.train(ex, tmp_path / "split", ctl=StopAfter(4), **kw)
    assert first["stopped"] and first["step"] == 4
    second = N.train(ex, tmp_path / "split", **kw)
    assert not second["stopped"] and second["step"] == full["step"]
    for a, b in zip(full["model"].parameters(), second["model"].parameters()):
        assert torch.allclose(a.cpu(), b.cpu(), atol=1e-5)


def test_deadline_saves_a_checkpoint_and_reports_stopped(tmp_path):
    res = N.train(synth(300), tmp_path, backend="bow", epochs=5, dim=32, deadline_minutes=1e-9, log=lambda *_: None)
    assert res["stopped"] and res["step"] == 0 and (tmp_path / "ckpt.pt").exists()


def test_dry_run_is_small_writes_nothing_and_still_evaluates(tmp_path):
    res = N.train(synth(), tmp_path / "d", backend="bow", dim=32, lr=3e-3, dry_run=True, log=lambda *_: None)
    assert res["step"] == 40 and res["metrics"]["dry_run"]["learned"] and not (tmp_path / "d" / "ckpt.pt").exists() and not (tmp_path / "d" / "metrics.json").exists()
    assert res["metrics"]["test"]["n"] > 0


def test_resume_refuses_a_different_configuration(tmp_path):
    ex = synth(200)
    N.train(ex, tmp_path, backend="bow", epochs=1, dim=32, log=lambda *_: None)
    with pytest.raises(ValueError, match="different configuration"):
        N.train(ex, tmp_path, backend="bow", epochs=1, dim=48, log=lambda *_: None)


def test_predict_after_load_gives_concepts_judgement_and_evaluation(tmp_path):
    N.train(synth(600), tmp_path, backend="bow", epochs=8, batch=32, dim=64, lr=3e-3, log=lambda *_: None)
    model, cfg = N.load(tmp_path, device="cpu")
    out = N.predict(model, [CONTEXT["outpost"] + " what a terrible blunder that was, a complete disaster", CONTEXT["open_file"]], cfg)
    assert len(out) == 2 and set(out[0]) >= {"concepts", "judgement", "evaluation", "concept_scores"} and out[0]["judgement"] in N.JUDGEMENT


def test_metrics_helpers():
    y, p = np.array([0, 0, 1, 1, 2]), np.array([0, 1, 1, 1, 2])
    assert abs(N.f1_macro(y, p, 3) - np.mean([2 / 3, 0.8, 1.0])) < 1e-9
    Y, P = np.array([[1, 0], [1, 1]], float), np.array([[1, 0], [0, 1]], float)
    micro, macro = N.concept_f1(Y, P)
    assert abs(micro - 2 * 2 / (2 * 2 + 0 + 1)) < 1e-9 and 0 < macro <= 1


def test_a_zero_minute_deadline_still_stops(tmp_path):
    res = N.train(synth(300), tmp_path, backend="bow", epochs=5, dim=32, deadline_minutes=0, log=lambda *_: None)
    assert res["stopped"] and res["step"] == 0


def test_average_precision_and_threshold_tuning():
    y = np.array([1, 0, 1, 0, 0], float)
    assert N.average_precision(y, np.array([0.9, 0.1, 0.8, 0.2, 0.3])) == 1.0
    assert abs(N.average_precision(y, np.array([0.1, 0.9, 0.2, 0.8, 0.7])) - 0.325) < 1e-9      # hits at ranks 4 and 5: (1/4 + 2/5) / 2
    assert np.isnan(N.average_precision(np.zeros(3), np.array([0.1, 0.2, 0.3])))
    Y = np.array([[1, 0], [1, 0], [0, 0], [0, 0]], float)
    S = np.array([[0.30, 0.9], [0.35, 0.8], [0.10, 0.7], [0.05, 0.6]])
    th = N.tune_thresholds(Y, S)
    assert 0.1 <= th[0] < 0.35 and th[1] == 0.5                       # concept 0 needs a low cut-off; concept 1 never occurs


def test_training_reports_average_precision_above_the_base_rate_and_saves_thresholds(tmp_path):
    res = N.train(synth(), tmp_path, backend="bow", epochs=10, batch=32, dim=64, lr=3e-3, log=lambda *_: None)
    t = res["metrics"]["test"]
    assert t["concept_ap_macro"] > 2 * t["concept_ap_baseline"] and abs(t["concept_f1_micro_tuned"] - t["concept_f1_micro"]) < 0.15
    model, cfg = N.load(tmp_path, device="cpu")
    assert len(cfg["thresholds"]) == len(N.CONCEPTS)


def test_dry_run_flags_a_model_that_cannot_learn(tmp_path):
    res = N.train(synth(), tmp_path / "d", backend="bow", dim=32, lr=1e-12, dry_run=True, log=lambda *_: None)     # a learning rate of ~0
    assert res["metrics"]["dry_run"]["learned"] is False


def test_each_epoch_logs_validation_and_warns_when_concepts_are_not_learned(tmp_path):
    logs = []
    N.train(synth(300), tmp_path, backend="bow", epochs=2, batch=64, dim=32, lr=1e-12, log=logs.append)
    assert sum("validation:" in l for l in logs) == 2 and any("WARNING" in l for l in logs)


def test_training_logs_each_heads_loss_and_a_validation_check_every_few_steps(tmp_path):
    logs = []
    N.train(synth(600), tmp_path, backend="bow", epochs=2, batch=32, dim=32, val_every=5, ckpt_every=10 ** 9, log=logs.append)
    step_lines = [l for l in logs if l.startswith("step ")]
    assert step_lines and "concepts " in step_lines[0] and "judgement " in step_lines[0] and "evaluation " in step_lines[0] and "wobble" in step_lines[0]
    assert any("step 5 validation" in l or "step 10 validation" in l for l in logs) and any("epoch 1 validation" in l for l in logs)
