"""Unity (scenario 2) career finish must send the CURRENT-version release payload
{target_viewer_id, target_trained_chara_id} -- the old 1.32.8 {current_turn, factor_lottery_id} shape
102s and never releases the team slot, so a LOOP's next single_mode_team/start 102s. MANT/URA keep the
old shape (no current-version capture for them yet).

Run:
    python tests/test_unity_finish_release.py
    python -m pytest tests/test_unity_finish_release.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uma_api.client import UmaClient  # noqa: E402


class _Fake:
    def __init__(self, scenario):
        self.current_scenario_id = scenario
        self.viewer_id = 999
        self.last = None

    def call(self, ep, payload, **kw):
        self.last = (ep, payload)
        return {}


def _finish(scenario, **kw):
    f = _Fake(scenario)
    UmaClient.finish_career(f, **kw)
    return f.last[1]


def test_unity_finish_uses_target_ids():
    p = _finish(2, current_turn=78, factor_lottery_id=1, target_trained_chara_id=1513)
    assert p == {"target_viewer_id": 999, "target_trained_chara_id": 1513}


def test_unity_force_delete_adds_flag():
    p = _finish(2, current_turn=78, is_force_delete=True, target_trained_chara_id=1513)
    assert p == {"target_viewer_id": 999, "target_trained_chara_id": 1513, "is_force_delete": True}


def test_unity_without_tcid_falls_back_to_old_shape():
    # No id known -> can't build the release payload -> old shape (still 102s, but no worse than before).
    p = _finish(2, current_turn=78, factor_lottery_id=1, target_trained_chara_id=None)
    assert p == {"is_force_delete": False, "current_turn": 78, "factor_lottery_id": 1}


def test_mant_and_ura_keep_old_shape():
    for scn in (4, 1):
        p = _finish(scn, current_turn=78, factor_lottery_id=2, target_trained_chara_id=1513)
        assert p == {"is_force_delete": False, "current_turn": 78, "factor_lottery_id": 2}, scn


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("unity_finish_release OK")
