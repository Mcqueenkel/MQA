"""Per-scenario TRAIN-TO stat ceilings (DEFAULT_STAT_CAPS in scenarios/*.py). Set near the game's
absolute per-stat max (1800) so the bot trains each stat UP to its live in-game cap instead of
holding it at a low conservative number (the reported "won't train Wit past ~1100"). A scenario cap
is the training target -- foresight (a lower aptitude aim) does NOT pull it back down. Explicit
stat_caps override it per stat; scenario_stat_caps=False falls back to foresight's aptitude aim.

Run:
    python tests/test_scenario_stat_caps.py
    python -m pytest tests/test_scenario_stat_caps.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.training_brain import BaseTrainingStrategy  # noqa: E402
from career_bot.scenarios.mant import MantStrategy               # noqa: E402
from career_bot.scenarios.unity import UnityStrategy             # noqa: E402
from career_bot.scenarios.ura import UraStrategy                 # noqa: E402
from career_bot.scenarios.grand_live import GrandLiveStrategy    # noqa: E402


# a Wit training (target_type 5 -> stat index 4). Wit takes NO climax stat credit, so the ratio math
# is clean; the user's exact complaint was Wit stuck ~1100 despite a ~1800 game cap.
_WIT = {"command_id": 106, "params_inc_dec_info_array": [{"target_type": 5, "value": 100}]}


def _scorer(cls):
    b = cls.__new__(cls)                       # _score_command uses only args + module consts + these
    b._merged_emphasis = lambda preset, chara: {}
    return b


class _FakeForecast:
    """A career forecast that wants LOW stats (aptitude aim ~900) -- the thing that used to hold Wit."""
    active = True
    stat_targets = [900, 900, 900, 900, 900]


def test_scenario_stat_caps_lookup():
    # each scenario's own caps: game base 1200 + the scenario's master.mdb cap bonuses
    assert BaseTrainingStrategy.__new__(BaseTrainingStrategy)._scenario_stat_caps({}) is None
    assert UraStrategy.__new__(UraStrategy)._scenario_stat_caps({}) == [1400, 1400, 1400, 1400, 1400]
    assert UnityStrategy.__new__(UnityStrategy)._scenario_stat_caps({}) == [1300, 1300, 1300, 1300, 1800]
    assert MantStrategy.__new__(MantStrategy)._scenario_stat_caps({}) == [1200, 1900, 1200, 1200, 1500]
    # Grand Live: user's "reach toward these" profile [SPD, STA, PWR, GUT, WIT] -- also hard stat_caps
    assert GrandLiveStrategy.__new__(GrandLiveStrategy)._scenario_stat_caps({}) == [1600, 1300, 1300, 1500, 1300]


def test_toggle_off_returns_none():
    assert UnityStrategy.__new__(UnityStrategy)._scenario_stat_caps({"scenario_stat_caps": False}) is None


def test_does_not_hold_wit_below_the_game_cap():
    # THE FIX: Wit at 1100 with a 1800 live game cap -> the scenario ceiling (1800) does not hold it,
    # so the bot still trains Wit (scores like the uncapped base brain), instead of stopping at ~1100.
    base = _scorer(BaseTrainingStrategy)
    unity = _scorer(UnityStrategy)
    chara = {"turn": 30, "wiz": 1100, "max_wiz": 1800}
    b = base._score_command(_WIT, {}, chara, {"stat_balance": False})
    u = unity._score_command(_WIT, {}, chara, {"stat_balance": False})
    assert b > 0
    assert u == b            # scenario cap 1800 vs base's game cap 1800 -> identical, still training


def test_scenario_cap_beats_low_foresight_aim():
    # With a forecast that wants only ~900 Wit, the scenario ceiling must WIN: at wiz 1200 (above the
    # forecast's relaxed aim, below the game cap) the bot keeps training -- it is NOT clamped down to
    # the aptitude number. Turning scenario_stat_caps off lets the (lower) foresight aim bind instead.
    unity = _scorer(UnityStrategy)
    unity._forecast = _FakeForecast()
    chara = {"turn": 30, "wiz": 1200, "max_wiz": 1800}
    on = unity._score_command(_WIT, {}, chara, {"stat_balance": False})
    off = unity._score_command(_WIT, {}, chara, {"stat_balance": False, "scenario_stat_caps": False})
    assert on > off          # scenario ceiling trains higher than foresight's low aim would


def test_explicit_stat_cap_still_binds_over_scenario():
    # An explicit low Wit cap (1000) must still HARD-cap: at wiz 1100 (over 1000) the Wit gain zeroes,
    # far below the scenario-ceiling score -- the user's own stat_caps always win.
    unity = _scorer(UnityStrategy)
    chara = {"turn": 30, "wiz": 1100, "max_wiz": 1800}
    ceil = unity._score_command(_WIT, {}, chara, {"stat_balance": False})
    capped = unity._score_command(_WIT, {}, chara, {"stat_balance": False, "stat_caps": {"wiz": 1000}})
    assert capped < ceil * 0.1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("scenario stat caps OK")
