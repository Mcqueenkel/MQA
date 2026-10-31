"""Runner fixes from the MQA review: race guard on the resume path, sticky breaker stop, Stop during a
breaker cooldown, result-code matching instead of bare digit substrings, a bounded Live 205 retry,
and desync tolerance on the finish path.

Run:
    python tests/test_runner_review_fixes.py
    python -m pytest tests/test_runner_review_fixes.py
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.base import Decision  # noqa: E402
from career_bot.runner import CareerRunner  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COOLDOWN = "Stopped during circuit-breaker cooldown (request not sent)"
# A real 1503 whose embedded servertime happens to contain '205' (the review's own example).
RC1503_WITH_205 = 'API error 1503 on single_mode/race_entry: {"data_headers": {"servertime": 1783520512}}'


def _guard_runner():
    r = CareerRunner.__new__(CareerRunner)
    r._race_attempt_turn = None
    r._race_attempt_count = 0
    r.stop_requested = False
    r.status = {}
    r.logged = []
    r._log = lambda kind, turn, msg="": r.logged.append((kind, turn, msg))
    r._mark = lambda **kw: r.status.update(kw)
    r._scenario_id = lambda preset: 1
    return r


MID_RACE = {"data": {"chara_info": {"turn": 30, "playing_state": 2},
                     "race_start_info": {"program_id": 1234}}}
RESUME = {"current_turn": 30, "phase": "start", "chara_info": {"turn": 30, "playing_state": 3},
          "race_start_info": {"program_id": 1234, "race_horse_data": [{}]}}


class _StuckRaceClient:
    """race_end / race_out answer 1503 forever -- the live loop from commit b264ffc."""

    def __init__(self):
        self.calls = 0

    def race_entry(self, **_kw):
        self.calls += 1
        raise Exception("API error 217 on single_mode/race_entry: {}")

    def race_start(self, **_kw):
        self.calls += 1
        return {}

    def race_end(self, **_kw):
        self.calls += 1
        raise Exception("API error 1503 on single_mode/race_end: {}")

    def race_out(self, **_kw):
        self.calls += 1
        raise Exception("API error 1503 on single_mode/race_out: {}")


def test_resume_path_race_loop_stops_after_the_limit():
    r = _guard_runner()
    r._fresh_career_state = lambda client, strategy=None: MID_RACE
    client = _StuckRaceClient()
    for _ in range(10):
        r._race_progress(client, RESUME, preset={}, source_state=MID_RACE)
    assert r.stop_requested is True, "race_progress never counted -- the 1503 loop is unbounded"
    assert r.status.get("last_action") == "race-stuck-stop"
    assert client.calls == 4 * 3, client.calls    # 4 passes x (start, end, out), then no more traffic


def test_race_and_resume_share_one_counter():
    r = _guard_runner()
    r._fresh_career_state = lambda client, strategy=None: MID_RACE
    client = _StuckRaceClient()
    r._race(client, MID_RACE, {}, {"program_id": 1234, "current_turn": 30})   # pass 1 (entry desync)
    for _ in range(3):
        r._race_progress(client, RESUME, preset={}, source_state=MID_RACE)    # passes 2-4
    assert r.stop_requested is False, "4 passes is still within the default limit"
    r._race_progress(client, RESUME, preset={}, source_state=MID_RACE)        # pass 5
    assert r.stop_requested is True


def test_race_entry_error_with_desync_digits_in_servertime_is_not_a_desync():
    r = _guard_runner()
    r._fresh_career_state = lambda client, strategy=None: MID_RACE

    class _Client:
        def race_entry(self, **_kw):
            raise Exception(RC1503_WITH_205)

    try:
        r._race(_Client(), MID_RACE, {}, {"program_id": 1234, "current_turn": 30})
    except Exception as exc:
        assert "1503" in str(exc)
    else:
        raise AssertionError("a 1503 was treated as a 205 desync because servertime contains '205'")


# --- main-loop (_run) harness -------------------------------------------------------------------

STATE = {"data": {"chara_info": {"turn": 24, "playing_state": 1}}}


class _Strategy:
    """Re-emits `decision` until the runner marks it handled (like GrandLiveStrategy), then idles."""

    def __init__(self, decision):
        self.decision = decision
        self.marked = []
        self.asked = 0

    def next_decision(self, state, preset):
        self.asked += 1
        return Decision("idle", {}, "done") if self.marked else self.decision

    def mark_decision_handled(self, decision, accepted=False):
        self.marked.append(decision)


class _LiveClient:
    def __init__(self, error):
        self.error = error
        self.live_calls = 0

    def call(self, ep, args, retry_205=0):
        self.live_calls += 1
        raise Exception(self.error)


def _loop_runner(scenario_id=3):
    r = CareerRunner(ROOT)
    r.base_dir = Path(tempfile.mkdtemp(prefix="mqa_runner_test_"))   # a crash trace never lands in uma_runtime
    r.status.update(running=True, scenario_id=scenario_id)
    r._log_goal_progress = lambda state, turn: None
    r._track_turn_scores = lambda state: None
    r._debug_turn = lambda state, preset: None
    r._buy_skills = lambda client, state, preset, force, retry=True: state
    r._fresh_career_state = lambda client, strategy=None: STATE
    return r


def _live(turn=24):
    return Decision("grand_live_perform", {"current_turn": turn}, "concert")


def test_live_start_205_gets_one_retry_then_is_consumed():
    r = _loop_runner()
    client = _LiveClient("API error 205 on single_mode_live/live_start: {}")
    strategy = _Strategy(_live())
    r._run(client, {}, STATE, strategy, 10)
    assert client.live_calls == 2, f"live_start 205 retried {client.live_calls}x (want 1 retry)"
    assert len(strategy.marked) == 1
    # unchanged: a master_square 205 is consumed at once
    r = _loop_runner()
    client = _LiveClient("API error 205 on single_mode_live/master_square: {}")
    strategy = _Strategy(Decision("master_square", {"current_turn": 24, "square_id": 3}, "sq"))
    r._run(client, {}, STATE, strategy, 10)
    assert client.live_calls == 1 and len(strategy.marked) == 1


def test_only_a_real_102_marks_the_live_done():
    # Windows curl connect timeout '... after 21024 ms' contains '102'; so can a 217's viewer_id.
    for error in ("Network error on single_mode_live/live_start: curl: (7) Failed to connect after 21024 ms",
                  'API error 217 on single_mode_live/live_start: {"viewer_id": 6816102617175}'):
        r = _loop_runner()
        client = _LiveClient(error)
        strategy = _Strategy(_live())
        r._run(client, {}, STATE, strategy, 3)
        assert strategy.marked == [], f"never-accepted Live was marked done on: {error}"
        assert client.live_calls == 3
    r = _loop_runner()
    client = _LiveClient("API error 102 on single_mode_live/live_start: {}")
    strategy = _Strategy(_live())
    r._run(client, {}, STATE, strategy, 10)
    assert client.live_calls == 1 and len(strategy.marked) == 1


def test_sticky_breaker_flag_stops_the_career():
    # The client's lazy cooldown already cleared circuit_tripped inside the reload; the sticky flag stays.
    class _Client:
        circuit_tripped = False
        circuit_trip_seen = True

    r = _loop_runner()
    strategy = _Strategy(_live())
    r._run(_Client(), {}, STATE, strategy, 10)
    assert strategy.asked == 0, "the runner kept playing after the breaker tripped"
    assert r.status.get("circuit_tripped") is True
    assert r.status.get("last_action") == "auto-backoff"


def test_stop_during_breaker_cooldown_is_a_normal_stop():
    r = _loop_runner(scenario_id=1)

    def _event(client, strategy, payload):
        r.stop()                       # user pressed Stop; the client's should_abort ended the cooldown
        raise Exception(COOLDOWN)

    r._event = _event

    class _Client:
        should_abort = None

    client = _Client()
    client.should_abort = lambda: r.stop_requested     # what start() wires
    r._run(client, {}, STATE, _Strategy(Decision("event", {"event_id": 1}, "ev")), 10)
    assert r.status.get("last_error") == "", r.status.get("last_error")
    assert not any(row["action"] == "error" for row in r.status["log"])
    assert client.should_abort is None, "should_abort must be cleared when the run ends"


def test_fresh_reload_does_not_retry_after_a_cooldown_stop():
    r = CareerRunner(ROOT)
    r.stop()

    class _Client:
        loads = 0

        def login(self):
            pass

        def load_career(self):
            self.loads += 1
            raise Exception(COOLDOWN)

    client = _Client()
    with patch("career_bot.runner.backoff_sleep", lambda *a, **k: None):
        try:
            r._fresh_career_state(client)
        except Exception as exc:
            assert COOLDOWN in str(exc)
    assert client.loads == 1, f"reloaded {client.loads}x after Stop"


def test_start_wires_should_abort_to_stop():
    class _Client:
        current_scenario_id = 1

    class _NoThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    r = CareerRunner(ROOT)
    client = _Client()
    with patch("career_bot.runner.threading.Thread", _NoThread):
        r.start(client, {"name": "t", "scenario_id": 1}, STATE)
    assert callable(client.should_abort) and client.should_abort() is False
    r.stop()
    assert client.should_abort() is True


def test_finish_tolerates_desync_on_race_out_and_close():
    r = _loop_runner(scenario_id=1)
    r.dev_mode = True
    r._record_action = lambda decision, chara=None: None
    r._drain_events = lambda client, strategy, state, limit=20: state
    r._spend_remaining_sp = lambda client, state, preset: state
    r._spark_factor_chooser = lambda client, preset: None

    class _Client:
        def race_out(self, **_kw):
            raise Exception("API error 217 on single_mode/race_out: {}")

        def close_career(self, **_kw):
            raise Exception("API error 208 on single_mode/finish: {}")

    state = {"data": {"chara_info": {"turn": 78, "playing_state": 1, "state": 3},
                      "race_start_info": {"program_id": 1}}}
    r._run(_Client(), {}, state, _Strategy(Decision("finish", {"current_turn": 78}, "end")), 5)
    assert r.status.get("last_error") == "", r.status.get("last_error")
    assert r.status.get("finished") is True


def test_trip_during_finish_still_stops_the_loop():
    # The breaker trips inside the finish (e.g. 205s in the skill dump), after the last loop-top check:
    # the run must still report circuit_tripped, or manage_career_loop starts the next career.
    r = _loop_runner(scenario_id=1)
    r.dev_mode = True
    r._record_action = lambda decision, chara=None: None
    r._drain_events = lambda client, strategy, state, limit=20: state
    r._spend_remaining_sp = lambda client, state, preset: state
    r._spark_factor_chooser = lambda client, preset: None

    class _Client:
        circuit_tripped = False
        circuit_trip_seen = False

        def race_out(self, **_kw):
            raise Exception("API error 217 on single_mode/race_out: {}")

        def close_career(self, **_kw):
            self.circuit_trip_seen = True      # tripped (and cooled down) inside the finish
            raise Exception("API error 208 on single_mode/finish: {}")

    state = {"data": {"chara_info": {"turn": 78, "playing_state": 1, "state": 3},
                      "race_start_info": {"program_id": 1}}}
    r._run(_Client(), {}, state, _Strategy(Decision("finish", {"current_turn": 78}, "end")), 5)
    assert r.status.get("finished") is True
    assert r.status.get("circuit_tripped") is True, "the loop would start another career on a tripped breaker"


def test_pre_race_items_are_not_spent_again_on_a_same_race_retry():
    r = _guard_runner()
    r._scenario_id = lambda preset: 4
    r._pre_race_items_for = None
    r._fresh_career_state = lambda client, strategy=None: MID_RACE
    r._debug = lambda *a, **k: None
    used = []

    class _Items:
        recover_after_use_error = False
        use_attempt_events = []

        def handle_pre_race(self, client, state, preset, payload, status, planner):
            used.append(payload["current_turn"])
            return state, 0

    r.item_manager, r.race_planner = _Items(), None
    client = _StuckRaceClient()        # race_entry 217 -> desync, the same race is kept for a retry
    r._race(client, MID_RACE, {}, {"program_id": 1234, "current_turn": 30})
    r._race(client, MID_RACE, {}, {"program_id": 1234, "current_turn": 30})
    assert used == [30], f"pre-race hammer/glow stick spent {len(used)}x for one race"
    r._race(client, MID_RACE, {}, {"program_id": 999, "current_turn": 30})
    assert used == [30, 30], "a different race on the same turn still gets its items"

def test_event_217_resyncs_and_keeps_draining():
    # Live 2026-10-30 (career_log_20261030_225954): one 217 on check_event ended the career at turn 13.
    r = _guard_runner()
    pending = {"data": {"chara_info": {"turn": 13}, "unchecked_event_array": [{"event_id": 3039}]}}
    done = {"data": {"chara_info": {"turn": 13}, "unchecked_event_array": []}}
    calls = []

    def event(client, strategy, payload):
        calls.append(payload["event_id"])
        if len(calls) == 1:
            raise Exception('API error 217 on single_mode_live/check_event: {"servertime": 1793375994}')
        return done

    class _Client:
        resynced = 0

        def resync_session(self):
            self.resynced += 1

    class _S:
        _choice = staticmethod(lambda event: 0)

    r._event = event
    r._fresh_career_state = lambda client, strategy=None: pending
    client = _Client()
    assert r._drain_events(client, _S(), pending) is done
    assert calls == [3039, 3039] and client.resynced == 1
    assert [k for k, *_ in r.logged] == ["event_desync"]

    calls.clear()                                    # a second desync in the same drain still raises
    r._event = lambda c, s, p: (_ for _ in ()).throw(Exception("API error 217 on x: {}"))
    try:
        r._drain_events(client, _S(), pending)
        raise AssertionError("expected the second 217 to raise")
    except Exception as exc:
        assert "217" in str(exc)


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
