"""Career-goal GROUP races (master single_mode_route_race.race_type == 4).

A goal row with race_type 4 points at a race GROUP, not a single race: "place in ANY of these".
The generator used to write the group id straight in as a program_id, producing a phantom race the
bot could never enter -- live failure: Copano Rickey's turn-69 goal is group 20003 (the four JBC
Classic dirt variants); it became `program 20003`, was never raced, and the career failed at turn 69
while the fallback picked Queen Elizabeth II Cup (2200m TURF) for a dirt miler.

Covers RacePlanner.goal_program picking a member race -- preferring one the trainee can actually run.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.races import RacePlanner

# the real shape: turn-69 goal = any of the four JBC Classic variants (all dirt)
GOALS = [{"turn": 69, "kind": "race", "race": "JBC Classic",
          "program_id": 1026, "program_ids": [1026, 1112, 1115, 1118], "require": "Top 3"}]

PROGRAM = {
    1026: {"name": "JBC Classic", "distance": 2000, "ground": 2},
    1112: {"name": "JBC Classic", "distance": 2100, "ground": 2},
    1115: {"name": "JBC Classic", "distance": 1800, "ground": 2},
    1118: {"name": "JBC Classic", "distance": 2000, "ground": 2},
    77:   {"name": "Queen Elizabeth II Cup", "distance": 2200, "ground": 1},
}


class _Store:
    def race_map(self):
        return {"meta": {}, "program": {}, "instance": {}}

    def career_goals_for(self, chara_id):
        return GOALS


def _planner(offered, apt):
    rp = RacePlanner("/__nope__", data_store=_Store())
    rp.program = PROGRAM
    rp.available_programs = lambda state: list(offered)
    rp._apt_grades = lambda chara, pid: apt.get(pid, (1, 1))
    return rp


def _state(turn=69):
    return {"data": {"chara_info": {"card_id": 109801, "turn": turn}}}


def test_group_goal_picks_an_offered_member():
    # only the 1800m variant is on the board -> take it (not the listed-first 1026)
    rp = _planner(offered=[77, 1115], apt={1115: (7, 7), 77: (1, 1)})
    assert rp.goal_program(_state()) == 1115


def test_group_goal_prefers_a_member_she_can_run():
    # both offered, but she can only run the 1800m one -> aptitude decides
    rp = _planner(offered=[1026, 1115], apt={1026: (1, 1), 1115: (7, 7)})
    assert rp.goal_program(_state()) == 1115


def test_group_goal_falls_back_when_nothing_is_runnable():
    # unsuited for every member, but the goal is still mandatory -> take an offered one anyway
    rp = _planner(offered=[1026], apt={1026: (1, 1)})
    assert rp.goal_program(_state()) == 1026


def test_no_member_offered_returns_zero():
    rp = _planner(offered=[77], apt={77: (7, 7)})
    assert rp.goal_program(_state()) == 0, "must NOT fall back to a non-member race"


def test_plain_single_program_goal_still_works():
    global GOALS
    saved = GOALS
    try:
        GOALS = [{"turn": 69, "kind": "race", "race": "Tokyo Daishoten",
                  "program_id": 1026, "require": "Top 3"}]          # no program_ids
        rp = _planner(offered=[1026], apt={1026: (7, 7)})
        assert rp.goal_program(_state()) == 1026
    finally:
        GOALS = saved


def test_unknown_kind_goal_is_ignored():
    global GOALS
    saved = GOALS
    try:
        GOALS = [{"turn": 69, "kind": "unknown", "condition_type": 2, "condition_id": 700}]
        rp = _planner(offered=[1026, 77], apt={1026: (7, 7)})
        assert rp.goal_program(_state()) == 0    # never chase an unresolved goal
    finally:
        GOALS = saved


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_goal_race_group: OK")
