import io
import json
import tarfile
import urllib.error

import numpy as np

from chessme.books import learn as L
from chessme.books import pdf as P
from chessme.books import studies as S
from chessme.books import text as T
from chessme.books import topics as TP
from tests.unit.test_books_annotated import GK, STUDY, make_archive

BOOK = ("x" * 6000) + "\n\nAn outpost helps a lot.\n\n1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 shows the centre.\n\nA blockade can win.\n"


# ---- studies --------------------------------------------------------------------------------------------------------

def test_studies_export_skips_done_waits_on_429_and_stores_no_usernames(tmp_path):
    calls, waits = [], []

    def opener(url):
        calls.append(url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(url, 429, "slow", None, None)
        if "nobody" in url:
            raise urllib.error.HTTPError(url, 404, "no", None, None)
        return STUDY.encode()
    stats = S.run(tmp_path, users=["alice", "nobody"], study_ids=["abcd1234"], sleep=waits.append, opener=opener, log=lambda *_: None)
    assert stats == {"done": 2, "empty": 1, "failed": 0} and 60 in waits            # waited a full minute after the 429
    names = [p.name for p in tmp_path.glob("*.pgn")]
    assert len(names) == 2 and not any("alice" in n for n in names)
    n = len(calls)
    S.run(tmp_path, users=["alice"], sleep=lambda s: None, opener=opener, log=lambda *_: None)
    assert len(calls) == n                                                          # finished export is not fetched again


def test_studies_failed_request_is_reported_and_retried_later(tmp_path):
    def opener(url):
        raise OSError("down")
    assert S.run(tmp_path, users=["u"], sleep=lambda s: None, opener=opener, log=lambda *_: None)["failed"] == 1
    assert not list(tmp_path.glob("*.pgn"))


# ---- pdf ------------------------------------------------------------------------------------------------------------

class FakePage:
    def __init__(self, t): self.t = t
    def extract_text(self): return self.t


def fake_reader(pages_by_name):
    class R:
        def __init__(self, path): self.pages = [FakePage(t) for t in pages_by_name[path.rsplit("/", 1)[-1]]]
    return R


def test_pdf_with_text_layer_is_read_and_a_scan_is_reported(tmp_path):
    (tmp_path / "in").mkdir()
    for n in ("book.pdf", "scan.pdf"):
        (tmp_path / "in" / n).write_bytes(b"%PDF")
    reader = fake_reader({"book.pdf": [("word " * 80) + " 1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 " + ("word " * 80)] * 2, "scan.pdf": ["", ""]})
    stats = P.run(tmp_path / "in", tmp_path / "out", reader=reader, log=lambda *_: None)
    assert stats == {"read": ["book.pdf"], "needs_ocr": ["scan.pdf"]}
    d = json.loads((tmp_path / "out" / "book.json").read_text())
    assert d["pages"] == 2 and d["notation"]["algebraic"] >= 1 and (tmp_path / "out" / "book.txt").exists()


# ---- topics ---------------------------------------------------------------------------------------------------------

def test_kmeans_separates_two_blobs_and_topics_name_their_words():
    rng = np.random.default_rng(0)
    X = np.vstack([rng.normal(0, 0.05, (30, 4)) + [1, 0, 0, 0], rng.normal(0, 0.05, (30, 4)) + [0, 1, 0, 0]])
    lab = TP.kmeans(X, 2)
    assert len(set(lab[:30])) == 1 and len(set(lab[30:])) == 1 and lab[0] != lab[30]
    paras = ["rook file seventh rank invasion rook file"] * 30 + ["pawn chain blockade passed pawn chain pawn"] * 30
    words = TP.top_words(paras, lab)
    assert "rook" in words[int(lab[0])] and "pawn" in words[int(lab[30])]


def test_cluster_uses_the_injected_embedder():
    paras = ["rook file seventh rank"] * 12 + ["pawn chain blockade pawn"] * 12
    emb = lambda ts: np.array([[1.0, 0.0] if "rook" in t else [0.0, 1.0] for t in ts])
    res = TP.cluster(paras, k=2, embed=emb)
    assert sorted(r["size"] for r in res) == [12, 12]


# ---- pairs and the whole flow ---------------------------------------------------------------------------------------

def test_concept_line_pairs_use_a_window_of_neighbouring_paragraphs():
    pairs = T.concept_line_pairs(T.paragraphs(BOOK.split("\n\n", 1)[1] if False else BOOK), window=1, book="b")
    assert len(pairs) == 1 and {"outpost", "centre", "blockade"} <= set(pairs[0]["concepts"]) and pairs[0]["notation"] == "algebraic"
    assert T.concept_line_pairs(T.paragraphs(BOOK), window=0, book="b")[0]["concepts"].keys() == {"centre"}


def test_learn_runs_all_steps_reports_and_resumes(tmp_path):
    archive = make_archive(tmp_path)
    books = [{"id": "bk", "author": "A", "title": "T", "notation": "algebraic", "archive": "bk"}]
    import chessme.books.fetch as F
    real = F.load_sources
    F.load_sources = lambda path=F.SOURCES: books
    try:
        opener = lambda u: BOOK
        logs = []
        res = L.run(tmp_path / "out", archive=archive, opener=opener, control_dir=str(tmp_path / "ctl"), log=logs.append)
        assert res == {"steps": ["books", "pairs", "annotated", "report"], "stopped": False}
        report = (tmp_path / "out" / "report.md").read_text()
        assert "| bk |" in report and "gameknot" in report and "Human move glyphs found" in report and "`!`" in report
        assert (tmp_path / "out" / "concept_line_pairs.jsonl").exists()
        before = (tmp_path / "out" / "annotated" / "stats.json").stat().st_mtime_ns
        L.run(tmp_path / "out", archive=archive, opener=lambda u: (_ for _ in ()).throw(AssertionError("refetched")),
              control_dir=str(tmp_path / "ctl"), log=lambda *_: None)
        assert (tmp_path / "out" / "annotated" / "stats.json").stat().st_mtime_ns == before          # nothing was redone
    finally:
        F.load_sources = real


def test_learn_stops_cleanly_when_asked(tmp_path):
    (tmp_path / "ctl").mkdir()
    (tmp_path / "ctl" / "books.stop").write_text("")
    res = L.run(tmp_path / "out", steps=("annotated",), archive=make_archive(tmp_path), control_dir=str(tmp_path / "ctl"), log=lambda *_: None)
    assert res == {"steps": [], "stopped": True}
