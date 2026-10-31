"""The end-of-career skill dump (force=True) and the _spend_remaining_sp loop.

Per-turn buys are TIER 0 only (a preset with no learn_skill_tier0 buys nothing mid-run); the
force=True career-end dump must NOT be blocked by that. See test_skill_buy.py for the full
tier/leftover coverage.

Run:
    python tests/test_skill_buy_at_career_end.py            # standalone, prints PASS/FAIL
    python -m pytest tests/test_skill_buy_at_career_end.py  # if you have pytest
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.skills import SkillBuyer  # noqa: E402
from career_bot.runner import CareerRunner  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _state(points=9999):
    chara = {"skill_point": points, "turn": 40, "skill_tips_array": [], "skill_array": []}
    return {"data": {"chara_info": chara}}


def test_no_tier0_buys_nothing_mid_run():
    buyer = SkillBuyer(ROOT)
    # No learn_skill_tier0 -> nothing is a must-buy, so the mid-run pass holds ALL SP for the finish.
    # A tier-1 list (learn_skill_list) explicitly does NOT trigger a mid-run buy.
    for preset in ({}, {"learn_skill_list": [["Corner Acceleration"]]}):
        _, bought = buyer.buy(client=None, state=_state(), preset=preset, force=False)
        assert bought == 0
        assert buyer.last_result.get("skip") == "no_tier0", preset


def test_end_of_career_is_not_blocked():
    buyer = SkillBuyer(ROOT)
    # force=True must reach the purchase logic. No tips here -> nothing to buy, but the reason
    # must be candidate-driven, never the mid-career deferral.
    _, bought = buyer.buy(client=None, state=_state(), preset={}, force=True)
    assert bought == 0
    assert buyer.last_result.get("skip") != "deferred_to_career_end"


def test_preview_mirrors_deferral():
    buyer = SkillBuyer(ROOT)
    buyer.preview(_state(), {"learn_skill_list": [["Corner Acceleration"]]}, force=False)
    assert buyer.last_selected == []
    assert buyer.last_candidates == []


def test_spend_remaining_sp_buys_until_broke():
    # Keeps buying until SP can't afford anything (cheapest skill ~100 SP here), leaving only the floor.
    r = CareerRunner(ROOT)
    r._log = lambda *a, **k: None
    calls = {"n": 0}

    def fake_buy(client, state, preset, force, retry=True):
        calls["n"] += 1
        sp = int(state["data"]["chara_info"]["skill_point"])
        if sp >= 100:                                        # affordable -> spend 100
            state["data"]["chara_info"]["skill_point"] = sp - 100
        return state                                         # < 100 -> buys nothing (no progress)

    r._buy_skills = fake_buy
    state = {"data": {"chara_info": {"skill_point": 350}}}
    out = r._spend_remaining_sp(None, state, {})
    assert out["data"]["chara_info"]["skill_point"] == 50    # 350->250->150->50, then can't buy -> stop
    assert calls["n"] == 4                                   # 3 real buys + 1 no-progress pass that ends it


def test_spend_remaining_sp_stops_at_zero_and_caps():
    r = CareerRunner(ROOT)
    r._log = lambda *a, **k: None
    # buy that never makes progress must not loop forever (safety cap), and 0 SP exits immediately.
    r._buy_skills = lambda c, s, p, f, retry=True: s
    state = {"data": {"chara_info": {"skill_point": 500}}}
    r._spend_remaining_sp(None, state, {}, max_passes=8)      # no progress -> breaks after 1 pass
    zero = {"data": {"chara_info": {"skill_point": 0}}}
    assert r._spend_remaining_sp(None, zero, {})["data"]["chara_info"]["skill_point"] == 0


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
