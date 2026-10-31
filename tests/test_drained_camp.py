"""Pins the rest-before-camp fix for the drained-camp pathology.

The uma raced into the first Lv5 summer camp at ~0 HP, so all camp turns went to
Wit (the only safe near-0-energy training). The fix: on the race-week turn right
before a Lv5 camp ({36,60}, NOT the actual Lv5 turns 37-40/61-64), REST to bank
energy instead of recreating (recreation restores ~0 energy).

These tests guard:
  - the new rest-before-camp behavior on {36,60} at low vital,
  - byte-identity on a healthy board (still recreates) and on an ACTUAL Lv5 camp
    turn (37) where the `turn not in RACE_VALUE_CAMP_TURNS` exclusion holds,
  - the _summer_conserve_command mirror.

No game/network needed -- synthetic board.

Run:
    python tests/test_drained_camp.py
    python -m pytest tests/test_drained_camp.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.mant import MantStrategy  # noqa: E402
from career_bot.core.training_brain import TRAINING_COMMANDS  # noqa: E402

_S = MantStrategy()
_TRAIN_ID = list(TRAINING_COMMANDS)[0]  # a valid training command_id


def _board():
    """rest (7/701) + generic recreation (3, non-group id) + one high-failure
    training so the camp branch (failure >= 35) always fires."""
    return {
        "home_info": {
            "command_info_array": [
                {"command_type": 7, "command_id": 701, "is_enable": 1},
                {"command_type": 3, "command_id": 1, "is_enable": 1},
                {"command_type": 1, "command_id": _TRAIN_ID, "is_enable": 1,
                 "failure_rate": 50, "training_partner_array": [], "tips_event_partner_array": []},
            ]
        }
    }


def _chara(turn, vital):
    return {"turn": turn, "vital": vital, "max_vital": 100, "motivation": 3,
            "support_card_array": []}


def test_precamp_raceweek_rests_low_vital():
    # t36 / t60 (race week before a Lv5 camp), near-0 vital -> REST (type 7) to bank energy.
    for turn in (36, 60):
        cmd = _S._best_command(_board(), _chara(turn, 5), preset={}, record=False)
        assert cmd is not None and cmd.get("command_type") == 7, (turn, cmd)


def test_healthy_board_still_recreates():
    # t36 healthy vital -> recreation (type 3), unchanged (vital > precamp_rest_vital).
    cmd = _S._best_command(_board(), _chara(36, 80), preset={}, record=False)
    assert cmd is not None and cmd.get("command_type") == 3, cmd


def test_actual_lv5_camp_turn_not_forced_to_rest():
    # t37 is an ACTUAL Lv5 camp turn (in RACE_VALUE_CAMP_TURNS) -> the new rest guard is
    # excluded, keeps existing recreation behavior (type 3), proving the exclusion holds.
    cmd = _S._best_command(_board(), _chara(37, 5), preset={}, record=False)
    assert cmd is not None and cmd.get("command_type") == 3, cmd


def test_conserve_helper_mirror():
    enabled = _board()["home_info"]["command_info_array"]
    rest = _S._rest_command(enabled)
    recreation = _S._recreation_command(enabled)
    # near-0 vital on a conserve turn -> rest (type 7)
    cmd = _S._summer_conserve_command(enabled, 36, 5, -1.0, {}, rest, recreation)
    assert cmd is not None and cmd.get("command_type") == 7, cmd
    # vital above crit but below conserve threshold -> recreation (type 3), unchanged
    cmd = _S._summer_conserve_command(enabled, 36, 45, -1.0, {}, rest, recreation)
    assert cmd is not None and cmd.get("command_type") == 3, cmd


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok", name)
            except AssertionError as e:
                failures += 1
                print("FAIL", name, e)
    sys.exit(1 if failures else 0)
