"""Review fixes in the shared training brain (career_bot/core/training_brain.py):

- Royal Kale Juice is not an energy rescue without a cupcake (the item manager never drinks it alone).
- The fan race flag is keyed on the turn: a same-turn retry re-offers it, later turns stay blocked.
- Junior bond-rush never picks a -999 sentinel (forbidden / over max_failure_rate) over a viable one.
- Pre-summer conserve respects the user's stat caps and a blocked Wit.
- goal_progress comes from goal emphasis only (the forecast-urgency branch was dead and is gone).

Run:
    python tests/test_training_brain_review_fixes.py
    python -m pytest tests/test_training_brain_review_fixes.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.training_brain import BaseTrainingStrategy as B  # noqa: E402

KALE, CUPCAKE = 2101, 2301
SPEED = {"command_type": 1, "command_id": 101, "is_enable": 1, "failure_rate": 0}
GUTS = {"command_type": 1, "command_id": 103, "is_enable": 1, "failure_rate": 0}
WIT = {"command_type": 1, "command_id": 106, "is_enable": 1, "failure_rate": 0}
REST = {"command_type": 7, "command_id": 701, "is_enable": 1}


def _brain():
    b = B.__new__(B)
    b.race_planner = None
    b._score_history = []
    b._quality_last_turn = None
    b._raced_turns = set()
    b._fan_raced = 0
    b._junior_recreated_turn = 0
    return b


def _bag(items):
    return {"free_data_set": {"user_item_info_array": [{"item_id": i, "num": n} for i, n in items.items()]}}


def test_royal_kale_is_not_a_rescue_without_a_cupcake():
    b = _brain()
    kale_only = _bag({KALE: 1})
    with_cake = _bag({KALE: 1, CUPCAKE: 1})
    assert b._rescue_energy_value(kale_only, 30, 48, 12) is None
    assert b._rescue_energy_value(with_cake, 30, 48, 12) == 100
    # End to end: a strong low-energy turn holding only Kale is NOT rescued (rest), with a cupcake it is.
    chara = {"turn": 30, "vital": 30}
    strong = dict(SPEED, failure_rate=45)
    assert b._can_rescue_training(kale_only, chara, {}, strong, 0.6, 30, 45, 48) is False
    assert b._can_rescue_training(with_cake, chara, {}, strong, 0.6, 30, 45, 48) is True


class _Planner:
    rerun_program = 0

    def goal_program(self, state):
        return 0

    def forced_program(self, state, preset):
        return 0

    def fan_goal_program(self, state, preset):
        return 1234 if state["data"]["chara_info"]["turn"] in (23, 24) else 0

    def label(self, pid):
        return "Asahi Hai"

    def choose(self, state, preset):
        return 0


def test_fan_race_retried_same_turn_but_blocked_later():
    b = _brain()
    b.race_planner = _Planner()
    b._best_command = lambda *a, **k: None
    preset = {"career_foresight": False, "fan_eligibility_farm": False, "dump_recreation_debug": False}

    def decide(turn):
        d = b.next_decision({"data": {"chara_info": {"turn": turn}}}, preset)
        return d.action, (d.payload or {}).get("program_id")

    assert decide(23) == ("race", 1234)
    # race_entry failed -> runner reloads the SAME turn: the mandatory fan race must be offered again.
    assert decide(23) == ("race", 1234)
    # It ran: Hopeful on turn 24 is not a second fan race.
    assert decide(24)[0] != "race"


def test_junior_bond_rush_never_picks_a_sentinel_over_a_viable_training():
    b = _brain()
    b._deck_has_group_cards = lambda chara: False
    b._score_command = lambda cmd, d, c, p: -999.0 if cmd["command_id"] == 103 else 0.3
    guts = dict(GUTS, training_partner_array=[1, 2, 3])   # most unbonded partners, but forbidden
    speed = dict(SPEED, training_partner_array=[4])
    b._bondable_count = lambda cmd, chara: len(cmd["training_partner_array"])
    score, picked = b._pick_scored_training([guts, speed], {}, {}, {}, 15)
    assert picked is speed and score == 0.3, (score, picked)
    # Only sentinels on the board -> still returns one (the rest gate handles the negative score).
    score, picked = b._pick_scored_training([guts], {}, {}, {}, 15)
    assert picked is guts and score == -999.0


def _conserve_turn(preset, chara_extra=None):
    """Turn 35 (pre-summer conserve), vital 75, weak board (Speed 0.2 < summer_score_threshold)."""
    b = _brain()
    b._scheduled_recreation = lambda *a, **k: None
    b._has_curable_bad_status = lambda *a, **k: False
    b._score_command = lambda cmd, d, c, p: 0.2 if cmd["command_id"] == 101 else 0.1
    chara = {"turn": 35, "vital": 75, "max_vital": 100, "motivation": 5, **(chara_extra or {})}
    data = {"home_info": {"command_info_array": [SPEED, WIT, REST]}}
    return b._best_command(data, chara, preset, record=False)


def test_pre_summer_conserve_respects_stat_caps_and_blocked_wit():
    # Baseline: the conserve step dedicates the weak turn to Wit.
    assert _conserve_turn({}) is WIT
    # Wit is at the user's cap -> never DEDICATE a turn to it; train the best capped-list option.
    assert _conserve_turn({"stat_caps": {"wiz": 800}}, {"wiz": 800}) is SPEED
    # Wit forbidden by extra_weight -1 for this phase (turns 25-48 = row 1).
    forbid_wit = [[0] * 5, [0, 0, 0, 0, -1], [0] * 5, [0] * 5]
    assert _conserve_turn({"extra_weight": forbid_wit}) is SPEED


def test_goal_progress_follows_goal_emphasis_not_the_forecast():
    b = _brain()
    b._goal_stat_emphasis = lambda chara, preset: {"speed": 0.5}
    # Even a dict-shaped stat_targets (the to_dict() output shape) no longer feeds an urgency term.
    b._forecast = types.SimpleNamespace(stat_targets={"speed": 1000})
    cmd = dict(SPEED, params_inc_dec_info_array=[{"target_type": 1, "value": 20}])
    adj = b._score_command_adjustment(cmd, {"turn": 30, "speed": 0}, {})
    gain = b._command_stat_total(cmd)
    assert abs(adj["goal_progress"] - gain * 0.20 * 0.5) < 1e-9, adj


def test_fan_race_that_already_ran_this_turn_is_done():
    # Grand Live's Concert screen stays on turn 24 after Hopeful: race_history, not the turn, says it ran.
    me = types.SimpleNamespace(_fan_raced=24)
    ran = {"data": {"race_history": [{"turn": 23, "program_id": 624}, {"turn": 24, "program_id": 625}]}}
    not_yet = {"data": {"race_history": [{"turn": 23, "program_id": 624}]}}
    assert B._fan_race_done(me, ran, 24) is True
    assert B._fan_race_done(me, not_yet, 24) is False     # same-turn retry after a failed entry
    assert B._fan_race_done(me, not_yet, 25) is True
    assert B._fan_race_done(types.SimpleNamespace(_fan_raced=0), ran, 24) is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
