import io
import json
import zipfile

import chess
import pytest

from chessme.style import anchor_sources as AS
from chessme.style import anchors as A
from tests.unit.test_style_anchors import MOVES

TAL = {"aliases": ["Tal, Mikhail", "Tal, M"], "years": [1957, 1962], "selected": True, "hypothesis": "attack"}


def game(white="Tal, Mikhail", black="X, Y", date="1960.05.05", event="Candidates", site="Bled"):
    return (f'[Event "{event}"]\n[Site "{site}"]\n[Date "{date}"]\n[White "{white}"]\n[Black "{black}"]\n[Result "1-0"]\n'
            f'[WhiteElo "2700"]\n\n{MOVES}\n\n')


def archive(games):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Tal.pgn", "".join(games))
    return buf.getvalue()


class Resp:
    def __init__(self, data=b"", status=200):
        self.content, self.status_code = data, status

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]


def getter(files):
    calls = []

    def g(url, **kw):
        calls.append(url)
        name = url.rsplit("/", 1)[1]
        return Resp(files[name]) if name in files else Resp(status=404)
    g.calls = calls
    return g


class TestFilterStats:
    def test_reasons_for_dropping_games_are_counted(self):
        texts = [game(), game(event="Blitz Championship"), game(date="1990.01.01"), game(date="????.??.??"),
                 game(white="A, B"), game(site="chess.com")]
        st = {}
        kept = A.anchor_games(texts, TAL["aliases"], min_year=1957, max_year=1962, stats=st)
        assert len(kept) == 1
        assert st == {"seen": 6, "anchor_games": 5, "not_serious": 2, "variant": 0, "no_date": 1, "outside_window": 1, "kept": 1}

    def test_time_control_below_fifteen_minutes_is_not_classical(self):
        fast = game().replace("[Result", '[TimeControl "300+3"]\n[Result')
        slow = game().replace("[Result", '[TimeControl "5400+30"]\n[Result')
        assert len(A.anchor_games([fast, slow], TAL["aliases"])) == 1


class TestPeakWindow:
    def test_window_is_widened_when_too_few_games_and_the_widening_is_recorded(self, tmp_path):
        texts = [game(date="1960.01.01")] * 3 + [game(date="1964.01.01")] * 10
        att = []
        d = tmp_path / "tal.pgn"
        d.write_text("".join(texts))
        games, window, _ = A.games_in_peak([d], TAL, want=8, attempts=att)
        assert len(games) == 13 and window == (1955, 1964)
        assert [a[0] for a in att] == [[1957, 1962], [1955, 1964]] and [a[1] for a in att] == [3, 13]

    def test_no_widening_when_enough_games(self, tmp_path):
        f = tmp_path / "tal.pgn"
        f.write_text("".join([game(date="1960.01.01")] * 12))
        att = []
        games, window, _ = A.games_in_peak([f], TAL, want=10, attempts=att)
        assert len(games) == 12 and window == (1957, 1962) and len(att) == 1


class TestFetch:
    def cfg(self):
        return {"anchors": {"tal": TAL, "dubov": {"aliases": ["Dubov, Daniil"], "years": [2018, 2022], "selected": True}}}

    def test_download_sample_delete_and_log(self, tmp_path):
        g = getter({"Tal.zip": archive([game(date=f"196{i % 3}.01.01") for i in range(12)] + [game(event="Simul")])})
        logs = []
        idx = AS.fetch_anchors(self.cfg(), tmp_path / "out", tmp_path / "raw", max_games=10, per_game=3, pause=0,
                               getter=g, log=logs.append)
        text = "\n".join(logs)
        assert list(idx) == ["anchor_tal"] and idx["anchor_tal"]["games_used"] == 10 and idx["anchor_tal"]["decisions"] == 30
        assert not list((tmp_path / "raw").glob("*")), "raw archive must be deleted"
        assert g.calls == ["https://www.pgnmentor.com/players/Tal.zip", "https://www.pgnmentor.com/players/Dubov.zip"]
        for needle in ("downloading", "downloaded", "raw archive deleted", "1 not classical", "used 10 of the 10", "SUMMARY",
                       "dubov", "MISSING", "1 of 2 anchors have data", "years [", "as White"):
            assert needle in text, needle
        src = json.loads((tmp_path / "out" / "sources.json").read_text())
        assert src["tal"]["status"] == "ok" and src["dubov"]["source"] is None

    def test_rerun_skips_finished_anchors_without_downloading(self, tmp_path):
        files = {"Tal.zip": archive([game() for _ in range(6)])}
        kw = dict(max_games=5, per_game=2, pause=0, log=lambda *_: None)
        AS.fetch_anchors(self.cfg(), tmp_path / "o", tmp_path / "r", getter=getter(files), **kw)
        g2 = getter(files)
        logs = []
        AS.fetch_anchors(self.cfg(), tmp_path / "o", tmp_path / "r", getter=g2, **dict(kw, log=logs.append))
        assert g2.calls == ["https://www.pgnmentor.com/players/Dubov.zip"] and any("already done" in l for l in logs)

    def test_a_local_file_is_used_instead_of_a_download(self, tmp_path):
        files_dir = tmp_path / "mine"
        files_dir.mkdir()
        (files_dir / "dubov.pgn").write_text("".join(game("Dubov, Daniil", "Q, R", "2020.01.01") for _ in range(6)))
        g = getter({})
        idx = AS.fetch_anchors({"anchors": {"dubov": self.cfg()["anchors"]["dubov"]}}, tmp_path / "o", tmp_path / "r",
                               files_dir=files_dir, max_games=5, per_game=2, pause=0, getter=g, log=lambda *_: None)
        assert idx["anchor_dubov"]["games_used"] == 5 and g.calls == []

    def test_oversized_and_failed_downloads_are_reported_not_fatal(self, tmp_path):
        assert AS.download("u", tmp_path / "a.zip", getter=lambda *a, **k: Resp(b"x" * 100), max_bytes=10) is None
        assert not (tmp_path / "a.zip").exists()
        def boom(*a, **k):
            raise SystemExit("gave up")
        assert AS.download("u", tmp_path / "b.zip", getter=boom) is None

    def test_file_stem_follows_the_surname_naming(self):
        assert AS.file_stem({"aliases": ["Nepomniachtchi, Ian"]}) == "Nepomniachtchi"
        assert AS.file_stem({"aliases": ["Ding, Liren", "Ding Liren"]}) == "Ding"

    def test_only_restricts_the_anchors(self, tmp_path):
        g = getter({"Tal.zip": archive([game() for _ in range(6)])})
        AS.fetch_anchors(self.cfg(), tmp_path / "o", tmp_path / "r", only={"tal"}, max_games=5, per_game=2, pause=0,
                         getter=g, log=lambda *_: None)
        assert g.calls == ["https://www.pgnmentor.com/players/Tal.zip"]

    def test_shipped_peak_windows_are_present_and_sane(self):
        import yaml
        cfg = yaml.safe_load(open("configs/anchors.yaml"))["anchors"]
        assert all(v["years"][0] < v["years"][1] for v in cfg.values())
        assert cfg["giri"]["years"][0] >= 2010 and cfg["capablanca"]["years"][1] <= 1930


