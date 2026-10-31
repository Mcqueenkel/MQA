"""Auto-schedule each trainee's career-goal races into the wanted set -- URA/Unity only, NEVER MANT.
So the goal route is entered with no hand-built extra_race_list. The planner is scenario-agnostic:
each scenario's RACE_POLICY (career_bot/scenarios/*.py) is what flips goal_races_only on/off, bound
onto the planner by BaseTrainingStrategy.__init__."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from career_bot.core.races import RacePlanner
from career_bot.scenarios.mant import MantStrategy
from career_bot.scenarios.ura import UraStrategy
from career_bot.scenarios.unity import UnityStrategy


def _planner(goals, policy, program=None):
    r = RacePlanner.__new__(RacePlanner)          # bypass heavy __init__; only exercise wanted_programs
    r.base_dir = None                              # lets a real Strategy(planner) construct against it
    r.meta = {}
    r.program = program or {}
    r.instance = {}
    r.policy = dict(policy)                        # what BaseTrainingStrategy.__init__ binds in production
    r._goals = lambda chara: goals
    return r


def test_goal_scheduling():
    goals = [
        {"kind": "race", "turn": 34, "program_id": 166, "require": "Top 5"},
        {"kind": "race", "turn": 44, "program_id": 168},
        {"kind": "fan",  "turn": 34, "program_id": 0},     # not a race -> ignored
    ]
    # explicit use_race_schedule:False -> the preset race is IGNORED for URA/Unity (goals only), still
    # honoured for MANT. (A populated schedule with NO toggle now defaults ON -- covered elsewhere.)
    preset = {"extra_race_list": [999], "use_race_schedule": False}
    chara = {"card_id": 100100}

    # the per-scenario policies themselves (from the scenario files -- the thing production binds)
    assert UraStrategy.RACE_POLICY["goal_races_only"] is True
    assert UnityStrategy.RACE_POLICY["goal_races_only"] is True
    assert MantStrategy.RACE_POLICY["goal_races_only"] is False

    ura, unity, mant = UraStrategy.RACE_POLICY, UnityStrategy.RACE_POLICY, MantStrategy.RACE_POLICY
    # URA: schedule = the current-turn career-goal race ONLY; preset extra_race_list is ignored
    assert _planner(goals, ura, program={999: {}}).wanted_programs(preset, 34, chara) == [166]
    assert _planner(goals, ura, program={999: {}}).wanted_programs(preset, 44, chara) == [168]
    # a turn with no goal race -> empty (no off-schedule preset fill-in)
    assert _planner(goals, ura, program={999: {}}).wanted_programs(preset, 20, chara) == []
    # Unity is also goals-only
    assert _planner(goals, unity, program={999: {}}).wanted_programs(preset, 34, chara) == [166]
    # MANT: preset only, NEVER career goals
    assert _planner(goals, mant, program={999: {}}).wanted_programs(preset, 34, chara) == [999]
    # unbound/neutral policy (no scenario) -> preset only (backward compat)
    assert _planner(goals, {}, program={999: {}}).wanted_programs(preset, 34, chara) == [999]

    # the binding itself: constructing a strategy stamps its policy onto the planner it receives
    p = _planner(goals, {}, program={999: {}})
    UraStrategy(p)
    assert p.policy["goal_races_only"] is True
    print("career-goal schedule OK (URA/Unity = goals only, MANT = preset only, policy-bound)")


if __name__ == "__main__":
    test_goal_scheduling()
