"""Regression guards for irreversible TP-recovery requests.

Jewel and potion recovery may have reached the server even when the response is lost. They must use
``call_once`` so the generic transport never transparently replays the spend.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uma_api.client as client_module
from uma_api.client import UmaClient


def _recovery_client(response):
    client = UmaClient.__new__(UmaClient)
    client.coin_info = {"fcoin": 15, "coin": 25}
    client.tp_info = {"current_tp": 0}
    client.item_map = {UmaClient.TP_POTION_ITEM_ID: 4}
    client.once_calls = []

    def call_once(endpoint, payload=None, timeout=30):
        client.once_calls.append((endpoint, payload, timeout))
        return response

    client.call_once = call_once
    client.call = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("irreversible TP recovery used retrying call()")
    )
    return client


def test_jewel_tp_recovery_dispatches_once_and_updates_cached_balances():
    client = _recovery_client({
        "data": {
            "tp_info": {"current_tp": 30},
            "coin_info": {"fcoin": 5, "coin": 20},
        }
    })

    result = client.recovery_tp(count=1)

    assert client.once_calls == [(
        "user/recovery_trainer_point",
        {"count": 1, "client_own_num": 40},
        30,
    )]
    assert result == {"current_tp": 30}
    assert client.tp_info == {"current_tp": 30}
    assert client.coin_info == {"fcoin": 5, "coin": 20}


def test_potion_tp_recovery_dispatches_once_and_reconciles_local_count():
    client = _recovery_client({"data": {"tp_info": {"current_tp": 60}}})

    result = client.use_recovery_item(item_num=2)

    assert client.once_calls == [(
        "item/use_recovery_item",
        {"item_id": UmaClient.TP_POTION_ITEM_ID, "client_own_num": 4, "item_num": 2},
        30,
    )]
    assert result == {"current_tp": 60}
    assert client.item_map[UmaClient.TP_POTION_ITEM_ID] == 2


def _transport_client(result_code, captured):
    """Build a no-I/O client whose first response swaps in a recursive-call recorder."""
    client = UmaClient.__new__(UmaClient)
    client.current_scenario_id = 4
    client._last_raw_call_ts = 0
    client.sid = b"\0" * 16
    client.udid_str = "00000000-0000-0000-0000-000000000000"
    client.viewer_id = 1
    client.app_ver = "1"
    client.res_ver = "1"
    client.tp_info = {}
    client.coin_info = {}
    client.item_map = {}
    client._wait_for_circuit_cooldown = lambda: None
    client._route_ep = lambda endpoint, scenario_id: endpoint
    client.common = lambda: {}
    client.auth_bytes = lambda: b""
    client.api_log = lambda *args, **kwargs: None

    def recursive_call(endpoint, args=None, **kwargs):
        captured.append((endpoint, args, kwargs))
        return {"recursive": True}

    def post(*args, **kwargs):
        # UmaClient.call resolves self.call only when it reaches its recursive retry. Replacing this
        # instance attribute here lets the test observe the exact budgets passed to that retry.
        client.call = recursive_call
        return SimpleNamespace(status_code=200, text="encoded")

    client.session = SimpleNamespace(post=post)
    return client


def _assert_state_error_retry_budgets(result_code, expected_208, expected_205):
    captured = []
    client = _transport_client(result_code, captured)

    with (
        patch.object(client_module, "pack", lambda *args, **kwargs: b"request"),
        patch.object(
            client_module,
            "unpack",
            lambda *args, **kwargs: {"data_headers": {"result_code": result_code}, "data": {}},
        ),
        patch.object(client_module, "server_sleep", lambda *args, **kwargs: None),
        patch.object(client_module, "backoff_sleep", lambda *args, **kwargs: None),
    ):
        result = UmaClient.call(
            client,
            "single_mode_free/exec_command",
            {"current_turn": 7},
            retry_208=4,
            retry_205=2,
            timeout=8.5,
            retry_net=1,
            retry_res=1,
        )

    assert result == {"recursive": True}
    assert len(captured) == 1
    endpoint, payload, budgets = captured[0]
    assert endpoint == "single_mode_free/exec_command"
    assert payload["current_turn"] == 7
    assert budgets == {
        "retry_208": expected_208,
        "retry_205": expected_205,
        "timeout": 8.5,
        "retry_net": 1,
        "retry_res": 1,
        "retry_394": 1,   # the 394 re-mint budget is threaded through too, never reset
    }


def test_205_retry_preserves_all_other_caller_budgets():
    _assert_state_error_retry_budgets(205, expected_208=4, expected_205=1)


def test_208_retry_preserves_all_other_caller_budgets():
    _assert_state_error_retry_budgets(208, expected_208=3, expected_205=2)


if __name__ == "__main__":
    for name, test in sorted(globals().copy().items()):
        if name.startswith("test_") and callable(test):
            test()
            print("PASS", name)
