"""Unit tests for the 'strong training beats a G2/G3 race' behavior.

User rule: when a G3/G2 race is on the schedule but THIS turn's training is strong
(>= 2 rainbows, OR a total stat gain > 40), train instead of racing -- and on that
training the bot must also use a megaphone and the matching-type Ankle Weights.

Covered here:
  A. MantStrategy._command_stat_total -- sums the five trainable stats ONLY (skill points + energy excluded).
  B. MantStrategy._train_outvalues_race -- the strong board overrides the scheduled-race
     and min-fans guards on a G2/G3, never on a G1, and never on a rest turn.
  C. MantItemManager._anklet_target / _megaphone_target -- a >= 2-rainbow board pulls the
     matching-type anklet + a megaphone even when its raw stat number is modest.

No game/network needed -- synthetic boards/items.

Run:
    python tests/test_strong_train_over_race.py
    python -m pytest tests/test_strong_train_over_race.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.mant_items import MantItemManager  # noqa: E402
from career_bot.scenarios.mant import MantStrategy  # noqa: E402

_IM = MantItemManager()


# ============================ A: _command_stat_total ============================

def _cmd(params):
    return {"command_id": 101, "command_type": 1, "params_inc_dec_info_array": params}


def test_stat_total_sums_five_stats():
    # target_type 1..5 = speed/stamina/power/guts/wit.
    assert MantStrategy()._command_stat_total(
        _cmd([{"target_type": 1, "value": 20}, {"target_type": 2, "value": 15},
              {"target_type": 3, "value": 10}])) == 45.0


def test_stat_total_excludes_sp_and_energy():
    # 30 = skill points (NOT counted now), 10 = energy (excluded): only the 20 speed counts.
    assert MantStrategy()._command_stat_total(
        _cmd([{"target_type": 1, "value": 20}, {"target_type": 30, "value": 100},
              {"target_type": 10, "value": -15}])) == 20.0


def test_stat_total_none_and_empty_safe():
    assert MantStrategy()._command_stat_total(None) == 0.0
    assert MantStrategy()._command_stat_total(_cmd([])) == 0.0


# ====================== B: _train_outvalues_race override =======================

class _FakeRP:
    """Minimal race_planner: grades by race_instance_id prefix (1=G1,2=G2,3=G3) and reports
    which programs the user scheduled this turn."""
    base_dir = None

    def __init__(self, programs, wanted=()):
        self.program = dict(programs)
        self._wanted = list(wanted)

    def wanted_programs(self, preset, turn=0):
        return list(self._wanted)


_G1, _G2, _G3 = 100001, 200001, 300001
_PROGRAMS = {_G1: {"race_instance_id": "100001"},
             _G2: {"race_instance_id": "200001"},
             _G3: {"race_instance_id": "300001"}}

# ai/foresight off so the gate reasons from raw scoring only.
_GP = {"ai_train_to_win": False, "enable_ai_policy": False}


def _strategy(wanted=()):
    s = MantStrategy()
    s._forecast = None
    s.race_planner = _FakeRP(_PROGRAMS, wanted)
    return s


def _gchara(fans=5000, vital=80, maxed=()):
    return {"turn": 30, "vital": vital, "motivation": 3, "fans": fans,
            "speed": 300, "stamina": 300, "power": 300, "guts": 300, "wiz": 300,
            "max_speed": 1200, "max_stamina": 1200, "max_power": 1200,
            "max_guts": 1200, "max_wiz": 1200, "skill_point": 0,
            "evaluation_info_array": [{"target_id": p, "evaluation": 85} for p in maxed]}


def _train(cmd_id=101, stat_tt=1, gain=20, partners=()):
    return {"command_id": cmd_id, "command_type": 1, "failure_rate": 0,
            "training_partner_array": list(partners), "tips_event_partner_array": [],
            "params_inc_dec_info_array": [{"target_type": stat_tt, "value": gain}]}


def _gboard(trainings, rest=True):
    cmds = list(trainings)
    if rest:
        cmds.append({"command_type": 7, "command_id": 701, "is_enable": 1})
    return {"home_info": {"command_info_array": cmds}, "free_data_set": {}}


def test_g2_two_rainbow_low_stat_trains_by_default():
    # The rainbow shortcut is ON by default now (strong_train_rainbow_min = 2): a 2-rainbow board
    # TRAINS over a G2 even when its raw stat total is under the 40 bar. Rationale: with the shortcut
    # off, the raw bar was cleared on only ~1 board in 3, so MANT's 28-race schedule left the bot
    # racing ~30 turns and training ~30 of 78 -- and train count correlates 0.83 with final stats.
    # A 2-rainbow board is the best trade in the game.
    s = _strategy()
    board = _gboard([_train(partners=[1, 2], gain=15)])
    assert s._train_outvalues_race(board, _gchara(fans=100, maxed=[1, 2]), _GP, _G2) is True


def test_rainbow_shortcut_can_be_disabled():
    # strong_train_rainbow_min = 0 restores the old behaviour: only raw stat total counts, so the
    # same low-stat 2-rainbow board races instead.
    s = _strategy()
    board = _gboard([_train(partners=[1, 2], gain=15)])
    preset = dict(_GP, strong_train_rainbow_min=0)
    assert s._train_outvalues_race(board, _gchara(fans=100, maxed=[1, 2]), preset, _G2) is False


def test_rainbow_shortcut_opt_in():
    # ...but setting strong_train_rainbow_min re-enables the rainbow shortcut.
    s = _strategy()
    board = _gboard([_train(partners=[1, 2], gain=15)])
    preset = dict(_GP, strong_train_rainbow_min=2)
    assert s._train_outvalues_race(board, _gchara(fans=100, maxed=[1, 2]), preset, _G2) is True


def test_g2_big_stat_board_trains():
    # G2, no rainbow but >40 total stat gain -> overrides.
    s = _strategy()
    board = _gboard([_train(gain=45)])
    assert s._train_outvalues_race(board, _gchara(fans=100), _GP, _G2) is True


def test_g2_sp_rich_board_no_longer_trains_over_race():
    # SP no longer counts: a 25 speed + 20 SP board is only 25 real stats (< 40), so it does NOT
    # override the G2 -- it races. (The +20 SP makes no difference now.)
    s = _strategy()
    sp_train = {"command_id": 101, "command_type": 1, "failure_rate": 0,
                "training_partner_array": [], "tips_event_partner_array": [],
                "params_inc_dec_info_array": [{"target_type": 1, "value": 25},
                                              {"target_type": 30, "value": 20}]}
    assert s._train_outvalues_race(_gboard([sp_train]), _gchara(fans=100), _GP, _G2) is False


def test_summer_lowers_threshold_to_30():
    # In summer camp (turn 37), a 35-stat board -- below the normal 40 -- now trains over a G2.
    s = _strategy()
    chara = _gchara(fans=100)
    chara["turn"] = 37
    assert s._train_outvalues_race(_gboard([_train(gain=35)]), chara, _GP, _G2) is True


def test_summer_threshold_still_needs_30():
    # A 25-stat board in summer is still below the summer bar (30) -> doesn't override.
    s = _strategy()
    chara = _gchara(fans=100)
    chara["turn"] = 37
    assert s._train_outvalues_race(_gboard([_train(gain=25)]), chara, _GP, _G2) is False


def test_non_summer_keeps_40_threshold():
    # Same 35-stat board outside summer (turn 30) stays below 40 -> races (summer bar is camp-only).
    s = _strategy()
    assert s._train_outvalues_race(_gboard([_train(gain=35)]), _gchara(fans=100), _GP, _G2) is False


def test_scheduled_g2_strong_board_trains_via_override():
    # The race is USER-SCHEDULED (in wanted). Normally never skipped; a >=40-stat board overrides.
    s = _strategy(wanted=[_G2])
    board = _gboard([_train(gain=45)])
    assert s._train_outvalues_race(board, _gchara(), _GP, _G2) is True


def test_scheduled_g2_strong_board_races_when_override_disabled():
    # Same board, override OFF -> the scheduled-race guard wins -> race (isolates the override's effect).
    s = _strategy(wanted=[_G2])
    board = _gboard([_train(partners=[1, 2], gain=15)])
    preset = dict(_GP, strong_train_over_race=False)
    assert s._train_outvalues_race(board, _gchara(maxed=[1, 2]), preset, _G2) is False


def test_g1_never_skipped_even_on_strong_board():
    s = _strategy()
    board = _gboard([_train(partners=[1, 2], gain=60)])
    assert s._train_outvalues_race(board, _gchara(maxed=[1, 2]), _GP, _G1) is False


def test_weak_board_does_not_override():
    # G2, low fans, weak board (no rainbow, small gain) -> override doesn't fire -> min-fans guard races.
    s = _strategy()
    board = _gboard([_train(gain=12)])
    assert s._train_outvalues_race(board, _gchara(fans=100), _GP, _G2) is False


def test_rest_turn_does_not_count_as_strong():
    # A 2-rainbow board the bot is too tired to train (vital 8 -> rests) must NOT skip the race.
    s = _strategy()
    board = _gboard([_train(partners=[1, 2], gain=15)])
    assert s._train_outvalues_race(board, _gchara(fans=100, vital=8, maxed=[1, 2]), _GP, _G2) is False


def test_rainbow_min_tunable():
    # Raise the bar to 3 rainbows: a 2-rainbow board no longer auto-trains a low-fans G2.
    s = _strategy()
    board = _gboard([_train(partners=[1, 2], gain=12)])
    preset = dict(_GP, strong_train_rainbow_min=3)
    assert s._train_outvalues_race(board, _gchara(fans=100, maxed=[1, 2]), preset, _G2) is False


# --- regression: the gate's probe must not pollute the turn-quality baseline on race turns ---

def test_probe_does_not_pollute_score_history_on_race_turn():
    # A scheduled G2 with a weak board RACES (override doesn't fire). The probe call to
    # _best_command(record=False) must leave the rolling baseline untouched -- pre-fix it
    # recorded a sample here and skewed the future rest/energy-banking gate.
    s = _strategy(wanted=[_G2])
    board = _gboard([_train(gain=12)])
    assert s._train_outvalues_race(board, _gchara(maxed=[]), _GP, _G2) is False
    assert s._score_history == []
    assert s._quality_last_turn == -1


def test_value_path_still_records_once():
    # A non-scheduled, high-fans, weak G3 falls through to the value comparison, whose
    # _best_command(record=True) call still logs exactly one baseline sample (not zero, not two).
    s = _strategy()
    board = _gboard([_train(gain=12)])
    assert s._train_outvalues_race(board, _gchara(fans=5000), _GP, _G3) is False
    assert len(s._score_history) == 1


# ================= C: anklet + megaphone fire on a 2-rainbow board ==============

def _ichara(maxed=(), turn=30):
    return {"turn": turn, "evaluation_info_array": [{"target_id": p, "evaluation": 85} for p in maxed]}


def _istate(maxed=(), turn=30):
    return {"data": {"chara_info": _ichara(maxed, turn), "free_data_set": {"item_effect_array": []}}}


def _itrain(cmd_id=101, gain=10, partners=()):
    return {"command_id": cmd_id, "command_type": 1,
            "training_partner_array": list(partners),
            "params_inc_dec_info_array": [{"target_type": 1, "value": gain}]}


_IP = {"prioritize_summer_buffs": False}  # don't reserve the buffs for summer in these tests


def test_anklet_fires_on_two_rainbow_low_stat_board():
    # Stat gain 10 is below the 30 threshold, but 2 rainbows -> spend the matching-type anklet.
    got = _IM._anklet_target(_istate(maxed=[1, 2]), _itrain(101, gain=10, partners=[1, 2]),
                             {"Speed Ankle Weights": 1}, _IP)
    assert got == ("Speed Ankle Weights", 1)


def test_anklet_skips_weak_low_stat_board():
    got = _IM._anklet_target(_istate(), _itrain(101, gain=10, partners=[]),
                             {"Speed Ankle Weights": 1}, _IP)
    assert got is None


def test_anklet_must_match_training_type():
    # A Power training (102) pulls the POWER anklet; holding only a Speed anklet -> nothing fires.
    state, cmd = _istate(maxed=[1, 2]), _itrain(102, gain=10, partners=[1, 2])
    assert _IM._anklet_target(state, cmd, {"Power Ankle Weights": 1}, _IP) == ("Power Ankle Weights", 1)
    assert _IM._anklet_target(state, cmd, {"Speed Ankle Weights": 1}, _IP) is None


def test_megaphone_fires_on_two_rainbow_low_stat_board():
    # Modest stat gain but 2 rainbows -> treated as a large board -> best owned megaphone fires.
    got = _IM._megaphone_target(_istate(maxed=[1, 2]), _itrain(101, gain=10, partners=[1, 2]),
                                {"Empowering Megaphone": 1}, _IP, None, 30, None)
    assert got == ("Empowering Megaphone", 1)


def test_megaphone_skips_weak_low_stat_board():
    got = _IM._megaphone_target(_istate(), _itrain(101, gain=8, partners=[]),
                                {"Empowering Megaphone": 1}, _IP, None, 30, None)
    assert got is None


def test_megaphone_not_restacked_while_one_is_active():
    # A Motivating Megaphone (8002) is already running. Even on a strong 2-rainbow board with an
    # Empowering in hand, the bot must WAIT for the active one to expire, not overwrite it.
    state = _istate(maxed=[1, 2])
    state["data"]["free_data_set"]["item_effect_array"] = [{"item_id": 8002}]  # Motivating active
    got = _IM._megaphone_target(state, _itrain(101, gain=10, partners=[1, 2]),
                                {"Empowering Megaphone": 2}, _IP, None, 30, None)
    assert got is None


# --- summer-camp megaphone schedule: Motivating at camp start (t37/t61), Empowering on the last
#     camp turn (t40/t64) only on a strong board ---

def test_summer_motivating_at_camp_start():
    # t37: always Motivating first (+40%, 3 turns covers 37-39), even holding an Empowering.
    got = _IM._megaphone_target(_istate(maxed=[1, 2], turn=37), _itrain(101, gain=10, partners=[1, 2]),
                                {"Motivating Megaphone": 1, "Empowering Megaphone": 1}, _IP, None, 37, None)
    assert got == ("Motivating Megaphone", 1)


def test_summer_empowering_on_strong_last_camp_turn():
    # t40 with a strong board: Empowering (+60%) caps the camp's final turn.
    got = _IM._megaphone_target(_istate(maxed=[1, 2], turn=40), _itrain(101, gain=10, partners=[1, 2]),
                                {"Empowering Megaphone": 1, "Motivating Megaphone": 1}, _IP, None, 40, None)
    assert got == ("Empowering Megaphone", 1)


def test_summer_empowering_held_on_weak_last_camp_turn():
    # t40 weak board -> hold the Empowering rather than waste it.
    got = _IM._megaphone_target(_istate(turn=40), _itrain(101, gain=8, partners=[]),
                                {"Empowering Megaphone": 1}, _IP, None, 40, None)
    assert got is None


def test_summer_motivating_falls_back_when_none_held():
    # t37 with no Motivating in hand -> fall back to the best owned tier (Empowering).
    got = _IM._megaphone_target(_istate(maxed=[1, 2], turn=37), _itrain(101, gain=10, partners=[1, 2]),
                                {"Empowering Megaphone": 1}, _IP, None, 37, None)
    assert got == ("Empowering Megaphone", 1)


# --- the summer-reserve hold must NOT withhold the buffs on a strong board (default config) ---
# Turn 30 is pre-summer, owned counts are at the reserve (anklet 1, mega 2), and
# prioritize_summer_buffs defaults ON -- so without the bypass, _hold_for_summer would suppress both.

def test_anklet_bypasses_summer_hold_on_strong_board():
    got = _IM._anklet_target(_istate(maxed=[1, 2]), _itrain(101, gain=10, partners=[1, 2]),
                             {"Speed Ankle Weights": 1}, {})  # default prioritize_summer_buffs (on)
    assert got == ("Speed Ankle Weights", 1)


def test_anklet_still_held_for_summer_on_weak_board():
    # Weak board at reserve stock pre-summer -> the hold correctly still saves it for summer.
    got = _IM._anklet_target(_istate(), _itrain(101, gain=10, partners=[]),
                             {"Speed Ankle Weights": 1}, {})
    assert got is None


def test_megaphone_bypasses_summer_hold_on_strong_board():
    got = _IM._megaphone_target(_istate(maxed=[1, 2]), _itrain(101, gain=10, partners=[1, 2]),
                                {"Empowering Megaphone": 2}, {}, None, 30, None)
    assert got == ("Empowering Megaphone", 1)


def test_megaphone_still_held_for_summer_on_weak_board():
    got = _IM._megaphone_target(_istate(), _itrain(101, gain=8, partners=[]),
                                {"Empowering Megaphone": 2}, {}, None, 30, None)
    assert got is None


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {fn.__name__}: {exc}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
