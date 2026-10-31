"""Career pacing: CAREER (MIN) is the length of one whole career (default 15-16 min). The pause before
each turn is what is left of the budget after the play itself, spread over the turns to come, so a
light career and a busy one both land on the target (a fixed 7-11 s a turn gave MANT careers ~17 min
but busy Grand Live careers 23-24 min). Stop must still end a long pause at once.

Run:
    python tests/test_turn_delay_default.py
    python -m pytest tests/test_turn_delay_default.py
"""
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core import delay as D  # noqa: E402


def test_default_career_length_is_15_to_16_minutes():
    assert (D.CAREER_MINUTES_MIN, D.CAREER_MINUTES_MAX) == (15.0, 16.0)
    assert (D.CAREER_MINUTES_RESTORE_MIN, D.CAREER_MINUTES_RESTORE_MAX) == (15.0, 16.0)  # after NO CD off


def _career(play, start_turn=1, target_min=16.0, seed=7):
    """A career on a fake clock: before each turn the pacing pause, then `play` seconds of play
    (a number, or a function of the turn for an uneven career). Returns its length in minutes."""
    dna = D.TimingDNA(seed)
    pace = {"target": target_min * 60, "t0": 0.0, "start_turn": start_turn, "slept": 0.0, "last_turn": 0}
    t = 0.0
    for turn in range(start_turn, D.CAREER_TURNS + 1):
        pause = dna.career_pause(pace, turn, now=t)
        t += pause
        pace["slept"] += pause
        t += play(turn) if callable(play) else play
    return t / 60


def test_light_and_busy_careers_both_land_on_the_target():
    for play in (3.0, 6.0, 9.0, 12.0):    # seconds of play per turn: light MANT .. busy Grand Live
        minutes = _career(play)
        assert 15.5 <= minutes <= 16.5, (play, minutes)


def test_an_uneven_career_still_lands_on_the_target():
    for play in (lambda turn: 3.0 if turn < 40 else 12.0,      # quiet start, heavy race blocks later
                 lambda turn: 12.0 if turn < 40 else 3.0):
        minutes = _career(play)
        assert 15.5 <= minutes <= 16.5, minutes


def test_a_career_slower_than_the_target_is_not_padded():
    minutes = _career(15.0)               # 78 x 15 s = 19.5 min of play with no pause at all
    assert 19.5 <= minutes <= 20.3, minutes


def test_a_resumed_career_only_gets_its_share_of_the_target():
    minutes = _career(6.0, start_turn=59)          # 20 of 78 turns left
    assert abs(minutes - 16.0 * 20 / 78) < 0.3, minutes


def test_stop_ends_a_long_pause_at_once():
    t0 = time.monotonic()
    D.TimingDNA(seed=12345).simulate_turn_delay(should_abort=lambda: True, seconds=600)
    assert time.monotonic() - t0 < 2, "Stop had to wait out the pause"


def test_the_runner_path_paces_each_turn_once_and_hands_over_its_stop_flag():
    # GateKeeper.wait_turn_delay is what the runner calls (with the turn); begin_career_pacing at start.
    client = SimpleNamespace(call=lambda *a, **k: None, viewer_id=0, should_abort=lambda: True)
    gate = D.GateKeeper(client)
    gate.begin_career_pacing()
    assert 15 * 60 <= gate.__dict__["_pace"]["target"] <= 16 * 60
    t0 = time.monotonic()
    assert gate.wait_turn_delay(1) > 0               # a real pause was planned...
    assert time.monotonic() - t0 < 2                 # ...and Stop cut it short
    assert gate.wait_turn_delay(1) == 0.0            # the same turn again: no second pause
    assert gate.wait_turn_delay(0) == 0.0            # Grand Live's concert screen reports turn 0
    gate.begin_career_pacing()                       # the next career gets a fresh clock
    assert gate.__dict__["_pace"]["t0"] is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
