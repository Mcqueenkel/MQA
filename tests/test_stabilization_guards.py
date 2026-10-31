"""Regression checks for the local stabilization fixes.

Runs both under pytest and directly with ``python tests/test_stabilization_guards.py``.
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException

from api import static_routes
from career_bot.core.ai_learn import _validate_training_policy
from uma_api.client import UmaClient, redact_for_log


def test_training_policy_validation_scores_real_candidates():
    context_key = "4:classic:mid:healthy"
    result = _validate_training_policy(
        {
            context_key: {
                "n": 8,
                "avg_gain": 10,
                "success_rate": 0.70,
                "avg_failure_rate": 8,
                "avg_career_reward": 4,
            }
        },
        {
            f"{context_key}:101": {
                "n": 6,
                "avg_gain": 20,
                "success_rate": 0.90,
                "avg_failure_rate": 2,
                "avg_career_reward": 8,
            }
        },
    )

    assert result["evaluated_contexts"] == 1
    assert result["positive_contexts"] == 1
    assert result["avg_improvement"] > 0
    assert result["validated"] is True


def test_training_policy_validation_skips_context_without_candidates():
    result = _validate_training_policy(
        {"4:classic:mid:healthy": {"n": 8, "avg_gain": 10}},
        {},
    )
    assert result["evaluated_contexts"] == 0
    assert result["validated"] is False


def test_static_asset_route_rejects_windows_backslash_traversal():
    try:
        asyncio.run(static_routes.get_asset_data(r"..\..\..\settings.json"))
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("asset route allowed a path outside public/assets/data")


def test_race_route_rejects_windows_backslash_traversal():
    try:
        asyncio.run(static_routes.get_race_image(r"..\..\settings.json"))
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("race route allowed a path outside public/races")


def test_static_asset_route_still_serves_a_real_asset():
    response = asyncio.run(static_routes.get_asset_data("uma_race_data.json"))
    assert Path(response.path).resolve() == (
        static_routes.PUBLIC_DIR / "assets" / "data" / "uma_race_data.json"
    ).resolve()


def test_persistent_api_log_redacts_credentials_without_truncating_diagnostics():
    long_diagnostic = "x" * 500
    safe = redact_for_log({
        "payload": {
            "steam_session_ticket": "ticket-secret",
            "sid": "sid-secret",
            "nested": {"password": "password-secret"},
            "viewer_id": 12345,
            "diagnostic": long_diagnostic,
        }
    })

    payload = safe["payload"]
    assert payload["steam_session_ticket"] == "<redacted>"
    assert payload["sid"] == "<redacted>"
    assert payload["nested"]["password"] == "<redacted>"
    assert payload["viewer_id"] == 12345
    assert payload["diagnostic"] == long_diagnostic


def test_api_log_redacts_the_common_header_and_data_transfer_fields():
    # the api_library kept these in clear until 2026-10 (Data Transfer even logged its password pair)
    safe = redact_for_log({"steam_id": "7656", "ip_address": "192.0.2.1", "input_viewer_id": 123,
                           "one_time_password": "x", "dmm_onetime_token": "x", "authentication_token": "x",
                           "free_ticket_num": 3, "race_ticket": 1, "item_id": 32})
    assert {k for k, v in safe.items() if v == "<redacted>"} == {
        "steam_id", "ip_address", "input_viewer_id", "one_time_password", "dmm_onetime_token",
        "authentication_token"}
    assert (safe["free_ticket_num"], safe["race_ticket"], safe["item_id"]) == (3, 1, 32)   # gameplay kept


def test_api_log_callback_receives_only_redacted_payload():
    captured = {}

    class ClientStub:
        trace_file = None

        @staticmethod
        def on_api_log(direction, endpoint, data, req_id):
            captured.update({
                "direction": direction,
                "endpoint": endpoint,
                "data": data,
                "req_id": req_id,
            })

    previous = os.environ.get("UMA_NO_API_LIBRARY")
    os.environ["UMA_NO_API_LIBRARY"] = "1"
    try:
        UmaClient.api_log(
            ClientStub(),
            "REQ",
            "load/index",
            {"payload": {"steam_session_ticket": "secret", "viewer_id": 12345}},
            "request-1",
        )
    finally:
        if previous is None:
            os.environ.pop("UMA_NO_API_LIBRARY", None)
        else:
            os.environ["UMA_NO_API_LIBRARY"] = previous

    assert captured["data"]["payload"]["steam_session_ticket"] == "<redacted>"
    assert captured["data"]["payload"]["viewer_id"] == 12345


if __name__ == "__main__":
    import traceback

    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    passed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {test.__name__}: {exc}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    raise SystemExit(0 if passed == len(tests) else 1)