class TestNameCensus:
    def test_census_flags_a_frequent_unmatched_spelling(self):
        texts = [game("Jobava,Ba")] * 26 + [game("Jobava, Baadur")] * 2 + [game("Nakamura,Hi", "Q, R")]
        aliases = ["Jobava, Baadur", "Jobava, B"]
        census = A.name_census(texts, aliases)
        assert ("Jobava,Ba", 26, False) in census and ("Jobava, Baadur", 2, True) in census
        assert A.unmatched_variants(census, aliases) == [("Jobava,Ba", 26)]

    def test_other_players_are_not_reported_as_variants(self):
        texts = [game("Karpov, Anatoly", "Q, R")] * 30
        assert A.unmatched_variants(A.name_census(texts, ["Korchnoi, Viktor"]), ["Korchnoi, Viktor"]) == []

    def test_transliterated_surnames_are_flagged_and_rare_names_are_not(self):
        aliases = ["Korchnoi, Viktor"]
        texts = [game("Kortschnoj, Viktor", "A, B")] * 25 + [game("Kortschnoj, V", "C, D")] * 3
        assert A.unmatched_variants(A.name_census(texts, aliases), aliases) == [("Kortschnoj, Viktor", 25)]
        assert A.unmatched_variants(A.name_census([game("Petrosjan, T", "E, F")] * 30, ["Petrosian, Tigran"]), ["Petrosian, Tigran"]) \
            == [("Petrosjan, T", 30)]

    def test_variants_beyond_the_five_most_common_names_are_still_found(self):
        texts = [game(f"Opp{i}, Z", "X, Y") for i in range(9)] * 4 + [game("Jobava,Ba", "X, Y")] * 25
        aliases = ["Jobava, Baadur"]
        assert ("Jobava,Ba", 25) in A.unmatched_variants(A.name_census(texts, aliases), aliases)

    def test_fetch_logs_the_census_and_the_warning(self, tmp_path):
        arch = archive([game("Tal,Mi", date="1960.01.01")] * 26)  # spelled 'Tal,Mi': no alias matches it
        cfg = {"anchors": {"tal": TAL}}
        logs = []
        AS.fetch_anchors(cfg, tmp_path / "o", tmp_path / "r", max_games=5, per_game=2, pause=0,
                         getter=getter({"Tal.zip": arch}), log=logs.append)
        text = "\n".join(logs)
        assert "names in archive: 'Tal,Mi' x26 (NOT matched)" in text and "WARNING: 'Tal,Mi'" in text

    def test_shipped_aliases_cover_the_spellings_seen_in_pgn_mentor(self):
        import yaml
        cfg = yaml.safe_load(open("configs/anchors.yaml"))["anchors"]
        assert A.matches("Jobava,Ba", cfg["jobava"]["aliases"]) and A.matches("Kortschnoj, Viktor", cfg["korchnoi"]["aliases"])
        assert A.matches("Nakamura,Hi", cfg["nakamura"]["aliases"]) and A.matches("Korchnoi,V", cfg["korchnoi"]["aliases"])
