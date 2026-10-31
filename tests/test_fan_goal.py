"""Offline unit tests for RacePlanner.fan_goal_program (MANDATORY Junior fan race).

Pure, injected data. The Junior fan-count goal is a MUST -- a trainee that never races fails the
career. So on turn 23 (Asahi) / turn 24 (Hopeful) the bot runs the Junior G1 the trainee is best
suited to, with NO aptitude floor (there is no Junior short/long G1 alternative). Mile-priority when
it's A-B; otherwise the stronger band. Independent of any 'fan' goal in career_goals.json.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.races import RacePlanner


class _FakeStore:
    def race_map(self):
        return {"meta": {}, "program": {}, "instance": {}}

    def career_goals_for(self, chara_id):
        return []   # deliberately empty: the fan race must NOT depend on this data


# Asahi = 1600m turf mile G1; Hopeful = 2000m turf medium G1 (instance prefix 1 -> grade rank 0);
# 1107 = Zen-Nippon Junior Yushun, the DIRT Junior G1 (ground 2, turn 24, ~4,200 fans);
# 99 = a 1200m G3 (instance prefix 3 -> ignored).
PROGRAM = {
    624: {"distance": 1600, "race_instance_id": 102201, "name": "Asahi Hai Futurity Stakes"},
    625: {"distance": 2000, "race_instance_id": 102401, "name": "Hopeful Stakes"},
    1107: {"distance": 1600, "race_instance_id": 110801, "name": "Zen-Nippon Junior Yushun",
           "ground": 2, "win_fans": 4200},
    99: {"distance": 1200, "race_instance_id": 302201, "name": "Junior G3"},
}


def _planner():
    rp = RacePlanner("/__nope__", data_store=_FakeStore())
    rp.program = PROGRAM
    return rp


def _state(turn, mile, medium, offered, turf=0, dirt=0):
    return {"data": {
        "chara_info": {"card_id": 103802, "turn": turn,
                       "proper_distance_mile": mile, "proper_distance_middle": medium,
                       "proper_ground_turf": turf, "proper_ground_dirt": dirt},
        "race_condition_array": [{"program_id": p} for p in offered],
    }}


def test_mile_suited_runs_asahi_at_23():
    rp = _planner()
    assert rp.fan_goal_program(_state(23, mile=7, medium=1, offered=[624, 99])) == 624


def test_medium_suited_runs_hopeful_at_24():
    rp = _planner()
    assert rp.fan_goal_program(_state(24, mile=1, medium=7, offered=[625])) == 625


def test_mile_takes_priority_when_AB():
    # mile B (6) beats medium A (7) -> Asahi (the user's explicit mile-priority rule)
    rp = _planner()
    assert rp.fan_goal_program(_state(23, mile=6, medium=7, offered=[624, 625])) == 624


def test_low_aptitude_still_races():
    # THE bug this fixes: a mile-C / medium-G Oguri (mile=5, medium=1) MUST still race the fan G1.
    rp = _planner()
    assert rp.fan_goal_program(_state(23, mile=5, medium=1, offered=[624])) == 624


def test_terrible_aptitude_still_races():
    # even both-G aptitude -> still runs one (no Junior short/long G1 exists; the fan clear is a MUST)
    rp = _planner()
    assert rp.fan_goal_program(_state(23, mile=1, medium=1, offered=[624])) == 624


def test_dirt_uma_runs_zen_nippon_at_24():
    # THE fix: a dirt-specialist (turf G, dirt A) runs the DIRT Junior G1 (Zen-Nippon), not a turf race
    rp = _planner()
    assert rp.fan_goal_program(_state(24, mile=7, medium=1, offered=[625, 1107], turf=1, dirt=7)) == 1107


def test_dirt_uma_never_runs_turf_asahi_at_23():
    # the reported bug: on turn 23 a dirt uma must WAIT for its dirt G1, never get forced onto turf Asahi
    rp = _planner()
    assert rp.fan_goal_program(_state(23, mile=7, medium=1, offered=[624], turf=1, dirt=7)) == 0
    # even if the dirt G1 were somehow offered on 23, it still waits for the real turn-24 running
    assert rp.fan_goal_program(_state(23, mile=7, medium=1, offered=[624, 1107], turf=1, dirt=7)) == 0


def test_versatile_uma_still_takes_higher_fan_turf_g1():
    # turf-A AND dirt-A -> stay on the turf G1 (7,000 > 4,200, and two chances); don't reroute to dirt
    rp = _planner()
    assert rp.fan_goal_program(_state(23, mile=7, medium=1, offered=[624, 1107], turf=7, dirt=7)) == 624


def test_dirt_uma_last_resort_turf_when_no_dirt_g1():
    # a dirt uma on the LAST turn with no dirt G1 on the board -> the turf G1 is the only mandatory option
    rp = _planner()
    assert rp.fan_goal_program(_state(24, mile=1, medium=7, offered=[625], turf=1, dirt=7)) == 625


def test_medium_trainee_waits_for_hopeful_not_asahi():
    # a medium-suited trainee at turn 23 (only Asahi on the board) waits -> races Hopeful at 24
    rp = _planner()
    assert rp.fan_goal_program(_state(23, mile=1, medium=7, offered=[624])) == 0
    assert rp.fan_goal_program(_state(24, mile=1, medium=7, offered=[625])) == 625


def test_missed_asahi_takes_hopeful_at_24():
    # mile-suited but Asahi gone by turn 24 -> Hopeful is the last chance (mandatory)
    rp = _planner()
    assert rp.fan_goal_program(_state(24, mile=7, medium=1, offered=[625])) == 625


# ---- turf-aware fit: both fan G1s are TURF, so the pick requires GROUND aptitude too ----------

def test_turf_A_mile_A_runs_asahi():
    # turf A + mile A -> Asahi Hai (even with medium A too: mile is checked first)
    rp = _planner()
    assert rp.fan_goal_program(_state(23, mile=7, medium=7, offered=[624, 625], turf=7)) == 624


def test_turf_A_medium_A_mile_not_A_runs_hopeful():
    # turf A + medium A, mile only B (not A) -> Hopeful Stakes (the turf-A + medium-A rule)
    rp = _planner()
    assert rp.fan_goal_program(_state(24, mile=6, medium=7, offered=[624, 625], turf=7)) == 625


def test_no_turf_A_falls_back_to_distance_band():
    # medium A but turf only B -> NOT a clean turf-A fit -> fall back to the stronger runnable band
    # (mile 6 >= B) -> Asahi, so a poor-turf trainee isn't steered by distance alone.
    rp = _planner()
    assert rp.fan_goal_program(_state(23, mile=6, medium=7, offered=[624, 625], turf=6)) == 624


def test_only_fires_on_turns_23_24():
    rp = _planner()
    assert rp.fan_goal_program(_state(22, mile=7, medium=7, offered=[624])) == 0   # forecast turn
    assert rp.fan_goal_program(_state(12, mile=7, medium=7, offered=[624])) == 0
    assert rp.fan_goal_program(_state(25, mile=7, medium=7, offered=[624, 625])) == 0


def test_race_not_offered():
    rp = _planner()
    assert rp.fan_goal_program(_state(23, mile=7, medium=7, offered=[99])) == 0  # only a G3 on the board


def test_g3_at_mile_distance_ignored():
    rp = _planner()
    prog = dict(PROGRAM)
    prog[77] = {"distance": 1600, "race_instance_id": 302277, "name": "Mile G3"}
    rp.program = prog
    assert rp.fan_goal_program(_state(23, mile=7, medium=1, offered=[77])) == 0


# --- Only trainees with an actual fan-count goal should run the Junior fan race -------------------
class _NoFanGoalStore:
    """Sakura Bakushin O shape: 11 race goals + the finale, NO kind='fan' entry."""
    def race_map(self):
        return {"meta": {}, "program": {}, "instance": {}}
    def career_goals_for(self, chara_id):
        return [{"turn": 21, "kind": "race", "race": "Keio Hai Junior Stakes", "program_id": 626},
                {"turn": 74, "kind": "finale", "race": "URA Finals"}]


class _FanGoalStore(_NoFanGoalStore):
    def career_goals_for(self, chara_id):
        return [{"turn": 24, "kind": "fan", "fans": 3000, "require": "3,000 fans"}]


class _NoGoalsStore(_NoFanGoalStore):
    def career_goals_for(self, chara_id):
        return []


def _planner_for(store, offered=(624,)):
    from career_bot.core.races import RacePlanner
    rp = RacePlanner("/__nope__", data_store=store())
    rp.program = {624: {"name": "Asahi Hai Futurity Stakes", "distance": 1600, "ground": 1,
                        "race_instance_id": "102201", "win_fans": 7000}}
    rp._grade_rank = lambda pid: 0
    rp.available_programs = lambda state: list(offered)
    return rp


def _turf_miler_state(turn=23):
    return {"data": {"chara_info": {
        "card_id": 104101, "turn": turn, "proper_ground_turf": 7, "proper_ground_dirt": 1,
        "proper_distance_mile": 7, "proper_distance_middle": 4}}}


def test_no_fan_goal_means_no_fan_race():
    """Live report: Sakura Bakushin O ran Asahi Hai despite having no fan-count goal. 42 of the 62
    charas have no fan goal, so they were all burning a Junior turn + energy on it."""
    assert _planner_for(_NoFanGoalStore).fan_goal_program(_turf_miler_state()) == 0


def test_trainee_with_a_fan_goal_still_races():
    assert _planner_for(_FanGoalStore).fan_goal_program(_turf_miler_state()) == 624


def test_missing_goal_data_fails_safe_and_still_races():
    # unknown trainee -> keep the old always-race behaviour; the failure it guards is fatal
    assert _planner_for(_NoGoalsStore).fan_goal_program(_turf_miler_state()) == 624

# --- USER SCHEDULE wins the turn-23/24 slot (MANT free racing) ---------------------------------
# Reported live: "i didnt put asahi but it keep running asahi when i put it as hanshin at turn 23".
# The schedule was never consulted -- forced_program only fires on a RACE-ONLY turn, so on turn 23
# (training still offered) it bailed and this gate picked Asahi by aptitude, returning before
# choose() ever read extra_race_list. The fix returns the SCHEDULED id from here, so the race still
# runs authoritatively (fan goal still guaranteed) but it's the race the user actually asked for.

_HANSHIN = 626   # Hanshin Juvenile Fillies -- the same late-Dec Junior G1 slot as Asahi (624)


def _sched_planner():
    rp = _planner()
    rp.program = dict(PROGRAM)
    rp.program[_HANSHIN] = {"distance": 1600, "race_instance_id": 102601,
                            "name": "Hanshin Juvenile Fillies"}
    return rp


def test_scheduled_race_beats_the_aptitude_pick():
    rp = _sched_planner()
    st = _state(23, mile=7, medium=1, offered=[624, _HANSHIN], turf=7)
    assert rp.fan_goal_program(st) == 624                                   # no preset -> unchanged
    assert rp.fan_goal_program(st, {"extra_race_list": [_HANSHIN]}) == _HANSHIN


def test_scheduled_race_ignored_when_not_on_the_board():
    # Scheduled but not offered this turn -> fall back to the aptitude pick, never skip the fan race.
    rp = _sched_planner()
    st = _state(23, mile=7, medium=1, offered=[624], turf=7)
    assert rp.fan_goal_program(st, {"extra_race_list": [_HANSHIN]}) == 624


def test_empty_schedule_leaves_behaviour_unchanged():
    rp = _sched_planner()
    st = _state(23, mile=7, medium=1, offered=[624, _HANSHIN], turf=7)
    assert rp.fan_goal_program(st, {}) == 624
    assert rp.fan_goal_program(st, {"extra_race_list": []}) == 624


def test_scheduled_race_still_bound_by_the_turn_gate():
    # Outside 23/24 this gate never fires, schedule or not -- choose() owns those turns.
    rp = _sched_planner()
    st = _state(30, mile=7, medium=1, offered=[624, _HANSHIN], turf=7)
    assert rp.fan_goal_program(st, {"extra_race_list": [_HANSHIN]}) == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_fan_goal: OK")
