import io

from chessme.style import anchor_verify as AV
from tests.unit.test_style_anchor_sources import archive, game, getter

PAGE = ('<tr><td><a href="players/Tal.zip">Tal.pgn</a><br /><div><a href="players/Tal.zip" class="view">Download</a></div></td>'
        '<td>Mikhail Tal, 2,431 games</td></tr>'
        '<tr><td><a href="players/PolgarJ.zip">PolgarJ.pgn</a><br /><div></div></td><td>Judit Polgar, 1,825 games</td></tr>')
TAL = {"aliases": ["Tal, Mikhail", "Tal, M"], "years": [1957, 1962], "selected": True}


def test_page_parsing_reads_display_name_and_game_count():
    assert AV.parse_page(PAGE) == {"Tal": ("Mikhail Tal", 2431), "PolgarJ": ("Judit Polgar", 1825)}


def test_display_name_tokens_missing_from_aliases_are_reported():
    assert AV.display_name_problems("Mikhail Tal", ["Tal, Mikhail", "Tal, M"]) == []
    assert AV.display_name_problems("Judit Polgar", ["Polgar, Ju"]) == []                    # abbreviated first name is fine
    assert AV.display_name_problems("Shakhriyar Mamedyarov", ["Mamedyarov, Shahriar"]) == ["shakhriyar"]


def test_clean_anchor_passes_and_archive_is_deleted(tmp_path):
    cfg = {"anchors": {"tal": TAL}}
    g = getter({"Tal.zip": archive([game() for _ in range(30)])})
    logs = []
    res = AV.verify(cfg, PAGE.replace("2,431", "30"), tmp_path, getter=g, pause=0, log=logs.append)
    assert res[0]["problems"] == [] and res[0]["matched"] == 30 and not list(tmp_path.glob("*.zip"))
    assert any("ok" in l for l in logs) and "0 need attention" in logs[-1]


def test_spelling_variants_and_low_match_ratio_are_flagged(tmp_path):
    cfg = {"anchors": {"tal": TAL}}
    g = getter({"Tal.zip": archive([game() for _ in range(5)] + [game("Tal,Mi") for _ in range(25)])})
    logs = []
    res = AV.verify(cfg, PAGE.replace("2,431", "30"), tmp_path, getter=g, pause=0, log=logs.append)
    text = "\n".join(res[0]["problems"])
    assert "match only 5 of the 30" in text and "'Tal,Mi' x25" in text and "1 need attention" in logs[-1]


def test_anchor_missing_from_the_page_or_download_is_reported(tmp_path):
    cfg = {"anchors": {"tal": TAL, "zzz": {"aliases": ["Zzz, Q"], "selected": True}}}
    res = AV.verify(cfg, PAGE, tmp_path, getter=getter({}), pause=0, log=lambda *_: None)
    assert "not listed" in res[1]["problems"][0] and res[0]["problems"] == ["download failed"]


def test_html_entities_in_display_names_are_decoded_and_accents_match_aliases():
    page = '<tr><td><a href="players/Capablanca.zip">Capablanca.pgn</a></td><td>Jos&eacute; Ra&uacute;l Capablanca, 597 games</td></tr>'
    assert AV.parse_page(page) == {"Capablanca": ("José Raúl Capablanca", 597)}
    assert AV.display_name_problems("José Raúl Capablanca", ["Capablanca, Jose Raul", "Capablanca, J"]) == []
