"""Unity Cup phase-weighted training value: the shared score (raw "arrows") scaled by career phase,
PLUS per-teammate emphasis -- BUILDING (bond<80) vs RAINBOW (bond>=80) partners and Aoharu soul BURSTS
(team_data_set.command_info_array[].soul_event_partner_array, matched by command_id, verified vs dump
20260713_192951 seq 69). No-op outside Unity. Weights: early/mid/end from the user's table.

Run:
    python tests/test_soul_burst.py
    python -m pytest tests/test_soul_burst.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.unity import UnityStrategy  # noqa: E402


def test_phase_boundaries():
    ph = UnityStrategy._unity_phase
    assert [ph(t) for t in (1, 24)] == ["early", "early"]
    assert [ph(t) for t in (25, 48)] == ["mid", "mid"]
    assert [ph(t) for t in (49, 78)] == ["end", "end"]


def test_phase_weights_and_override():
    u = UnityStrategy.__new__(UnityStrategy)
    assert u._unity_phase_weights({}, 10) == {"arrows": 1.00, "building": 0.75, "rainbow": 1.25, "burst": 3.0, "soul_build": 0.70}
    assert u._unity_phase_weights({}, 30) == {"arrows": 1.00, "building": 1.00, "rainbow": 1.50, "burst": 3.0, "soul_build": 0.60}
    assert u._unity_phase_weights({}, 60) == {"arrows": 0.75, "building": 0.25, "rainbow": 2.00, "burst": 3.0, "soul_build": 0.20}
    # per-preset override merges over the phase defaults
    w = u._unity_phase_weights({"unity_phase_weights": {"end": {"rainbow": 5.0}}}, 60)
    assert w["rainbow"] == 5.0 and w["arrows"] == 0.75


def test_partner_states_building_vs_rainbow():
    u = UnityStrategy.__new__(UnityStrategy)
    u._bond_map = lambda chara: {1: 85, 2: 50, 3: 90, 4: 79}   # 1,3 maxed (rainbow); 2,4 building
    cmd = {"training_partner_array": [1, 2, 3, 4, 999]}          # 999 = NPC (not a deck slot) -> ignored
    assert u._partner_states(cmd, {}) == (2, 2)


def _tds(cid, souls=(), sp=()):
    return {"team_data_set": {"command_info_array": [
        {"command_id": cid, "soul_event_partner_array": list(souls), "sp_soul_event_partner_array": list(sp)}]}}


def test_soul_burst_count():
    b = UnityStrategy._soul_burst_count
    assert b({"command_id": 101}, {}) == 0                         # no team_data_set
    assert b({"command_id": 101}, _tds(101, souls=[2])) == 1
    assert b({"command_id": 101}, _tds(101, souls=[2, 3], sp=[4])) == 3   # soul + super counted
    assert b({"command_id": 105}, _tds(101, souls=[2])) == 0        # different facility


def _unity():
    u = UnityStrategy.__new__(UnityStrategy)
    u._merged_emphasis = lambda preset, chara: {}
    u._bond_map = lambda chara: {}
    return u


def test_soul_build_score():
    # facility 101: teammates target_id 1 (gauge tier 4) and 2 (tier 2) BUILDING (guide_event); target 3
    # (tier 5) is ARMED (soul_event) -> counted by the burst term, NOT the build score.
    u = UnityStrategy.__new__(UnityStrategy)
    data = {"team_data_set": {
        "command_info_array": [{"command_id": 101, "guide_event_partner_array": [1, 2],
                                "soul_event_partner_array": [3], "sp_soul_event_partner_array": []}],
        "evaluation_info_array": [
            {"target_id": 1, "member_state": 1, "soul_threshold_id": 4},
            {"target_id": 2, "member_state": 1, "soul_threshold_id": 2},
            {"target_id": 3, "member_state": 1, "soul_threshold_id": 5}]}}
    assert abs(u._soul_build_score({"command_id": 101}, data) - (4 / 5 + 2 / 5)) < 1e-9   # 1.2
    assert u._soul_build_score({"command_id": 105}, data) == 0.0        # a different facility
    assert u._soul_build_score({"command_id": 101}, {}) == 0.0          # no team_data_set


def test_soul_build_adds_to_score_end_to_end():
    # a facility whose teammate is near the top of the gauge scores higher (mid soul_build weight 0.60).
    u = _unity()
    cmd = {"command_id": 101, "command_type": 1, "params_inc_dec_info_array": [{"target_type": 1, "value": 100}]}
    chara = {"turn": 30, "speed": 400}
    preset = {"stat_balance": False}
    data = {"team_data_set": {
        "command_info_array": [{"command_id": 101, "guide_event_partner_array": [1],
                                "soul_event_partner_array": [], "sp_soul_event_partner_array": []}],
        "evaluation_info_array": [{"target_id": 1, "member_state": 1, "soul_threshold_id": 5}]}}
    base = u._score_command(cmd, {}, chara, preset)
    with_build = u._score_command(cmd, data, chara, preset)
    assert abs((with_build - base) - (5 / 5 * 0.60)) < 1e-9   # one tier-5 building teammate * mid weight


def test_soul_burst_adds_phase_weight_end_to_end():
    # Same Speed training; a ready soul on that facility adds exactly the phase burst weight (mid=3).
    u = _unity()
    cmd = {"command_id": 101, "command_type": 1, "params_inc_dec_info_array": [{"target_type": 1, "value": 100}]}
    chara = {"turn": 30, "speed": 400}
    preset = {"stat_balance": False}
    base = u._score_command(cmd, {}, chara, preset)
    with_soul = u._score_command(cmd, _tds(101, souls=[2]), chara, preset)
    assert abs((with_soul - base) - 3.0) < 1e-9


def test_non_training_command_is_left_alone():
    # A rest/recreate command (command_type != 1) keeps the base score -- no phase weighting applied.
    u = _unity()
    rest = {"command_id": 301, "command_type": 3}
    chara = {"turn": 30}
    assert u._score_command(rest, _tds(301, souls=[2]), chara, {}) == \
        UnityStrategy.__mro__[1]._score_command(u, rest, _tds(301, souls=[2]), chara, {})


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("unity phase weights OK")
