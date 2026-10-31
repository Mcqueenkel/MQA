"""BEFORE GOAL RACES (Skills tab): the preset's learn_skill_before_goal skills are bought right before
each hard career-goal race (Top 3 or better, Classic year on). On 2026-10-20 every career raced those
goals with no skill bought and 1,400-2,150 SP unspent; one lost Tenno Sho (Spring) 6th/10th/4th/11th
and ended at B+ holding 1,462 SP.

Run:
    python tests/test_skills_before_goal.py
    python -m pytest tests/test_skills_before_goal.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.presets import serialize_preset  # noqa: E402
from career_bot.core.report import new_report  # noqa: E402
from career_bot.core.skills import SkillBuyer  # noqa: E402
from career_bot.runner import CareerRunner  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOURBON = 102602     # Mihono Bourbon (Alt): goals T44 Top 3, T56 Top 3, T70 Top 2, T72 WIN, Top 5 earlier


def test_preset_keeps_the_before_goal_list():
    p = serialize_preset({"name": "x", "learn_skill_before_goal": ["A", "B", "A", " "]})
    assert p["learn_skill_before_goal"] == ["A", "B"]
    assert serialize_preset({"name": "x", "learn_skill_before_goal": "A, B"})["learn_skill_before_goal"] == ["A", "B"]
    assert serialize_preset({"name": "x"})["learn_skill_before_goal"] == []


class _SkillClient:
    def __init__(self):
        self.sent = []

    def gain_skills(self, payload, turn, retry_205=3):
        self.sent.append(payload)
        return {"data": {"chara_info": {"turn": turn}}}


def _chara(sp=2000):
    # Right-Handed ○ (group 20001) and Pace Chaser Savvy ○ (a Pace Chaser skill) on offer
    sb = SkillBuyer(ROOT)
    savvy = next(sid for sid, n in sb.skill_names.items() if n.startswith("Pace Chaser Savvy"))
    return {"skill_array": [], "skill_point": sp, "turn": 56, "race_running_style": 1,
            "proper_running_style_nige": 7,
            "skill_tips_array": [{"group_id": 20001, "rarity": 1, "level": 1},
                                 {"group_id": sb.skill_to_group_id.get(savvy, savvy // 10), "rarity": 1, "level": 1}]}


def test_buys_only_listed_skills_that_fit_and_are_affordable():
    sb, client = SkillBuyer(ROOT), _SkillClient()
    preset = {"running_style": 1, "learn_skill_before_goal": ["Right-Handed ○", "Pace Chaser Savvy ○"]}
    state, bought = sb.buy_before_goal(client, {"data": {"chara_info": _chara()}}, preset)
    assert bought == 1, (bought, sb.last_candidates)
    names = [c["name"] for c in sb.last_selected]
    assert names == ["Right-Handed ○"], names          # the Pace Chaser skill can't fire for a front runner


def test_nothing_listed_or_nothing_affordable_buys_nothing():
    sb, client = SkillBuyer(ROOT), _SkillClient()
    assert sb.buy_before_goal(client, {"data": {"chara_info": _chara()}}, {"running_style": 1})[1] == 0
    preset = {"running_style": 1, "learn_skill_before_goal": ["Right-Handed ○"]}
    assert sb.buy_before_goal(client, {"data": {"chara_info": _chara(sp=5)}}, preset)[1] == 0
    assert client.sent == []


def _runner_with_stub_buyer():
    runner = CareerRunner(ROOT)
    runner.report = new_report({"name": "t"}, 3)
    runner.report["identity"] = {"card_id": BOURBON}
    calls = []

    class _Buyer:
        attempt_events = []

        def buy_before_goal(self, client, state, preset):
            calls.append(int(((state.get("data") or {}).get("chara_info") or {}).get("turn") or 0))
            return state, 1
    runner.skill_buyer = _Buyer()
    return runner, calls


def _goal_pid(runner, turn):
    g = next(g for g in runner.race_planner._goals({"card_id": BOURBON}) if int(g.get("turn") or 0) == turn)
    return int(g.get("program_id") or (g.get("program_ids") or [0])[0])


def test_runner_buys_only_before_hard_goal_races_once_each():
    runner, calls = _runner_with_stub_buyer()
    preset = {"learn_skill_before_goal": ["Right-Handed ○"]}

    def race(turn, pid):
        state = {"data": {"chara_info": {"turn": turn, "card_id": BOURBON}}}
        return runner._buy_before_goal(None, state, preset, {"current_turn": turn, "program_id": pid})

    race(56, _goal_pid(runner, 56))          # Tenno Sho (Spring), Top 3 -> buy
    race(56, _goal_pid(runner, 56))          # the same race retried -> not again
    race(72, _goal_pid(runner, 72))          # Arima Kinen, WIN -> buy
    race(34, _goal_pid(runner, 34))          # Japanese Derby, Top 5 -> easy, no buy
    race(12, _goal_pid(runner, 12))          # Make Debut -> no buy
    race(57, 80)                             # not a goal race -> no buy
    assert calls == [56, 72], calls
    assert runner.status["skills_bought"] == 2


def test_runner_does_nothing_without_a_list():
    runner, calls = _runner_with_stub_buyer()
    state = {"data": {"chara_info": {"turn": 56, "card_id": BOURBON}}}
    runner._buy_before_goal(None, state, {}, {"current_turn": 56, "program_id": _goal_pid(runner, 56)})
    assert calls == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
