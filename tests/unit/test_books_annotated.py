import gzip
import io
import json
import tarfile

import chess.pgn

from chessme.books import annotated as A

GK = """[Event "x"]
[White "a"]
[Black "b"]
[Result "*"]

1. e4 e5 2. Nf3 {The classical way, a fight for the centre.} Nc6 3. Bb5 $1 {A good move.} 3... a6 $6 4. Ba4 *

"""
STUDY = """[Event "study"]
[Annotator "https://lichess.org/@/someone"]
[Result "*"]

{ Intro to the study. } 1. d4 d5 2. c4 $2 { Not the point: the outpost matters. } *

"""


def make_archive(tmp_path):
    p = tmp_path / "a.tar.gz"
    with tarfile.open(p, "w:gz") as t:
        for name, text in (("gameknot/game_1.pgn", GK), ("lichess_studies/s.pgn", STUDY + STUDY), ("other/x.pgn", GK), ("gameknot/readme.txt", "x")):
            data = text.encode()
            info = tarfile.TarInfo("./" + name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return p


def test_annotated_moves_keep_only_commented_or_glyphed_moves_with_the_position_before():
    game = chess.pgn.read_game(io.StringIO(GK))
    moves = A.annotated_moves(game)
    assert [(m["ply"], m["san"], m["glyph"]) for m in moves] == [(3, "Nf3", None), (5, "Bb5", "!"), (6, "a6", "?!")]
    assert moves[0]["fen"].startswith("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w") and moves[0]["uci"] == "g1f3"
    assert moves[0]["color"] == "white" and moves[2]["color"] == "black"
    assert "centre" in moves[0]["concepts"] and moves[1]["comment"] == "A good move."


def test_game_comment_before_the_first_move_is_ply_zero_and_glyphs_are_mapped():
    moves = A.annotated_moves(chess.pgn.read_game(io.StringIO(STUDY)))
    assert moves[0]["ply"] == 0 and moves[0]["comment"] == "Intro to the study." and moves[0]["san"] is None
    assert (moves[1]["san"], moves[1]["glyph"]) == ("c4", "?") and "outpost" in moves[1]["concepts"]


def test_iter_games_reads_selected_sources_and_respects_the_limit(tmp_path):
    p = make_archive(tmp_path)
    got = [s for s, _ in A.iter_games(p, sources=("gameknot", "lichess_studies"))]
    assert got == ["gameknot", "lichess_studies", "lichess_studies"]          # "other" is not a wanted source, readme is not a pgn
    assert [s for s, _ in A.iter_games(p, sources=("lichess_studies",), limit_per_source=1)] == ["lichess_studies"]


def test_extract_writes_records_and_statistics_without_annotator_names(tmp_path):
    p = make_archive(tmp_path)
    stats = A.extract(p, tmp_path / "out", log=lambda *_: None)
    assert stats["games"] == {"gameknot": 1, "lichess_studies": 2}
    assert stats["glyphs"] == {"!": 1, "?!": 1, "?": 2} and stats["with_glyph"] == 4
    assert stats["concepts"]["outpost"] == 2
    raw = gzip.open(tmp_path / "out" / "annotated_moves.jsonl.gz", "rt").read()
    assert "someone" not in raw and "lichess.org/@" not in raw
    rows = [json.loads(l) for l in raw.splitlines()]
    assert {r["source"] for r in rows} == {"gameknot", "lichess_studies"} and all("fen" in r for r in rows)


def test_broken_game_record_stops_that_game_but_not_the_run():
    bad = chess.pgn.read_game(io.StringIO('[Result "*"]\n\n1. e4 e5 2. Ke3 {x} *\n'))
    assert isinstance(A.annotated_moves(bad), list)


def test_download_keeps_an_existing_archive_and_writes_atomically(tmp_path):
    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass
    calls = []
    def opener(u):
        calls.append(u)
        return R(b"x" * 1_500_000)
    p = A.download(tmp_path, opener=opener)
    assert p.stat().st_size == 1_500_000 and not list(tmp_path.glob("*.part")) and len(calls) == 1
    A.download(tmp_path, opener=opener)
    assert len(calls) == 1
