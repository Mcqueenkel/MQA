"""Post-race 'Victory!' event -> ALWAYS the bottom (last) option (user rule).

The Victory event shows its choices as varying subsets of select_index 1..4, so the pick
is by POSITION (last shown), never by select_index/good-bad. It's detected via the curated
DB name ('Victory!'), matched by exact story id OR the 708 suffix (char/scenario prefix varies).
A manual override still wins; unrelated events are untouched.

Run:
    python tests/test_victory_bottom.py
    python -m pytest tests/test_victory_bottom.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.events import EventManager  # noqa: E402

VICTORY = {"event_name": "Victory!", "outcomes": {"1": "good", "2": "good", "3": "bad", "4": "bad"}}
DB = {"501004708": VICTORY}   # the curated data/event_outcomes.json shape


def _em(overrides=None):
    em = EventManager(os.path.join(os.path.dirname(__file__), "_tmp_victory_nonexistent"))
    em.outcomes = dict(DB)
    em.choice_outcomes = lambda: {}
    em._read_overrides = lambda: overrides or {}
    return em


def _event(story_id, selects):
    return {"story_id": str(story_id),
            "event_contents_info": {"choice_array": [{"select_index": s} for s in selects]}}


def test_victory_always_bottom():
    em = _em()
    # exact id: select 1 is "good" in the DB -> old logic picks pos 0; rule forces the LAST pos.
    assert em.choose(_event("501004708", [1, 2])) == 1
    # suffix match: a char-prefixed id NOT in the DB but ending 708 -> 4 choices -> last = pos 3.
    assert em.choose(_event("509999708", [1, 2, 3, 4])) == 3
    # subset of two "bad" selects -> still the last POSITION (proves position-based, not good/bad).
    assert em.choose(_event("501004708", [3, 4])) == 1

    # a manual override still wins over the always-bottom rule.
    assert _em(overrides={"501004708": 0}).choose(_event("501004708", [1, 2])) == 0

    # unrelated event is NOT forced to bottom: 3-choice non-victory -> blind fallback pos 1, not 2.
    assert em.choose(_event("123456789", [1, 2, 3])) == 1

    print("victory-bottom OK (always last position; suffix + exact match; override wins; others untouched)")


if __name__ == "__main__":
    test_victory_always_bottom()
