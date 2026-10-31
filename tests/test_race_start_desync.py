"""Live 2026-10-20: an HTTP 504 on race_start landed server-side, so its retry went out on a stale
session and got 217 -> RUNNER CRASH. Then every loop retry 217'd on the pre-start load/index refresh
without re-syncing the session, so the loop never recovered.

  * race_start 217 now reloads (re-logs in) and lets the next pass resume the race, like race_entry.
  * the pre-start load/index refresh re-syncs the session once on 217 and retries.

Run:
    python tests/test_race_start_desync.py
    python -m pytest tests/test_race_start_desync.py
"""
import os
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)

import main  # noqa: E402
from test_main_review_fixes import FakeClient, _request, _start_env  # noqa: E402
from test_runner_review_fixes import MID_RACE, _guard_runner  # noqa: E402

RC217 = "API error 217 on single_mode_live/race_start: {}"


class _RaceClient:
    def __init__(self, start_error):
        self.start_error = start_error

    def race_entry(self, **_kw):
        return {"data": {"chara_info": {"turn": 30, "race_running_style": 0}}}

    def race_start(self, **_kw):
        raise Exception(self.start_error)


def test_race_start_217_reloads_instead_of_crashing():
    r = _guard_runner()
    r._fresh_career_state = lambda client, strategy=None: MID_RACE
    out = r._race(_RaceClient(RC217), MID_RACE, {}, {"program_id": 1234, "current_turn": 30})
    assert out is MID_RACE
    assert any(kind == "race_start_desync" for kind, _t, _m in r.logged), r.logged


def test_race_start_other_errors_still_raise():
    r = _guard_runner()
    r._fresh_career_state = lambda client, strategy=None: MID_RACE
    try:
        r._race(_RaceClient("API error 214 on single_mode_live/race_start: {}"), MID_RACE, {},
                {"program_id": 1234, "current_turn": 30})
    except Exception as exc:
        assert "214" in str(exc)
    else:
        raise AssertionError("a 214 was swallowed as a desync")


class _DesyncedClient(FakeClient):
    def __init__(self, error):
        super().__init__()
        self.error, self.resyncs = error, 0

    def call(self, endpoint, payload=None):
        if self.error and not self.resyncs:
            raise Exception(self.error)
        return super().call(endpoint, payload)

    def resync_session(self):
        self.resyncs += 1


def test_prestart_refresh_resyncs_once_on_217():
    client = _DesyncedClient("API error 217 on load/index: {}")
    with _start_env(client):
        result = main.start_career_from_request(_request())
    assert client.resyncs == 1
    assert result["success"] is True, result


def test_prestart_refresh_does_not_resync_other_errors():
    client = _DesyncedClient("API error 214 on load/index: {}")
    with _start_env(client):
        result = main.start_career_from_request(_request())
    assert client.resyncs == 0
    assert result["success"] is False and "214" in result["detail"], result


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
