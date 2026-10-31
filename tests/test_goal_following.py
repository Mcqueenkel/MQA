"""Offline unit tests for JSON-driven career-goal following (RacePlanner goal_* methods).

Pure, injected data. Verifies the bot enters a trainee's scheduled goal race from career_goals.json
(not just the game's forcing), labels it, warns when a fan goal is at risk, and can summarize the
whole schedule for the start-of-career log.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.races import RacePlanner


class _FakeStore:
    def __init__(self, goals_dict):
        self._d = {str(k): v for k, v in goals_dict.items()}

    def race_map(self):
        return {"meta": {}, "program": {}, "instance": {}}

    def career_goals(self):
        return self._d

    def career_goals_for(self, chara_id):
        return (self._d.get(str(int(chara_id))) or {}).get("goals") or []


GOALS = {1038: {"name": "Curren Chan", "goals": [
    {"turn": 12, "kind": "race", "race": "Make Debut", "program_id": 1077, "require": "Complete"},
    {"turn": 23, "kind": "fan", "fans": 3000, "require": "3,000 fans"},
    {"turn": 29, "kind": "race", "race": "Fillies' Revue", "program_id": 170, "require": "Top 5"},
]}}


def _planner():
    rp = RacePlanner("/__nope__", data_store=_FakeStore(GOALS))
    rp.program = {170: {"name": "Fillies' Revue", "distance": 1400, "race_instance_id": 200170},
                  1077: {"name": "Make Debut", "race_instance_id": 900000}}
    return rp


def _state(turn, offered, card_id=103802, fans=0):
    return {"data": {"chara_info": {"card_id": card_id, "turn": turn, "fans": fans},
                     "race_condition_array": [{"program_id": p} for p in offered]}}


def test_enters_scheduled_goal_race():
    rp = _planner()
    assert rp.goal_program(_state(29, offered=[170, 999])) == 170


def test_skips_goal_race_when_not_offered():
    rp = _planner()
    assert rp.goal_program(_state(29, offered=[999])) == 0


def test_no_goal_this_turn():
    rp = _planner()
    assert rp.goal_program(_state(30, offered=[170])) == 0   # goal is turn 29, not 30


def test_fan_goal_is_not_a_race_goal():
    rp = _planner()
    assert rp.goal_program(_state(23, offered=[170])) == 0   # turn 23 goal is a fan goal, not a race


def test_goal_label():
    rp = _planner()
    assert rp.goal_label(_state(29, offered=[170]), 170) == "goal: Fillies' Revue (Top 5)"


def test_goal_risk_fan_unmet_vs_met():
    rp = _planner()
    assert rp.goal_risk(_state(23, offered=[], fans=500)) == "fan goal at risk: 500/3000 fans due turn 23"
    assert rp.goal_risk(_state(23, offered=[], fans=3000)) == ""   # met -> no warning
    assert rp.goal_risk(_state(29, offered=[170])) == ""            # non-fan turn -> no warning


def test_goal_schedule_line():
    rp = _planner()
    line = rp.goal_schedule_line({"card_id": 103802})
    assert line == ("Curren Chan goals -> T12 Make Debut (Complete) | "
                    "T23 3,000 fans | T29 Fillies' Revue (Top 5)")
    assert rp.goal_schedule_line({"card_id": 999999}) == ""         # unknown trainee -> empty


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_goal_following: OK")
