"""Pre-summer mood banking: on the run-up to a Lv5 summer camp (turns 35/36/59/60) the bot must
recreate until mood reaches GREAT (5), so every camp turn trains at the max mood multiplier. Camp
runs all-out with no recreation mid-camp, so mood has to be banked BEFORE it.

Run:
    python tests/test_pre_summer_mood.py
    python -m pytest tests/test_pre_summer_mood.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.training_brain import BaseTrainingStrategy, SUMMER_CONSERVE_TURNS  # noqa: E402

REC = {"command_id": 301}
NB = {"wait_for_free_bonus": False}   # ignore free-bonus timing so the tests are deterministic
OK_VITAL = 70                          # above the precamp rest floor (48) -> mood push may fire


def _b():
    return BaseTrainingStrategy.__new__(BaseTrainingStrategy)


def test_recreates_before_camp_until_great():
    b = _b()
    # every pre-camp run-up turn, below Great + energy to spare -> recreate to lift mood
    for turn in sorted(SUMMER_CONSERVE_TURNS):        # 35, 36, 59, 60
        assert b._pre_summer_mood_command(REC, turn, 3, OK_VITAL, NB) is REC, turn
        assert b._pre_summer_mood_command(REC, turn, 4, OK_VITAL, NB) is REC, turn


def test_already_great_does_nothing():
    b = _b()
    assert b._pre_summer_mood_command(REC, 35, 5, OK_VITAL, NB) is None   # already Great -> bank energy


def test_critical_energy_defers_to_rest():
    b = _b()
    # low mood but CRITICAL vital (<= floor 30) -> DON'T recreate; energy must be banked first (a
    # Great-mood camp is useless with no energy to train). The pre-camp rest handles it.
    assert b._pre_summer_mood_command(REC, 36, 2, 5, NB) is None
    assert b._pre_summer_mood_command(REC, 36, 2, 30, NB) is None    # exactly at the floor 30 -> defer
    # ABOVE the 30 floor (e.g. 40): energy is workable -> recreate for mood (a Wit training would be
    # the soft-rest alternative if mood were already fine; here mood<Great so bank mood for camp).
    assert b._pre_summer_mood_command(REC, 36, 2, 40, NB) is REC
    # the floor is tunable
    assert b._pre_summer_mood_command(REC, 36, 2, 40, {**NB, "precamp_rest_vital": 45}) is None


def test_only_fires_on_prep_turns():
    b = _b()
    assert b._pre_summer_mood_command(REC, 30, 2, OK_VITAL, NB) is None   # ordinary turn
    assert b._pre_summer_mood_command(REC, 37, 2, OK_VITAL, NB) is None   # a Lv5 CAMP turn (train all-out)
    assert b._pre_summer_mood_command(REC, 24, 2, OK_VITAL, NB) is None


def test_no_recreation_or_disabled():
    b = _b()
    assert b._pre_summer_mood_command(None, 35, 2, OK_VITAL, NB) is None                          # no cmd
    assert b._pre_summer_mood_command(REC, 35, 2, OK_VITAL, {**NB, "pre_summer_mood": False}) is None  # opt-out


def test_target_is_tunable():
    b = _b()
    # lower the target to Good(4): mood 4 no longer recreates, mood 3 still does
    assert b._pre_summer_mood_command(REC, 35, 4, OK_VITAL, {**NB, "pre_summer_target": 4}) is None
    assert b._pre_summer_mood_command(REC, 35, 3, OK_VITAL, {**NB, "pre_summer_target": 4}) is REC


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("pre_summer_mood OK")
