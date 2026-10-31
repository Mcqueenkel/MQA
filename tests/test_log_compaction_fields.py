"""compact_api_data must keep the two fields four separate investigations stalled without.

The career log trims responses to keep a full career at a few hundred KB. That trimming dropped:
  - playing_state    -> a Grand Live idle-out could not be explained (career_log_20260731_105832):
                        no way to tell a Concert screen from a normal turn.
  - unchecked_event_array -> check_event is ~39% of a URA career (139 of 356 requests), and without
                        a queue length there is no way to tell a poll that found work from one that
                        found nothing, so the drain loop cannot be judged.

A COUNT is kept, never the events themselves -- the whole point of compaction is to stay small.

Run:
    python tests/test_log_compaction_fields.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.report import compact_api_data  # noqa: E402


def _res(queue=None, playing_state=None, extra_chara=None):
    chara = {"turn": 24, "vital": 58, "motivation": 5, "speed": 324}
    if playing_state is not None:
        chara["playing_state"] = playing_state
    chara.update(extra_chara or {})
    body = {"chara_info": chara, "home_info": {"blob": "x" * 5000}}
    if queue is not None:
        body["unchecked_event_array"] = queue
    return {"data_headers": {"result_code": 1}, "data": body}


def test_queue_length_is_recorded():
    assert compact_api_data("RES", _res(queue=[{"event_id": 1}, {"event_id": 2}]))["queued_events"] == 2


def test_an_empty_queue_is_distinguishable_from_a_full_one():
    """THE point: 0 means the poll found nothing, which is what makes a wasted call visible."""
    assert compact_api_data("RES", _res(queue=[]))["queued_events"] == 0


def test_a_missing_queue_field_is_not_invented():
    # absent != empty; a response that never carried the field must not report 0
    assert "queued_events" not in compact_api_data("RES", _res())


def test_playing_state_is_kept():
    assert compact_api_data("RES", _res(playing_state=10))["playing_state"] == 10


def test_playing_state_absent_when_the_game_did_not_send_it():
    assert "playing_state" not in compact_api_data("RES", _res())


def test_the_event_bodies_are_never_kept():
    """Only the count -- keeping the events would undo the compaction."""
    out = compact_api_data("RES", _res(queue=[{"event_id": 1, "story_id": "x" * 2000}]))
    assert out["queued_events"] == 1
    assert "x" * 2000 not in str(out)
    assert len(str(out)) < 400, len(str(out))


def test_the_giant_response_blob_is_still_dropped():
    out = compact_api_data("RES", _res(queue=[], playing_state=10))
    assert "home_info" not in out and "blob" not in str(out)


def test_requests_are_unaffected():
    out = compact_api_data("REQ", {"payload": {"current_turn": 24, "viewer_id": 123, "device": "x"}})
    assert out == {"current_turn": 24}          # envelope keys still stripped


def test_never_raises_on_junk():
    for bad in (None, [], "x", {"data": None}, {"data": {"chara_info": None}},
                {"data": {"unchecked_event_array": "not-a-list"}}):
        compact_api_data("RES", bad)
        compact_api_data("REQ", bad)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("log compaction fields OK")
