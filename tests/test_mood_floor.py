"""Low-mood recovery: at Bad(2)/Awful(1) motivation the bot must recreate to recover mood REGARDLESS
of how good the training board is -- the motivation multiplier crushes every gain, so recovery
outvalues any board. Previously _should_recreate only recovered mood on a weak board (best_score<=0.3),
so a friendship/rainbow deck (usually >0.3) kept training through sinking mood and spiraled to Awful.

Run:
    python tests/test_mood_floor.py
    python -m pytest tests/test_mood_floor.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.training_brain import BaseTrainingStrategy  # noqa: E402

REC = {"command_id": 301}   # a mood-recreation command (truthy)


def _b():
    return BaseTrainingStrategy.__new__(BaseTrainingStrategy)


def test_low_mood_forces_recreation_over_good_board():
    b = _b()
    # THE FIX: Awful(1) mood on a GOOD board (0.8) + energy to spare -> recreate. Old code trained
    # (best_score>0.3 blocked recovery) and let mood spiral.
    assert b._should_recreate(REC, {}, 30, 1, 60, 0.8) is True
    assert b._should_recreate(REC, {}, 30, 2, 60, 0.8) is True     # Bad(2) too


def test_normal_mood_does_not_over_recreate():
    b = _b()
    # Normal(3) on a good board -> keep training (don't waste a turn on recreation).
    assert b._should_recreate(REC, {}, 30, 3, 60, 0.8) is False


def test_low_mood_low_energy_defers_to_rest():
    b = _b()
    # Awful mood but vital below rest_threshold(48) -> DON'T recreate; the rest gate recovers energy
    # (and can nudge mood) so we don't burn a recreation turn while energy is critical.
    assert b._should_recreate(REC, {}, 30, 1, 30, 0.8) is False


def test_no_recreation_available_never_fires():
    b = _b()
    assert b._should_recreate(None, {}, 30, 1, 60, 0.8) is False


def test_summer_camp_never_recreates_even_at_low_mood():
    b = _b()
    # Camp turns (37 in SUMMER_CAMP_TURNS) go all-out training -- no recreation even at Awful mood.
    assert b._should_recreate(REC, {}, 37, 1, 60, 0.8) is False


def test_mood_floor_is_tunable():
    b = _b()
    # Lower the floor to 1 (Awful only): Bad(2) on a good board no longer force-recreates.
    assert b._should_recreate(REC, {"mood_floor": 1}, 30, 2, 60, 0.8) is False
    assert b._should_recreate(REC, {"mood_floor": 1}, 30, 1, 60, 0.8) is True


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("mood_floor OK")
