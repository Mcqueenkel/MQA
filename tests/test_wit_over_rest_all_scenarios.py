"""Wit-over-rest is now on EVERY scenario. On a turn the brain would REST, train Wit instead when
Wit is safe (failure below <scenario>_wit_rest_max, default 10%). The Wit facility (cmd 106, summer
605) RECOVERS energy while still paying stats + skill points, so a safe Wit beats a dead 0-stat rest
turn -- measured on real careers, 63% of MANT rest turns had a sub-10%-failure Wit on the board, and
the user's manual UG run took ZERO rests because Wit was ~35% of its trainings.

Unity and Grand Live already had the hook; MANT and URA did not (base returned None -> plain rest).
This locks all four in, and pins the per-scenario toggle/threshold key names.

Run:
    python tests/test_wit_over_rest_all_scenarios.py
    python -m pytest tests/test_wit_over_rest_all_scenarios.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.training_brain import BaseTrainingStrategy
from career_bot.scenarios.mant import MantStrategy
from career_bot.scenarios.ura import UraStrategy
from career_bot.scenarios.unity import UnityStrategy
from career_bot.scenarios.grand_live import GrandLiveStrategy

# scenario class -> (toggle key, threshold key)
SCENARIOS = {
    MantStrategy: ("mant_wit_over_rest", "mant_wit_rest_max"),
    UraStrategy: ("ura_wit_over_rest", "ura_wit_rest_max"),
    UnityStrategy: ("unity_wit_over_rest", "unity_wit_rest_max"),
    GrandLiveStrategy: ("grand_live_wit_over_rest", "grand_live_wit_rest_max"),
}


def _s(cls):
    return cls.__new__(cls)                    # method-only; skip __init__ (no data files needed)


def _wit(failure):
    return {"command_id": 106, "failure_rate": failure}       # 106 = Wit facility (stat index 4)


def _spd(failure):
    return {"command_id": 101, "failure_rate": failure}       # 101 = Speed


def test_every_scenario_trains_a_safe_wit_instead_of_resting():
    for cls in SCENARIOS:
        got = _s(cls)._rest_alternative([_spd(40), _wit(6)], {}, {}, 30)
        assert got == _wit(6), f"{cls.__name__} rested instead of training a 6% Wit"


def test_every_scenario_rests_when_wit_is_risky():
    for cls in SCENARIOS:
        assert _s(cls)._rest_alternative([_spd(40), _wit(12)], {}, {}, 30) is None, cls.__name__


def test_boundary_is_strict_below_ten():
    for cls in SCENARIOS:
        assert _s(cls)._rest_alternative([_wit(10)], {}, {}, 30) is None, cls.__name__
        assert _s(cls)._rest_alternative([_wit(9)], {}, {}, 30) == _wit(9), cls.__name__


def test_no_wit_on_the_board_rests():
    # Wit absent (e.g. already at the scenario cap -> stripped from `training`) -> rest as usual
    for cls in SCENARIOS:
        assert _s(cls)._rest_alternative([_spd(4)], {}, {}, 30) is None, cls.__name__


def test_summer_camp_wit_facility_counts():
    # 605 = summer-camp Wit (also stat index 4)
    for cls in SCENARIOS:
        got = _s(cls)._rest_alternative([{"command_id": 605, "failure_rate": 3}], {}, {}, 40)
        assert got == {"command_id": 605, "failure_rate": 3}, cls.__name__


def test_each_scenario_has_its_own_toggle_and_threshold():
    for cls, (toggle, thresh) in SCENARIOS.items():
        s = _s(cls)
        assert s._rest_alternative([_wit(2)], {}, {toggle: False}, 30) is None, f"{cls.__name__} {toggle}"
        assert s._rest_alternative([_wit(15)], {}, {thresh: 20}, 30) == _wit(15), f"{cls.__name__} {thresh}"


def test_base_strategy_still_rests():
    # the shared base keeps the old behaviour; only scenarios opt in
    assert BaseTrainingStrategy.__new__(BaseTrainingStrategy)._rest_alternative([_wit(2)], {}, {}, 30) is None


# ---------------- the energy-trap guard ----------------

def test_a_much_better_board_rests_instead_of_taking_wit():
    """THE REGRESSION THIS GUARD EXISTS FOR. Substituting Wit unconditionally made a live run WORSE:
    the bot sat at HP <= 48 for 52 of 78 turns, took 25 rest-gate Wit substitutions, trained Speed
    only 9 times, and finished Speed 774 / Wit 856 -- Wit the top stat in a SPEED build, rank A
    (down from A+ with 15 Speed trainings). Rest turns did not even drop (5 -> 5). The real board it
    got wrong: Wit 12 stats / 0 partners chosen over Speed 30 stats / 3 partners, because Speed cost
    energy the bot never rebuilt. Resting restores the 40-70 energy that unlocks the better board."""
    strong = {"command_type": 1, "command_id": 101, "failure_rate": 22,
              "params_inc_dec_info_array": [{"target_type": 1, "value": 30}]}
    weak_wit = {"command_type": 1, "command_id": 106, "failure_rate": 0,
                "params_inc_dec_info_array": [{"target_type": 5, "value": 12}]}
    for cls in SCENARIOS:
        assert _s(cls)._rest_alternative([strong, weak_wit], {}, {}, 14) is None, cls.__name__


def test_a_comparable_board_still_takes_wit():
    # 18 vs 14 is only 1.29x -- below wit_rest_skip_ratio, so Wit still beats a dead rest turn
    ok = {"command_type": 1, "command_id": 101, "failure_rate": 0,
          "params_inc_dec_info_array": [{"target_type": 1, "value": 18}]}
    wit = {"command_type": 1, "command_id": 106, "failure_rate": 0,
           "params_inc_dec_info_array": [{"target_type": 5, "value": 14}]}
    for cls in SCENARIOS:
        assert _s(cls)._rest_alternative([ok, wit], {}, {}, 20) == wit, cls.__name__


def test_skip_ratio_is_tunable_and_can_be_disabled():
    strong = {"command_type": 1, "command_id": 101, "failure_rate": 0,
              "params_inc_dec_info_array": [{"target_type": 1, "value": 30}]}
    wit = {"command_type": 1, "command_id": 106, "failure_rate": 0,
           "params_inc_dec_info_array": [{"target_type": 5, "value": 12}]}
    g = _s(MantStrategy)
    assert g._rest_alternative([strong, wit], {}, {"wit_rest_skip_ratio": 0}, 14) == wit   # old behaviour
    assert g._rest_alternative([strong, wit], {}, {"wit_rest_skip_ratio": 3.0}, 14) == wit  # 2.5x < 3.0


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
