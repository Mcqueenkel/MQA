"""Career-start response unwrap (UmaClient._promote_start_common). A mid-July 2026 game update
stopped duplicating the career state flat at data.* -- chara_info/home_info now live ONLY inside
data.single_mode_start_common. The bot reads the flat shape, so start_career promotes the nested
block; without it every fresh loop start looked like an empty turn-0 state and the runner idled
out instantly (zero-second "error / ended@turn0" stub careers that ate run slots and spammed the
webhook, while the real career dangled server-side until the next pass resumed it).

Shapes verified against live captures:
  old (2026-07-06, dumps/20260706_042752 tx 0005): chara_info flat at data.* AND nested
  new (2026-07-24, dumps/20260724_124011 tx 0004): nested under single_mode_start_common ONLY

Run:
    python tests/test_start_response_unwrap.py
    python -m pytest tests/test_start_response_unwrap.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uma_api.client import UmaClient

_P = UmaClient._promote_start_common


def _new_shape():
    # the post-update start response: state ONLY inside single_mode_start_common
    return {
        "data_headers": {"result_code": 1},
        "data": {
            "single_mode_start_common": {
                "chara_info": {"turn": 1, "speed": 100, "scenario_id": 4},
                "home_info": {"command_info_array": [{"command_id": 101}]},
                "unchecked_event_array": [],
            },
            "free_data_set": {"shop_info": {}},
        },
    }


def test_new_shape_promotes_nested_state():
    res = _P(_new_shape())
    d = res["data"]
    assert d["chara_info"]["turn"] == 1                       # runner reads data.chara_info
    assert d["home_info"]["command_info_array"]               # brain reads data.home_info
    assert d["unchecked_event_array"] == []
    assert d["free_data_set"] == {"shop_info": {}}            # scenario block untouched
    assert "single_mode_start_common" in d                    # original left in place


def test_old_shape_is_untouched():
    # pre-update servers sent BOTH; the flat copy must win and nothing may be overwritten
    res = {
        "data": {
            "chara_info": {"turn": 1, "speed": 999},
            "home_info": {"command_info_array": []},
            "single_mode_start_common": {"chara_info": {"turn": 77, "speed": 1}},
        }
    }
    out = _P(res)
    assert out["data"]["chara_info"]["speed"] == 999          # flat copy NOT clobbered


def test_no_start_common_is_a_noop():
    res = {"data": {"chara_info": {"turn": 5}}}               # e.g. a load/resume state
    assert _P(res) == {"data": {"chara_info": {"turn": 5}}}


def test_garbage_inputs_pass_through():
    assert _P(None) is None
    assert _P({}) == {}
    assert _P({"data": None}) == {"data": None}
    assert _P({"data": {"single_mode_start_common": "not-a-dict"}}) \
        == {"data": {"single_mode_start_common": "not-a-dict"}}


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
