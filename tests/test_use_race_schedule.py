"""Race schedule for non-MANT scenarios (preset extra_race_list). The explicit `use_race_schedule`
toggle wins both ways; when it's UNSET, a POPULATED extra_race_list defaults to ON (a schedule you
built should run). Empty schedule + no toggle -> off. ON -> extra_race_list runs ON TOP of the
mandatory goals, and the forced/optional-race gates open. MANT is unaffected (always uses the schedule).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from career_bot.core.races import RacePlanner
from career_bot.scenarios.ura import UraStrategy
from career_bot.scenarios.unity import UnityStrategy
from career_bot.scenarios.mant import MantStrategy


def _planner(policy, program=None):
    r = RacePlanner.__new__(RacePlanner)
    r.meta = {}; r.program = program or {}; r.instance = {}
    r.rejected = set(); r.rerun_program = 0
    r.policy = dict(policy)
    r._goals = lambda chara: [{"kind": "race", "turn": 34, "program_id": 166}]   # one goal race @ t34
    return r


def _state():   # t34: race command enabled + a training command, scheduled race 999 on offer
    return {"data": {
        "chara_info": {"turn": 34},
        "home_info": {"command_info_array": [
            {"command_type": 4, "command_id": 401, "is_enable": 1},
            {"command_type": 1, "command_id": 101, "is_enable": 1}]},
        "race_condition_array": [{"program_id": 999}]}}


def test_use_schedule_gate():
    us = RacePlanner._use_schedule
    assert us({}) is False                                              # no schedule, no toggle -> off
    assert us({"extra_race_list": []}) is False                        # empty schedule -> off
    assert us({"extra_race_list": [1]}) is True                        # DEFAULT: a schedule you built runs
    assert us({"extra_race_list": [1], "use_race_schedule": False}) is False   # explicit OFF wins
    assert us({"use_race_schedule": True}) is True                     # explicit ON wins (even w/o list)
    assert us({"extra_race_list": [1], "use_race_schedule": True}) is True


def test_use_race_schedule():
    chara = {"card_id": 100100}
    URA, UNITY, MANT = UraStrategy.RACE_POLICY, UnityStrategy.RACE_POLICY, MantStrategy.RACE_POLICY
    prog = {999: {}, 166: {}}
    OFF = {"extra_race_list": [999], "use_race_schedule": False}   # explicit off
    DEFAULT = {"extra_race_list": [999]}                           # no toggle -> defaults ON (has a schedule)
    ON = {"extra_race_list": [999], "use_race_schedule": True}

    # --- wanted_programs ---
    for pol in (URA, UNITY):
        assert _planner(pol, prog).wanted_programs(OFF, 34, chara) == [166], pol       # explicit off -> goals only
        assert _planner(pol, prog).wanted_programs(DEFAULT, 34, chara) == [166, 999], pol  # default -> goals + schedule
        assert _planner(pol, prog).wanted_programs(ON, 34, chara) == [166, 999], pol
    # MANT -> always the schedule, toggle irrelevant
    assert _planner(MANT, prog).wanted_programs(OFF, 34, chara) == [999]
    assert _planner(MANT, prog).wanted_programs(DEFAULT, 34, chara) == [999]

    # --- Unity's closed gates open when effectively-on (default OR explicit ON), stay shut on explicit OFF ---
    assert _planner(UNITY, prog).choose(_state(), OFF) == 0            # explicit off -> no optional race
    assert _planner(UNITY, prog).choose(_state(), DEFAULT) == 999      # default (has schedule) -> runs it
    assert _planner(UNITY, prog).choose(_state(), ON) == 999
    fstate = {"data": {"chara_info": {"turn": 34},
                       "home_info": {"command_info_array": [{"command_type": 4, "command_id": 401, "is_enable": 1}]},
                       "race_condition_array": [{"program_id": 555}, {"program_id": 166}]}}
    assert _planner(UNITY, prog).forced_program(fstate, DEFAULT) == 166   # default: honors goal/schedule
    assert _planner(UNITY, prog).forced_program(fstate, OFF) == 555       # explicit off: Unity game default

    print("use_race_schedule OK (explicit toggle wins; populated schedule defaults ON; MANT unaffected)")


if __name__ == "__main__":
    test_use_schedule_gate()
    test_use_race_schedule()
