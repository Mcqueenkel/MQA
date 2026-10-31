"""career_bot/core/delay.py -- the "NO CD" kill-switch floor, and the sleeps that must survive it.

Two invariants, both previously untested (delay.py had zero coverage):

  1. NO_CD_MIN_DELAY. With the kill-switch ON, paced calls used to return 0.0 AND the 0.14s
     inter-call floor in UmaClient.call vanished too -- that floor goes through
     dna_sleep -> TimingDNA.sleep, which is itself gated on GLOBAL_DELAYS_DISABLED. Net result was
     literally zero spacing between requests. The floor puts a small real gap back.

  2. backoff_sleep / server_sleep are kill-switch IMMUNE. These are server-mandated waits (208 busy,
     205 stale, throttle walls). If a refactor ever routes them through the kill-switch, a throttled
     retry becomes a zero-sleep hammer loop -- the exact pattern that gets an account flagged. CLAUDE.md
     calls this invariant out by name; nothing tested it until now.

Run:
    python tests/test_delay_floor.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core import delay as D  # noqa: E402


def _dna():
    return D.TimingDNA(seed=12345)


def _disabled(flag):
    """Toggle the module-level kill-switch the way the UI's NO CD button does."""
    D.GLOBAL_DELAYS_DISABLED = flag


def test_kill_switch_returns_exactly_the_configured_floor():
    """Mechanism, not policy: whatever NO_CD_MIN_DELAY is set to (including 0), that is what the
    paced call reports and honours. Written this way so an A/B on the constant doesn't red the suite."""
    _disabled(True)
    try:
        assert _dna().simulate_delay("single_mode_free/check_event") == D.NO_CD_MIN_DELAY
        assert _dna().simulate_turn_delay() == D.NO_CD_MIN_DELAY
    finally:
        _disabled(False)


def test_a_positive_floor_actually_sleeps():
    """A returned number that didn't sleep would be a lie to the caller. Uses its own value so the
    mechanism is verified regardless of what the constant is currently tuned to."""
    _disabled(True)
    original = D.NO_CD_MIN_DELAY
    D.NO_CD_MIN_DELAY = 0.02
    try:
        t0 = time.perf_counter()
        dt = _dna().simulate_delay("single_mode_free/check_event")
        elapsed = time.perf_counter() - t0
        assert dt == 0.02
        assert elapsed >= 0.01, elapsed          # generous: Windows timer tick is coarse
    finally:
        D.NO_CD_MIN_DELAY = original
        _disabled(False)


def test_zero_floor_means_no_sleep_at_all():
    """0 is a legitimate setting -- the `if dt:` guard skips the sleep entirely."""
    _disabled(True)
    original = D.NO_CD_MIN_DELAY
    D.NO_CD_MIN_DELAY = 0.0
    try:
        t0 = time.perf_counter()
        assert _dna().simulate_delay("single_mode_free/check_event") == 0.0
        assert (time.perf_counter() - t0) < 0.005, "0 must not sleep"
    finally:
        D.NO_CD_MIN_DELAY = original
        _disabled(False)


def test_floor_is_tiny_enough_to_stay_a_kill_switch():
    # Guard against someone "fixing" pacing by raising this: NO CD must stay fast. The real
    # humanization path is the kill-switch being OFF, not a big number here. 0 is allowed.
    assert 0 <= D.NO_CD_MIN_DELAY <= 0.1, D.NO_CD_MIN_DELAY


def test_normal_pacing_is_unaffected_by_the_floor():
    _disabled(False)
    dt = _dna().simulate_delay("single_mode_free/check_event")
    # The humanized path must still produce a real, much larger delay than the NO-CD floor.
    assert dt > D.NO_CD_MIN_DELAY, dt


def test_backoff_sleep_is_immune_to_the_kill_switch():
    """A 208/throttle retry must still wait even under NO CD."""
    _disabled(True)
    try:
        t0 = time.perf_counter()
        dt = _dna().backoff_sleep(attempt=1, base=0.05, cap=0.2)
        elapsed = time.perf_counter() - t0
        assert dt > 0, "backoff must never be zero -- that is a hammer loop"
        assert elapsed >= dt * 0.5, (elapsed, dt)
    finally:
        _disabled(False)


def test_server_sleep_is_immune_to_the_kill_switch():
    _disabled(True)
    try:
        t0 = time.perf_counter()
        dt = D.server_sleep(0.02, 0.04)
        assert dt >= 0.02, dt
        assert time.perf_counter() - t0 >= 0.01
    finally:
        _disabled(False)


def test_humanization_sleeps_do_obey_the_kill_switch():
    """The switch must still turn OFF humanization pacing -- that's its whole job."""
    _disabled(True)
    try:
        dna = _dna()
        assert dna.sleep(0.5, 1.0) == 0.0
        assert dna.jittered_sleep(0.5) == 0.0
    finally:
        _disabled(False)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("delay floor OK")
