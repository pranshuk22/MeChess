import json

from chessme.ingest import normalize
from tests.samples import LICHESS_960, LICHESS_GAME, LICHESS_SHORT, chesscom_game, fill


def cfg_for(tmp_path, accounts):
    return {"_raw_dir": tmp_path / "data" / "raw", "accounts": accounts}


def write_lichess(tmp_path, user, text, name="games_1.pgn"):
    d = tmp_path / "data" / "raw" / "lichess" / user
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)


def write_chesscom(tmp_path, user, games, month="2024-05"):
    d = tmp_path / "data" / "raw" / "chesscom" / user
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{month}.json").write_text(json.dumps({"games": games}))


def rows_of(tmp_path):
    return [json.loads(l) for l in (tmp_path / "data" / "processed" / "games.jsonl").read_text().splitlines()]


def test_time_class_rule():
    f = normalize.time_class_from_tc
    assert f("15+0") == "ultrabullet"
    assert f("60+0") == "bullet"
    assert f("180+2") == "blitz"
    assert f("300+0") == "blitz"
    assert f("600+0") == "rapid"
    assert f("900+10") == "rapid"
    assert f("1800+0") == "classical"
    assert f("-") == "correspondence"
    assert f(None) == "correspondence"
    assert f("junk+x") == "correspondence"


def test_lichess_game_becomes_one_clean_row(tmp_path):
    write_lichess(tmp_path, "Me", fill(LICHESS_GAME, "Me", "Opp1"))
    normalize.ingest(cfg_for(tmp_path, [{"platform": "lichess", "username": "Me"}]))
    (r,) = rows_of(tmp_path)
    assert r["game_id"] == "lichess:abcd1234"
    assert r["color"] == "white" and r["my_rating"] == 1900 and r["opp_rating"] == 1850
    assert r["my_result"] == "win" and r["result"] == "1-0"
    assert r["time_class"] == "blitz" and r["rated"] is True and r["variant"] == "standard"
    assert r["plies"] == 10 and r["moves"].split()[:4] == ["e4", "c5", "Nf3", "d6"]
    assert r["clocks"][:3] == [300.0, 300.0, 298.0]
    assert r["played_at"].startswith("2024-03-30T12:00:00")
    assert r["eco"] == "B90" and r["opening"].startswith("Sicilian Defense")
    assert r["usable"] is True and r["unusable_reason"] is None


def test_playing_black_flips_colour_rating_and_result(tmp_path):
    write_lichess(tmp_path, "Me", fill(LICHESS_GAME, "Opp1", "Me"))
    normalize.ingest(cfg_for(tmp_path, [{"platform": "lichess", "username": "Me"}]))
    (r,) = rows_of(tmp_path)
    assert r["color"] == "black" and r["my_rating"] == 1850 and r["opp_rating"] == 1900
    assert r["my_result"] == "loss" and r["opp_name"] == "Opp1"


def test_account_matching_is_case_insensitive(tmp_path):
    write_lichess(tmp_path, "me", fill(LICHESS_GAME, "ME", "Opp1"))
    normalize.ingest(cfg_for(tmp_path, [{"platform": "lichess", "username": "me"}]))
    assert rows_of(tmp_path)[0]["color"] == "white"


def test_short_games_are_flagged_not_dropped(tmp_path):
    write_lichess(tmp_path, "Me", fill(LICHESS_SHORT, "Me", "Opp1"))
    normalize.ingest(cfg_for(tmp_path, [{"platform": "lichess", "username": "Me"}]))
    (r,) = rows_of(tmp_path)
    assert r["usable"] is False and r["unusable_reason"] == "too_short"


def test_variants_and_custom_start_positions_are_unusable(tmp_path):
    write_lichess(tmp_path, "Me", fill(LICHESS_960, "Me"))
    normalize.ingest(cfg_for(tmp_path, [{"platform": "lichess", "username": "Me"}]))
    (r,) = rows_of(tmp_path)
    assert r["usable"] is False and r["unusable_reason"] == "variant" and r["variant"] == "chess960"
    assert r["moves"] == ""


def test_chesscom_game_uses_json_metadata(tmp_path):
    write_chesscom(tmp_path, "example_user", [chesscom_game(black="someone")])
    normalize.ingest(cfg_for(tmp_path, [{"platform": "chesscom", "username": "example_user"}]))
    (r,) = rows_of(tmp_path)
    assert r["game_id"] == "chesscom:uuid-1"
    assert r["time_class"] == "rapid" and r["rated"] is True
    assert r["color"] == "white" and r["my_rating"] == 1700 and r["my_result"] == "loss"
    assert r["opening"].startswith("Queens Pawn Opening")
    assert r["clocks"][0] == 600.0 and r["plies"] == 8 and r["usable"] is True


def test_chesscom_variant_rules_are_unusable(tmp_path):
    write_chesscom(tmp_path, "example_user", [chesscom_game(rules="chess960")])
    normalize.ingest(cfg_for(tmp_path, [{"platform": "chesscom", "username": "example_user"}]))
    (r,) = rows_of(tmp_path)
    assert r["usable"] is False and r["unusable_reason"] == "variant"


def test_game_between_my_own_accounts_is_deduplicated_and_flagged(tmp_path):
    text = fill(LICHESS_GAME, "AccA", "AccB")
    write_lichess(tmp_path, "AccA", text)
    write_lichess(tmp_path, "AccB", text)
    normalize.ingest(cfg_for(tmp_path, [{"platform": "lichess", "username": "AccA"},
                                        {"platform": "lichess", "username": "AccB"}]))
    (r,) = rows_of(tmp_path)  # one row, not two
    assert r["usable"] is False and r["unusable_reason"] == "vs_own_account"


def test_rows_are_sorted_by_time_and_missing_files_are_fine(tmp_path):
    late = fill(LICHESS_GAME, "Me", "o").replace("abcd1234", "late0001").replace("12:00:00", "20:00:00")
    early = fill(LICHESS_GAME, "Me", "o").replace("abcd1234", "early001").replace("12:00:00", "08:00:00")
    write_lichess(tmp_path, "Me", late + early)
    normalize.ingest(cfg_for(tmp_path, [{"platform": "lichess", "username": "Me"},
                                        {"platform": "chesscom", "username": "NoFilesHere"}]))
    ids = [r["game_id"] for r in rows_of(tmp_path)]
    assert ids == ["lichess:early001", "lichess:late0001"]
