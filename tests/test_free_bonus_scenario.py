"""The free-bonus calendar (fixed-turn mood/energy) is MANT-only. It's now MANT-OWNED via polymorphism:
the shared brain calls self._free_mood_bonus(turn) which is 0 for every scenario except MANT, which
overrides it with its calendar. So a URA/Unity career never waits for a bonus that never arrives.

Run:
    python tests/test_free_bonus_scenario.py
    python -m pytest tests/test_free_bonus_scenario.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.mant_free_bonus import free_bonus_within  # noqa: E402
from career_bot.core.training_brain import BaseTrainingStrategy  # noqa: E402
from career_bot.scenarios.mant import MantStrategy  # noqa: E402


def test_mant_calendar_values():
    # free_bonus_within is a MANT-only helper; it returns MANT's calendar values.
    assert free_bonus_within(26, "mood") == 1       # turn 27 = +1 Mood
    assert free_bonus_within(28, "energy") == 20    # turn 29 = +20 Energy
    assert free_bonus_within(30, "mood") == 0       # nothing lands at 31


def test_free_mood_bonus_hook_is_mant_only():
    # Base (URA/Unity) has no calendar -> hook returns 0; MANT overrides it with the calendar.
    assert BaseTrainingStrategy.__new__(BaseTrainingStrategy)._free_mood_bonus(26) == 0
    assert MantStrategy.__new__(MantStrategy)._free_mood_bonus(26) == 1


def test_recreation_differs_by_scenario_near_a_mant_bonus():
    # At mood 4 on turn 26 (a MANT +1-mood arrives turn 27), with the mood_target_recreate opt-in:
    #   MANT waits for the free bonus (4+1>=5) -> does NOT recreate;
    #   base (URA/Unity) has no bonus -> recreates now.
    REC = {"command_id": 301}
    preset = {"mood_target_recreate": True}
    assert MantStrategy.__new__(MantStrategy)._should_recreate(REC, preset, 26, 4, 60, 0.2) is False
    assert BaseTrainingStrategy.__new__(BaseTrainingStrategy)._should_recreate(REC, preset, 26, 4, 60, 0.2) is True


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("free_bonus_scenario OK")
