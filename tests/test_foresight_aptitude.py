"""Foresight builds a SMART stat target from the trainee's distance aptitude, focused on its real
strengths (B/A/S = grade >= 6). A C-or-below aptitude must NOT pull the build toward its distance.
Grades: C=5, B=6, A=7, S=8.

Run:
    python tests/test_foresight_aptitude.py
    python -m pytest tests/test_foresight_aptitude.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.foresight import CareerForecaster, STAT_KEYS  # noqa: E402

SPD, STA, PWR, GUT, WIT = 0, 1, 2, 3, 4


def _forecast(short=0, mile=0, middle=0, long=0, preset=None, turn=30):
    f = CareerForecaster()   # no base_dir -> empty support map; deck policy sees a 0-count deck
    chara = {"turn": turn, "proper_distance_short": short, "proper_distance_mile": mile,
             "proper_distance_middle": middle, "proper_distance_long": long}
    for k in STAT_KEYS:
        chara[k] = 0
    return f.forecast({"chara_info": chara}, preset or {})


def test_long_aptitude_builds_stamina():
    fc = _forecast(long=7)                       # A-Long
    assert fc.active and fc.archetype.startswith("Long")
    assert fc.stat_targets[STA] >= 1000          # a stayer needs stamina
    assert fc.stat_targets[SPD] >= fc.stat_targets[STA]   # Speed still maxed


def test_short_aptitude_keeps_stamina_lean():
    fc = _forecast(short=6)                       # B-Short
    assert fc.archetype.startswith("Short")
    assert fc.stat_targets[STA] < 500             # a sprinter should NOT chase stamina (kept lean)
    assert fc.stat_targets[GUT] < 500             # nor guts
    assert fc.stat_targets[PWR] >= 1000           # sprint wants power
    assert fc.stat_targets[WIT] >= 800            # Wit valued high (skill activation / safe training)


def test_c_aptitude_does_not_pull_the_build():
    # THE FIX: A-Long + C-Short. The weak C-Short must not drag the build toward a sprint profile.
    fc = _forecast(long=7, short=5)
    assert fc.archetype.startswith("Long")
    assert fc.stat_targets[STA] >= 1000           # Long dominates; C-Short is ignored
    # sanity: with the OLD C+ floor, C-Short would have pulled stamina down toward the short profile


def test_no_strong_aptitude_falls_back_to_middle():
    fc = _forecast(short=5, mile=5, middle=5, long=5)   # all C, no standout
    assert fc.archetype.startswith("Middle")


def test_lone_c_standout_still_builds_for_it():
    fc = _forecast(mile=5, short=1, middle=1, long=1)   # only Mile is above the floor-of-standout
    assert fc.archetype.startswith("Mile")


def test_focus_grade_is_tunable():
    # A-Long + B-Mile. At the default B floor the B-Mile blends in and pulls stamina DOWN; raising the
    # focus to A (7) drops the B-Mile from the blend -> a purer stayer build with MORE stamina.
    blended = _forecast(long=7, mile=6).stat_targets[STA]                                   # B floor
    pure = _forecast(long=7, mile=6, preset={"aptitude_focus_grade": 7}).stat_targets[STA]  # A floor
    assert pure > blended


class _Store:
    """Minimal DataStore stand-in: one trainee's goal races + a race_map."""
    def __init__(self, goal_pids, programs):
        self._goals = [{"kind": "race", "program_id": p} for p in goal_pids]
        self._programs = {str(k): {"distance": v} for k, v in programs.items()}

    def career_goals_for(self, cid):
        return self._goals

    def race_map(self):
        return {"program": self._programs}

    def support_list(self):
        return {}


def _forecast_with_goals(goal_pids, programs, preset=None, **apt):
    f = CareerForecaster(data_store=_Store(goal_pids, programs))
    chara = {"turn": 30, "card_id": 100401,   # card_id//100 = 1004 -> any cid, store ignores it
             "proper_distance_short": apt.get("short", 0), "proper_distance_mile": apt.get("mile", 0),
             "proper_distance_middle": apt.get("middle", 0), "proper_distance_long": apt.get("long", 0)}
    for k in STAT_KEYS:
        chara[k] = 0
    return f.forecast({"chara_info": chara}, preset or {})


def test_goal_stamina_floor_raises_a_lean_build():
    # A SPRINT-apt uma (short=A) whose aptitude build runs lean on stamina (~450), but whose career goal
    # includes a 3200m stayer race -> the floor lifts Stamina to 550 so it can actually finish it.
    lean = _forecast_with_goals([1], {1: 1200}, short=7).stat_targets[STA]      # goal 1200m: no floor
    floored = _forecast_with_goals([1], {1: 3200}, short=7).stat_targets[STA]   # goal 3200m: floor 550
    assert lean < 550
    assert floored >= 550


def test_goal_floor_does_not_lower_a_stayer():
    # A LONG-apt uma already targets ~1150 stamina; a 2500m goal floor (380) must NOT drag it down.
    fc = _forecast_with_goals([1], {1: 2500}, long=7)
    assert fc.stat_targets[STA] >= 1000


def test_goal_floor_tunable():
    # Override the bands: a 3000m goal now demands 900 stamina.
    fc = _forecast_with_goals([1], {1: 3000}, short=7, preset={"goal_stamina_floor": {3000: 900, 0: 300}})
    assert fc.stat_targets[STA] >= 900


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("foresight_aptitude OK")
