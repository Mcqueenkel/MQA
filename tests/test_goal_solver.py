"""Unit checks for the per-trainee career-goal solver's scoring.

Run:
    python tests/test_goal_solver.py
    python -m pytest tests/test_goal_solver.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core import goal_solver as gs  # noqa: E402
from career_bot.scenarios.mant import MantStrategy  # noqa: E402
from career_bot.scenarios.unity import UnityStrategy  # noqa: E402


def test_distance_band():
    assert gs.distance_band(1200) == "short"
    assert gs.distance_band(1600) == "mile"
    assert gs.distance_band(2000) == "middle"
    assert gs.distance_band(2500) == "long"


def test_placement_demand():
    assert gs.placement_demand("Complete") == 1
    assert gs.placement_demand("Top 5") == 2
    assert gs.placement_demand("Top 3") == 3
    assert gs.placement_demand("Top 2") == 4
    assert gs.placement_demand("WIN (1st)") == 5


def test_goal_fit():
    assert gs.goal_fit(7, 7) == "strong"      # both A
    assert gs.goal_fit(6, 7) == "ok"          # min B
    assert gs.goal_fit(5, 7) == "weak"        # a C drags it to weak


def test_goal_risk():
    assert gs.goal_risk("weak", 3) == "high"          # weak aptitude + must place top 3
    assert gs.goal_risk("weak", 1) == "medium"        # weak but only "complete"
    assert gs.goal_risk("ok", 4) == "medium"          # ok aptitude but must place top 2
    assert gs.goal_risk("strong", 5) == "low"         # strong fit, even a win is low-risk


def test_recommended_style_and_priority():
    apt = {"nige": 7, "senko": 3, "sashi": 1, "oikomi": 1}
    key, label, grade = gs.recommended_style(apt)
    assert key == "nige" and label == "Front-runner" and grade == "A"
    # a long-heavy goal set must push stamina above power
    pri = gs.stat_priority(["long", "long", "middle"], "nige")
    assert pri.index("stamina") < pri.index("power")


def test_solve_card_flags_weak_demanding_goal():
    apt = {"chara_id": 9999, "aptitude": {"short": 3, "mile": 3, "middle": 3, "long": 3,
                                          "turf": 7, "dirt": 1, "nige": 7, "senko": 1, "sashi": 1, "oikomi": 1}}
    goals = [{"turn": 30, "kind": "race", "race": "Test G1", "program_id": "P1", "require": "Top 3"}]
    programs = {"P1": {"distance": 2000, "ground": 1, "name": "Test G1"}}  # middle, turf
    plan = gs.solve_card(1, goals, apt, programs)
    g = plan["goals"][0]
    assert g["band"] == "middle" and g["distance_apt"] == "E"   # middle aptitude 3 == E
    assert g["fit"] == "weak" and g["risk"] == "high"
    assert plan["solvability"]["high_risk_goals"]              # surfaced


def test_goal_emphasis_on_for_non_mant_off_for_mant():
    # The solver plan is wired into training: _goal_stat_emphasis turns a trainee's stat_priority into a
    # normalized per-stat nudge so training follows the career goals from turn 1 -- for every scenario
    # EXCEPT MANT (4). Playing MANT is the only way to disable the career-goal focus.
    unity = UnityStrategy(race_planner=None)                 # scenario 2 -> ON
    emp = unity._goal_stat_emphasis({"card_id": 100101}, {})   # Special Week: stamina-first goals
    assert emp, "Unity/non-MANT must follow career goals"
    assert abs(sum(emp.values()) - 1.0) < 2e-3             # normalized (4-dp rounding) -> strength unchanged
    assert max(emp, key=emp.get) == "stamina"             # follows the goal-demanded stat
    # MANT (scenario 4) is the off-switch -> no goal nudge, whatever the preset says
    mant = MantStrategy(race_planner=None)
    assert mant._goal_stat_emphasis({"card_id": 100101}, {}) == {}
    # even for a non-MANT scenario, a missing card yields no nudge (nothing to solve)
    assert unity._goal_stat_emphasis({}, {}) == {}


def test_merged_emphasis_keeps_sum_one():
    # Blending goal + learned emphasis must stay a sum-1 distribution (only the AIM changes, not the
    # deliberately-small overall strength). With no learned data, it's the pure goal emphasis.
    s = UnityStrategy(race_planner=None)                    # non-MANT -> goal emphasis is active
    m = s._merged_emphasis({}, {"card_id": 100101})
    assert m and abs(sum(m.values()) - 1.0) < 2e-3
    # a learned emphasis blends in and the result is still normalized
    s._train_emphasis = {"power": 1.0}
    s._train_emphasis_loaded = True
    s._goal_emphasis_card = None  # force re-solve
    blended = s._merged_emphasis({}, {"card_id": 100101})
    assert abs(sum(blended.values()) - 1.0) < 2e-3
    assert blended["power"] > m.get("power", 0)           # learned pulled power up


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
