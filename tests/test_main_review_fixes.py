"""main.py review fixes: live ps-5 careers are resumed (never closed), start-102 diagnosis treats a
201 load as "no career here", result codes come from the 'API error <rc> on' prefix (not digits of
servertime/viewer_id), unfinished runner exits stop the loop instead of counting as careers, the
start-retry cooldown survives NO CD, and captured auth is never written to disk."""
from contextlib import contextmanager, nullcontext
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main

# servertime 1783102055 contains both "102" and "205" -- exactly the false-positive shape.
NOISY = 'API error 208 on single_mode_free/start: {"data_headers": {"servertime": 1783102055}}'
LIVE_PS5 = {"data": {
    "chara_info": {"card_id": 100101, "turn": 20, "state": 0, "playing_state": 5},
    "unchecked_event_array": [{"event_id": 1}],
}}


class FakeClient:
    def __init__(self, *, index_chara=None, career_result=None, career_error=None, start_errors=()):
        self.tp_info = {"current_tp": 100, "max_tp": 100}
        self.viewer_id = 123
        self.current_scenario_id = 0
        self.index_chara = index_chara
        self.career_result = career_result
        self.career_error = career_error
        self.start_errors = list(start_errors)
        self.start_calls = 0
        self.load_calls = 0
        self.close_calls = []

    def call(self, endpoint, payload=None):
        assert endpoint == "load/index"
        data = {"tp_info": dict(self.tp_info), "item_list": [{"item_id": 59, "number": 1000}]}
        if self.index_chara:
            data["chara_info"] = dict(self.index_chara)
        return {"data": data}

    def refresh_cached_account_state(self, data):
        pass

    def pre_single_mode(self, _excluded):
        return {"data": {}}

    def start_career(self, **_kwargs):
        self.start_calls += 1
        if self.start_errors:
            raise RuntimeError(self.start_errors.pop(0))
        return {"data": {"chara_info": {"card_id": 100101, "turn": 1}}}

    def probing_102(self):
        return nullcontext()

    def load_career(self):
        self.load_calls += 1
        if self.career_error:
            raise RuntimeError(self.career_error)
        return self.career_result

    def close_career(self, **kwargs):
        self.close_calls.append(kwargs)

    def reset_circuit(self):
        pass


def _request():
    return main.RunCareerRequest(
        card_id=100101, support_card_ids=[1, 2, 3, 4, 5, 6], friend_viewer_id=99,
        friend_card_id=77, parent_id_1=10, parent_id_2=11, scenario_id=4, use_tp=30,
        tp_recovery_mode="off", run_count=0,
    )


