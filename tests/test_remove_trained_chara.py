"""UmaClient.remove_trained_chara -- the batch trainee-release call behind the manual
delete-trainees UI. Verified against a live umacap capture:

    POST trained_chara/remove  {"trained_chara_id_array": [ ... ], "viewer_id": <viewer>}

viewer_id + device fields ride in via common() (added inside call/call_once), so the method
itself only needs to pass trained_chara_id_array. It uses call_once (no 205/208 replay) because a
release is irreversible and must never be transparently re-issued.

Run:
    python tests/test_remove_trained_chara.py
    python -m pytest tests/test_remove_trained_chara.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uma_api.client import UmaClient  # noqa: E402


def _client():
    """A UmaClient with __init__ bypassed (no crypto/network setup); remove_trained_chara only
    touches self.call_once, which we record instead of dispatching."""
    c = UmaClient.__new__(UmaClient)
    c.calls = []

    def fake_call_once(ep, args=None, timeout=30):
        c.calls.append((ep, args))
        return {"data": {"reward_summary_info": {}, "trained_chara_array": []}}

    # Guard: the real network call_once must never be reached in a unit test.
    def fake_call(*a, **k):
        raise AssertionError("remove_trained_chara used call(), not call_once()")

    c.call_once = fake_call_once
    c.call = fake_call
    return c


def test_single_id_sends_remove_batch():
    c = _client()
    c.remove_trained_chara([42])
    assert len(c.calls) == 1, c.calls
    ep, args = c.calls[0]
    assert ep == "trained_chara/remove", ep
    assert args == {"trained_chara_id_array": [42]}, args


def test_list_preserves_order_and_ints():
    c = _client()
    c.remove_trained_chara(["10", 19, "29"])   # mixed str/int -> all coerced to int, order kept
    ep, args = c.calls[0]
    assert ep == "trained_chara/remove"
    assert args == {"trained_chara_id_array": [10, 19, 29]}, args
    assert all(isinstance(x, int) for x in args["trained_chara_id_array"])


def test_empty_is_a_noop():
    c = _client()
    assert c.remove_trained_chara([]) is None
    assert c.remove_trained_chara(None) is None
    assert c.calls == [], "an empty selection must never fire a blank delete"


def test_zero_and_negative_ids_are_dropped():
    c = _client()
    # 0 / negatives are not real trained_chara_ids; drop them. If nothing survives, no call.
    assert c.remove_trained_chara([0, -1]) is None
    assert c.calls == []
    c.remove_trained_chara([0, 7, -3, 8])
    _, args = c.calls[0]
    assert args == {"trained_chara_id_array": [7, 8]}, args


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("remove_trained_chara OK")
