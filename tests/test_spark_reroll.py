"""End-of-career spark chooser: score by per-colour priority, optionally spend TP to reroll, and keep
the BEST option across the original + rerolled sets. Reroll is OFF by default because it spends 30 TP
each. Every failure path is non-fatal -- the career still finishes on whatever option we already have.
Covers CareerRunner._spark_factor_chooser.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.runner import CareerRunner

# id -> colour/stars. 101 blue 3*, 1101 pink 1*, 20001 white 3*
FMAP = {
    "101": {"name": "Speed", "category": "stat", "stars": 3},
    "1101": {"name": "Turf", "category": "aptitude", "stars": 1},
    "20001": {"name": "Corner Adept", "category": "skill", "stars": 3},
}


def _opt(lottery_id, *fids):
    return {"lottery_id": lottery_id, "factor_info_array": [{"factor_id": f} for f in fids]}


def _resp(initial, rerolled=None, remain=1, tp=200):
    common = {
        "factor_select_info_array": initial,
        "lottery_remain_num": remain,
        "tp_info": {"current_tp": tp, "max_tp": 300, "max_recovery_time": 0},
    }
    if rerolled is not None:
        common["factor_relottery_info_array"] = rerolled
    return {"data": {"single_mode_factor_select_common": common}}


class FakeClient:
    """Minimal stand-in: records reroll calls and hands back queued responses."""

    def __init__(self, responses=None, tp=200, raise_on_reroll=False):
        self.responses = list(responses or [])
        self.calls = 0
        self.tp = tp
        self.raise_on_reroll = raise_on_reroll

    def current_tp_snapshot(self, tp_info=None):
        return {"current_tp": self.tp, "max_tp": 300, "max_recovery_time": 0}

    def factor_lottery(self, lottery_count=1, tp_info=None, use_tp=30):
        self.calls += 1
        if self.raise_on_reroll:
            raise RuntimeError("API error 102 on factor_lottery")
        self.tp -= use_tp
        return self.responses.pop(0) if self.responses else {}


def _runner():
    r = CareerRunner(".")
    r.data_store.factor_map = lambda: FMAP     # inject the tiny map
    return r


# want SKILL sparks most, ignore aptitude entirely
PRESET_WHITE = {"spark_priority_white": 5, "spark_priority_blue": 1,
                "spark_priority_pink": 0, "spark_priority_green": 0}


def test_reroll_off_picks_best_without_spending_tp():
    r, client = _runner(), FakeClient()
    choose = r._spark_factor_chooser(client, dict(PRESET_WHITE))          # spark_reroll unset -> OFF
    # option 2 is the white 3* -> wins under white=5
    assert choose(_resp([_opt(1, 101), _opt(2, 20001)])) == 2
    assert client.calls == 0, "must not spend TP when reroll is off"


def test_reroll_takes_a_better_rerolled_option():
    # initial roll is weak (pink only, weight 0); the reroll produces the white 3*
    reroll_resp = _resp([_opt(1, 1101)], rerolled=[_opt(9, 20001)], remain=0)
    r, client = _runner(), FakeClient([reroll_resp])
    choose = r._spark_factor_chooser(client, dict(PRESET_WHITE, spark_reroll=True, spark_reroll_max=2))
    assert choose(_resp([_opt(1, 1101)])) == 9
    assert client.calls == 1


def test_reroll_keeps_the_original_when_the_reroll_is_worse():
    # reroll response still carries the ORIGINAL array -> a worse reroll must not displace it
    reroll_resp = _resp([_opt(1, 20001)], rerolled=[_opt(9, 1101)], remain=0)
    r, client = _runner(), FakeClient([reroll_resp])
    choose = r._spark_factor_chooser(client, dict(PRESET_WHITE, spark_reroll=True, spark_reroll_max=2))
    assert choose(_resp([_opt(1, 20001)])) == 1, "a reroll must never lose a better original roll"


def test_tp_floor_blocks_the_reroll():
    r, client = _runner(), FakeClient(tp=50)
    # floor 40 -> needs 30 + 40 = 70 TP, only 50 available
    choose = r._spark_factor_chooser(client, dict(PRESET_WHITE, spark_reroll=True,
                                                 spark_reroll_max=2, spark_reroll_tp_floor=40))
    assert choose(_resp([_opt(1, 101)])) == 1
    assert client.calls == 0, "must not reroll below the TP floor"


def test_no_reroll_when_none_remain():
    r, client = _runner(), FakeClient()
    choose = r._spark_factor_chooser(client, dict(PRESET_WHITE, spark_reroll=True, spark_reroll_max=3))
    assert choose(_resp([_opt(1, 101)], remain=0)) == 1
    assert client.calls == 0


def test_reroll_max_caps_the_spend():
    # every reroll keeps remain=2 so only spark_reroll_max stops it
    responses = [_resp([_opt(1, 1101)], rerolled=[_opt(9, 1101)], remain=2) for _ in range(5)]
    r, client = _runner(), FakeClient(responses)
    choose = r._spark_factor_chooser(client, dict(PRESET_WHITE, spark_reroll=True, spark_reroll_max=2))
    choose(_resp([_opt(1, 1101)], remain=2))
    assert client.calls == 2, f"capped at 2, got {client.calls}"


def test_reroll_failure_is_non_fatal():
    r, client = _runner(), FakeClient(raise_on_reroll=True)
    choose = r._spark_factor_chooser(client, dict(PRESET_WHITE, spark_reroll=True, spark_reroll_max=2))
    assert choose(_resp([_opt(1, 20001)])) == 1, "a failed reroll must still return a valid pick"


def test_no_options_returns_none():
    r, client = _runner(), FakeClient()
    choose = r._spark_factor_chooser(client, dict(PRESET_WHITE))
    assert choose({}) is None          # -> close_career keeps its default roll


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_spark_reroll: OK")
