"""Skill hints get no priority in the Senior year (turn 49+): not in training scores, not in Grand Live
lesson picks, not in event choices. The panel's "Prioritise hints until turn" can only end it earlier,
and 0 now means 0 (both settings used to fall back to their defaults via `or`).

Run:
    python tests/test_hints_senior.py
    python -m pytest tests/test_hints_senior.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.events import EventManager  # noqa: E402
from career_bot.core.training_brain import BaseTrainingStrategy, SENIOR_START_TURN  # noqa: E402
from career_bot.scenarios.grand_live import GrandLiveStrategy  # noqa: E402


def _hint(turn, preset=None, hints=2):
    s = BaseTrainingStrategy.__new__(BaseTrainingStrategy)
    return s._hint_bonus(hints, turn, 0.09, preset or {})


def test_training_hint_bonus_stops_at_the_senior_year_whatever_the_setting():
    assert SENIOR_START_TURN == 49
    assert _hint(30) > 0
    assert _hint(49) == 0.0 and _hint(70) == 0.0
    assert _hint(60, {"hint_priority_until_turn": 78}) == 0.0     # can't be carried into Senior
    assert _hint(30, {"hint_priority_until_turn": 25}) == 0.0     # can still end earlier


def test_zero_now_means_zero():
    assert _hint(10, {"hint_priority_until_turn": 0}) == 0.0      # used to become 49
    assert _hint(10, {"hint_presenior_boost": 0}) == 0.0          # used to become 2.0


def test_grand_live_hint_lessons_drop_to_last_in_senior():
    # 20000 = Group Lesson (skill hint, 15 dance); 11004 = Makeup Basics (+5 Guts, 10 visual)
    lds = {"next_square_info_array": [{"square_id": 20000}, {"square_id": 11004}],
           "live_performance_info": {"dance": 20, "visual": 20}}
    s = GrandLiveStrategy.__new__(GrandLiveStrategy)
    s._last_turn = 30
    assert s.pick_square(lds, {"grand_live_chase_songs": False}) == 20000
    s._last_turn = 50
    assert s.pick_square(lds, {"grand_live_chase_songs": False}) == 11004
    only_hint = {**lds, "next_square_info_array": [{"square_id": 20000}]}
    assert s.pick_square(only_hint, {"grand_live_chase_songs": False}) == 20000   # still claimed if alone


def _event(story_id="999990001"):
    return {"story_id": story_id, "event_contents_info": {"choice_array": [{"select_index": 1}, {"select_index": 2}]}}


def test_event_hint_must_pick_is_skipped_in_senior():
    em = EventManager(tempfile.mkdtemp())          # temp base dir: events_seen.json lands there
    em._build_hint_pick = lambda story_id, choices, preset: 0     # "option 1 hints a wanted skill"
    assert em.choose(_event(), {"turn": 30, "vital": 80, "motivation": 4}, {}) == 0
    assert em.choose(_event(), {"turn": 55, "vital": 80, "motivation": 4}, {}) == 1   # fallback instead


def test_event_scorers_give_hints_no_value_in_senior():
    em = EventManager(tempfile.mkdtemp())
    hint_effect = [["sk", "+2", 0]]
    em.choose(_event(), {"turn": 30}, {})
    assert em._score_effects(hint_effect, {}, set()) == 2 * em.DB_HINT_VALUE
    em.choose(_event(), {"turn": 60}, {})
    assert em._score_effects(hint_effect, {}, set()) == 0.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
