"""A race the server will not let us finish must stop the career, not spin forever.

Observed live: an endless cycle of
    race_start -> race_end (API error 1503) -> race_out -> load_career -> race_start -> ...
Each pass is ~4 API calls. Treating 102/1503/desync as non-fatal is correct on its own -- it lets a
genuine mid-race hiccup reconcile -- but nothing bounded the RETRIES, so:
  * the generic stuck-turn watchdog only reacts after ~150 iterations (~600 API calls),
  * the circuit breaker tripped, cooled 300s, and handed the loop straight back,
  * repeat until the process is killed.

_race (and the _race_progress resume path, sharing one counter -- see
tests/test_runner_review_fixes.py) counts attempts per turn and stops cleanly past
UMA_RACE_MAX_ATTEMPTS (default 4), so the report is still written and the career can be finished by hand.

Run:
    python tests/test_race_retry_guard.py
    python -m pytest tests/test_race_retry_guard.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.runner import CareerRunner


class _Boom:
    """Stands in for the whole race flow: every attempt raises, as the live 1503 did."""

    def __init__(self):
        self.calls = 0


def _runner():
    r = CareerRunner.__new__(CareerRunner)
    r._race_attempt_turn = None
    r._race_attempt_count = 0
    r.stop_requested = False
    r.status = {}
    r.logged = []
    r._log = lambda kind, turn, msg="": r.logged.append((kind, turn, msg))
    r._mark = lambda **kw: r.status.update(kw)
    r._scenario_id = lambda preset: 4
    return r


def _attempt(runner, turn, sentinel):
    """Call the guard exactly as _race does, stopping before the real race flow."""
    state = {"data": {"chara_info": {"turn": turn}}}
    # The guard runs at the top of _race; if it does NOT stop us it falls through to the scenario
    # work, which we do not want to execute here -- so give it a payload and watch stop_requested.
    before = runner.stop_requested
    try:
        CareerRunner._race(runner, sentinel, state, {}, {"current_turn": turn})
    except Exception:
        pass                       # fell through past the guard into the real flow -> not stopped
    return runner.stop_requested and not before


def test_repeated_races_on_one_turn_eventually_stop():
    r = _runner()
    stops = [_attempt(r, 30, _Boom()) for _ in range(6)]
    assert any(stops), "the guard never fired -- a stuck race would loop forever"
    assert r.stop_requested is True
    assert r.status.get("last_action") == "race-stuck-stop"
    assert "1503" not in (r.status.get("last_error") or "")     # message is about the loop, not the code
    assert "stopping cleanly" in (r.status.get("last_error") or "")


def test_it_takes_more_than_one_attempt():
    # a single failed race must NOT kill the career -- reconciliation is the normal path
    r = _runner()
    assert _attempt(r, 30, _Boom()) is False
    assert r.stop_requested is False


def test_a_new_turn_resets_the_counter():
    r = _runner()
    for _ in range(3):
        _attempt(r, 30, _Boom())
    assert r.stop_requested is False          # still under the limit
    for _ in range(3):
        _attempt(r, 31, _Boom())              # different turn -> counter restarts
    assert r.stop_requested is False, "a new turn must not inherit the previous turn's attempts"
    assert r._race_attempt_turn == 31


def test_limit_is_tunable():
    os.environ["UMA_RACE_MAX_ATTEMPTS"] = "1"
    try:
        r = _runner()
        _attempt(r, 30, _Boom())
        assert _attempt(r, 30, _Boom()) is True    # second attempt exceeds a limit of 1
    finally:
        os.environ.pop("UMA_RACE_MAX_ATTEMPTS", None)


def test_the_giveup_is_logged():
    r = _runner()
    for _ in range(6):
        _attempt(r, 30, _Boom())
    assert any(kind == "race_stuck_giveup" for kind, _t, _m in r.logged)


def test_transient_entry_failure_does_not_blacklist_mandatory_race():
    """Network/SID/busy failures describe the session, not race eligibility. Rejecting the pid here
    makes a required goal race disappear permanently after one recoverable fault."""
    for message in (
        "Network error on race_entry: timed out",
        "API error 201 on single_mode/race_entry",
        "API error 208 on single_mode/race_entry",
        "API error 217 on single_mode/race_entry",
    ):
        r = _runner()
        r._scenario_id = lambda preset: 1
        sentinel = {"data": {"chara_info": {"turn": 30}}}
        r._fresh_career_state = lambda client, strategy=None: sentinel
        rejected = []

        class _Planner:
            def reject(self, turn, pid):
                rejected.append((turn, pid))

        class _Client:
            def race_entry(self, **kwargs):
                raise Exception(message)

        r.race_planner = _Planner()
        out = r._race(_Client(), {"data": {}}, {"scenario_id": 1},
                      {"program_id": 1001, "current_turn": 30, "_strategy": None})
        assert out is sentinel
        assert rejected == [], (message, rejected)
        assert any(kind == "race_entry_retry" for kind, _turn, _msg in r.logged)


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
