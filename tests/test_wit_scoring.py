"""How MQA scores the Wit facility (2026-10-20 analysis: a 3-Speed / 2-Wit deck trained Wit on 15% of
turns and took 4 of 12 double Wit friendship trainings).

  fix 1: overflowing energy is credited at 0, instead of cutting Wit's WHOLE score to 75% (35% after
         turn 72) whenever any of its +energy would overflow max energy.
  (fix 3, a type-aware deck-card bonus, was reverted the same day: careers got weaker.)

Run:
    python tests/test_wit_scoring.py
    python -m pytest tests/test_wit_scoring.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.training_brain import BaseTrainingStrategy  # noqa: E402
from career_bot.scenarios.grand_live import GrandLiveStrategy  # noqa: E402

WIT = 106


def _wit(energy=14, partners=()):
    return {"command_type": 1, "command_id": WIT, "failure_rate": 0, "training_partner_array": list(partners),
            "params_inc_dec_info_array": [{"target_type": 5, "value": 30}, {"target_type": 1, "value": 4},
                                          {"target_type": 30, "value": 19}, {"target_type": 10, "value": energy}]}


def _chara(vital, turn=40):
    return {"turn": turn, "vital": vital, "max_vital": 100, "speed": 500, "stamina": 400, "power": 500,
            "guts": 300, "wiz": 400, "max_speed": 1200, "max_stamina": 1200, "max_power": 1200,
            "max_guts": 1200, "max_wiz": 1200}


def _base(cmd, chara):
    s = BaseTrainingStrategy.__new__(BaseTrainingStrategy)
    return s._score_command_base(cmd, {"chara_info": chara}, chara, {"stat_balance": False, "ai_train_to_win": False})


def test_overflowing_energy_only_loses_the_energy_that_does_not_fit():
    # At vital 95 only 5 of Wit's +14 energy fit; at 86 all of it does. The score may differ by the
    # 9 wasted energy points (x 0.006, x the Wit focus) and nothing else -- the old rule cut the whole
    # score to 75%.
    full, overflow = _base(_wit(14), _chara(86)), _base(_wit(14), _chara(95))
    assert abs((full - overflow) - 9 * 0.006 * BaseTrainingStrategy.WIT_FOCUS) < 1e-6, (full, overflow)
    assert _base(_wit(14), _chara(100)) == _base(_wit(0), _chara(100))      # nothing fits: energy worth 0
    late = _base(_wit(14), _chara(95, turn=74))                               # used to be x0.35 here
    assert abs(late - overflow) < 0.2 * overflow, (late, overflow)


def test_wit_over_stamina_focus():
    # The user's rule (2026-10-30): Wit scores x1.3 for every uma; Stamina x0.7 once it covers what
    # the goal races need, and full weight while it is still short (a stayer keeps its Stamina).
    class _Planner:
        stamina_need = staticmethod(lambda chara: 400)
    s = BaseTrainingStrategy.__new__(BaseTrainingStrategy)
    s.race_planner = _Planner()
    assert s._stat_focus(4, {"stamina": 200}) == 1.3
    assert s._stat_focus(1, {"stamina": 450}) == 0.7
    assert s._stat_focus(1, {"stamina": 350}) == 1.0
    assert s._stat_focus(0, {"stamina": 450}) == 1.0
    g = GrandLiveStrategy.__new__(GrandLiveStrategy)
    g.race_planner = _Planner()
    chara = {"stamina": 450, "support_card_array": [], "evaluation_info_array": []}
    # the deck-card term, which decides most Grand Live boards, carries the same focus
    g._rainbow_count = lambda c, ch: 2
    g._bondable_count = lambda c, ch: 0
    for cid, want in ((106, 2 * 1.5 * 1.3), (105, 2 * 1.5 * 0.7), (101, 2 * 1.5)):
        BaseTrainingStrategy._score_command, orig = (lambda *a, **k: 0.0), BaseTrainingStrategy._score_command
        try:
            got = g._score_command({"command_type": 1, "command_id": cid}, {}, chara, {})
        finally:
            BaseTrainingStrategy._score_command = orig
        assert abs(got - want) < 1e-9, (cid, got, want)


def test_training_earns_the_performance_points_a_wanted_song_needs():
    # Song 40004 costs dance/vocal/mental 21 each. With vocal 5 the song is 16 vocal short: a training
    # giving 24 vocal earns 16 x 0.03, a mental-only one earns its 21 mental x 0.03 (also short), and
    # nothing counts once the song is affordable or after the last concert.
    g = GrandLiveStrategy.__new__(GrandLiveStrategy)
    g._last_turn = 40
    perf = {"dance": 30, "vocal": 5, "mental": 0}
    rows = [{"command_id": 102, "performance_inc_dec_info_array": [{"performance_type": 3, "value": 24}]},
            {"command_id": 106, "performance_inc_dec_info_array": [{"performance_type": 5, "value": 21}]},
            {"command_id": 101, "performance_inc_dec_info_array": [{"performance_type": 1, "value": 20}]}]
    data = lambda p: {"live_data_set": {"live_performance_info": p, "command_info_array": rows,
                                        "next_square_info_array": [{"square_id": 40004}]}}
    score = lambda cid, p=perf: g._song_points_score({"command_id": cid}, data(p))
    assert abs(score(102) - 16 * 0.03) < 1e-9
    assert abs(score(106) - 21 * 0.03) < 1e-9
    assert score(101) == 0.0                                    # dance already covered
    assert score(102, {"dance": 30, "vocal": 30, "mental": 30}) == 0.0   # affordable
    g._last_turn = 73
    assert score(102) == 0.0


def test_preset_stat_caps_are_no_longer_loaded_so_the_scenario_caps_apply():
    # The STAT CAPS panel row is gone: one user cap (Front Farm: stamina 400) used to replace Grand
    # Live's whole cap profile and its goal-driven stamina target. Old preset files may still hold it.
    from career_bot.core.presets import hydrate_preset, serialize_preset
    old_file = {"name": "Front Farm", "stat_caps": {"stamina": 400}}
    assert "stat_caps" not in serialize_preset(old_file)
    preset = hydrate_preset(old_file)
    assert "stat_caps" not in preset
    caps = GrandLiveStrategy.__new__(GrandLiveStrategy)._with_stat_caps(preset, {})["stat_caps"]
    assert caps["speed"] == 1600 and caps["stamina"] >= 1300          # Grand Live's own profile


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
