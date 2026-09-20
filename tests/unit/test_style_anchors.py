import io
import zipfile

import chess
import numpy as np
import pytest

from chessme.style import anchors as A
from chessme.style.features import INDEX
from tests.unit.test_style_model import make_positions

MOVES = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 8. c3 O-O 9. h3 Nb8 10. d4 Nbd7 11. Nbd2 Bb7 12. Bc2 Re8 1-0"


def pgn(white, black, date="1970.01.01", welo="", belo="", variant=None):
    tags = [("Event", "Test"), ("Site", "?"), ("Date", date), ("White", white), ("Black", black), ("Result", "1-0")]
    tags += [(k, v) for k, v in (("WhiteElo", welo), ("BlackElo", belo), ("Variant", variant)) if v]
    return "".join(f'[{k} "{v}"]\n' for k, v in tags) + f"\n{MOVES}\n\n"


TAL = ["Tal, Mikhail", "Tal, M"]


class TestNames:
    @pytest.mark.parametrize("name", ["Tal, Mikhail", "TAL, MIKHAIL", "Tal, M", "Tal, M.", "Tal,Mikhail"])
    def test_variants_match(self, name):
        assert A.matches(name, TAL)

    @pytest.mark.parametrize("name", ["Talamanca, Mikhail", "Tallinn, M", "Petrosian, Tigran", ""])
    def test_other_players_do_not(self, name):
        assert not A.matches(name, TAL)

    def test_accents_are_folded(self):
        assert A.matches("Capablanca, José Raúl", ["Capablanca, Jose Raul"])


class TestGames:
    def test_games_of_the_anchor_on_either_side_with_colour_and_rating(self):
        texts = [pgn("Tal, Mikhail", "X, Y", welo="2700"), pgn("A, B", "Tal, M.", belo="2650"), pgn("A, B", "C, D")]
        g = A.anchor_games(texts, TAL)
        assert [(c, e) for _, c, e in g] == [(chess.WHITE, 2700), (chess.BLACK, 2650)]

    def test_missing_rating_is_zero_and_variants_and_early_years_are_filtered(self):
        texts = [pgn("Tal, M", "X, Y"), pgn("Tal, M", "X, Y", variant="Atomic"), pgn("Tal, M", "X, Y", date="1955.05.05")]
        assert [e for _, _, e in A.anchor_games(texts, TAL)] == [0, 0]
        assert len(A.anchor_games(texts, TAL, min_year=1960)) == 1

    def test_reads_plain_pgn_and_zip(self, tmp_path):
        text = pgn("Tal, M", "X, Y") + pgn("A, B", "C, D")
        (tmp_path / "tal.pgn").write_text(text)
        with zipfile.ZipFile(tmp_path / "tal2.zip", "w") as z:
            z.writestr("games/tal.pgn", text)
            z.writestr("readme.txt", "not a game")
        assert len(list(A.read_game_texts(tmp_path / "tal.pgn"))) == 2
        assert len(list(A.read_game_texts(tmp_path / "tal2.zip"))) == 2

    def test_decisions_are_the_anchors_own_moves_only(self):
        games = A.anchor_games([pgn("A, B", "Tal, M")] * 3, TAL)
        items = A.decisions(games, "tal", per_game=50)
        assert items and all(chess.Board(i.fen).turn == chess.BLACK and i.ply >= 8 for i in items)
        assert {i.game for i in items} == {0, 1, 2} and all(i.player == "tal" for i in items)

    def test_sampling_is_reproducible_and_capped(self):
        games = A.anchor_games([pgn("Tal, M", "X, Y")] * 30, TAL)
        a, b = A.decisions(games, "tal", max_games=10, per_game=3), A.decisions(games, "tal", max_games=10, per_game=3)
        assert a == b and len({i.game for i in a}) == 10 and len(a) == 30


class TestBuild:
    def test_files_are_matched_by_key_and_missing_anchors_are_skipped(self, tmp_path):
        files, out = tmp_path / "f", tmp_path / "o"
        files.mkdir()
        (files / "Tal.pgn").write_text(pgn("Tal, Mikhail", "X, Y") * 5)
        cfg = {"anchors": {"tal": {"aliases": TAL, "hypothesis": "attack"}, "karpov": {"aliases": ["Karpov, A"]}}}
        logs = []
        idx = A.build_anchors(cfg, files, out, per_game=2, log=logs.append)
        assert list(idx) == ["anchor_tal"] and idx["anchor_tal"]["games_available"] == 5
        assert (out / "items" / "anchor_tal.jsonl").exists() and any("karpov" in l and "skipped" in l for l in logs)

    def test_items_load_with_the_cohort_reader(self, tmp_path):
        from chessme.style import cohort as CO
        files, out = tmp_path / "f", tmp_path / "o"
        files.mkdir()
        (files / "tal.pgn").write_text(pgn("Tal, Mikhail", "X, Y") * 3)
        A.build_anchors({"anchors": {"tal": {"aliases": TAL}}}, files, out, per_game=2, log=lambda *_: None)
        items = CO.load_items(out / "items" / "anchor_tal.jsonl")
        assert len(items) == 6 and items[0].player == "tal"


