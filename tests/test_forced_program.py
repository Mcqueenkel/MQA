"""On a forced race turn, RacePlanner.forced_program runs the user's SCHEDULED race when the
game offers it (MANT is free to race anywhere), instead of the game's default first-listed race.

Run:
    python tests/test_forced_program.py
    python -m pytest tests/test_forced_program.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.races import RacePlanner  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 162 = Oka Sho, 163 = Satsuki Sho -- same turn (Classic Early April) in race_map.json.


def _forced_state(turn, offered_pids, training_enabled=False):
    return {"data": {
        "chara_info": {"turn": turn},
        "home_info": {"command_info_array": [
            {"command_type": 4, "command_id": 401, "is_enable": 1},                 # race enabled
            {"command_type": 1, "command_id": 101, "is_enable": 1 if training_enabled else 0},
        ]},
        "race_condition_array": [{"program_id": p} for p in offered_pids],
    }}


def test_prefers_scheduled_over_game_default():
    rp = RacePlanner(ROOT)
    state = _forced_state(31, [162, 163])   # game lists Oka Sho (162) first
    assert rp.forced_program(state, {"extra_race_list": [163]}) == 163   # scheduled Satsuki wins
    assert rp.forced_program(state, {"extra_race_list": []}) == 162      # none scheduled -> game default
    assert rp.forced_program(state) == 162                               # no preset -> legacy default


def test_falls_back_when_scheduled_not_offered():
    rp = RacePlanner(ROOT)
    state = _forced_state(31, [162])        # only Oka Sho on offer
    assert rp.forced_program(state, {"extra_race_list": [163]}) == 162   # scheduled not offered -> game race


def test_not_forced_when_training_enabled():
    rp = RacePlanner(ROOT)
    state = _forced_state(31, [162], training_enabled=True)
    assert rp.forced_program(state, {"extra_race_list": [163]}) == 0     # not a forced turn


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
