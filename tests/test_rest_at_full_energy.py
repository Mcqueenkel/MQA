"""A REST turn at full energy recovers nothing -- it must never be the answer.

REGRESSION (live): 67 of 118 careers in the 2026-08-03 batch rested inside the first 12 turns at
hp >= 90, including SIX CONSECUTIVE turns at 100/100 (career_log_20260803_183039, preset Front Farm).
Cause: _best_command's "nothing trainable" branch returned `rest or recreation` without ever looking
at vital, so an empty/disabled training board meant rest regardless of energy.

Not energy and not stat caps -- both were ruled out from the logs first: the command payload carried
current_vital 100, and Front Farm caps only stamina (400) against a stamina of 176.

Run:
    python tests/test_rest_at_full_energy.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.training_brain import BaseTrainingStrategy as B  # noqa: E402

REST = {"command_type": 7, "command_id": 701, "is_enable": 1}
RECREATION = {"command_type": 3, "command_id": 301, "is_enable": 1}
TRAIN_SPEED = {"command_type": 1, "command_id": 101, "is_enable": 1, "failure_rate": 0}


def _brain():
    """A bare strategy with the per-career attributes __init__ would normally create.
    __init__ itself wants a live RacePlanner, which an offline test has no business building."""
    b = B.__new__(B)
    b._preset = {}
    b.race_planner = None
    b.event_manager = None
    b._score_history = []
    b._quality_last_turn = None
    b._train_emphasis = {}
    b._train_emphasis_loaded = True
    b._goal_emphasis = {}
    b._raced_turns = set()
    b._fan_raced = False
    b._junior_recreated_turn = None
    return b


def _decide(commands, vital, max_vital=100, preset=None):
    chara = {"turn": 4, "vital": vital, "max_vital": max_vital, "motivation": 4}
    data = {"home_info": {"command_info_array": list(commands)}}
    return _brain()._best_command(data, chara, preset or {}, record=False)


# ---- the helper ----

def test_rest_is_wasted_tracks_the_live_ceiling():
    assert B._rest_is_wasted({"vital": 100, "max_vital": 100}) is True
    assert B._rest_is_wasted({"vital": 104, "max_vital": 104}) is True   # energy-up events raise it
    assert B._rest_is_wasted({"vital": 96, "max_vital": 104}) is True    # within the margin
    assert B._rest_is_wasted({"vital": 40, "max_vital": 100}) is False
    assert B._rest_is_wasted({"vital": 61, "max_vital": 100}) is False


def test_rest_is_wasted_fails_safe_on_missing_data():
    # Unknown ceiling -> keep the historical behaviour rather than invent one.
    assert B._rest_is_wasted({}) is False
    assert B._rest_is_wasted({"vital": 100}) is False
    assert B._rest_is_wasted({"vital": "x", "max_vital": "y"}) is False


# ---- the decision ----

def test_no_trainable_board_at_full_energy_does_not_rest():
    got = _decide([REST, RECREATION], vital=100)
    assert got is RECREATION, got          # mood is a real gain; rest at 100/100 is not


def test_no_trainable_board_at_low_energy_still_rests():
    got = _decide([REST, RECREATION], vital=35)
    assert got is REST, got


def test_rest_still_used_at_full_energy_when_nothing_else_exists():
    # Only rest on offer -> it is the sole legal move; do not return None and strand the turn.
    got = _decide([REST], vital=100)
    assert got is REST, got


def test_a_trainable_board_is_unaffected():
    """With something to train, the "nothing trainable" branch must not be entered at all. The
    scorer itself needs a fully-built strategy, so it is stubbed -- what's under test is the branch."""
    b = _brain()
    # Stub the scoring pipeline wholesale -- it needs a fully-built strategy, and what's under test
    # here is only that the "nothing trainable" branch is NOT entered when training exists.
    b._pick_scored_training = lambda training, data, chara, preset, turn: (5.0, training[0])
    b._turn_quality_threshold = lambda best_score, preset, turn: 48
    # turn 30: past the junior window, so the mandatory pre-debut recreation isn't the answer
    chara = {"turn": 30, "vital": 100, "max_vital": 100, "motivation": 4}
    data = {"home_info": {"command_info_array": [REST, RECREATION, TRAIN_SPEED]}}
    got = b._best_command(data, chara, {}, record=False)
    assert got is not REST and got is not RECREATION, got


def test_the_live_case_six_full_energy_rests():
    """career_log_20260803_183039 turns 2-7: hp 100/100, mood 4, no training taken."""
    for _ in range(6):
        assert _decide([REST, RECREATION], vital=100, max_vital=100) is not REST


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("rest-at-full-energy OK")
