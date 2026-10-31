"""MANT: a Reset Whistle is used alone and reshuffles the board, so the runner runs the item step
again for the new pick. That second pass must consider the charm and must not whistle again
(live 2026-10-29 turn 63: Speed trained at 95% failure with 2 Good-Luck Charms owned).

Run:
    python tests/test_whistle_then_charm.py
    python -m pytest tests/test_whistle_then_charm.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.mant_items import MantItemManager  # noqa: E402


class _Client:
    def __init__(self):
        self.sent = []

    def use_items(self, payload, turn):
        self.sent.append(sorted(int(p["item_id"]) for p in payload))
        return {"data": {}}


def _state():
    items = [{"item_id": 7001, "num": 2}, {"item_id": 10001, "num": 2}]   # whistle x2, charm x2
    return {"data": {"chara_info": {"turn": 63, "vital": 11, "max_vital": 100, "motivation": 4},
                     "free_data_set": {"user_item_info_array": items}}}


def _training(gain):
    return {"command_type": 1, "command_id": 601, "failure_rate": 95, "speed": gain}


def test_the_pick_after_a_whistle_gets_the_charm_and_no_second_whistle():
    im, client = MantItemManager(), _Client()
    im.use_items(client, _state(), {}, _training(10))       # weak board -> whistle alone
    assert client.sent == [[7001]] and im.whistled_turn == 63
    im.use_items(client, _state(), {}, _training(50))       # strong pick at 95% after the reshuffle
    assert client.sent[-1] == [10001], client.sent           # charm, not another whistle


if __name__ == "__main__":
    test_the_pick_after_a_whistle_gets_the_charm_and_no_second_whistle()
    print("PASS")
