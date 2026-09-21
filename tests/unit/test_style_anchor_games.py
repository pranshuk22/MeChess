import io
import zipfile

import numpy as np
import pytest

from chessme.style import anchor_games as AG
from chessme.style import embed as E
from chessme.style import gamefeatures as G
from chessme.style import games_fetch as GF
from tests.unit.test_style_embed import NF, players

MOVES = ["1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 8. c3 O-O 9. h3 Nb8 10. d4 Nbd7 1-0",
         "1. d4 d5 2. c4 e6 3. Nc3 Nf6 4. Bg5 Be7 5. e3 O-O 6. Nf3 h6 7. Bh4 b6 8. cxd5 Nxd5 9. Bxe7 Qxe7 10. Nxd5 exd5 1/2-1/2",
         "1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6 6. Be3 e5 7. Nb3 Be6 8. f3 Be7 9. Qd2 O-O 10. O-O-O Nbd7 0-1"]


def pgn(i, white="Tal, Mikhail", black="Other, Player", year=1960):
    return (f'[Event "Tournament {i}"]\n[Site "Moscow"]\n[Date "{year}.03.0{1 + i % 9}"]\n[Round "{i}"]\n[White "{white}"]\n[Black "{black}"]\n'
            f'[Result "*"]\n[WhiteElo "2650"]\n[BlackElo "2600"]\n\n{MOVES[i % 3]}\n\n')


SPEC = {"aliases": ["Tal, Mikhail"], "years": [1957, 1962]}


def archive(tmp_path, n=45, name="tal.zip", **kw):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("tal.pgn", "".join(pgn(i, **kw) for i in range(n)))
    return path


def test_build_player_keeps_only_derived_numbers_and_the_year(tmp_path):
    rec = AG.build_player("tal", SPEC, [archive(tmp_path)], max_games=30)
    assert rec["n"] == 30 and rec["pid"] == "anchor_tal" and rec["rating"] == 2650
    g = rec["games"][0]
    assert g["moves"] == "" and g["clocks"] == [] and g["meta"]["year"] == 1960 and len(g["feat"]) == NF
    assert AG.build_player("tal", SPEC, [archive(tmp_path, n=10, name="few.zip")], max_games=30) is None       # under the minimum


def test_fetch_is_resumable_deletes_archives_and_reports_missing(tmp_path):
    cfg = {"anchors": {"tal": dict(SPEC), "ghost": {"aliases": ["Ghost, A"], "years": [1900, 1910]}}}
    calls = []

    class Resp:
        def __init__(self, ok):
            self.status_code = 200 if ok else 404
            self._b = archive(tmp_path, name="served.zip").read_bytes() if ok else b""

        def iter_content(self, chunk_size):
            yield self._b

    def getter(url, stream=True):
        calls.append(url)
        return Resp("Tal" in url)

    out = tmp_path / "out"
    st = AG.fetch(cfg, out, tmp_path / "raw", getter=getter, pause=0, max_games=30, log=lambda *_: None)
    assert st["done"] == 1 and st["missing"] == ["ghost"]
    assert not (tmp_path / "raw" / "tal.zip").exists()                                # the archive is not kept
    n = len(calls)
    AG.fetch(cfg, out, tmp_path / "raw", getter=getter, pause=0, max_games=30, log=lambda *_: None)
    assert len(calls) == n + 1                                                        # tal is skipped; only the missing one is tried again
    assert GF.load_players(out, min_games=30)["anchor_tal"][0] == 2650


def trained(P, tmp_path):
    E.train(P, tmp_path / "emb", steps=150, batch=16, bag=10, hidden=32, dim=8, ckpt_every=1000, eval_every=1000, log=lambda *_: None)
    return E.load(tmp_path / "emb")


def test_evaluation_finds_planted_signatures_and_is_at_chance_without_them(tmp_path):
    P = players(n=24, games=40, noise=0.3)
    model, norm, _ = trained(P, tmp_path)
    anchors = {k: (v[0], v[1], [{"year": 1900 + 5 * i}] * len(v[1])) for i, (k, v) in enumerate(P.items())}
    res = AG.evaluate(anchors, model, norm)
    assert res["n_anchors"] == 24 and abs(res["chance"] - 1 / 24) < 1e-9
    # the raw path standardises every kept column (noise columns included), so it finds fewer than the embedding does; both are far above chance
    assert res["raw_top1"] > 5 * res["chance"] and res["embedding_top1"] > 5 * res["chance"]
    rng = np.random.default_rng(1)
    flat = {f"a{i}": (0, rng.normal(size=(40, NF)), [{"year": 1950}] * 40) for i in range(24)}
    res0 = AG.evaluate(flat, model, norm)
    assert res0["raw_top1"] < 0.15 and res0["embedding_top1"] < 0.15                  # no signatures: near chance


def test_era_and_cohort_statistics(tmp_path):
    P = players(n=24, games=40)
    model, norm, _ = trained(P, tmp_path)
    anchors = {k: (v[0], v[1], [{"year": 1900 + 5 * i}] * len(v[1])) for i, (k, v) in enumerate(P.items())}
    res = AG.evaluate(anchors, model, norm, cohort=players(n=10, games=40, seed=5))
    assert 0 <= res["nearest_is_contemporary"] <= 1 and 0 < res["contemporary_pair_share"] < 1
    assert set(res["nearest"]) == set(anchors) and -1 <= res["nearest_cohort_similarity"] <= 1
    text = AG.render(res)
    assert "| trained embedding |" in text and "contemporary" in text and "format" in text


def test_embedding_load_matches_training(tmp_path):
    P = players(n=16, games=30)
    model, norm, cfg = trained(P, tmp_path)
    assert cfg["dim"] == 8 and norm.dim > 0
    z = np.random.default_rng(0).normal(size=(5, NF)).astype(np.float32)
    import torch
    with torch.no_grad():
        v = model(torch.from_numpy(norm(z))[None], torch.ones(1, 5))
    assert abs(float(v.norm()) - 1) < 1e-5
