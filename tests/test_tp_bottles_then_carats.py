"""Default TP recovery at career start: TP bottles (Toughness 30) first, carats once they have run
out (tp_recovery_mode 'item_then_jewels', the user's choice). One start never pays through both
endpoints: a failed bottle call must not fall through to carats."""
import os
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)

import main  # noqa: E402
from test_main_review_fixes import FakeClient, _start_env  # noqa: E402


class TPClient(FakeClient):
    def __init__(self, tp, bottles, bottle_fails=False):
        super().__init__()
        self.tp_info = {"current_tp": tp, "max_tp": 100}
        self.bottles, self.bottle_fails, self.spent = bottles, bottle_fails, []

    def tp_potion_count(self, item_id=None):
        return self.bottles

    def _refill(self, kind, n):
        self.spent.append((kind, n))
        self.tp_info = {"current_tp": self.tp_info["current_tp"] + 30 * n, "max_tp": 100}

    def use_recovery_item(self, item_num=1, item_id=None):
        if self.bottle_fails:
            self.spent.append(("bottle-failed", item_num))
            raise RuntimeError("Network error on item/use_recovery_item: timeout")
        self._refill("bottle", item_num)

    def recovery_tp(self, count=1):
        self._refill("carats", count)


def _start(client, **mode):
    req = main.RunCareerRequest(card_id=100101, support_card_ids=[1, 2, 3, 4, 5, 6], friend_viewer_id=99,
                                friend_card_id=77, parent_id_1=10, parent_id_2=11, scenario_id=4,
                                use_tp=30, run_count=0, **mode)
    with _start_env(client):
        return main.start_career_from_request(req)


def test_the_default_is_bottles_then_carats():
    assert main.RunCareerRequest().tp_recovery_mode == "item_then_jewels"


def test_a_bottle_is_used_while_there_is_one():
    client = TPClient(tp=5, bottles=2)
    assert _start(client)["success"] is True
    assert client.spent == [("bottle", 1)], "a bottle was available but carats were spent"


def test_carats_only_once_the_bottles_ran_out():
    client = TPClient(tp=5, bottles=0)
    assert _start(client)["success"] is True
    assert client.spent == [("carats", 1)]


def test_a_failed_bottle_never_falls_through_to_carats():
    client = TPClient(tp=5, bottles=1, bottle_fails=True)
    assert _start(client)["success"] is False
    assert client.spent == [("bottle-failed", 1)], client.spent   # no second, carat payment


def test_enough_tp_spends_nothing():
    client = TPClient(tp=60, bottles=0)
    assert _start(client)["success"] is True
    assert client.spent == []


def test_explicit_item_mode_still_never_spends_carats():
    client = TPClient(tp=5, bottles=0)
    assert _start(client, tp_recovery_mode="item")["success"] is False
    assert client.spent == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
