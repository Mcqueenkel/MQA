"""Unity rest rule (_failure_forces_rest): only TRAIN when the best training's failure rate is low
(< unity_failure_max, default 8%); otherwise REST to protect energy. Two keep-training exceptions
override that at higher failure: after turn 32 a WIT training with >=2 rainbows, or ANY training with
a lot of Aoharu soul bursts ('unity spirit', >=2). The base brain keeps its ~35% ceiling.

Run:
    python tests/test_unity_rest_rule.py
    python -m pytest tests/test_unity_rest_rule.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.training_brain import BaseTrainingStrategy  # noqa: E402
from career_bot.scenarios.unity import UnityStrategy             # noqa: E402


def _unity():
    u = UnityStrategy.__new__(UnityStrategy)
    u._bond_map = lambda chara: {}       # default: no maxed bonds -> 0 rainbows
    return u


def _wit(partners=()):
    return {"command_id": 106, "command_type": 1, "training_partner_array": list(partners)}


def _spd():
    return {"command_id": 101, "command_type": 1, "training_partner_array": []}


def _tds(cid, souls=()):
    return {"team_data_set": {"command_info_array": [
        {"command_id": cid, "soul_event_partner_array": list(souls), "sp_soul_event_partner_array": []}]}}


# --- base brain unchanged: ~35% ceiling --------------------------------------------------------

def test_base_uses_35_percent_ceiling():
    b = BaseTrainingStrategy.__new__(BaseTrainingStrategy)
    assert b._failure_forces_rest(_spd(), {}, {}, {}, 40, 20) is False   # 20% < 35 -> train
    assert b._failure_forces_rest(_spd(), {}, {}, {}, 40, 35) is True    # 35% -> rest


# --- Unity: 8% ceiling --------------------------------------------------------------------------

def test_unity_trains_below_8_rests_at_or_above():
    u = _unity()
    assert u._failure_forces_rest(_spd(), {}, {}, {}, 40, 7) is False    # <8% -> train
    assert u._failure_forces_rest(_spd(), {}, {}, {}, 40, 8) is True     # >=8% -> rest


def test_wit_two_rainbow_after_turn_32_keeps_training():
    u = _unity()
    u._bond_map = lambda chara: {1: 90, 2: 85}          # partners 1,2 maxed -> rainbows
    wit = _wit(partners=[1, 2])
    chara = {}
    # failure 20% (>=8) but a 2-rainbow Wit after turn 32 -> keep training
    assert u._failure_forces_rest(wit, {}, chara, {}, 40, 20) is False
    # same board BEFORE turn 32 -> the exception doesn't apply -> rest
    assert u._failure_forces_rest(wit, {}, chara, {}, 30, 20) is True
    # only 1 rainbow -> not enough -> rest
    u._bond_map = lambda chara: {1: 90}
    assert u._failure_forces_rest(_wit(partners=[1, 2]), {}, chara, {}, 40, 20) is True


def test_unity_spirit_soul_bursts_keep_training():
    u = _unity()
    spd = _spd()
    # 2 soul bursts on this facility -> keep training even at high failure, any turn
    assert u._failure_forces_rest(spd, _tds(101, souls=[7, 8]), {}, {}, 20, 25) is False
    # only 1 soul burst -> not "a lot" -> rest
    assert u._failure_forces_rest(spd, _tds(101, souls=[7]), {}, {}, 20, 25) is True


def test_unity_thresholds_are_tunable():
    u = _unity()
    # raise the ceiling to 15% -> 12% failure now trains
    assert u._failure_forces_rest(_spd(), {}, {}, {"unity_failure_max": 15}, 40, 12) is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("unity rest rule OK")
