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
    run(monkeypatch, "humanlike-judge", "--testset", testset, "--scores", tmp_path / "s.npz", "--per-regime", 12, "--min-ply", 1, "--workers", 1, "--candidates", 12,
        "--nodes-child", 100, "--nodes-root", 100, "--out", tmp_path / "j12.npz")
    import numpy as np
    assert np.load(tmp_path / "j12.npz")["cand_cp"].shape[1] == 12
    run(monkeypatch, "humanlike-errors", "--testset", testset, "--scores", tmp_path / "s.npz", "--judged", tmp_path / "j12.npz", "--boot", 20, "--out", tmp_path / "e12.md")
    assert "12 most probable moves" in (tmp_path / "e12.md").read_text()
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


def test_selfplay_command_plays_games_with_and_without_a_saved_adapter(tmp_path, monkeypatch, testset):
    import json as _json
    torch.manual_seed(1)
    ck = tmp_path / "n.pt"
    net.save_checkpoint(ck, net.MeNet(TINY))
    run(monkeypatch, "humanlike-score", "--testset", testset, "--scorer", f"ours={ck}", "--out", tmp_path / "s.npz")
    run(monkeypatch, "humanlike-adapter", "--testset", testset, "--scores", tmp_path / "s.npz", "--epochs", 1, "--boot", 20, "--save-dir", tmp_path / "ad", "--out", tmp_path / "a.md")
    saved = sorted(p.name for p in (tmp_path / "ad").glob("*.pt"))
    assert "adapter_all_features_temperature_tail_slot_biases.pt" in saved and all(not n.startswith("wrapper") for n in saved)
    out = tmp_path / "games.jsonl"
    run(monkeypatch, "humanlike-selfplay", "--testset", testset, "--white", f"ours={ck}", "--black", f"ours={ck}", "--white-adapter",
        tmp_path / "ad" / "adapter_all_features_temperature_tail_slot_biases.pt", "--games", 5, "--max-plies", 24, "--min-start-ply", 8, "--max-start-ply", 11, "--min-clock", 10,
        "--out", out)
    recs = [_json.loads(line) for line in out.read_text().splitlines()]
    assert len(recs) == 5 and all(r["result"] in ("1-0", "0-1", "1/2-1/2") and r["plies"] <= 24 for r in recs)
    assert all("adapter" in r["models"]["white"] and "adapter" not in r["models"]["black"] for r in recs)
    run(monkeypatch, "humanlike-selfplay", "--testset", testset, "--white", f"ours={ck}", "--games", 3, "--max-plies", 20, "--min-start-ply", 8, "--max-start-ply", 11,
        "--min-clock", 10, "--out", tmp_path / "g2.jsonl")
    assert len((tmp_path / "g2.jsonl").read_text().splitlines()) == 3


def test_gamestats_command_compares_generated_games_with_the_real_continuations(tmp_path, monkeypatch, capsys):
    import json as _json
    start, moves = "e2e4 e7e5", "g1f3 b8c6 f1b5 a7a6"
    rec = {"gid": "abcd1234@2", "white": 1500, "black": 1450, "base": 180, "inc": 0, "start": start, "moves": moves, "spent": [1.0] * 4, "clock_after": [100.0] * 4,
           "result": "1-0", "termination": "checkmate", "plies": 6}
    (tmp_path / "g.jsonl").write_text(_json.dumps(rec) + "\n")
    real = {"id": "abcd1234", "status": "resign", "winner": "white", "moves": "e4 e5 Nf3 Nc6 Bb5", "clocks": [18000, 18000, 17900, 17850, 17700, 17000],
            "clock": {"initial": 180, "increment": 0}, "players": {"white": {"rating": 1500}, "black": {"rating": 1450}}}
    (tmp_path / "real.ndjson").write_text(_json.dumps(real) + "\n")
    run(monkeypatch, "humanlike-gamestats", "--games", f"model={tmp_path / 'g.jsonl'}", "--real", tmp_path / "real.ndjson", "--out", tmp_path / "s.md")
    text = (tmp_path / "s.md").read_text()
    assert "matched stretches" in text and "whole games" in text and "| statistic | real | model |" in text
    assert "1 starting positions with the real continuation" in text
    run(monkeypatch, "humanlike-gamestats", "--games", f"model={tmp_path / 'g.jsonl'}")
    assert "| statistic | model |" in capsys.readouterr().out


