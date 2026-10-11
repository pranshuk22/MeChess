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


def test_the_project_root_is_found_in_a_checkout_and_overridable(tmp_path, monkeypatch):
    assert (config.find_root() / "configs" / "profiles" / "example.yaml").exists()           # this checkout
    monkeypatch.setenv("CHESSME_ROOT", str(tmp_path))
    assert config.find_root() == tmp_path.resolve()


def test_every_package_and_the_book_list_are_declared_for_installation():
    """Regression: pyproject listed the packages by hand and left out chessme.analysis and chessme.books (and sources.json), so an installed
    copy failed with ModuleNotFoundError on `analyse`, `report-*` and every `books-*` command."""
    from pathlib import Path

    tomllib = pytest.importorskip("tomllib")                                  # Python 3.11+

    root = Path(__file__).resolve().parents[2]
    cfg = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["setuptools"]
    assert cfg["packages"]["find"]["include"] == ["chessme*"]
    assert "sources.json" in cfg["package-data"]["chessme.books"]
    from setuptools import find_packages
    found = set(find_packages(str(root), include=["chessme*"]))
    on_disk = {".".join(p.parent.relative_to(root).parts) for p in (root / "chessme").rglob("__init__.py")}
    assert found == on_disk and {"chessme.analysis", "chessme.books"} <= found
