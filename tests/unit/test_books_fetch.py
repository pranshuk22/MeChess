import json

from chessme.books import fetch as F

TEXT = ("x" * 6000) + "\n\nAn outpost helps: 1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 shows it.\n"


def test_sources_are_wellformed_and_public_domain_only():
    books = F.load_sources()
    assert len({b["id"] for b in books}) == len(books) >= 10
    assert all(b.get("gutenberg") or b.get("archive") for b in books) and all(b["year"] is None or b["year"] <= 1925 for b in books)
    assert all(F.urls(b) for b in books)


def test_get_retries_transient_errors_and_rejects_error_pages():
    calls = []

    def opener(u):
        calls.append(u)
        if len(calls) == 1:
            raise OSError("boom")
        if len(calls) == 2:
            return "<html><head><title>500 Internal Server Error</title>" + "x" * 6000
        return TEXT
    assert F.get("u", opener=opener, sleep=lambda s: None) == TEXT and len(calls) == 3
    assert F.get("u", tries=2, opener=lambda u: "short", sleep=lambda s: None) is None


def test_run_downloads_analyses_skips_finished_and_reports_failures(tmp_path):
    books = [{"id": "a", "author": "A", "title": "T", "notation": "algebraic", "archive": "aa"},
             {"id": "b", "author": "B", "title": "U", "notation": "algebraic", "archive": "bb"}]
    seen = []

    def opener(u):
        seen.append(u)
        if "bb" in u:
            raise OSError("down")
        return TEXT
    res = F.run(tmp_path, books, opener=opener, sleep=lambda s: None, log=lambda *_: None)
    assert res == {"done": ["a"], "failed": ["b"]}
    data = json.loads((tmp_path / "a.json").read_text())
    assert data["notation"]["algebraic"] == 1 and data["concepts"]["outpost"] == 1 and (tmp_path / "a.txt").exists()
    n = len(seen)
    assert F.run(tmp_path, books[:1], opener=opener, sleep=lambda s: None, log=lambda *_: None)["done"] == ["a"] and len(seen) == n   # not fetched again
