"""Mid-Lv5-camp recreation fix: a summer camp already pins mood at GREAT (5), so recreating mid-camp
is a wasted turn (0 mood, ~0 energy). At GREAT mood the bot must REST -- or, in Unity, train a safe Wit
via _rest_alternative -- to bank energy for the remaining camp turns. Below GREAT, recreation still
earns a real multiplier and stays.

Live symptom (career_log_20260721_224927 etc.): Unity careers recreated at turns 39/62/63/64 sitting on
20-29 HP and mot5, because Unity has no energy items to rescue the board and the camp branch fell to
`return recreation`.

Drives BaseTrainingStrategy._best_command through the summer-camp branch on a camp turn (39), stubbing
the scoring helpers so the board is a non-rescuable negative (best_score < 0 -> enters the branch,
skips the all-out train path). Run:
    python tests/test_camp_recreation.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.unity import UnityStrategy


REST = {"command_type": 7, "command_id": 701}
REC = {"command_type": 3, "command_id": 301}


def _wit(fail):
    return {"command_type": 1, "command_id": 605, "failure_rate": fail}   # 605 = summer Wit facility


def _spd(fail):
    return {"command_type": 1, "command_id": 601, "failure_rate": fail}   # 601 = summer Speed facility


def _strategy(commands):
    s = UnityStrategy.__new__(UnityStrategy)
    # Non-rescuable NEGATIVE board -> enters the camp branch and skips the all-out train path.
    training = [c for c in commands if c["command_type"] == 1]
    s._pick_scored_training = lambda tr, data, chara, preset, turn: (-1.0, training[0])
    s._stat_capped_trainings = lambda tr, chara, preset: tr
    s._turn_quality_threshold = lambda score, preset, turn: 48
    s._record_turn_quality = lambda *a, **k: None
    s._has_curable_bad_status = lambda chara, preset: False
    s._medic_command = lambda commands: None
    s._scheduled_recreation = lambda *a, **k: None
    return s


def _state(commands, motivation, vital=25, turn=39):   # turn 39 is a Lv5 camp turn
    return {"data": {
        "home_info": {"command_info_array": commands},
        "chara_info": {"turn": turn, "vital": vital, "motivation": motivation, "max_vital": 100},
    }}


def test_great_mood_trains_wit_not_recreation():
    cmds = [REST, REC, _wit(5), _spd(40)]
    got = _strategy(cmds)._best_command(_state(cmds, motivation=5)["data"], _state(cmds, 5)["data"]["chara_info"], {})
    assert int(got.get("command_id") or 0) == 605, f"expected safe Wit train, got {got}"


def test_great_mood_rests_when_wit_unsafe():
    # Wit too risky (>=10% fail) and no other safe train -> REST, still not recreation
    cmds = [REST, REC, _wit(20), _spd(50)]
    got = _strategy(cmds)._best_command(_state(cmds, motivation=5)["data"], _state(cmds, 5)["data"]["chara_info"], {})
    assert int(got.get("command_id") or 0) == 701, f"expected rest, got {got}"


def test_below_great_still_recreates():
    # mot 4 -> recreation still earns a real multiplier, so keep it (unchanged behavior)
    cmds = [REST, REC, _wit(5), _spd(40)]
    got = _strategy(cmds)._best_command(_state(cmds, motivation=4)["data"], _state(cmds, 4)["data"]["chara_info"], {})
    assert int(got.get("command_type") or 0) == 3, f"expected recreation, got {got}"


def test_toggle_forces_rest_path_even_below_great():
    # camp_recreate_below_great=false -> never recreate mid-camp; a safe Wit is trained at any mood
    cmds = [REST, REC, _wit(5)]
    st = _state(cmds, motivation=3)
    got = _strategy(cmds)._best_command(st["data"], st["data"]["chara_info"], {"camp_recreate_below_great": False})
    assert int(got.get("command_id") or 0) == 605, f"expected Wit train, got {got}"


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
