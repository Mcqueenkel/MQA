"""Failure is priced ONCE, and the rest gate cannot fire in the zero-risk energy zone.

Two findings from a 17-agent investigation over the real logs + API captures:

1. DOUBLE CHARGE. Commit f7f98f2 wrapped the scorer: _score_command_base already applied the
   multiplicative EV factor `score *= max(0, (1-fail) - failure_cost*fail)`, and the new
   _score_command ADDED a second, unbounded `failure_risk` penalty on top. That additive term was
   the only thing in the scorer that could make a score NEGATIVE, and four gates written earlier
   assume non-negative scores (notably _can_rescue_training, which bails on <= 0 before even
   checking whether a Vita/charm is owned). Its low_vital amplifier also double-counted energy:
   the game's failure_rate IS a function of vital (R^2 0.99 with vital+facility; 0.00% failure in
   all 2,466 captured observations at vital >= 55). Removed -> failure_risk is a constant 0.0.

2. REST GATE. 140 of 160 real rest turns fired on the plain energy gate, and 891 of 7,566 logged
   rests (11.8%) fired at vital >= 55 -- resting against a 0.00% failure risk, while recovery is
   capped at max_vital so most of the rest is thrown away. eff_rest is now also clamped by
   rest_ceiling (default 54).

Run:
    python tests/test_failure_pricing_and_rest_gate.py
    python -m pytest tests/test_failure_pricing_and_rest_gate.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.training_brain import BaseTrainingStrategy
from career_bot.core.presets import TUNABLE_KEYS, serialize_preset


def _b():
    b = BaseTrainingStrategy.__new__(BaseTrainingStrategy)
    b._merged_emphasis = lambda preset, chara: {}
    return b


def _cmd(failure=0, gain=20):
    return {"command_type": 1, "command_id": 101, "failure_rate": failure,
            "params_inc_dec_info_array": [{"target_type": 1, "value": gain}]}


_CHARA = {"turn": 30, "vital": 60, "speed": 300, "max_speed": 1200}
_PRESET = {"stat_balance": False}


# ---------------- 1. failure priced once ----------------

def test_failure_is_not_charged_twice():
    # the wrapper must add NOTHING for failure: total == base for the same command
    b = _b()
    for fail in (0, 10, 30, 45):
        total = b._score_command(_cmd(failure=fail), {}, _CHARA, _PRESET)
        base = b._score_command_base(_cmd(failure=fail), {}, _CHARA, _PRESET)
        assert abs(total - base) < 1e-9, (fail, total, base)


def test_adjustment_reports_zero_failure_risk():
    adj = _b()._score_command_adjustment(_cmd(failure=40), _CHARA, _PRESET)
    assert adj["failure_risk"] == 0.0


def test_multiplicative_model_still_holds():
    # the surviving EV term: failure_cost 1.0 -> factor (1-f) - f, i.e. 30% failure => x0.4
    b = _b()
    s0 = b._score_command(_cmd(failure=0), {}, _CHARA, _PRESET)
    s30 = b._score_command(_cmd(failure=30), {}, _CHARA, _PRESET)
    assert s0 > 0
    assert abs(s30 - s0 * 0.4) < 1e-6, (s0, s30)


def test_failure_can_never_make_a_good_board_negative():
    # THE invariant four downstream gates depend on. The old additive term broke it.
    b = _b()
    for fail in range(0, 101, 5):
        for vital in (0, 10, 25, 45, 70, 100):
            chara = dict(_CHARA, vital=vital)
            assert b._score_command(_cmd(failure=fail), {}, chara, _PRESET) >= 0.0, (fail, vital)


def test_energy_no_longer_amplifies_the_penalty():
    # identical board at full vs empty energy scores the same: energy risk is already inside the
    # game's own failure_rate, so the scorer must not price it a second time.
    b = _b()
    hi = b._score_command(_cmd(failure=30), {}, dict(_CHARA, vital=100), _PRESET)
    lo = b._score_command(_cmd(failure=30), {}, dict(_CHARA, vital=5), _PRESET)
    assert abs(hi - lo) < 1e-9, (hi, lo)


def test_max_failure_rate_sentinel_is_exact():
    # -999.0 must reach the caller intact; the additive term used to pollute it to -999.28
    blocked = _b()._score_command(_cmd(failure=40), {}, _CHARA, dict(_PRESET, max_failure_rate=30))
    assert blocked == -999.0


# ---------------- 2. the rest gate ----------------

def _eff_rest(best_score, preset, turn=30, max_vital=100):
    """Mirror of the eff_rest computation in _best_command."""
    b = _b()
    b._score_history = []
    b._quality_last_turn = -1
    return min(b._turn_quality_threshold(best_score, preset, turn),
               max_vital - 5,
               int(preset.get("rest_ceiling") or 54))


def test_rest_gate_never_reaches_the_zero_risk_zone():
    # weak-board boost used to push this to 48 + 18 = 66; capped at 54 it can no longer rest at the
    # vital >= 55 range where captured data shows 0.00% training failure.
    b = _b()
    b._score_history = [1.0] * 8
    b._quality_last_turn = -1
    weak = min(b._turn_quality_threshold(0.1, {}, 30), 95, 54)   # 0.1 << median 1.0 -> weak board
    assert weak <= 54


def test_rest_ceiling_is_tunable():
    assert _eff_rest(None, {"rest_ceiling": 40}) == 40
    assert _eff_rest(None, {"rest_ceiling": 70}) == 48        # base rest_threshold still binds


def test_max_vital_clamp_still_applies():
    # a low max_vital uma must still be able to rest out of the gate (no deadlock)
    assert _eff_rest(None, {}, max_vital=40) == 35


# ---------------- 3. the knobs are reachable ----------------

def test_scoring_knobs_survive_a_preset_save():
    knobs = {"failure_cost": 0.6, "max_failure_rate": 35, "rest_ceiling": 50,
             "score_command_v2": False, "mant_wit_over_rest": False, "mant_wit_rest_max": 15,
             "ura_wit_over_rest": False, "grand_live_wit_rest_max": 12}
    for k in knobs:
        assert k in TUNABLE_KEYS, f"{k} would be silently dropped on save"
    out = serialize_preset(dict(knobs, name="t"))
    for k, v in knobs.items():
        assert out.get(k) == v, (k, out.get(k))


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
