"""Forced-race turns must still match the trainee's aptitude.

On a turn where racing is the ONLY enabled command the bot must race something -- but it used to grab
whatever the game listed FIRST. Live effect (career_log_20260721_212011/212609/213208): Oguri Cap is
turf=A / dirt=D and her schedule is 49 turf races with zero dirt, yet every career ran FIVE unscheduled
dirt races (M.C. Nambu Hai x2, Kawasaki Kinen, February S., Kashiwa Kinen) purely from list order.

Now: prefer a race she can actually run (surface + distance), best combined aptitude; fall back to the
game's first entry only when nothing on the board is runnable (the turn is still mandatory).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.races import RacePlanner


class _Store:
    def race_map(self):
        return {"meta": {}, "program": {}, "instance": {}}

    def career_goals_for(self, chara_id):
        return []


class _GoalStore(_Store):
    """A trainee whose career goal on turn 31 is Fukuryu S. (program 1135)."""
    def career_goals_for(self, chara_id):
        return [{"turn": 31, "kind": "race", "race": "Fukuryu S.",
                 "program_id": 1135, "require": "Top 3"}]


def test_race_day_with_no_offered_list_falls_back_to_the_career_goal():
    """Grand Live omits race_condition_array entirely on a Race Day and sends no race_start_info, so
    both race gates found nothing, training was disabled, and next_decision returned "idle" -- the
    career stalled dead on Race Day (career_log_20260723_094646 t31, "Place top 3 in Fukuryu S.").
    The game IS forcing the race, so fall back to the trainee's career-goal program for that turn."""
    rp = RacePlanner("/__nope__", data_store=_GoalStore())
    rp.program = {1135: {"name": "Fukuryu S.", "distance": 1800, "ground": 1}}
    rp._apt_grades = lambda chara, pid: (7, 7)
    state = {"data": {"chara_info": {"card_id": 100601, "turn": 31}, "home_info": {"command_info_array": [
        {"command_type": 1, "command_id": 101, "is_enable": 0},
        {"command_type": 3, "command_id": 301, "is_enable": 0},
        {"command_type": 4, "command_id": 401, "is_enable": 1},   # race is the ONLY enabled command
        {"command_type": 7, "command_id": 701, "is_enable": 0},
    ]}}}                                                           # note: NO race_condition_array
    assert rp.forced_program(state, preset={}) == 1135


def test_goal_fallback_respects_the_rejected_set():
    rp = RacePlanner("/__nope__", data_store=_GoalStore())
    rp.program = {1135: {"name": "Fukuryu S.", "distance": 1800, "ground": 1}}
    rp._apt_grades = lambda chara, pid: (7, 7)
    rp.reject(31, 1135)
    state = {"data": {"chara_info": {"card_id": 100601, "turn": 31}, "home_info": {"command_info_array": [
        {"command_type": 4, "command_id": 401, "is_enable": 1},
        {"command_type": 1, "command_id": 101, "is_enable": 0},
    ]}}}
    assert rp.forced_program(state, preset={}) == 0


PROGRAM = {
    1109: {"name": "M.C. Nambu Hai", "distance": 1600, "ground": 2},   # DIRT
    1106: {"name": "Kawasaki Kinen", "distance": 2100, "ground": 2},   # DIRT
    77:   {"name": "Tenno Sho (Autumn)", "distance": 2000, "ground": 1},  # turf
    91:   {"name": "Stayers Stakes", "distance": 3600, "ground": 1},   # turf, long
}

# Oguri-shaped: turf-A mile/medium, dirt-D. (ground_apt, distance_apt) per program.
OGURI = {1109: (4, 7), 1106: (4, 3), 77: (7, 7), 91: (7, 2)}


def _planner(apt):
    rp = RacePlanner("/__nope__", data_store=_Store())
    rp.program = PROGRAM
    rp._apt_grades = lambda chara, pid: apt.get(pid, (1, 1))
    return rp


def _forced_state(offered):
    """A forced-race turn: the race command is enabled and nothing else is."""
    return {"data": {
        "chara_info": {"card_id": 100401, "turn": 43},
        "home_info": {"command_info_array": [
            {"command_type": 4, "command_id": 401, "is_enable": 1},
            {"command_type": 1, "command_id": 101, "is_enable": 0},
        ]},
        "race_condition_array": [{"program_id": p} for p in offered],
    }}


def test_skips_the_dirt_race_listed_first():
    # THE bug: dirt Nambu Hai is listed first, but she is dirt-D -> take the turf race she can run
    rp = _planner(OGURI)
    assert rp.forced_program(_forced_state([1109, 77]), preset={}) == 77


def test_picks_best_aptitude_among_runnable():
    rp = _planner(OGURI)
    # both turf, but Stayers is a 3600m she has no distance for -> Tenno Sho wins
    assert rp.forced_program(_forced_state([91, 77]), preset={}) == 77


def test_falls_back_to_first_when_nothing_is_runnable():
    # she can run neither -> the turn is still mandatory, so take the game's first entry
    rp = _planner(OGURI)
    assert rp.forced_program(_forced_state([1109, 1106]), preset={}) == 1109


def test_respects_the_rejected_set():
    rp = _planner(OGURI)
    rp.reject(43, 77)                     # the good turf race already 205'd
    assert rp.forced_program(_forced_state([1109, 77]), preset={}) == 1109


def test_not_a_forced_turn_returns_zero():
    st = _forced_state([1109, 77])
    st["data"]["home_info"]["command_info_array"][1]["is_enable"] = 1   # training also enabled
    assert _planner(OGURI).forced_program(st, preset={}) == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_forced_race_aptitude: OK")
