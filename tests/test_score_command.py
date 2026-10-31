"""Unit tests for MantStrategy._score_command -- the per-command training scorer.

This is the single biggest validation gap: the scorer drives every training pick but had
no tests. These assert the SHAPE of the scoring (failure expected-value, stat-gain ordering,
stat-cap attenuation, rainbow reward, the new tunable failure_cost / max_failure_rate) so a
refactor can't silently change behaviour. No game/network needed -- pure synthetic boards.

Run:
    python tests/test_score_command.py            # standalone, prints PASS/FAIL
    python -m pytest tests/test_score_command.py  # if you have pytest
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.mant import MantStrategy  # noqa: E402


def _strategy():
    s = MantStrategy()      # race_planner=None -> base_dir None, no external deps
    s._forecast = None      # foresight off so tests reason from raw scoring
    return s


def _chara(**over):
    base = {
        "turn": 20, "vital": 80, "motivation": 3,
        "speed": 300, "stamina": 300, "power": 300, "guts": 300, "wiz": 300,
        "max_speed": 1200, "max_stamina": 1200, "max_power": 1200,
        "max_guts": 1200, "max_wiz": 1200,
        "skill_point": 0, "evaluation_info_array": [],
    }
    base.update(over)
    return base


def _speed_cmd(gain=20, failure_rate=0, partners=None, level=1):
    # command_id 101 = Speed training; target_type 1 = Speed stat.
    return {
        "command_id": 101, "command_type": 1, "level": level, "failure_rate": failure_rate,
        "training_partner_array": partners or [],
        "tips_event_partner_array": [],
        "params_inc_dec_info_array": [{"target_type": 1, "value": gain}],
    }


_DATA = {"home_info": {"command_info_array": []}}
# ai_train_to_win off keeps the learned emphasis out of unit scoring.
_PRESET = {"ai_train_to_win": False}


def _score(cmd, chara=None, preset=None):
    return _strategy()._score_command(cmd, _DATA, chara or _chara(), preset or _PRESET)


def test_more_stat_gain_scores_higher():
    assert _score(_speed_cmd(gain=30)) > _score(_speed_cmd(gain=10))


def test_failure_default_matches_old_one_minus_fail_over_50():
    # Default failure_cost=1.0 must reproduce the old `1 - fail/50` exactly: 30% -> x0.4.
    s0 = _score(_speed_cmd(gain=20, failure_rate=0))
    s30 = _score(_speed_cmd(gain=20, failure_rate=30))
    assert abs(s30 - s0 * 0.4) < 1e-6, (s0, s30)


def test_higher_failure_scores_lower():
    assert _score(_speed_cmd(gain=20, failure_rate=40)) < _score(_speed_cmd(gain=20, failure_rate=10))


def test_failure_cost_is_tunable():
    cmd = _speed_cmd(gain=20, failure_rate=30)
    lenient = _score(cmd, preset={"ai_train_to_win": False, "failure_cost": 0.5})
    strict = _score(cmd, preset={"ai_train_to_win": False, "failure_cost": 1.0})
    assert lenient > strict  # lower failure_cost -> less penalty -> higher score


def test_max_failure_rate_hard_filters():
    cmd = _speed_cmd(gain=20, failure_rate=40)
    blocked = _score(cmd, preset={"ai_train_to_win": False, "max_failure_rate": 30})
    assert blocked == -999.0


def test_stat_near_cap_attenuates():
    far = _score(_speed_cmd(gain=20), _chara(speed=300))
    near = _score(_speed_cmd(gain=20), _chara(speed=1190))   # ratio ~0.99 -> heavy attenuation
    assert near < far


def test_capped_stat_loses_gain():
    capped = _score(_speed_cmd(gain=20), _chara(speed=1200))   # ratio 1.0 -> stat gain zeroed
    open_stat = _score(_speed_cmd(gain=20), _chara(speed=300))
    assert capped < open_stat


def test_rainbow_partner_adds_reward():
    chara = _chara(evaluation_info_array=[{"target_id": 1, "evaluation": 85}])  # deck partner, bond 85
    with_rainbow = _score(_speed_cmd(gain=20, partners=[1]), chara)
    without = _score(_speed_cmd(gain=20, partners=[]), chara)
    assert with_rainbow > without


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


def test_ura_versus_duel_bonus():
    # URA: a facility flagged with a rival VERSUS duel (ura_data_set.command_info_array
    # .versus_event_partner_id) gets a DOMINANT flat bonus so the duel is always taken --
    # ported from the working "new api bot" URA fork. Identical inputs otherwise, so the
    # delta must be exactly the bonus.
    from career_bot.scenarios.ura import UraStrategy
    s = UraStrategy()
    s._forecast = None
    cmd = _speed_cmd(gain=20)
    plain = dict(_DATA)
    duel = dict(_DATA)
    duel["ura_data_set"] = {"command_info_array": [
        {"command_type": 1, "command_id": 101, "versus_event_partner_id": 1003},
    ]}
    base = s._score_command(cmd, plain, _chara(), _PRESET)
    with_duel = s._score_command(cmd, duel, _chara(), _PRESET)
    assert abs((with_duel - base) - UraStrategy.URA_VERSUS_BONUS) < 1e-6, (base, with_duel)
    # a duel on a DIFFERENT facility gives this one nothing
    other = dict(_DATA)
    other["ura_data_set"] = {"command_info_array": [
        {"command_type": 1, "command_id": 105, "versus_event_partner_id": 1003},
    ]}
    assert abs(s._score_command(cmd, other, _chara(), _PRESET) - base) < 1e-6
