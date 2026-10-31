"""Fail-closed career-start guards for TP spending and occupied career slots."""
from contextlib import contextmanager, nullcontext
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main


class FakeClient:
    def __init__(self, *, tp=30, potions=0, start_error=None, career_result=None,
                 recovery_error=None, load_error=None, career_error=None):
        self.tp_info = {"current_tp": tp, "max_tp": 100, "max_recovery_time": 0}
        self.item_map = {32: potions, 59: 1000, 75: 0}
        self.coin_info = {"fcoin": 1000, "coin": 0}
        self.viewer_id = 123
        self.current_scenario_id = 0
        self.start_error = start_error
        self.career_result = career_result
        self.recovery_error = recovery_error
        self.load_error = load_error
        self.career_error = career_error
        self.calls = []
        self.item_recoveries = []
        self.jewel_recoveries = []
        self.close_calls = []
        self.start_calls = 0

    def call(self, endpoint, payload):
        self.calls.append(endpoint)
        if self.load_error:
            raise RuntimeError(self.load_error)
        assert endpoint == "load/index"
        return {"data": {
            "tp_info": dict(self.tp_info),
            "coin_info": dict(self.coin_info),
            "item_list": [
                {"item_id": 32, "number": self.item_map[32]},
                {"item_id": 59, "number": self.item_map[59]},
                {"item_id": 75, "number": self.item_map[75]},
            ],
        }}

    def refresh_cached_account_state(self, data):
        if data.get("tp_info"):
            self.tp_info = dict(data["tp_info"])
        for row in data.get("item_list") or []:
            self.item_map[int(row["item_id"])] = int(row["number"])

    def tp_potion_count(self, item_id):
        return self.item_map.get(int(item_id), 0)

    def use_recovery_item(self, item_num, item_id):
        self.item_recoveries.append((item_num, item_id))
        if self.recovery_error:
            raise RuntimeError(self.recovery_error)
        self.item_map[item_id] -= item_num
        self.tp_info = dict(self.tp_info)
        self.tp_info["current_tp"] += 30 * item_num

    def recovery_tp(self, count):
        self.jewel_recoveries.append(count)
        if self.recovery_error:
            raise RuntimeError(self.recovery_error)
        self.tp_info = dict(self.tp_info)
        self.tp_info["current_tp"] += 30 * count

    def pre_single_mode(self, _excluded):
        return {"data": {}}

    def start_career(self, **_kwargs):
        self.start_calls += 1
        if self.start_error:
            raise RuntimeError(self.start_error)
        return {"data": {"chara_info": {"card_id": 100101, "turn": 1}}}

    def probing_102(self):
        return nullcontext()

    def load_career(self):
        if self.career_error:
            raise RuntimeError(self.career_error)
        if self.career_result is None:
            raise RuntimeError("API error 102 on load")
        return self.career_result

    def close_career(self, **kwargs):
        self.close_calls.append(kwargs)


def _request(mode="item", use_tp=30):
    return main.RunCareerRequest(
        card_id=100101,
        support_card_ids=[1, 2, 3, 4, 5, 6],
        friend_viewer_id=99,
        friend_card_id=77,
        parent_id_1=10,
        parent_id_2=11,
        scenario_id=4,
        use_tp=use_tp,
        tp_recovery_mode=mode,
    )


@contextmanager
def _installed(client):
    replacements = {
        "active_client": client,
        "active_account": None,
        "active_dashboard_data": None,
        "active_start_state": {},
        "validate_start_selection": lambda _req: None,
        "selected_succession_rank_point": lambda _req: 0,
        "dna_sleep": lambda *_args, **_kwargs: None,
    }
    originals = {name: getattr(main, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(main, name, value)
        yield
    finally:
        for name, value in originals.items():
            setattr(main, name, value)


def test_invalid_tp_mode_fails_before_any_client_call():
    client = FakeClient()
    with _installed(client):
        result = main.start_career_from_request(_request("items"))   # a typo must spend nothing

    assert result["success"] is False
    assert "Invalid tp_recovery_mode" in result["detail"]
    assert client.calls == []
    assert client.item_recoveries == []
    assert client.jewel_recoveries == []


def test_item_mode_checks_full_quantity_and_never_falls_back():
    client = FakeClient(tp=0, potions=1)
    with _installed(client):
        result = main.start_career_from_request(_request("item", use_tp=60))

    assert result["success"] is False
    assert "need 2" in result["detail"] and "have 1" in result["detail"]
    assert client.item_recoveries == []
    assert client.jewel_recoveries == []


def test_item_and_jewel_modes_use_only_the_explicit_resource():
    item_client = FakeClient(tp=0, potions=2)
    with _installed(item_client):
        assert main.start_career_from_request(_request("item", use_tp=60))["success"] is True
    assert item_client.item_recoveries == [(2, 32)]
    assert item_client.jewel_recoveries == []

    jewel_client = FakeClient(tp=0, potions=99)
    with _installed(jewel_client):
        assert main.start_career_from_request(_request("jewels", use_tp=60))["success"] is True
    assert jewel_client.item_recoveries == []
    assert jewel_client.jewel_recoveries == [2]


def test_ambiguous_recovery_failure_is_never_redispatched_or_fallback_spent():
    client = FakeClient(tp=0, potions=2, recovery_error="network response lost")
    with _installed(client):
        result = main.start_career_from_request(_request("item", use_tp=60))

    assert result["success"] is False
    assert "no fallback was attempted" in result["detail"]
    assert client.item_recoveries == [(2, 32)]
    assert client.jewel_recoveries == []


def test_failed_live_refresh_never_uses_cached_tp_or_spends_anything():
    client = FakeClient(tp=0, potions=5, load_error="session refresh failed")
    with _installed(client):
        # Simulate values left by an earlier run. The start path must discard them before refresh.
        main.active_start_state = {
            "tp_info": {"current_tp": 0},
            "current_money": 9999,
        }
        result = main.start_career_from_request(_request("jewels", use_tp=30))

    assert result["success"] is False
    assert "Could not refresh live account state" in result["detail"]
    assert client.item_recoveries == []
    assert client.jewel_recoveries == []
    assert client.start_calls == 0


def test_authoritative_empty_item_list_clears_stale_counts():
    client = FakeClient()
    with _installed(client):
        main.active_start_state = {"current_money": 999, "succession_rank_point": 999}
        main.update_start_state({"item_list": []})
        assert main.active_start_state["current_money"] == 0
        assert main.active_start_state["succession_rank_point"] == 0


def test_start_102_resumes_turn_one_and_never_closes_it():
    active = {"data": {"chara_info": {
        "card_id": 100101,
        "turn": 1,
        "state": 0,
        "playing_state": 1,
    }}}
    client = FakeClient(start_error="API error 102 on single_mode_free/start",
                        career_result=active)
    with _installed(client):
        result = main.start_career_from_request(_request("off", use_tp=30))

    assert result == {"success": True, "result": active, "resumed": True}
    assert client.close_calls == []


def test_start_102_with_ambiguous_load_fails_closed_without_deleting_anything():
    client = FakeClient(start_error="API error 102 on single_mode_free/start",
                        career_error="Network error while checking active career")
    with _installed(client):
        result = main.start_career_from_request(_request("off", use_tp=30))

    assert result["success"] is False
    assert result.get("fatal_start") is True
    assert "No career was closed or deleted" in result["detail"]
    assert client.close_calls == []
    assert client.start_calls == 1


if __name__ == "__main__":
    tests = [value for name, value in globals().items()
             if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
