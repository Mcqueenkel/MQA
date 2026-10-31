"""Fixes from the 2026-10-16 Grand Live runs (preset asdad: 35-38 races, 7-8 in a row, 33 dirt starts
at dirt G with 0 wins, 4 of 5 careers lost at the must-win T72 goal; same trainee goals-only: A+/SS):

  1. optional-race guard: a SCHEDULED race is skipped on aptitude < B / 3rd race in a row / a goal
     race within 2 turns / mood <= 2 (Grand Live by default; never goal/forced/fan races)
  2. a master_square reply carries no race board -> keep the turn's board instead of "no races"
  3. logs: every decision kept per turn, one record per race with every finishing position, races
     counted from those, history rows carry outcome + scenario, capture library keeps 3 old files
  4. Grand Live clocks only on a missed goal race (the server 205s every other continue); the mid-run
     tier-0 skill buy no longer buys every unlisted circle skill

Run:
    python tests/test_run_quality_fixes.py
    python -m pytest tests/test_run_quality_fixes.py
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core import notify  # noqa: E402
from career_bot.core.report import add_decision, new_report  # noqa: E402
from career_bot.core.base import Decision  # noqa: E402
from career_bot.core.skills import SkillBuyer  # noqa: E402
from career_bot.runner import CareerRunner  # noqa: E402
from career_bot.scenarios.grand_live import GrandLiveStrategy  # noqa: E402
from career_bot.scenarios.mant import MantStrategy  # noqa: E402
from career_bot.scenarios.unity import UnityStrategy  # noqa: E402
from career_bot.scenarios.ura import UraStrategy  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRT_G1 = 1        # February Stakes (dirt, 1600m)
TURF_G1 = 3        # Osaka Hai (turf, 2000m)
BOURBON = 102602   # Mihono Bourbon (Alt): turf A, dirt G, short C; goals T44 / T56 / T70 / T72


def _turn(pid, turn=40, mood=4, raced=(), history=None, **preset_extra):
    """One NORMAL Grand Live turn (training on offer, so not a forced race day) through the real
    strategy and planner."""
    runner = CareerRunner(ROOT)
    strategy = GrandLiveStrategy(race_planner=runner.race_planner)
    strategy._raced_turns = set(raced)
    chara = {"card_id": BOURBON, "turn": turn, "motivation": mood, "vital": 60, "scenario_id": 3,
             "proper_ground_turf": 7, "proper_ground_dirt": 1, "proper_distance_short": 5,
             "proper_distance_mile": 7, "proper_distance_middle": 7, "proper_distance_long": 6,
             "speed": 500, "stamina": 400, "power": 400, "guts": 300, "wiz": 300,
             "max_speed": 1200, "max_stamina": 1200, "max_power": 1200, "max_guts": 1200, "max_wiz": 1200}
    commands = [{"command_type": 4, "command_id": 401, "is_enable": 1}] + [
        {"command_type": 1, "command_id": c, "is_enable": 1, "failure_rate": 5,
         "params_inc_dec_info_array": [{"target_type": 1, "value": 10}], "training_partner_array": []}
        for c in (101, 105, 102, 103, 106)]
    data = {"chara_info": chara, "race_condition_array": [{"program_id": pid}],
            "home_info": {"command_info_array": commands},
            "live_data_set": {"live_result_array": [1], "next_square_info_array": []}}
    if history is not None:
        data["race_history"] = [{"turn": t, "program_id": 9} for t in history]
    preset = {"use_race_schedule": True, "extra_race_list": [pid], **preset_extra}
    return strategy.next_decision({"data": data}, preset)


# ---- 1. optional-race guard -------------------------------------------------------------------

def test_dirt_race_for_a_dirt_g_trainee_is_skipped_and_logged():
    d = _turn(DIRT_G1)
    assert d.action == "command", d
    assert "skipped" in d.reason and "aptitude below B" in d.reason, d.reason


def test_a_fine_turf_race_still_runs():
    assert _turn(TURF_G1).action == "race"


def test_never_a_third_race_in_a_row():
    d = _turn(TURF_G1, raced=(38, 39))
    assert d.action == "command" and "race 3 in a row" in d.reason, d.reason
    assert _turn(TURF_G1, raced=(39,)).action == "race"          # 2nd in a row is fine


def test_a_resumed_career_knows_its_streak_from_the_servers_race_history():
    d = _turn(TURF_G1, raced=(), history=(38, 39))
    assert d.action == "command" and "race 3 in a row" in d.reason, d.reason


def test_keeps_the_turns_before_a_goal_race_free():
    d = _turn(TURF_G1, turn=42)                                   # Kikuka Sho goal on T44
    assert d.action == "command" and "goal race in 2 turns" in d.reason, d.reason


def test_no_optional_race_at_bad_mood():
    d = _turn(TURF_G1, mood=2)
    assert d.action == "command" and "mood 2" in d.reason, d.reason


def test_preset_can_switch_the_guard_off():
    assert _turn(DIRT_G1, optional_race_guard=False).action == "race"


def test_guard_is_grand_live_only_by_default():
    assert GrandLiveStrategy.RACE_POLICY["optional_race_guard"] is True
    for cls in (MantStrategy, UraStrategy, UnityStrategy):        # MANT races on purpose; URA fan farms
        assert cls.RACE_POLICY.get("optional_race_guard") is False, cls


def test_this_turns_goal_race_is_never_vetoed():
    runner = CareerRunner(ROOT)
    strategy = GrandLiveStrategy(race_planner=runner.race_planner)
    strategy._raced_turns = {70, 71}                              # even as the 3rd race in a row
    chara = {"card_id": BOURBON, "turn": 72, "motivation": 1,
             "proper_ground_turf": 7, "proper_distance_long": 6, "proper_distance_middle": 7}
    assert strategy._optional_race_veto({"data": {}}, chara, {}, 81) == ""   # Arima Kinen, T72 goal


# ---- 2. master_square keeps the race board --------------------------------------------------------

def test_master_square_reply_keeps_the_turns_race_board():
    board = [{"program_id": TURF_G1}]
    prev = {"data": {"chara_info": {"turn": 30}, "race_condition_array": board}}
    reply = {"data": {"chara_info": {"turn": 30}, "live_data_set": {}}}        # what the server sends
    assert CareerRunner._keep_race_board(reply, prev)["data"]["race_condition_array"] == board
    moved_on = {"data": {"chara_info": {"turn": 31}}}
    assert "race_condition_array" not in CareerRunner._keep_race_board(moved_on, prev)["data"]
    own = {"data": {"chara_info": {"turn": 30}, "race_condition_array": []}}
    assert CareerRunner._keep_race_board(own, prev)["data"]["race_condition_array"] == []


def test_grand_live_call_passes_the_board_through_a_square_claim():
    runner = CareerRunner.__new__(CareerRunner)
    runner._log = lambda *a, **k: None
    runner._drain_events = lambda client, strategy, state: state

    class _Client:
        def call(self, endpoint, payload, **kwargs):
            return {"data": {"chara_info": {"turn": 30}, "live_data_set": {}}}

    strategy = GrandLiveStrategy.__new__(GrandLiveStrategy)
    decision = Decision("master_square", {"square_id": 11002, "current_turn": 30}, "square")
    prev = {"data": {"chara_info": {"turn": 30}, "race_condition_array": [{"program_id": TURF_G1}]}}
    state = runner._grand_live_call(_Client(), strategy, decision, prev_state=prev)
    assert state["data"]["race_condition_array"] == [{"program_id": TURF_G1}]


# ---- 3 + 4. race records, summary counts, Grand Live clocks -------------------------------------

class _RaceClient:
    def __init__(self, ranks):
        self.ranks = list(ranks)
        self.continues = 0

    def race_continue(self, current_turn, continue_type):
        self.continues += 1
        return {"data": {"home_info": {"available_continue_num": 3 - self.continues,
                                       "available_free_continue_num": 0}}}

    def race_start(self, is_short, current_turn):
        return {"rank": self.ranks.pop(0), "data": {}}


def _race(scenario, program_id, turn, ranks, card_id=100101):
    """Run _process_race_result with a fake client; returns (client, the race record)."""
    runner = CareerRunner(ROOT)
    runner.status["scenario_id"] = scenario
    runner.report = new_report({"name": "t"}, scenario)
    runner._parse_race_rank = lambda res: res["rank"]
    runner.api_jitter = 0
    client = _RaceClient(ranks[1:])
    client.api_jitter = 0
    state = {"data": {"chara_info": {"card_id": card_id, "turn": turn},
                      "home_info": {"available_continue_num": 3, "available_free_continue_num": 0}}}
    with patch("career_bot.runner.ai_learn.log_experience", lambda *a, **k: None), \
            patch("career_bot.runner.dna_sleep", lambda *a, **k: None), \
            patch("career_bot.runner.dna_gauss", lambda *a, **k: None):
        runner._process_race_result(client, {"rank": ranks[0], "data": {}}, state, {}, program_id, turn)
    return client, runner.report["races"][-1]


def test_grand_live_clocks_a_missed_goal_until_it_is_met():
    client, row = _race(3, 81, 72, [6, 3, 1])                    # Special Week T72 Arima: WIN (1st)
    assert client.continues == 2
    assert row["ranks"] == [6, 3, 1] and row["final_rank"] == 1 and row["clocks"] == 2
    assert row["goal"] == "WIN (1st)" and row["goal_met"] is True


def test_grand_live_never_clocks_a_non_goal_race_or_a_met_goal():
    client, row = _race(3, 80, 71, [16])                          # Champions Cup, not a goal
    assert client.continues == 0 and row["goal"] is None and row["ranks"] == [16]
    client, row = _race(3, 79, 70, [2])                           # Japan Cup, Top 2: met at 2nd
    assert client.continues == 0 and row["goal_met"] is True


def test_other_scenarios_still_clock_every_loss():
    client, row = _race(4, 80, 71, [5, 1])                        # MANT accepts non-goal clocks
    assert client.continues == 1 and row["final_rank"] == 1


def test_summary_counts_races_from_the_records_not_the_last_decision():
    runner = CareerRunner(ROOT)
    report = new_report({"name": "t"}, 3)
    # T24: race, then the concert overwrote selected_action. T36: training, then the concert.
    for turn, decisions in ((24, [Decision("race", {"program_id": 7, "current_turn": 24}, "goal"),
                                  Decision("grand_live_perform", {"current_turn": 24}, "Grand Live")]),
                            (36, [Decision("command", {"command_type": 1, "command_id": 101, "current_turn": 36}, "train"),
                                  Decision("event", {"current_turn": 36}, "event"),
                                  Decision("grand_live_perform", {"current_turn": 36}, "Grand Live")])):
        for d in decisions:
            add_decision(report, {"data": {"chara_info": {"turn": turn}}}, d)
    report["races"] = [{"turn": 24, "final_rank": 1}, {"turn": 50, "final_rank": 3}]
    runner.report = report
    s = runner._career_summary("completed")
    assert s["races"] == 2 and s["races_won"] == 1
    assert s["actions"]["train"] == 1 and s["training_by_stat"]["speed"] == 1   # hidden by the concert before
    assert s["actions"]["grand_live_perform"] == 2
    t24 = next(t for t in report["turns"] if t["turn"] == 24)
    assert [x["action"] for x in t24["decisions"]] == ["race", "grand_live_perform"]
    t36 = next(t for t in report["turns"] if t["turn"] == 36)
    assert "event" not in [x["action"] for x in t36["decisions"]]


def test_old_logs_without_race_records_still_summarise():
    runner = CareerRunner(ROOT)
    runner.report = {"turns": [{"turn": 5, "selected_action": "race", "current_command": {}},
                               {"turn": 6, "selected_action": "command",
                                "current_command": {"command_type": 1, "command_id": 105}}]}
    s = runner._career_summary("completed")
    assert s["races"] == 1 and s["actions"]["train"] == 1


def test_history_rows_carry_outcome_and_scenario():
    base = tempfile.mkdtemp()
    notify.record_career_history(base, {"status": "finished", "card_id": 102602, "rank": 12,
                                        "rank_score": 9674, "fans": 1,
                                        "preset": "asdad", "outcome": "goal_failed@turn72",
                                        "scenario_id": 3, "races": 35, "races_won": 18})
    row = json.load(open(os.path.join(base, "uma_runtime", "career_history.json"), encoding="utf-8"))[-1]
    assert (row["outcome"], row["scenario_id"], row["races"], row["races_won"]) == ("goal_failed@turn72", 3, 35, 18)
    shown = notify.read_career_history(base)[0]
    assert shown["outcome"] == "goal_failed@turn72" and shown["scenario_id"] == 3


def test_mid_run_tier0_buy_skips_unlisted_circle_skills():
    sb = SkillBuyer(ROOT)
    chara = {"skill_array": [], "skill_point": 2000, "turn": 30,
             "skill_tips_array": [{"group_id": 20001, "rarity": 1, "level": 1}]}   # Right-Handed ○
    only_listed = {"learn_skill_only_user_provided": True, "learn_skill_tier0": ["Concentration"]}
    relaxed = sb._candidates(chara, {**only_listed, "learn_skill_only_user_provided": False})
    assert [c["resolution_reason"] for c in relaxed] == ["circle_variant"], relaxed   # unlisted ○ hint
    assert sb._candidates(chara, only_listed) == []                                  # leaked before the fix
    listed = {"learn_skill_only_user_provided": True, "learn_skill_tier0": ["Right-Handed ○"]}
    assert [c["resolution_reason"] for c in sb._candidates(chara, listed)] == ["priority_match"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
