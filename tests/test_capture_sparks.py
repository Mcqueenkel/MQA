"""Regression test for CareerRunner._capture_sparks field/nesting.

Guards the 1.32.8 spark-capture bug: sparks live in `factor_info_array`
([{factor_id, level}, ...]) on the factor_select CONFIRM response at
res['data']['single_mode_finish_common'] (single level, per the live capture
in UmaDumpy dumps/20260702_005444). The old code read a non-existent
`factor_id_array`, so notify embeds always showed no sparks.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.runner import CareerRunner


class _Fake:
    """Minimal stand-in so we can call the unbound method without CareerRunner.__init__."""
    _notify_factor_ids = None
    _notify_rank = None
    _notify_rank_score = None


# Shape mirrors the real 1.32.8 factor_select-confirm capture (0003.json):
# res['data']['single_mode_finish_common']{trained_chara_id, trained_chara:[...]}.
CONFIRM_RESPONSE = {
    "data_headers": {"result_code": 1},
    "data": {
        "single_mode_finish_common": {
            "trained_chara_id": 1447,
            "trained_chara": [
                {"trained_chara_id": 999, "factor_info_array": [{"factor_id": 1, "level": 3}]},
                {
                    "trained_chara_id": 1447,  # the just-finished uma
                    "factor_info_array": [
                        {"factor_id": 402, "level": 0},
                        {"factor_id": 3302, "level": 0},
                        {"factor_id": 1000301, "level": 0},
                    ],
                    "rank": 16,
                    "rank_score": 16124,
                },
            ],
        }
    },
}


def test_capture_sparks_reads_factor_info_array():
    f = _Fake()
    CareerRunner._capture_sparks(f, CONFIRM_RESPONSE)
    assert f._notify_factor_ids == [402, 3302, 1000301], f._notify_factor_ids
    assert f._notify_rank == 16
    assert f._notify_rank_score == 16124


def test_capture_sparks_ignores_missing_finish_common():
    # A reconciled (102) finish carries only trained_chara_info -> no sparks, no crash.
    f = _Fake()
    CareerRunner._capture_sparks(f, {"data": {"trained_chara_info": {"trained_chara_id": 1447}}})
    assert not f._notify_factor_ids
    assert not f._notify_rank_score


def test_tcid_reads_finish_common_shape():
    # 1.32.8 finish returns single_mode_finish_common.trained_chara_id (no trained_chara_info).
    # _tcid must still find it, else change_nickname is skipped and the career slot never releases.
    # _tcid is a closure inside close_career; mirror its logic here (keep in sync with client.py).
    def tcid(state):
        d = (state or {}).get("data") or {}
        for c in (d.get("trained_chara_info"), d.get("single_mode_finish_common")):
            if isinstance(c, dict) and c.get("trained_chara_id"):
                return int(c["trained_chara_id"])
        return None
    assert tcid({"data": {"single_mode_finish_common": {"trained_chara_id": 1452}}}) == 1452
    assert tcid({"data": {"trained_chara_info": {"trained_chara_id": 1447}}}) == 1447
    assert tcid({"data": {}}) is None


if __name__ == "__main__":
    test_capture_sparks_reads_factor_info_array()
    test_capture_sparks_ignores_missing_finish_common()
    test_tcid_reads_finish_common_shape()
    print("test_capture_sparks: OK")
