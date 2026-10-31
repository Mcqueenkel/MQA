"""Grand Live Wit-over-rest: on a turn the training brain would REST, train Wit instead when Wit is
safe (failure below grand_live_wit_rest_max, default 10%). In Grand Live the Wit facility (cmd 106 /
summer 605) is energy-POSITIVE and skill-point-rich -- a manual UG run leans on it ~19x and never
takes a dead rest turn. Mirrors Unity's hook; base scenarios (MANT/URA) still rest.

Covers GrandLiveStrategy._rest_alternative (the scenario hook the shared _best_command calls at its
rest gate).

Run:
    python tests/test_grand_live_wit_over_rest.py
    python -m pytest tests/test_grand_live_wit_over_rest.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.grand_live import GrandLiveStrategy
from career_bot.scenarios.mant import MantStrategy


def _g():
    return GrandLiveStrategy.__new__(GrandLiveStrategy)   # method-only; skip __init__ (no data files)


def _wit(failure):
    return {"command_id": 106, "failure_rate": failure}          # 106 = Wit facility (stat index 4)


def _spd(failure):
    return {"command_id": 101, "failure_rate": failure}          # 101 = Speed


def test_trains_wit_when_safe():
    assert _g()._rest_alternative([_spd(40), _wit(6)], {}, {}, 30) == _wit(6)


def test_rests_when_wit_too_risky():
    assert _g()._rest_alternative([_spd(40), _wit(12)], {}, {}, 30) is None


def test_boundary_is_strict_below():
    assert _g()._rest_alternative([_wit(10)], {}, {}, 30) is None
    assert _g()._rest_alternative([_wit(9)], {}, {}, 30) == _wit(9)


def test_no_wit_offered_rests():
    # Wit not on the board (e.g. already at the 1300 cap -> stripped from `training`) -> rest
    assert _g()._rest_alternative([_spd(4)], {}, {}, 30) is None


def test_matches_summer_wit_facility():
    assert _g()._rest_alternative([{"command_id": 605, "failure_rate": 3}], {}, {}, 40) \
        == {"command_id": 605, "failure_rate": 3}


def test_tunable_threshold():
    assert _g()._rest_alternative([_wit(15)], {}, {"grand_live_wit_rest_max": 20}, 30) == _wit(15)


def test_toggle_off_always_rests():
    assert _g()._rest_alternative([_wit(2)], {}, {"grand_live_wit_over_rest": False}, 30) is None


def test_the_shared_base_still_rests():
    # The SHARED base keeps the old no-op; scenarios opt in. MANT/URA opted in later -- all four are
    # covered together in tests/test_wit_over_rest_all_scenarios.py.
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