def anchor_set(rng, n=700, games=20):
    tastes = {"attacker": {"sacrifice": 2.0, "trade": -2.0}, "grinder": {"sacrifice": -2.0, "trade": 2.0},
              "neutral": {}}
    out = {}
    for k, t in tastes.items():
        ps = make_positions(n, t, rng)
        for j, p in enumerate(ps):
            p.game = j % games
        out[k] = ps
    return out


class TestComparison:
    def test_distinct_anchors_are_told_apart_and_similar_ones_are_not(self):
        rng = np.random.default_rng(0)
        conf = A.anchor_confusion(anchor_set(rng))
        assert conf["keys"] == ["attacker", "grinder", "neutral"] and conf["chunks"] >= 20
        assert conf["accuracy"] > 0.6
        twins = {k: make_positions(600, {"sacrifice": 1.0}, rng) for k in ("a", "b")}
        for ps in twins.values():
            for j, p in enumerate(ps):
                p.game = j % 20
        assert A.anchor_confusion(twins)["accuracy"] < 0.75  # same taste -> near coin flip (chance 0.5)

    def test_player_is_ranked_closest_to_the_anchor_with_the_same_taste(self):
        rng = np.random.default_rng(1)
        anchors = anchor_set(rng)
        player = make_positions(800, {"sacrifice": 2.0, "trade": -2.0}, rng)
        for j, p in enumerate(player):
            p.game = j % 20
        r = A.rank_anchors(anchors, player)
        assert r["anchors"][0][0] == "attacker" and r["anchors"][-1][0] == "grinder"
        assert r["own"] < r["uniform"]

    def test_too_few_anchors_is_an_error(self):
        rng = np.random.default_rng(2)
        with pytest.raises(ValueError):
            A.fit_anchors({"only": anchor_set(rng)["attacker"]})

    def test_render_shows_matrix_and_ranking(self):
        rng = np.random.default_rng(3)
        anchors = anchor_set(rng)
        player = make_positions(600, {"sacrifice": 2.0}, rng)
        for j, p in enumerate(player):
            p.game = j % 20
        text = A.render(A.anchor_confusion(anchors), A.rank_anchors(anchors, player), {"attacker": "attack"})
        assert "attacker" in text and "chance 33%" in text and "your own style" in text and "(attack)" in text


class TestSelectionAndRank:
    def test_only_selected_anchors_are_built_unless_all_is_asked(self, tmp_path):
        files = tmp_path / "f"
        files.mkdir()
        for k, n in (("tal", "Tal, M"), ("karpov", "Karpov, A")):
            (files / f"{k}.pgn").write_text(pgn(n, "X, Y") * 3)
        cfg = {"anchors": {"tal": {"selected": True, "aliases": TAL}, "karpov": {"selected": False, "aliases": ["Karpov, A"]}}}
        assert list(A.build_anchors(cfg, files, tmp_path / "a", per_game=2, log=lambda *_: None)) == ["anchor_tal"]
        assert set(A.build_anchors(cfg, files, tmp_path / "b", per_game=2, only_selected=False, log=lambda *_: None)) == \
            {"anchor_tal", "anchor_karpov"}

    def test_shipped_config_is_consistent(self):
        import yaml
        cfg = yaml.safe_load(open("configs/anchors.yaml"))["anchors"]
        assert {"tal", "petrosian", "giri", "rapport", "dubov", "karpov", "kasparov", "carlsen", "nakamura"} <= set(cfg)
        # the user asked for all of them; Dubov has no available game file, so Judit Polgar (attack pole) stands in
        assert [k for k, v in cfg.items() if not v["selected"]] == ["dubov"]
        assert cfg["polgar"]["selected"] and cfg["polgar"]["pole"] == "attack" and cfg["polgar"]["file"] == "PolgarJ"
        assert all(v["aliases"] and v["hypothesis"] and v["pole"] for v in cfg.values())
        assert {v["pole"] for v in cfg.values()} == {"attack", "creative", "solid", "positional", "universal"}
        for k, v in cfg.items():  # every alias normalises to something a PGN name can equal
            assert all(A.normalise(a) for a in v["aliases"]), k

    def test_rank_with_an_explicit_held_out_set(self):
        rng = np.random.default_rng(5)
        anchors = anchor_set(rng)
        train = make_positions(800, {"sacrifice": 2.0, "trade": -2.0}, rng)
        test = make_positions(400, {"sacrifice": 2.0, "trade": -2.0}, rng)
        r = A.rank_anchors(anchors, train, player_test=test)
        assert r["anchors"][0][0] == "attacker" and r["n"] > 200
