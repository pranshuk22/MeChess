import numpy as np

from chessme.style import report as R
from chessme.style.axes import AXES
from chessme.style.features import FEATURE_NAMES, INDEX


def cmp(**z):
    v = np.zeros(len(FEATURE_NAMES))
    for k, x in z.items():
        v[INDEX[k]] = x
    return {"names": FEATURE_NAMES, "z": v, "w_player": v, "w_base": np.zeros_like(v)}


def render(comp, axes=None, gains=(), held=None):
    return R.render(player_label="Test Player", n_player=1000, n_base=9000, rating=1900, band=(1500, 2600),
                    comparison=comp, axis_scores=axes or {a: 0.0 for a in AXES}, gains=list(gains), held_out=held,
                    loss_coef=3.0)


def test_every_feature_has_a_plain_phrase_and_every_axis_a_description():
    assert set(R.PHRASES) <= set(FEATURE_NAMES)
    assert set(R.AXIS_TEXT) == set(AXES)


def test_notable_habits_are_described_in_words_with_direction():
    text = render(cmp(sacrifice=3.5, trade=-2.4, capture=0.3))
    assert "sacrifice material more readily" in text and "clearly" in text
    assert "keep pieces on the board more" in text and "noticeably" in text
    assert "z = " in text


def test_no_notable_habit_says_so_instead_of_inventing_one():
    assert "No single habit differs" in render(cmp(capture=0.5))


def test_axis_lines_use_strength_words_and_typical():
    axes = {a: 0.0 for a in AXES}
    axes.update(aggression=3.2, risk_taking=-2.2)
    text = render(cmp(), axes)
    assert "clearly more attacking than typical" in text and "noticeably plays safer than typical" in text
    assert "**Simplification**: about typical" in text


def test_report_states_data_size_band_and_limits():
    text = render(cmp())
    assert "1,000" in text and "9,000" in text and "1500-2600" in text and "hypotheses" in text
    assert "Limits of this report" in text


def test_hardening_table_and_heldout_section_render():
    held = {"n": 500, "style": {"top1": 0.46, "nll": 1.4}, "loss_only": {"top1": 0.40, "nll": 1.5},
            "uniform": {"top1": 0.22, "nll": 1.65}}
    text = render(cmp(), gains=[(1500, 1700, 900, 0.02, 0.011), (2400, 2600, 150, float("nan"), float("nan"))], held=held)
    assert "| 1500-1700 | 900 | +0.020 | +1.1 pts |" in text and "too few" in text
    assert "**46%**" in text
