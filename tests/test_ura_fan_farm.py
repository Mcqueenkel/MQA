"""URA fan-farm mode (preset ura_fan_farm) -- farm FANS, not a strong trainee.

The plan, as specified:
  1. bond the SPEED cards to orange fast, so friendship training starts early
  2. on non-race turns, train Speed or rest -- nothing else earns a turn
  3. reach ~700 Speed and ~500 Power/Stamina for the year-3 long races
  4. keep buying skills throughout (skills win races, races are the fans)

Steps 2 and 3 are the same mechanism: cap the OTHER stats at the plan's numbers and the shared
_stat_capped_trainings drops each as it is reached, collapsing the board to Speed then rest.

URA-ONLY: every assertion here also checks the other scenarios are untouched.

Run:
    python tests/test_ura_fan_farm.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.skills import SkillBuyer  # noqa: E402
from career_bot.core.training_brain import BaseTrainingStrategy  # noqa: E402
from career_bot.scenarios.grand_live import GrandLiveStrategy  # noqa: E402
from career_bot.scenarios.mant import MantStrategy  # noqa: E402
from career_bot.scenarios.unity import UnityStrategy  # noqa: E402
from career_bot.scenarios.ura import UraStrategy  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FARM = {"ura_fan_farm": True}


def _ura():
    u = UraStrategy.__new__(UraStrategy)      # method-only; __init__ wants a RacePlanner
    u._preset = {}
    return u


def _speed_cmd(partners=()):
    return {"command_type": 1, "command_id": 101, "training_partner_array": list(partners)}


def _chara(bonds):
    return {"support_card_array": [{"position": p, "opponent_evaluation": b} for p, b in bonds.items()]}


# ---- steps 2 + 3: the stat plan ----

def test_fan_farm_caps_everything_except_speed():
    caps = UraStrategy.FAN_FARM_STAT_CAPS
    assert caps["power"] == 500 and caps["stamina"] == 500      # the year-3 long-race numbers
    assert caps["speed"] > 700, "speed is a FLOOR to clear, never a ceiling to stop at"
    assert caps["guts"] < 500 and caps["wiz"] < 500             # not worth a turn in this plan


def test_caps_are_injected_only_when_the_mode_is_on():
    u = _ura()
    assert u._with_stat_caps({}) == {}                          # off -> preset untouched
    got = u._with_stat_caps(dict(FARM))
    assert got["stat_caps"] == UraStrategy.FAN_FARM_STAT_CAPS


def test_user_stat_caps_always_win():
    mine = {"speed": 900, "stamina": 300}
    got = _ura()._with_stat_caps({**FARM, "stat_caps": mine})
    assert got["stat_caps"] == mine


# ---- step 1: bond the speed cards first ----

def test_speed_facility_is_pushed_while_its_cards_are_still_bonding():
    u = _ura()
    u._bond_map = lambda chara: {1: 20, 2: 45}                  # both deck cards below orange
    base = BaseTrainingStrategy._score_command
    BaseTrainingStrategy._score_command = lambda *a, **k: 1.0
    try:
        hot = u._score_command(_speed_cmd([1, 2]), {}, {}, FARM)
        cold = u._score_command(_speed_cmd([1, 2]), {}, {}, {})
    finally:
        BaseTrainingStrategy._score_command = base
    assert hot > cold, (hot, cold)
    # standing Speed preference + one bond bonus per still-bonding deck card
    assert hot == 1.0 + UraStrategy.FAN_FARM_SPEED_BONUS + 2 * UraStrategy.FAN_FARM_SPEED_BOND_BONUS


def test_the_bond_push_fades_once_every_speed_card_is_orange():
    """The BOND bonus goes away at orange; the standing Speed preference stays."""
    u = _ura()
    u._bond_map = lambda chara: {1: 80, 2: 95}                  # at/above orange
    base = BaseTrainingStrategy._score_command
    BaseTrainingStrategy._score_command = lambda *a, **k: 1.0
    try:
        got = u._score_command(_speed_cmd([1, 2]), {}, {}, FARM)
    finally:
        BaseTrainingStrategy._score_command = base
    assert got == 1.0 + UraStrategy.FAN_FARM_SPEED_BONUS


def test_non_speed_facilities_get_no_push():
    u = _ura()
    u._bond_map = lambda chara: {1: 10}
    base = BaseTrainingStrategy._score_command
    BaseTrainingStrategy._score_command = lambda *a, **k: 1.0
    try:
        guts = {"command_type": 1, "command_id": 103, "training_partner_array": [1]}
        assert u._score_command(guts, {}, {}, FARM) == 1.0
    finally:
        BaseTrainingStrategy._score_command = base


def test_orange_threshold_matches_the_friendship_bar():
    assert UraStrategy.FAN_FARM_ORANGE_BOND == 80


# ---- step 4: keep buying skills ----

def _buyer():
    sb = SkillBuyer(ROOT)
    sb._candidates = lambda chara, preset: (
        [{"skill_id": 1, "name": "Zero", "cost": 100, "priority": 0}]
        if preset.get("learn_skill_tier0") else []
    ) + (
        [{"skill_id": 2, "name": "One", "cost": 100, "priority": 1}]
        if any(r for r in (preset.get("learn_skill_list") or [])) else []
    )
    return sb


def _state(sp=9999, turn=30):
    return {"data": {"chara_info": {"skill_point": sp, "turn": turn,
                                    "skill_array": [], "skill_tips_array": []}}}


def test_buy_throughout_opens_the_mid_run_buy_to_the_whole_list():
    sb = _buyer()
    got = {}
    sb._buy_batch = lambda c, s, sel, t, **k: (got.update(sel=sel) or (s, len(sel)))
    preset = {"learn_skill_tier0": ["Zero"], "learn_skill_list": [["One"]],
              "skill_buy_throughout": True}
    _, bought = sb.buy(None, _state(), preset, force=False)
    assert bought == 2, bought
    assert [c["skill_id"] for c in got["sel"]] == [1, 2]


def test_default_still_buys_tier0_only_mid_run():
    sb = _buyer()
    got = {}
    sb._buy_batch = lambda c, s, sel, t, **k: (got.update(sel=sel) or (s, len(sel)))
    preset = {"learn_skill_tier0": ["Zero"], "learn_skill_list": [["One"]]}
    sb.buy(None, _state(), preset, force=False)
    assert [c["skill_id"] for c in got["sel"]] == [1], "tier 1 must stay end-of-career by default"


def test_buy_throughout_works_with_no_tier0_at_all():
    """The fan-farm list may be a plain learn_skill_list with an empty tier 0."""
    sb = _buyer()
    got = {}
    sb._buy_batch = lambda c, s, sel, t, **k: (got.update(sel=sel) or (s, len(sel)))
    preset = {"learn_skill_list": [["One"]], "skill_buy_throughout": True}
    _, bought = sb.buy(None, _state(), preset, force=False)
    assert bought == 1 and [c["skill_id"] for c in got["sel"]] == [2]


# ---- URA only ----

def test_no_other_scenario_gains_fan_farm():
    for cls in (MantStrategy, UnityStrategy, GrandLiveStrategy):
        assert not hasattr(cls, "FAN_FARM_STAT_CAPS"), cls.__name__
        assert not hasattr(cls, "fan_farm"), cls.__name__


def test_ura_defaults_are_unchanged_with_the_mode_off():
    assert UraStrategy.DEFAULT_STAT_CAPS == (1400, 1400, 1400, 1400, 1400)
    assert UraStrategy.RACE_POLICY["goal_races_only"] is True
    assert UraStrategy.fan_farm({}) is False


# ---- the knobs must SURVIVE being saved ----

def test_fan_farm_knobs_survive_serialize_preset():
    """serialize_preset drops any key not on its allow-list, so an unlisted knob works until the
    preset is first saved from the UI and then silently vanishes. Every flag this mode needs has to
    round-trip."""
    from career_bot.core.presets import serialize_preset
    out = serialize_preset({"name": "URA Farm", "ura_fan_farm": True,
                            "skill_buy_throughout": True, "ura_fan_farm_bond_bonus": 4.0,
                            "learn_skill_tier0": [], "stat_caps": {}})
    assert out.get("ura_fan_farm") is True
    assert out.get("skill_buy_throughout") is True
    assert "ura_fan_farm_bond_bonus" in out


def test_every_scenario_knob_this_bot_reads_is_allow_listed():
    """Guards the whole scenario-knob block, not just URA's: a knob a scenario reads but the
    allow-list omits is a setting that cannot be persisted."""
    from career_bot.core.presets import serialize_preset
    knobs = ["ura_force_races", "ura_versus_bonus", "ura_fan_farm", "ura_fan_farm_bond_bonus",
             "skill_buy_throughout", "unity_config",
             "grand_live_song_targets", "grand_live_chase_songs", "grand_live_song_priority",
             "grand_live_hold_for_song", "grand_live_hold_song_min_score",
             "grand_live_hold_song_max_turns", "grand_live_cost_efficiency",
             "grand_live_card_weight", "grand_live_bonus_weight", "grand_live_light_hello",
             "grand_live_date_dead_score", "grand_live_date_energy_classic",
             "grand_live_date_energy_senior", "grand_live_date_energy_critical",
             "grand_live_wit_over_rest", "grand_live_wit_rest_max",
             "grand_live_reward_priority", "grand_live_square_priority"]
    raw = {"name": "x", "learn_skill_tier0": [], "stat_caps": {}, "unity_config": {},
           "grand_live_song_targets": {}, "grand_live_reward_priority": {},
           "grand_live_square_priority": {}}
    for k in knobs:
        raw.setdefault(k, 1)
    out = serialize_preset(raw)
    missing = [k for k in knobs if k not in out]
    assert not missing, f"dropped on save: {missing}"


# ---- standing Speed preference (the "always train speed" step) ----

def _scored(cmd, preset, bonds):
    u = _ura()
    u._bond_map = lambda chara: dict(bonds)
    base = BaseTrainingStrategy._score_command
    BaseTrainingStrategy._score_command = lambda *a, **k: 1.0
    try:
        return u._score_command(cmd, {}, {}, preset)
    finally:
        BaseTrainingStrategy._score_command = base


def test_speed_stays_in_front_after_the_cards_reach_orange():
    """The bond bonus fades at orange; without a standing preference the bot goes back to raw stat
    scoring and spreads taps again. Speed must keep leading for the whole career."""
    orange = {1: 90, 2: 95}
    speed = _scored(_speed_cmd([1, 2]), FARM, orange)
    guts = _scored({"command_type": 1, "command_id": 103, "training_partner_array": [1, 2]},
                   FARM, orange)
    assert speed > guts, (speed, guts)
    assert speed == 1.0 + UraStrategy.FAN_FARM_SPEED_BONUS


def test_bonding_phase_still_pushes_hardest():
    bonding = _scored(_speed_cmd([1, 2]), FARM, {1: 20, 2: 30})
    settled = _scored(_speed_cmd([1, 2]), FARM, {1: 90, 2: 95})
    assert bonding > settled, (bonding, settled)


def test_a_versus_duel_still_outranks_the_speed_preference():
    """URA duels drive the finale power-ups, so the duel bonus must stay the bigger lever."""
    assert UraStrategy.URA_VERSUS_BONUS > UraStrategy.FAN_FARM_SPEED_BONUS


def test_speed_preference_is_off_when_the_mode_is_off():
    assert _scored(_speed_cmd([1, 2]), {}, {1: 90, 2: 95}) == 1.0


def test_speed_preference_is_tunable_and_can_be_disabled():
    hot = _scored(_speed_cmd([]), {**FARM, "ura_fan_farm_speed_bonus": 9.0}, {})
    assert hot == 10.0
    off = _scored(_speed_cmd([]), {**FARM, "ura_fan_farm_speed_bonus": 0}, {})
    assert off == 1.0


def test_speed_bonus_knob_survives_a_save():
    from career_bot.core.presets import serialize_preset
    out = serialize_preset({"name": "x", "ura_fan_farm_speed_bonus": 3.0,
                            "learn_skill_tier0": [], "stat_caps": {}})
    assert "ura_fan_farm_speed_bonus" in out


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("URA fan farm OK")
