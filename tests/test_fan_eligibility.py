"""Goal ENTRY-fan guard: race to earn the fans an upcoming goal race needs to ENTER.

Live failure this exists to prevent (career_log_20260721_115707): Copano Rickey's turn-47 goal was the
Champions Cup, which needs 12,000 fans to enter. She sat on 11,196 for turns 40-46 -- training earns no
fans -- so the race was never offered and the career failed at turn 47.

HARD RULE covered here: it may only pick a race the trainee can ACTUALLY RUN (surface AND distance).
Without that filter the fallback grabbed Stayers Stakes -- a 3600m TURF stayer race -- for a dirt miler.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.races import RacePlanner


class _Store:
    def race_map(self):
        return {"meta": {}, "program": {}, "instance": {}}

    def career_goals_for(self, chara_id):
        # the turn-47 goal race needs 12,000 fans to ENTER (Champions Cup shape)
        return [{"kind": "race", "turn": 47, "program_id": 80}]


PROGRAM = {
    80:  {"name": "Champions Cup", "distance": 1800, "ground": 2, "entry_fans": 12000, "win_fans": 10000},
    113: {"name": "Miyako Stakes", "distance": 1800, "ground": 2, "entry_fans": 1000, "win_fans": 3800},
    91:  {"name": "Stayers Stakes", "distance": 3600, "ground": 1, "entry_fans": 2000, "win_fans": 6200},
    502: {"name": "Make Debut", "distance": 1600, "ground": 2, "entry_fans": 0, "win_fans": 700},
}

# a DIRT miler: runnable on the dirt 1800 (113), NOT on the 3600m turf stayer (91)
DIRT_MILER = {113: (7, 7), 91: (1, 1), 80: (7, 7), 502: (7, 7)}


def _planner(apt, offered=(80, 91, 113, 502)):
    rp = RacePlanner("/__nope__", data_store=_Store())
    rp.program = PROGRAM
    rp._grade_rank = lambda pid: 0
    rp.available_programs = lambda state: list(offered)
    rp._apt_grades = lambda chara, pid: apt.get(pid, (1, 1))
    return rp


def _state(turn, fans):
    return {"data": {"chara_info": {"card_id": 109801, "turn": turn, "fans": fans}}}


def test_copano_rickey_regression_farms_the_gap():
    # turn 43, 11,196 fans vs a 12,000 gate 4 turns out -> race the SUITED dirt race to close it
    rp = _planner(DIRT_MILER)
    assert rp.eligibility_fan_program(_state(43, 11196)) == 113


def test_never_picks_a_race_she_cannot_run():
    # THE Stayers Stakes bug: the turf 3600m is enterable (2,000) and fan-rich (6,200), but she is a
    # dirt miler -- aptitude is a HARD filter, so it must be skipped even though it scores higher.
    rp = _planner(DIRT_MILER, offered=(80, 91))     # only the goal + the unsuited stayer
    assert rp.eligibility_fan_program(_state(43, 11196)) == 0


def test_prefers_the_biggest_fan_reward_among_runnable():
    rp = _planner({113: (7, 7), 91: (7, 7), 80: (7, 7), 502: (7, 7)})   # suited for BOTH
    assert rp.eligibility_fan_program(_state(43, 11196)) == 91           # 6,200 > 3,800


def test_no_farm_far_from_the_deadline():
    rp = _planner(DIRT_MILER)
    assert rp.eligibility_fan_program(_state(20, 11196)) == 0    # 27 turns out (> window 8)


def test_no_farm_when_fans_already_cover_entry():
    rp = _planner(DIRT_MILER)
    assert rp.eligibility_fan_program(_state(43, 12000)) == 0


def test_skips_the_debut_race():
    rp = _planner(DIRT_MILER, offered=(80, 502))    # only the goal + a debut
    assert rp.eligibility_fan_program(_state(43, 11196)) == 0


def test_off_before_turn_12_and_on_the_goal_turn():
    rp = _planner(DIRT_MILER)
    assert rp.eligibility_fan_program(_state(8, 100)) == 0
    assert rp.eligibility_fan_program(_state(47, 11196)) == 0   # deadline turn itself -> too late


def test_window_is_tunable():
    rp = _planner(DIRT_MILER)
    rp.policy = {"fan_farm_window": 30}
    assert rp.eligibility_fan_program(_state(20, 11196)) == 113


def test_reports_the_shortfall():
    rp = _planner(DIRT_MILER)
    req = rp.next_goal_entry_requirement(_state(43, 11196))
    assert req["entry_fans"] == 12000 and req["short_by"] == 804


# --- fan-COUNT goals ("5,000 fans by turn 28") -- T.M. Opera O (Alt) failed 3 live careers on hers,
# --- once by only 144 fans, because the guard used to skip every kind != "race" goal.
class _FanGoalStore(_Store):
    def career_goals_for(self, chara_id):
        return [{"kind": "fan", "turn": 28, "fans": 5000, "require": "5,000 fans"}]


def _fan_goal_planner(apt=DIRT_MILER, offered=(113, 91)):
    rp = RacePlanner("/__nope__", data_store=_FanGoalStore())
    rp.program = PROGRAM
    rp._grade_rank = lambda pid: 0
    rp.available_programs = lambda state: list(offered)
    rp._apt_grades = lambda chara, pid: apt.get(pid, (1, 1))
    return rp


def test_fan_count_goal_is_seen_as_a_wall():
    rp = _fan_goal_planner()
    req = rp.next_goal_entry_requirement(_state(24, 4856))
    assert req["kind"] == "fan" and req["needed"] == 5000 and req["short_by"] == 144


def test_tm_opera_o_regression_farms_the_144_fan_gap():
    # turn 24, 4,856 fans, 5,000 needed by turn 28 -> race the SUITED one instead of failing by 144
    rp = _fan_goal_planner()
    assert rp.eligibility_fan_program(_state(24, 4856)) == 113


def test_fan_count_goal_still_respects_aptitude():
    # only the unsuited turf stayer is offered -> still refuse it
    rp = _fan_goal_planner(offered=(91,))
    assert rp.eligibility_fan_program(_state(24, 4856)) == 0


def test_fan_count_goal_met_needs_no_farming():
    rp = _fan_goal_planner()
    assert rp.eligibility_fan_program(_state(24, 5000)) == 0


# --- Junior fan-count goal (~3,000 by turn 24): the MANDATORY Asahi/Hopeful/dirt race (run at turn
# --- 23/24 by fan_goal_program, 7,000 turf / 4,200 dirt win-fans) clears it on its own, so DON'T
# --- pre-farm an off-schedule race. Live symptom: a turf-A Oguri was sent to Niigata Junior Stakes at
# --- turn 16 to top up a goal her turn-23 Asahi Hai would have cleared anyway.
class _JuniorFanStore(_Store):
    def career_goals_for(self, chara_id):
        return [{"kind": "fan", "turn": 24, "fans": 3000, "require": "3,000 fans"}]


def _junior_planner(apt=DIRT_MILER, offered=(80, 91, 113, 502)):
    rp = RacePlanner("/__nope__", data_store=_JuniorFanStore())
    rp.program = PROGRAM
    rp._grade_rank = lambda pid: 0
    rp.available_programs = lambda state: list(offered)
    rp._apt_grades = lambda chara, pid: apt.get(pid, (1, 1))
    return rp


def _jr_state(turn, fans, turf=7, mile=7, medium=7, dirt=1):
    return {"data": {"chara_info": {"card_id": 100601, "turn": turn, "fans": fans,
                                    "proper_ground_turf": turf, "proper_ground_dirt": dirt,
                                    "proper_distance_mile": mile, "proper_distance_middle": medium}}}


def test_junior_fan_goal_defers_to_the_mandatory_fan_race():
    # turn 16, 1,158 fans vs the 3,000-by-24 goal: a turf-A miler's turn-23 Asahi clears it -> no pre-farm
    rp = _junior_planner()
    assert rp.next_goal_entry_requirement(_jr_state(16, 1158)) == {}
    assert rp.eligibility_fan_program(_jr_state(16, 1158)) == 0


def test_junior_defer_works_for_a_dirt_trainee_too():
    # a dirt specialist (no turf) still has the dirt Zen-Nippon fan race -> defer, don't pre-farm
    rp = _junior_planner()
    assert rp.next_goal_entry_requirement(_jr_state(16, 1158, turf=1, mile=1, medium=1, dirt=7)) == {}


def test_junior_fan_goal_still_farms_when_no_fan_race_aptitude():
    # can't run ANY Junior fan race (turf AND dirt below the floor) -> keep the pre-farm safety net
    rp = _junior_planner()
    req = rp.next_goal_entry_requirement(_jr_state(16, 1158, turf=1, mile=1, medium=1, dirt=1))
    assert req.get("kind") == "fan" and req.get("short_by") == 1842


# ---------------- Junior farming stays on the three fan G1s ----------------

class _G1FarmStore(_Store):
    def career_goals_for(self, chara_id):
        # Silence Suzuka's real shape: a turn-25 goal RACE, no fan-count goal at all
        return [{"kind": "race", "turn": 25, "program_id": 178, "race": "Shinzan Kinen"}]


# 624 Asahi (turf mile G1), 1107 Zen-Nippon (dirt G1) = allowed;
# 632/633 = the ordinary Junior races the live run wrongly picked.
G1_FARM_PROGRAM = {
    624:  {"name": "Asahi Hai Futurity Stakes", "distance": 1600, "ground": 1,
           "entry_fans": 0, "win_fans": 7000},
    1107: {"name": "Zen-Nippon Junior Yushun", "distance": 1600, "ground": 2,
           "entry_fans": 0, "win_fans": 4200},
    632:  {"name": "Saudi Arabia Royal Cup", "distance": 1800, "ground": 1,
           "entry_fans": 0, "win_fans": 2000},
    633:  {"name": "Artemis Stakes", "distance": 1600, "ground": 1,
           "entry_fans": 0, "win_fans": 1800},
    178:  {"name": "Shinzan Kinen", "distance": 1600, "ground": 1,
           "entry_fans": 3000, "win_fans": 2500},
}


def _g1_farm_planner(offered=(624, 1107, 632, 633)):
    rp = RacePlanner("/__nope__", data_store=_G1FarmStore())
    rp.program = G1_FARM_PROGRAM
    rp._grade_rank = lambda pid: 0 if pid in (624, 1107) else 3
    rp.available_programs = lambda state: list(offered)
    rp._apt_grades = lambda chara, pid: (7, 7)
    return rp


def test_junior_fan_farm_only_uses_the_three_fan_g1s():
    """LIVE: Silence Suzuka's turn-25 Shinzan Kinen entry wall sent her to Saudi Arabia Royal Cup
    (t19) and Artemis Stakes (t20) -- neither a goal nor on any schedule. In Junior the farm may
    only use Asahi Hai / Hopeful Stakes / Zen-Nippon Junior Yushun, which pay 7,000/7,000/4,200
    against the ~1-2k of the ordinary Junior races the general picker reached for."""
    rp = _g1_farm_planner()
    got = rp.eligibility_fan_program(_state(19, 500))
    assert got != 632 and got != 633, f"picked an off-plan Junior race: {got}"
    assert got in (0, 624, 1107), got


def test_no_fan_g1_on_the_board_falls_back_rather_than_farming_nothing():
    """The restriction is a PREFERENCE, not a prohibition. T.M. Opera O died 144 fans short of a
    turn-24 fan-count goal on a board carrying no fan G1 -- narrowing to an empty set there would
    farm nothing and re-create that failure, so with none offered the general picker still runs."""
    rp = _g1_farm_planner(offered=(632, 633))
    assert rp.eligibility_fan_program(_state(19, 500)) == 632


def test_the_restriction_can_be_switched_off():
    """Same board, restriction off -> the general picker farms the best ordinary race again."""
    rp = _g1_farm_planner(offered=(632, 633))
    rp.policy = dict(getattr(rp, "policy", {}) or {})
    rp.policy["fan_farm_junior_g1_only"] = False
    got = rp.eligibility_fan_program(_state(19, 500))
    assert got == 632, f"expected the biggest win_fans runnable: {got}"


def test_junior_fan_g1_detection_is_structural():
    """No hardcoded ids: G1 grade, then dirt, or turf in the mile/medium band."""
    rp = _g1_farm_planner()
    got = rp.junior_fan_g1_programs(_state(20, 0))
    assert 624 in got and 1107 in got
    assert 632 not in got and 633 not in got


def test_senior_entry_walls_still_use_the_general_picker():
    """Arima Kinen wants 25,000 and Champions Cup 12,000; the Junior G1s are long gone by then, so
    the restriction must not reach past Junior -- the Copano Rickey case above still passes."""
    assert RacePlanner.JUNIOR_FAN_GOAL_LAST_TURN == 24


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_fan_eligibility: OK")
