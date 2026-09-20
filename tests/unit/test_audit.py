import json

from chessme import audit
from tests.samples import make_row

ROWS = [
    make_row(game_id="a", platform="lichess", color="white", moves="d4 Nf6 c4 e6", opening="Queen's Gambit Declined", my_result="win"),
    make_row(game_id="b", platform="lichess", color="black", moves="e4 c5 Nf3 d6", opening="Sicilian Defense: Najdorf", my_result="loss", result="1-0"),
    make_row(game_id="c", platform="lichess", color="black", moves="e4 c5 Nf3 e6", opening="Sicilian Defense: Kan", my_result="win", result="0-1"),
    make_row(game_id="d", platform="chesscom", account="cc", color="white", moves="d4 d5 c4 e6", time_class="rapid",
             my_rating=1600, opening="Queen's Gambit Declined", my_result="draw", result="1/2-1/2"),
    make_row(game_id="e", usable=False, unusable_reason="too_short", plies=4),
    make_row(game_id="f", variant="chess960", usable=False, unusable_reason="variant", plies=0, moves=""),
]


def test_load_round_trips_jsonl(tmp_path):
    p = tmp_path / "games.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in ROWS))
    assert audit.load(p) == ROWS


def test_report_counts_and_sections():
    text = audit.build(ROWS)
    assert "Games ingested: **6**" in text
    assert "Usable for training: **4**" in text
    for section in ["Unusable games by reason", "Games per account", "Games per time control",
                    "Colour split", "Most frequent openings", "Repertoire snapshot", "Data quality notes"]:
        assert section in text
    assert "too_short" in text and "variant" in text


def test_report_repertoire_snapshot_is_correct():
    text = audit.build(ROWS)
    assert "As white, first move: d4 100%" in text
    assert "As black vs 1.e4 (2 games): c5 100%" in text


def test_opening_family_groups_variations():
    assert audit.family({"opening": "Sicilian Defense: Najdorf Variation"}) == "Sicilian Defense"
    assert audit.family({"opening": None, "eco": "B20"}) == "(B20)"
    assert audit.family({"opening": None, "eco": None}) == "(?)"


def test_wdl_and_pct_helpers():
    assert audit.wdl([{"my_result": "win"}, {"my_result": "loss"}, {"my_result": "draw"}, {"my_result": "win"}]) == "2/1/1"
    assert audit.pct(1, 3) == "33%"
    assert audit.pct(0, 0) == "-"


def test_table_formatting_is_aligned_markdown():
    t = audit.table(["a", "bb"], [(1, "x"), (22, "yyy")])
    lines = t.splitlines()
    assert lines[0].startswith("| a ") and set(lines[1]) <= {"|", "-"}
    assert len({len(l) for l in lines}) == 1  # every row the same width


def test_effective_data_section_only_with_config():
    cfg = {"filters": {"min_rating": {"lichess": 1700, "chesscom": 1200},
                       "recency": {"half_life_days": 100, "min_weight": 0.1},
                       "time_class_weights": {"blitz": 1.0, "rapid": 1.0}}}
    assert "Effective training data" not in audit.build(ROWS)
    text = audit.build(ROWS, cfg)
    assert "Effective training data" in text
    assert "Games kept after rating floors / excluded time classes: **4** of 4 usable" in text
    assert "Total my moves kept" in text
