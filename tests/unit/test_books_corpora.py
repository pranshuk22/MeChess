import gzip
import json

from chessme.books import corpora as C

QA = ("Q: What are the consequences of an early a6 in the Sicilian? I saw it.\n[FEN \"\"]\n\n1. e4 c5 2. Nf3 a6\n\nWhat is the point?\n\n"
      "A: The point of ...a6 is to control the square b5, a good outpost for the knight.\n[FEN \"\"]\n1.e4 c5\n\n\n"
      "A: This is called the O'Kelly variation. ♘f3 develops.")
PGN = '[Event "s"]\n[Site "https://lichess.org/study/abcd1234/x"]\n[Result "*"]\n\n1. e4 { The centre. } e5 $1 2. Nf3 *\n\n'


def write_jsonl(path, recs):
    path.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return [path]


def test_parse_qa_splits_question_answers_and_keeps_fens():
    qa = C.parse_qa(QA.replace('[FEN ""]', '[FEN "8/8/8/8/8/8/8/K1k5 w - - 0 1"]', 1))
    assert qa["question"].startswith("What are the consequences") and len(qa["answers"]) == 2
    assert qa["fens"] == ["8/8/8/8/8/8/8/K1k5 w - - 0 1"] and "[FEN" not in qa["question"]
    assert "Nf3 develops" in qa["answers"][1]                       # figurines become letters
    assert C.parse_qa("not a thread") is None


def test_iter_annotated_pgn_reads_jsonl_text_and_skips_broken_lines(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text(json.dumps({"text": PGN}) + "\nnot json\n" + json.dumps({"text": PGN}) + "\n")
    games = list(C.iter_annotated_pgn([p]))
    assert len(games) == 2 and games[0][0] == "chessgpt_annotated" and len(list(C.iter_annotated_pgn([p], limit=1))) == 1


def test_write_prose_counts_and_attributes(tmp_path):
    se = write_jsonl(tmp_path / "se.jsonl", [{"text": QA}, {"text": "junk"}, {"text": "Q: only a question"}])
    wiki = write_jsonl(tmp_path / "w.jsonl", [
        {"metadata": {"title": "Outpost (chess)", "url": "https://en.wikipedia.org/wiki/Outpost_(chess)"}, "text": "An outpost is a square in chess " * 20},
        {"metadata": {"title": "Paris", "url": "u"}, "text": "A city in France. " * 30}])
    stats = C.write_prose(tmp_path / "out", se, wiki)
    assert stats["stackexchange"]["threads"] == 1 and stats["stackexchange"]["answers"] == 2 and stats["stackexchange"]["concepts"]["outpost"] == 1
    assert stats["wikipedia"]["articles"] == 1                                         # the article without chess is dropped
    rows = [json.loads(l) for l in gzip.open(tmp_path / "out" / "prose" / "stackexchange.jsonl.gz", "rt")]
    assert rows[0]["question"] and len(rows[0]["answers"]) == 2
    attribution = (tmp_path / "out" / "prose" / "wikipedia_attribution.tsv").read_text()
    assert "Outpost (chess)" in attribution and "CC BY-SA" in attribution and "Paris" not in attribution


def test_download_is_skipped_when_present_and_atomic(tmp_path):
    import io
    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass
    calls = []
    def opener(u):
        calls.append(u)
        return R(b"x" * 1_200_000)
    paths = C.download("stackexchange", tmp_path, opener=opener)
    assert paths[0].stat().st_size == 1_200_000 and not list(tmp_path.glob("*.part")) and len(calls) == 1
    C.download("stackexchange", tmp_path, opener=opener)
    assert len(calls) == 1
