"""Unity Wit-over-rest: on a turn the training brain would REST, train Wit instead when Wit is safe
(failure below unity_wit_rest_max, default 10%). Wit recovers energy and builds Unity's 1800 Wit cap,
so a safe Wit train beats a dead rest turn; if even Wit is too risky, rest as usual.

Covers UnityStrategy._rest_alternative (the scenario hook the shared _best_command calls at its rest
gate). Base scenarios (MANT/URA) return None there, so only Unity is affected.

Run:
    python tests/test_unity_wit_over_rest.py
    python -m pytest tests/test_unity_wit_over_rest.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.unity import UnityStrategy
from career_bot.scenarios.mant import MantStrategy


def _u():
    return UnityStrategy.__new__(UnityStrategy)   # method-only; skip __init__ (no data files needed)


def _wit(failure):
    return {"command_id": 106, "failure_rate": failure}          # 106 = Wit facility (stat index 4)


def _spd(failure):
    return {"command_id": 101, "failure_rate": failure}          # 101 = Speed


def test_trains_wit_when_safe():
    # Wit at 6% (< 10) on a would-rest turn -> train it instead of resting
    assert _u()._rest_alternative([_spd(40), _wit(6)], {}, {}, 30) == _wit(6)


def test_rests_when_wit_too_risky():
    # even Wit is 12% (>= 10) -> None -> the brain rests
    assert _u()._rest_alternative([_spd(40), _wit(12)], {}, {}, 30) is None


def test_boundary_is_strict_below():
    # exactly 10% is NOT below 10 -> rest
    assert _u()._rest_alternative([_wit(10)], {}, {}, 30) is None
    assert _u()._rest_alternative([_wit(9)], {}, {}, 30) == _wit(9)


def test_no_wit_offered_rests():
    # Wit not on the board (e.g. already at cap -> stripped from `training`) -> rest
    assert _u()._rest_alternative([_spd(4)], {}, {}, 30) is None


def test_matches_summer_wit_facility():
    # 605 = summer-camp Wit facility (also stat index 4) -> still recognised
    assert _u()._rest_alternative([{"command_id": 605, "failure_rate": 3}], {}, {}, 40) \
        == {"command_id": 605, "failure_rate": 3}


def test_tunable_threshold():
    # raise the bar to 20% -> a 15% Wit now trains
    assert _u()._rest_alternative([_wit(15)], {}, {"unity_wit_rest_max": 20}, 30) == _wit(15)


def test_toggle_off_always_rests():
    assert _u()._rest_alternative([_wit(2)], {}, {"unity_wit_over_rest": False}, 30) is None


def test_the_shared_base_still_rests():
    # The SHARED base keeps the old no-op; scenarios opt in. (MANT and URA have since opted in too --
    # see tests/test_wit_over_rest_all_scenarios.py, which covers all four scenarios.)
    from career_bot.core.training_brain import BaseTrainingStrategy
    assert BaseTrainingStrategy.__new__(BaseTrainingStrategy)._rest_alternative([_wit(2)], {}, {}, 30) is None
    assert MantStrategy.__new__(MantStrategy)._rest_alternative([_wit(2)], {}, {}, 30) == _wit(2)


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
