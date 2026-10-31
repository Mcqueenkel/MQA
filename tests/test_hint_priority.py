"""Skill-hint (red '!') training priority is PHASE-GATED: chase hints before Senior (they discount
the end-career skill buy while there's a whole career left to cash them in), then stop prioritising
them from Senior on (turn >= 49) where raw stats matter more. Covers BaseTrainingStrategy._hint_bonus.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.training_brain import BaseTrainingStrategy

W = 0.09   # the base hint weight (weights[3] default)


def _strat():
    return BaseTrainingStrategy(race_planner=None)


def test_prioritised_before_senior():
    s = _strat()
    assert s._hint_bonus(1, 10, W, {}) > 0   # Junior
    assert s._hint_bonus(1, 24, W, {}) > 0   # last Junior turn
    assert s._hint_bonus(1, 48, W, {}) > 0   # last Classic turn (still before Senior)


def test_not_prioritised_from_senior():
    s = _strat()
    assert s._hint_bonus(1, 49, W, {}) == 0.0   # Senior begins -> no hint priority
    assert s._hint_bonus(3, 60, W, {}) == 0.0   # deep Senior, even 3 hints -> 0
    assert s._hint_bonus(4, 78, W, {}) == 0.0   # finale


def test_no_hint_no_bonus():
    s = _strat()
    assert s._hint_bonus(0, 10, W, {}) == 0.0


def test_more_hints_scores_higher():
    s = _strat()
    assert s._hint_bonus(3, 10, W, {}) > s._hint_bonus(1, 10, W, {})
    # capped at 4 -> 5 hints scores the same as 4
    assert s._hint_bonus(5, 10, W, {}) == s._hint_bonus(4, 10, W, {})


def test_presenior_boost_makes_it_important():
    s = _strat()
    # default 2.0x boost -> a single pre-senior hint is worth ~2x the raw base weight
    assert abs(s._hint_bonus(1, 10, W, {}) - W * 2.0) < 1e-9
    # tunable: turn the boost off -> back to the base weight
    assert abs(s._hint_bonus(1, 10, W, {"hint_presenior_boost": 1.0}) - W) < 1e-9


def test_cutoff_turn_is_tunable_but_never_into_senior():
    s = _strat()
    # pull the cutoff earlier -> hints stop at turn 37
    assert s._hint_bonus(1, 30, W, {"hint_priority_until_turn": 37}) > 0
    assert s._hint_bonus(1, 40, W, {"hint_priority_until_turn": 37}) == 0.0
    # pushing it past the Senior start does nothing: hints stay silent in the Senior year
    assert s._hint_bonus(1, 55, W, {"hint_priority_until_turn": 60}) == 0.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_hint_priority: OK")
