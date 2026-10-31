"""Goal-driven Stamina: the bot trains Stamina ON DEMAND, only up to what the trainee's career-GOAL
races need -- never a flat blanket cap. A sprinter (all short/mile goals, e.g. Bakushin) stays at the
low floor so Stamina is never prioritized; a stayer with a long goal lifts it (Kikuka Sho ~400, Tenno
Sho Spring ~500). Grand Live pulls its 1300 Stamina ceiling DOWN to this need.

Covers RacePlanner.stamina_need + GrandLiveStrategy._with_stat_caps.

Run:
    python tests/test_grand_live_stamina_need.py
    python -m pytest tests/test_grand_live_stamina_need.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.races import RacePlanner
from career_bot.scenarios.grand_live import GrandLiveStrategy

# program_id -> race info, mirroring race_map.json['program'] (only distance matters here)
_PROG = {
    900: {"distance": 1200, "name": "Sprinters"},      # sprint
    901: {"distance": 1600, "name": "Mile"},           # mile
    902: {"distance": 2000, "name": "Middle"},         # middle
    168: {"distance": 3000, "name": "Kikuka Sho"},     # long
    4:   {"distance": 3200, "name": "Tenno Sho (Spring)"},  # extended long
}


def _rp(goals):
    rp = RacePlanner.__new__(RacePlanner)               # method-only; skip __init__ / data files
    rp.program = _PROG
    rp._goals = lambda chara: goals                     # stub the goal lookup
    return rp


def _race(pid):
    return {"kind": "race", "program_id": pid}


def test_pure_sprinter_stays_at_floor():
    assert _rp([_race(900), _race(900)]).stamina_need({}) == 300


def test_mile_goal_lifts_to_350():
    assert _rp([_race(900), _race(901)]).stamina_need({}) == 350


def test_kikuka_needs_400():
    assert _rp([_race(900), _race(168)]).stamina_need({}) == 400


def test_tenno_spring_needs_500():
    assert _rp([_race(168), _race(4)]).stamina_need({}) == 500   # max(400, 500)


def test_fan_goals_are_ignored():
    # a fan-count goal has no program_id/distance -> must not affect the stamina need
    assert _rp([{"kind": "fan", "fans": 3000}, _race(900)]).stamina_need({}) == 300


def test_no_goals_returns_floor():
    assert _rp([]).stamina_need({}) == 300


def test_grand_live_caps_stamina_to_need():
    # Grand Live's 1300 ceiling is pulled DOWN to the stayer's 500 need, other stats untouched.
    gl = GrandLiveStrategy.__new__(GrandLiveStrategy)
    gl.race_planner = _rp([_race(4)])                   # Tenno Spring stayer -> need 500
    caps = gl._with_stat_caps({}, {"card_id": 100100})["stat_caps"]
    assert caps["stamina"] == 500
    assert caps["speed"] == 1600 and caps["wiz"] == 1300  # untouched


def test_grand_live_sprinter_stamina_is_low():
    gl = GrandLiveStrategy.__new__(GrandLiveStrategy)
    gl.race_planner = _rp([_race(900)])                 # sprinter -> 300
    caps = gl._with_stat_caps({}, {"card_id": 100100})["stat_caps"]
    assert caps["stamina"] == 300


def test_user_stat_caps_still_win():
    gl = GrandLiveStrategy.__new__(GrandLiveStrategy)
    gl.race_planner = _rp([_race(4)])
    p = {"stat_caps": {"stamina": 800}}
    assert gl._with_stat_caps(p, {"card_id": 100100}) is p   # user's own caps returned unchanged


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
