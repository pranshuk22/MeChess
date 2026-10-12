"""The three humanlike commands, end to end: a synthetic multi-frame dump -> test set -> two tiny networks scored -> report."""
import json
import shutil
import sys

import pytest
import torch

from chessme import cli
from chessme.model import net
from tests.unit.test_explorer_rangescan import make_dump
from tests.unit.test_humanlike_testset import make_game
from tests.unit.test_model_train import TINY


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["chessme", *map(str, argv)])
    cli.main()


@pytest.fixture()
def testset(tmp_path, monkeypatch):
    games = [str(make_game(site=f"win{i:05d}", clocks=[170 - 3 * (j // 2) for j in range(12)])) + "\n\n" for i in range(60)]
    buf, _ = make_dump(["".join(games[i:i + 10]) for i in range(0, 60, 10)])
    dump = tmp_path / "month.pgn.zst"
    dump.write_bytes(buf)
    out = tmp_path / "ts.jsonl.gz"
    run(monkeypatch, "humanlike-testset", "--source", dump, "--parts", 6, "--windows", "0,1,2,3,4,5", "--per-game", 3, "--out", out)
    return out


def test_testset_command_writes_the_set_and_its_manifest(testset):
    manifest = json.loads((testset.parent / (testset.name + ".manifest.json")).read_text())
    assert manifest["positions"] > 50 and manifest["windows"] == [0, 1, 2, 3, 4, 5] and len(manifest["sha256"]) == 64
    assert manifest["time_class"] == "blitz" and manifest["source"] == "month.pgn.zst"


def test_score_and_report_commands(tmp_path, monkeypatch, testset, capsys):
    ckpts = []
    for seed in (1, 2):
        torch.manual_seed(seed)
        path = tmp_path / f"net{seed}.pt"
        net.save_checkpoint(path, net.MeNet(TINY))
        ckpts.append(path)
    for i, ck in enumerate(ckpts):
        run(monkeypatch, "humanlike-score", "--testset", testset, "--scorer", f"ours={ck}", "--limit", 40, "--seed", 5, "--out", tmp_path / f"s{i}.npz")
    out = tmp_path / "report.md"
    run(monkeypatch, "humanlike-report", "--testset", testset, "--scores", tmp_path / "s0.npz", tmp_path / "s1.npz", "--boot", 50, "--out", out)
    text = out.read_text()
    assert "| full |" in text and "| comparable |" in text and "minus" in text and "by rating" in text and "by the mover's clock" in text
    assert text.count("## ") >= 3 and "sampled match" in text


def test_report_refuses_scores_from_different_subsets_and_other_test_sets(tmp_path, monkeypatch, testset):
    torch.manual_seed(1)
    ck = tmp_path / "n.pt"
    net.save_checkpoint(ck, net.MeNet(TINY))
    run(monkeypatch, "humanlike-score", "--testset", testset, "--scorer", f"ours={ck}", "--limit", 30, "--seed", 1, "--out", tmp_path / "a.npz")
    run(monkeypatch, "humanlike-score", "--testset", testset, "--scorer", f"ours={ck}", "--limit", 30, "--seed", 2, "--out", tmp_path / "b.npz")
    with pytest.raises(SystemExit, match="different positions"):
        run(monkeypatch, "humanlike-report", "--testset", testset, "--scores", tmp_path / "a.npz", tmp_path / "b.npz", "--out", tmp_path / "r.md")
    other = tmp_path / "other.jsonl.gz"
    from chessme.humanlike import testset as T
    T.write_testset(other, T.read_testset(testset)[:-1])
    with pytest.raises(SystemExit, match="another test set"):
        run(monkeypatch, "humanlike-report", "--testset", other, "--scores", tmp_path / "a.npz", "--out", tmp_path / "r.md")


def test_unknown_scorer_is_reported(tmp_path, monkeypatch, testset):
    with pytest.raises(SystemExit, match="unknown scorer"):
        run(monkeypatch, "humanlike-score", "--testset", testset, "--scorer", "gpt=4", "--out", tmp_path / "x.npz")


@pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish")
def test_judge_and_errors_commands(tmp_path, monkeypatch, testset):
    torch.manual_seed(1)
    ck = tmp_path / "n.pt"
    net.save_checkpoint(ck, net.MeNet(TINY))
    run(monkeypatch, "humanlike-score", "--testset", testset, "--scorer", f"ours={ck}", "--limit", 40, "--seed", 1, "--out", tmp_path / "s.npz")
    run(monkeypatch, "humanlike-judge", "--testset", testset, "--scores", tmp_path / "s.npz", "--per-regime", 12, "--min-ply", 1, "--workers", 1,
        "--nodes-child", 200, "--nodes-root", 400, "--out", tmp_path / "j.npz")
    out = tmp_path / "errors.md"
    run(monkeypatch, "humanlike-errors", "--testset", testset, "--scores", tmp_path / "s.npz", "--judged", tmp_path / "j.npz", "--boot", 30, "--out", out)
    text = out.read_text()
    assert "positive control: sharpened" in text and "mean loss" in text and "clock 30s+" in text and "blunder" in text
    ad = tmp_path / "adapter_j.md"
    run(monkeypatch, "humanlike-adapter", "--testset", testset, "--scores", tmp_path / "s.npz", "--judged", tmp_path / "j.npz", "--epochs", 1, "--boot", 20, "--out", ad)
    assert "Sampled-play errors of the adapted models" in ad.read_text() and "Mass outside the 8 judged candidates" in ad.read_text()
    run(monkeypatch, "humanlike-judge", "--testset", testset, "--scores", tmp_path / "s.npz", "--per-regime", 12, "--min-ply", 1, "--workers", 1, "--split", "trainval",
        "--nodes-child", 200, "--nodes-root", 400, "--out", tmp_path / "jt.npz")
    run(monkeypatch, "humanlike-adapter", "--testset", testset, "--scores", tmp_path / "s.npz", "--judged", tmp_path / "j.npz", "--judged-train", tmp_path / "jt.npz",
        "--lambdas", "2", "--epochs", 1, "--boot", 20, "--out", ad)
    assert "behaviour-matched adapter (lambda=2)" in ad.read_text()
    run(monkeypatch, "humanlike-score", "--testset", testset, "--scorer", f"ours={ck}", "--limit", 40, "--seed", 2, "--out", tmp_path / "other.npz")
    with pytest.raises(SystemExit, match="another test set or model|do not match"):
        run(monkeypatch, "humanlike-errors", "--testset", testset, "--scores", tmp_path / "other.npz", "--judged", tmp_path / "j.npz", "--out", out)


def test_adapter_command_trains_and_compares_variants(tmp_path, monkeypatch, testset):
    torch.manual_seed(1)
    ck = tmp_path / "n.pt"
    net.save_checkpoint(ck, net.MeNet(TINY))
    run(monkeypatch, "humanlike-score", "--testset", testset, "--scorer", f"ours={ck}", "--out", tmp_path / "s.npz")
    out = tmp_path / "adapter.md"
    run(monkeypatch, "humanlike-adapter", "--testset", testset, "--scores", tmp_path / "s.npz", "--eval-testset", testset, "--eval-scores", tmp_path / "s.npz",
        "--epochs", 2, "--boot", 30, "--out", out)
    text = out.read_text()
    for name in ("frozen model", "wrapper: one temperature", "wrapper: temperature by clock regime and rating", "adapter: all features", "Independent check"):
        assert name in text
    assert "minus frozen model (paired)" in text


@pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish")
def test_judge_command_can_be_restricted_to_a_game_split(tmp_path, monkeypatch, testset):
    import numpy as np
    from chessme.humanlike import adapter as A
    from chessme.humanlike import score as S
    from chessme.humanlike import testset as T
    torch.manual_seed(1)
    ck = tmp_path / "n.pt"
    net.save_checkpoint(ck, net.MeNet(TINY))
    run(monkeypatch, "humanlike-score", "--testset", testset, "--scorer", f"ours={ck}", "--out", tmp_path / "s.npz")
    scores, _ = S.load_scores(tmp_path / "s.npz")
    gids = np.array([p.gid for p in T.read_testset(testset, scores["index"])])
    train, _, test = A.game_split(gids)
    assert train.any() and test.any()
    for split, expected in (("train", train), ("test", test)):
        run(monkeypatch, "humanlike-judge", "--testset", testset, "--scores", tmp_path / "s.npz", "--per-regime", 1000, "--min-ply", 1, "--workers", 1,
            "--nodes-child", 100, "--nodes-root", 100, "--split", split, "--out", tmp_path / f"j_{split}.npz")
        rows = np.load(tmp_path / f"j_{split}.npz")["rows"]
        assert len(rows) > 0 and expected[rows].all()                            # every judged position is from a game of that split
