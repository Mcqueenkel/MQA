"""Expected-102 probes must not feed the circuit breaker.

The start-102 recovery path (career-active diagnostic, force-delete no-op, succession-rank-point
sweep) generates 102s BY DESIGN while calibrating. Live log 20260706_171909: those probes tripped
the breaker, which then stopped the very career the sweep had just successfully started -- killing
the MANT loop. probing_102() scopes them out; real throttle signals (205/208/5xx) always count.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uma_api.client import UmaClient


def _bare_client():
    c = UmaClient.__new__(UmaClient)   # no network/auth -- just the breaker fields
    c.circuit_tripped = False
    c._err_window = collections.deque()
    c._probe_102_depth = 0
    return c


def test_probe_scope_silences_102_only():
    c = _bare_client()
    # outside any probe scope: 102 counts (the historical safety net stays)
    assert c._should_note_error("single_mode_free/start", 102) is True
    # inside the scope: 102 is an expected calibration probe -> breaker-silent
    with c.probing_102():
        assert c._should_note_error("single_mode_free/start", 102) is False
        assert c._should_note_error("single_mode_free/load", 102) is False
        # nesting works
        with c.probing_102():
            assert c._should_note_error("single_mode_free/finish", 102) is False
        assert c._should_note_error("single_mode_free/start", 102) is False
        # REAL throttle signals still count even while probing
        assert c._should_note_error("single_mode_free/start", 208) is True
        assert c._should_note_error("single_mode_free/start", 205) is True
        assert c._should_note_error("single_mode_free/start", 500) is True
    # scope exits cleanly -> 102 counts again
    assert c._probe_102_depth == 0
    assert c._should_note_error("single_mode_free/start", 102) is True


def test_probe_scope_exits_on_exception():
    # the sweep RAISES on every wrong value -- the scope must unwind correctly through exceptions
    c = _bare_client()
    try:
        with c.probing_102():
            raise Exception("API error 102 on single_mode_free/start")
    except Exception:
        pass
    assert c._probe_102_depth == 0


def test_race_end_out_still_excluded():
    # `call()` checks the routed endpoint, so benign already-done cleanup must stay breaker-silent
    # under every scenario namespace.
    c = _bare_client()
    for prefix in ("single_mode", "single_mode_team", "single_mode_live", "single_mode_free"):
        assert c._should_note_error(f"{prefix}/race_end", 102) is False
        assert c._should_note_error(f"{prefix}/race_out", 102) is False

    # Unity's team-race cleanup is a different operation, not the ordinary race_out no-op.
    assert c._should_note_error("single_mode_team/team_race_out", 102) is True
    assert c._should_note_error("other/race_out_extra", 102) is True
    assert c._should_note_error("single_mode_free/race_end", 208) is True


if __name__ == "__main__":
    test_probe_scope_silences_102_only()
    test_probe_scope_exits_on_exception()
    test_race_end_out_still_excluded()
    print("test_probe_102: OK")
