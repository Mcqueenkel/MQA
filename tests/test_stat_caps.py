"""Per-preset stat_caps: once a stat reaches its cap, the bot drops that stat's TRAINING from the
candidate list (so it won't dedicate a turn to it), while other trainings stay eligible -- the stat
can still climb from events / secondary gains. No-op when caps are absent/zero.

Run:
    python tests/test_stat_caps.py
    python -m pytest tests/test_stat_caps.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.training_brain import BaseTrainingStrategy  # noqa: E402


def _brain():
    return BaseTrainingStrategy.__new__(BaseTrainingStrategy)   # method uses only args + module consts


# command_id -> stat: 101=speed, 105=stamina, 102=power, 103=guts, 106=wiz
TRAIN = [{"command_id": c} for c in (101, 105, 102, 103, 106)]


def ids(cmds):
    return [c["command_id"] for c in cmds]


def test_no_caps_is_noop():
    b = _brain()
    chara = {"speed": 700, "stamina": 700, "power": 700, "guts": 700, "wiz": 700}
    assert ids(b._stat_capped_trainings(TRAIN, chara, {})) == [101, 105, 102, 103, 106]
    assert ids(b._stat_capped_trainings(TRAIN, chara, {"stat_caps": {}})) == [101, 105, 102, 103, 106]
    assert ids(b._stat_capped_trainings(TRAIN, chara, {"stat_caps": {"stamina": 0}})) == [101, 105, 102, 103, 106]


def test_capped_stat_dropped_others_kept():
    b = _brain()
    chara = {"speed": 500, "stamina": 620, "power": 400, "guts": 300, "wiz": 200}
    # stamina at 620 >= cap 600 -> its training (105) is dropped; the rest remain
    assert ids(b._stat_capped_trainings(TRAIN, chara, {"stat_caps": {"stamina": 600}})) == [101, 102, 103, 106]


def test_below_cap_kept():
    b = _brain()
    chara = {"speed": 500, "stamina": 500, "power": 400, "guts": 300, "wiz": 200}
    assert ids(b._stat_capped_trainings(TRAIN, chara, {"stat_caps": {"stamina": 600}})) == [101, 105, 102, 103, 106]


def test_at_cap_exactly_is_dropped():
    b = _brain()
    assert ids(b._stat_capped_trainings(TRAIN, {"stamina": 600}, {"stat_caps": {"stamina": 600}})) == [101, 102, 103, 106]


def test_string_cap_values_ok():
    b = _brain()   # UI number inputs may serialize as strings
    assert ids(b._stat_capped_trainings(TRAIN, {"stamina": 620}, {"stat_caps": {"stamina": "600"}})) == [101, 102, 103, 106]


def test_all_capped_returns_empty():
    b = _brain()
    chara = {"speed": 999, "stamina": 999, "power": 999, "guts": 999, "wiz": 999}
    caps = {"stat_caps": {"speed": 600, "stamina": 600, "power": 600, "guts": 600, "wiz": 600}}
    assert b._stat_capped_trainings(TRAIN, chara, caps) == []


# ---- stat_caps ALSO acts as the scorer's per-stat SOFT TARGET (not only the hard drop above) ----
# Uses Wit (target 4): the only stat with no _climax_stat_credit, so ratio math is clean & deterministic.

def _scorer():
    b = _brain()
    b._merged_emphasis = lambda preset, chara: {}   # neutralize learned/goal emphasis (needs instance state)
    return b


_WIT = {"command_id": 106, "params_inc_dec_info_array": [{"target_type": 5, "value": 100}]}


def test_stat_cap_soft_target_zeroes_over_cap_stat():
    # Wit already at 620; a cap of 600 makes the scorer treat it as over-target -> stat gain zeroed,
    # so a Wit training scores far below its uncapped value. This is the whole feature.
    b = _scorer()
    chara = {"turn": 30, "wiz": 620}
    base = b._score_command(_WIT, {}, chara, {"stat_balance": False})
    capped = b._score_command(_WIT, {}, chara, {"stat_balance": False, "stat_caps": {"wiz": 600}})
    assert base > 0
    assert capped < base * 0.05    # 620 > cap 600 -> ratio > 1 -> gain *= 0


def test_stat_cap_looser_than_game_cap_is_noop():
    # A cap above the live game cap (min(1200, 1300)=1200) must not change scoring.
    b = _scorer()
    chara = {"turn": 30, "wiz": 620}
    base = b._score_command(_WIT, {}, chara, {"stat_balance": False})
    loose = b._score_command(_WIT, {}, chara, {"stat_balance": False, "stat_caps": {"wiz": 1300}})
    assert loose == base


def test_stat_cap_removes_parity_boost():
    # The balance boost keys off cap: an uncapped low Wit (cap 1200, ratio 0.25) gets the toward-660
    # parity nudge; capping it low (cap 350, ratio 0.86) drops it out of the boost band -> no nudge.
    b = _scorer()
    low = {"turn": 30, "wiz": 300}
    boosted = b._score_command(_WIT, {}, low, {})                            # parity boost ON
    capped = b._score_command(_WIT, {}, low, {"stat_caps": {"wiz": 350}})     # boost gone
    assert boosted > capped


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("stat_caps OK")
