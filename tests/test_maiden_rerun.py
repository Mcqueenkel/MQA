"""Force-maiden-until-first-win safety net. After the trainee LOSES a maiden (the Junior Make Debut or
a Junior/Classic Maiden Race) while still winless, runner._race arms planner.rerun_program; the
strategy then forces the best maiden ON OFFER every turn -- ahead of training, behind mandatory
goal/fan races -- until a rank-1 finish (the first win) clears the arm. Aptitude guard: re-race the
maiden the trainee is likeliest to WIN, not the mismatched one it keeps losing.

Covers: is_maiden_program (name detection), apt_maiden_program (aptitude-fit pick + best-any fallback),
and the strategy override _forced_maiden_program (toggle + armed gating).

Run:
    python tests/test_maiden_rerun.py
    python -m pytest tests/test_maiden_rerun.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.races import RacePlanner            # noqa: E402
from career_bot.core.training_brain import BaseTrainingStrategy  # noqa: E402


def _planner(rerun=0):
    r = RacePlanner.__new__(RacePlanner)                  # bypass _load; inject a tiny program map
    r.meta = {}; r.instance = {}; r.rejected = set(); r.policy = {}; r.rerun_program = rerun
    r.program = {
        100: {"name": "Junior Make Debut", "ground": 1, "distance": 1200},   # turf SPRINT
        200: {"name": "Junior Maiden Race", "ground": 1, "distance": 1600},  # turf MILE
        250: {"name": "Classic Maiden Race", "ground": 1, "distance": 2000}, # turf MEDIUM
        300: {"name": "Satsuki Sho", "ground": 1, "distance": 2000},         # NOT a maiden
    }
    return r


def _state(offered, chara):
    return {"data": {"chara_info": chara,
                     "race_condition_array": [{"program_id": p} for p in offered]}}


# a mile specialist: turf good, mile A, sprint/medium poor
MILER = {"turn": 14, "proper_ground_turf": 7, "proper_ground_dirt": 4,
         "proper_distance_short": 3, "proper_distance_mile": 8,
         "proper_distance_middle": 4, "proper_distance_long": 1}


# --- identification: maiden vs not, purely by name ---------------------------------------------

def test_is_maiden_program_by_name():
    r = _planner()
    assert r.is_maiden_program(100)   # Make Debut
    assert r.is_maiden_program(200)   # Junior Maiden Race
    assert r.is_maiden_program(250)   # Classic Maiden Race
    assert not r.is_maiden_program(300)   # a graded race is not a maiden
    assert not r.is_maiden_program(999)   # unknown pid


# --- picker: which maiden to re-race ------------------------------------------------------------

def test_picks_aptitude_matching_maiden():
    r = _planner()
    st = _state([100, 200, 250, 300], MILER)
    # the MILE maiden (200), not the sprint it keeps losing, and never the non-maiden 300.
    assert r.apt_maiden_program(st, MILER) == 200


def test_prefers_strongest_aptitude_when_several_fit():
    r = _planner()
    chara = {**MILER, "proper_distance_middle": 6}     # medium now runnable, but mile(8) still wins
    st = _state([100, 200, 250], chara)
    assert r.apt_maiden_program(st, chara) == 200      # mile 7+8=15 > medium 7+6=13


def test_falls_back_to_best_any_when_none_fit():
    r = _planner()
    # poor at every band -> no clean (>=6/>=6) fit -> still race the best COMBINED-aptitude maiden.
    bad = {"turn": 14, "proper_ground_turf": 7, "proper_ground_dirt": 4,
           "proper_distance_short": 3, "proper_distance_mile": 5, "proper_distance_middle": 4,
           "proper_distance_long": 1}
    st = _state([100, 200, 250], bad)
    # scores: 100=7+3=10, 200=7+5=12, 250=7+4=11 -> best-any = 200
    assert r.apt_maiden_program(st, bad) == 200


def test_no_maiden_offered_returns_zero():
    r = _planner()
    assert r.apt_maiden_program(_state([300], MILER), MILER) == 0   # only a non-maiden on offer


def test_rejected_maiden_is_skipped():
    r = _planner()
    r.rejected.add((14, 200))                          # mile maiden already rejected this turn
    st = _state([200, 250], MILER)                     # 200 skipped -> best-any among the rest = 250
    assert r.apt_maiden_program(st, MILER) == 250


# --- strategy override: fire only when armed + toggle on ---------------------------------------

def _strategy(planner):
    s = BaseTrainingStrategy.__new__(BaseTrainingStrategy)   # only _forced_maiden_program is exercised
    s.race_planner = planner
    return s


def test_forces_maiden_when_armed():
    s = _strategy(_planner(rerun=100))                 # lost a maiden while winless -> armed
    assert s._forced_maiden_program(_state([100, 200, 300], MILER), MILER, {}) == 200


def test_not_armed_means_train():
    s = _strategy(_planner(rerun=0))                   # no loss recorded -> override off
    assert s._forced_maiden_program(_state([200], MILER), MILER, {}) == 0


def test_toggle_off_disables():
    s = _strategy(_planner(rerun=100))
    assert s._forced_maiden_program(_state([200], MILER), MILER, {"force_maiden_until_win": False}) == 0


def test_armed_but_no_maiden_offered_trains():
    s = _strategy(_planner(rerun=100))
    assert s._forced_maiden_program(_state([300], MILER), MILER, {}) == 0   # only a non-maiden -> train


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("maiden re-run OK")
