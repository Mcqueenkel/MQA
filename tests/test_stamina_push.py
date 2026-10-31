"""Grand Live stamina push: in the 16 turns before a long career-goal race (> 2400 m), a training's
Stamina gain earns score while Stamina is short of that race's need (400 up to 3000 m, 500 above).
On 2026-10-20 every failed goal was a 3000 m / 3200 m race run on 220-350 Stamina; the goal-driven
Stamina cap only limited Stamina and nothing aimed for it.

Run:
    python tests/test_stamina_push.py
    python -m pytest tests/test_stamina_push.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.runner import CareerRunner  # noqa: E402
from career_bot.scenarios.grand_live import GrandLiveStrategy  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOURBON = 102602     # goals: T44 Kikuka Sho 3000 m, T56 Tenno Sho Spring 3200 m, T70 Japan Cup 2400 m, T72 Arima 2500 m


def _s():
    return GrandLiveStrategy(race_planner=CareerRunner(ROOT).race_planner)


def _cmd(stamina=15, speed=0):
    arr = [{"target_type": 2, "value": stamina}] if stamina else []
    if speed:
        arr.append({"target_type": 1, "value": speed})
    return {"command_type": 1, "command_id": 105 if stamina else 101, "params_inc_dec_info_array": arr}


def test_targets_follow_the_next_long_goal():
    s = _s()
    at = lambda turn: s._long_goal_stamina({"card_id": BOURBON, "turn": turn})
    assert at(20) == (0, 0)            # Kikuka is 24 turns away: outside the window
    assert at(30) == (400, 14)         # Kikuka Sho, 3000 m -> 400
    assert at(42) == (400, 2)
    assert at(50) == (500, 6)          # Tenno Sho (Spring), 3200 m -> 500
    assert at(68) == (400, 4)          # Arima Kinen 2500 m (Japan Cup 2400 m is not long)


def test_push_is_only_the_gain_that_closes_the_gap_and_grows_near_the_race():
    s = _s()
    chara = lambda turn, sta: {"card_id": BOURBON, "turn": turn, "stamina": sta}
    near = s._stamina_push(_cmd(15), chara(42, 220))                 # 15 useful, 2 turns left
    assert abs(near - 1.5 * (2 - 2 / 16)) < 1e-9
    assert s._stamina_push(_cmd(15), chara(30, 220)) < near           # further out -> smaller
    assert abs(s._stamina_push(_cmd(15), chara(42, 395)) - 0.5 * (2 - 2 / 16)) < 1e-9   # only 5 short
    assert s._stamina_push(_cmd(15), chara(42, 400)) == 0.0          # need met -> switches off
    assert s._stamina_push(_cmd(0, speed=20), chara(42, 220)) == 0.0  # no Stamina in it
    assert s._stamina_push(_cmd(15), chara(20, 100)) == 0.0          # no long goal in the window


def test_the_push_is_part_of_the_training_score():
    s = _s()
    base = {"card_id": BOURBON, "turn": 42, "vital": 80, "max_vital": 100, "motivation": 4,
            "speed": 700, "power": 500, "guts": 400, "wiz": 300}
    short, met = dict(base, stamina=220), dict(base, stamina=450)
    cmd = dict(_cmd(15), failure_rate=0, training_partner_array=[])
    diff = (s._score_command(cmd, {"chara_info": short}, short, {})
            - s._score_command(cmd, {"chara_info": met}, met, {}))
    assert diff > 2.0, diff        # the push (~2.8) dominates the small stat-curve differences


KITASAN = 106802    # T44 Kikuka Sho 3000 m, T56 Tenno Sho Spring 3200 m


def test_only_grand_live_pushes():
    # MANT tried it on 2026-10-30 and scored lower (see training_brain STAMINA_PUSH).
    from career_bot.scenarios.mant import MantStrategy
    from career_bot.scenarios.ura import UraStrategy
    planner = CareerRunner(ROOT).race_planner
    chara = {"card_id": KITASAN, "turn": 42, "stamina": 200}
    assert GrandLiveStrategy(race_planner=planner)._stamina_push(_cmd(15), chara) > 0
    assert GrandLiveStrategy(race_planner=planner)._stamina_push({**_cmd(15), "command_type": 3}, chara) == 0.0
    for cls in (MantStrategy, UraStrategy):
        assert cls(race_planner=planner)._stamina_push(_cmd(15), chara) == 0.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
