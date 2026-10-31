"""resolve_running_style: preset styles 1-4, the new "Best" (5), and the aptitude auto-override.

Run:
    python tests/test_running_style.py
    python -m pytest tests/test_running_style.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.presets import resolve_running_style  # noqa: E402

# 1=nige (Front), 2=senko (Pace), 3=sashi (Late), 4=oikomi (End)
def _apt(nige=1, senko=1, sashi=1, oikomi=1):
    return {"proper_running_style_nige": nige, "proper_running_style_senko": senko,
            "proper_running_style_sashi": sashi, "proper_running_style_oikomi": oikomi}


def test_best_picks_highest_aptitude():
    assert resolve_running_style({"running_style": 5}, _apt(senko=7)) == 2   # senko highest
    assert resolve_running_style({"running_style": 5}, _apt(oikomi=8)) == 4  # oikomi highest


def test_best_ties_break_to_lower_index():
    # nige and sashi both 7 -> lower index (nige = 1) wins
    assert resolve_running_style({"running_style": 5}, _apt(nige=7, sashi=7)) == 1


def test_best_without_aptitude_data_defers_to_game():
    assert resolve_running_style({"running_style": 5}, {}) == 0


def test_fixed_style_is_honored_when_apt_ok_or_forced():
    # good aptitude for the chosen style -> keep it
    assert resolve_running_style({"running_style": 4}, _apt(oikomi=7)) == 4
    # auto off -> keep the preset style verbatim even on poor aptitude
    assert resolve_running_style({"running_style": 1, "auto_running_style": False}, _apt(senko=8)) == 1


def test_auto_override_switches_off_a_weak_fixed_style():
    # preset wants nige (1) but its aptitude is D(4) and senko is A(7) -> auto picks senko
    assert resolve_running_style({"running_style": 1}, _apt(nige=4, senko=7)) == 2


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