@contextmanager
def _patched(**replacements):
    originals = {name: getattr(main, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(main, name, value)
        yield
    finally:
        for name, value in originals.items():
            setattr(main, name, value)


def _start_env(client):
    return _patched(active_client=client, active_account=None, active_dashboard_data=None,
                    active_start_state={}, validate_start_selection=lambda _r: None,
                    selected_succession_rank_point=lambda _r: 0,
                    dna_sleep=lambda *a, **k: None, server_sleep=lambda *a, **k: None)


def test_precheck_resumes_live_event_pending_career_without_closing_it():
    client = FakeClient(index_chara=LIVE_PS5["data"]["chara_info"], career_result=LIVE_PS5)
    with _start_env(client):
        result = main.start_career_from_request(_request())
    assert result == {"success": True, "result": LIVE_PS5, "resumed": True}
    assert client.close_calls == []
    assert client.start_calls == 0


def test_start_102_with_201_load_takes_free_slot_recovery_not_fatal():
    client = FakeClient(career_error="API error 201 on single_mode_live/load: {}",
                        start_errors=["API error 102 on single_mode_free/start: {}"])
    with _start_env(client):
        result = main.start_career_from_request(_request())
    assert result.get("fatal_start") is not True, result
    assert result["success"] is True          # the post-finish wait-retry started career 2
    assert client.start_calls == 2
    assert client.close_calls == []


def test_start_205_with_a_finished_career_in_the_slot_closes_it_and_retries():
    # A finished-but-unreleased career that load/index doesn't flag: the 205 recovery used to skip
    # it (not resumable), re-send start into the occupied slot and end on 'Delete Career Data'.
    finished = {"data": {"chara_info": {"card_id": 100101, "turn": 78, "state": 3, "playing_state": 1}}}
    client = FakeClient(career_result=finished, start_errors=["API error 205 on single_mode_free/start: {}"])
    client.login = lambda: {"data": {}}
    with _start_env(client):
        result = main.start_career_from_request(_request())
    assert result["success"] is True and not result.get("resumed"), result
    assert len(client.close_calls) == 1 and client.start_calls == 2


def test_codes_embedded_in_servertime_do_not_route_start_errors():
    client = FakeClient(career_result=LIVE_PS5, start_errors=[NOISY])
    with _start_env(client):
        try:
            main.start_career_from_request(_request())
        except RuntimeError as exc:
            assert str(exc) == NOISY          # a 208 is re-raised to the loop's retry/cooldown
        else:
            raise AssertionError("a 208 must not be handled as a 102/205 start")
    assert client.load_calls == 0             # never entered the 102/205 recovery paths
    assert client.close_calls == []


class FakeRunner:
    def __init__(self, outcomes, stop_after=6):
        self.outcomes = list(outcomes)
        self.status = {}
        self.starts = 0
        self.loop_info = []
        self.stop_after = stop_after

    def set_loop_info(self, n, target):
        self.loop_info.append(n)

    def start(self, *a, **k):
        self.starts += 1
        self.status = dict(self.outcomes.pop(0) if self.outcomes else self.status, running=False)
        if self.starts >= self.stop_after:   # bound the old (endless) behaviour
            main.backend_loop_stop = True

    def snapshot(self):
        return dict(self.status)

    def stop(self):
        pass


def _run_loop(runner, start_fn, sleeps=None):
    rec = sleeps if sleeps is not None else []
    with _patched(career_runner=runner, start_career_from_request=start_fn,
                  apply_career_result=lambda r: ({}, {}), active_account=None,
                  server_sleep=lambda *a, **k: rec.append("server"),
                  dna_sleep=lambda *a, **k: rec.append("dna"), backend_loop_stop=False):
        main.manage_career_loop(_request(), {}, {"data": {}})


def test_idle_exit_mid_career_is_a_failure_not_a_finished_run():
    idle = {"turn": 50, "finished": False, "last_error": "", "last_action": "idle"}
    runner = FakeRunner([idle] * 10)
    _run_loop(runner, lambda _req: {"success": True, "result": LIVE_PS5})
    assert runner.starts == 3                  # stopped by the 3-failure limit
    assert runner.loop_info == [1, 1, 1]       # no run slot consumed


def test_crashes_that_make_progress_keep_looping_but_a_stuck_crash_stops():
    def err(turn):
        return {"turn": turn, "finished": False, "last_error": "Network error on x", "last_action": ""}

    runner = FakeRunner([err(30), err(40), err(50), {"turn": 78, "finished": True, "last_error": ""}])
    _run_loop(runner, lambda _req: {"success": True, "result": LIVE_PS5})
    assert runner.starts == 6                  # resumed past every crash; only the test bound stops it
    assert runner.loop_info == [1, 1, 1, 1, 2, 3]

    stuck = FakeRunner([err(30)] * 10)
    _run_loop(stuck, lambda _req: {"success": True, "result": LIVE_PS5})
    assert stuck.starts == 3                   # same turn every time -> the 3-failure limit


def test_detail_with_servertime_digits_does_not_stop_the_loop():
    calls = []

    def start(_req):
        calls.append(1)
        if len(calls) == 1:
            return {"success": False, "detail": f"Could not refresh live account state: {NOISY}"}
        return {"success": True, "result": LIVE_PS5}

    runner = FakeRunner([{"turn": 78, "finished": True, "last_error": ""}] * 3, stop_after=2)
    _run_loop(runner, start)
    assert len(calls) == 2                     # retried after a cooldown, not "slot stuck"
    assert runner.starts == 2


def test_start_exception_cooldown_ignores_the_delay_kill_switch():
    sleeps = []

    def start(_req):
        raise RuntimeError("Network error on single_mode_free/start: timeout")

    runner = FakeRunner([{"turn": 78, "finished": True, "last_error": ""}])
    _run_loop(runner, start, sleeps)
    assert "dna" not in sleeps
    assert sleeps.count("server") >= 6 + 4 * 15


def test_captured_auth_is_kept_in_memory_only():
    writes = []
    creds = {"type": "creds", "app_ver": "1.0", "res_ver": "abc", "viewer_id": 1,
             "udid": "u", "auth_key": "SECRET", "body": ""}

    class Script:
        def on(self, _name, cb):
            self.cb = cb

        def load(self):
            self.cb({"type": "send", "payload": dict(creds)}, None)

    class Session:
        def create_script(self, _js):
            return Script()

        def detach(self):
            pass

    class Frida:
        @staticmethod
        def attach(_name):
            return Session()

    orig_write_text = pathlib.Path.write_text
    pathlib.Path.write_text = lambda self, *a, **k: writes.append(str(self))
    try:
        with _patched(launch_game=lambda: True, frida=Frida, has_fresh_auth_config=lambda _c: True,
                      kill_process_by_name=lambda _n: None, dna_sleep=lambda *a, **k: None,
                      pending_game_auth_config={}):
            assert main.refresh_auth_before_serving(timeout_sec=5) is True
            assert main.pending_game_auth_config.get("auth_key") == "SECRET"
    finally:
        pathlib.Path.write_text = orig_write_text
    assert writes == []


def test_second_start_while_one_is_in_flight_is_refused():
    # run_career awaits worker threads before its running/loop guard flags are set; a second Run (another
    # tab, the Discord remote) must not slip in and double-spend TP recovery on the same client.
    import asyncio

    async def go():
        async with main._run_career_lock:
            return await main.run_career_endpoint(_request())

    result = asyncio.run(go())
    assert result["success"] is False and "in progress" in result["detail"], result

if __name__ == "__main__":
    test_second_start_while_one_is_in_flight_is_refused()
    tests = [value for name, value in globals().items()
             if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