def fake_export(testset_path):
    """Lichess-export-like games built from the test set itself: every game of the set, in full (history plus the played move)."""
    import chess
    from chessme.humanlike import testset as T
    longest = {}
    for p in T.iter_testset(testset_path):
        if p.gid not in longest or p.ply > longest[p.gid].ply:
            longest[p.gid] = p
    games = []
    for gid, p in longest.items():
        board, sans = chess.Board(), []
        for u in (p.moves.split() + [p.played]):
            sans.append(board.san(chess.Move.from_uci(u)))
            board.push_uci(u)
        games.append({"id": gid, "status": "resign", "winner": "white", "moves": " ".join(sans), "clocks": [18000 - 100 * i for i in range(len(sans) + 1)],
                      "clock": {"initial": p.base, "increment": p.inc}, "players": {"white": {"rating": p.me}, "black": {"rating": p.opp}}})
    return games


def test_humangames_command_writes_real_continuations_and_selfplay_can_start_from_them(tmp_path, monkeypatch, testset):
    import json as _json
    from chessme.humanlike import lichess_games as LG
    requested = []

    def fake_fetch(ids, **kw):
        requested.append(list(ids))
        wanted = set(ids)
        return (g for g in fake_export(testset) if g["id"] in wanted)
    monkeypatch.setattr(LG, "fetch_games", fake_fetch)
    out = tmp_path / "human.jsonl"
    run(monkeypatch, "humanlike-humangames", "--testset", testset, "--split", "all", "--games", 12, "--min-start-ply", 8, "--max-start-ply", 11, "--min-clock", 10, "--out", out)
    recs = [_json.loads(line) for line in out.read_text().splitlines()]
    manifest = _json.loads((tmp_path / "human.jsonl.manifest.json").read_text())
    assert 0 < len(recs) <= 12 and manifest["games"] == len(recs) and len(set(r["gid"].split("@")[0] for r in recs)) == len(recs)
    assert all(r["models"] == {"white": "human", "black": "human"} and r["moves"] for r in recs) and len(requested) == 1 and len(requested[0]) == 12
    # the same starts, played by a model
    torch.manual_seed(1)
    ck = tmp_path / "n.pt"
    net.save_checkpoint(ck, net.MeNet(TINY))
    run(monkeypatch, "humanlike-selfplay", "--testset", testset, "--white", f"ours={ck}", "--starts-from", out, "--games", 100, "--max-plies", 20, "--min-start-ply", 8,
        "--max-start-ply", 11, "--min-clock", 10, "--out", tmp_path / "gen.jsonl")
    gen = [_json.loads(line) for line in (tmp_path / "gen.jsonl").read_text().splitlines()]
    assert [g["gid"] for g in gen] == [r["gid"] for r in recs] and [g["start"] for g in gen] == [r["start"] for r in recs]


def test_humangames_drops_games_that_were_not_returned_or_whose_history_differs(tmp_path, monkeypatch, testset):
    import json as _json
    from chessme.humanlike import lichess_games as LG

    def fake_fetch(ids, **kw):
        games = [g for g in fake_export(testset) if g["id"] in set(ids)]
        import chess
        board, sans = chess.Board(), []
        for _ in games[1]["moves"].split():                                                 # a different (legal) game under the same id
            m = sorted(board.legal_moves, key=lambda x: x.uci())[1]
            sans.append(board.san(m))
            board.push(m)
        games[1]["moves"] = " ".join(sans)
        return iter(games[1:])                                                               # and the first is missing
    monkeypatch.setattr(LG, "fetch_games", fake_fetch)
    out = tmp_path / "human.jsonl"
    run(monkeypatch, "humanlike-humangames", "--testset", testset, "--split", "all", "--games", 6, "--min-start-ply", 8, "--max-start-ply", 11, "--min-clock", 10, "--out", out)
    manifest = _json.loads((tmp_path / "human.jsonl.manifest.json").read_text())
    assert manifest["dropped"]["not returned"] == 1 and manifest["dropped"]["history differs"] == 1 and manifest["games"] == manifest["chosen"] - 2
