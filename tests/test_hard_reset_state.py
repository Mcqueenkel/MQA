"""Hard-reset recovery must hand the runner a career state, never the home response."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uma_api.client as client_module
from uma_api.client import UmaClient


class _Session:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _bare_client(career_result):
    client = UmaClient.__new__(UmaClient)
    old_session = _Session()
    replacement_session = _Session()
    client.session = old_session
    client.sid = b"stale-session-id"
    client.current_scenario_id = 3
    client.regen_sid = lambda: None
    client.update_headers = lambda: None

    account_result = {"data": {"tp_info": {"current_tp": 42}}}
    calls = []
    refreshed = []

    def fake_call(endpoint, args=None, **_kwargs):
        calls.append(endpoint)
        if endpoint == "tool/start_session":
            return {"data": {}}
        if endpoint == "load/index":
            return account_result
        if endpoint == "single_mode_free/load":
            if isinstance(career_result, Exception):
                raise career_result
            return career_result
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    client.call = fake_call
    client.refresh_cached_account_state = lambda data: refreshed.append(data)
    return client, old_session, replacement_session, account_result, calls, refreshed


def test_hard_reset_returns_loaded_career_state():
    career_result = {
        "data": {
            "chara_info": {"scenario_id": 3, "turn": 25},
            "home_info": [{"command_info_array": []}],
        }
    }
    client, old_session, new_session, account_result, calls, refreshed = _bare_client(career_result)

    with patch.object(client_module.requests, "Session", return_value=new_session):
        result = client.hard_reset()

    assert result is career_result
    assert result is not account_result
    assert old_session.closed is True
    assert client.session is new_session
    assert refreshed == [account_result["data"]]
    assert calls == ["tool/start_session", "load/index", "single_mode_free/load"]


def test_hard_reset_canonical_load_endpoint_routes_by_scenario():
    routes = [
        (1, "single_mode/load"),
        (2, "single_mode_team/load"),
        (3, "single_mode_live/load"),
        (4, "single_mode_free/load"),
    ]
    for scenario_id, expected in routes:
        assert UmaClient._route_ep("single_mode_free/load", scenario_id) == expected


def test_hard_reset_does_not_fall_back_to_home_state_when_career_load_fails():
    failure = RuntimeError("career load failed")
    client, _old_session, new_session, *_rest = _bare_client(failure)

    try:
        with patch.object(client_module.requests, "Session", return_value=new_session):
            client.hard_reset()
    except RuntimeError as exc:
        assert str(exc) == "career load failed"
    else:
        raise AssertionError("hard_reset returned a home response after career load failed")


if __name__ == "__main__":
    test_hard_reset_returns_loaded_career_state()
    test_hard_reset_canonical_load_endpoint_routes_by_scenario()
    test_hard_reset_does_not_fall_back_to_home_state_when_career_load_fails()
    print("test_hard_reset_state: OK")
