import pytest

from chessme import config


def test_example_profile_loads_and_has_required_sections():
    cfg = config.load_profile("example")
    assert cfg["profile"] == "example"
    assert {a["platform"] for a in cfg["accounts"]} == {"lichess", "chesscom"}
    assert all(a["username"].startswith("your_") for a in cfg["accounts"])  # placeholders only, never real accounts
    assert cfg["_raw_dir"].name == "raw"
    f = cfg["filters"]
    assert f["min_rating"] == {"lichess": 1400, "chesscom": 1200}
    assert f["recency"]["half_life_days"] > 0
    assert cfg["rating_range"]["min"] < cfg["rating_range"]["default"] < cfg["rating_range"]["max"]


def test_profile_has_no_secrets():
    text = (config.ROOT / "configs" / "profiles" / "example.yaml").read_text().lower()
    assert "token:" not in text and "password" not in text and "api_key" not in text


def test_missing_profile_exits_cleanly():
    with pytest.raises(SystemExit):
        config.load_profile("does-not-exist")


def test_custom_root(tmp_path, monkeypatch):
    prof = tmp_path / "configs" / "profiles"
    prof.mkdir(parents=True)
    (prof / "alice.yaml").write_text("profile: alice\naccounts: []\npaths: {raw: somewhere/raw}\n")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    cfg = config.load_profile("alice")
    assert cfg["_raw_dir"] == tmp_path / "somewhere" / "raw"
