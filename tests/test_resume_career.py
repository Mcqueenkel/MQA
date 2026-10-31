"""Resume detection: post-1.32.8 load/index surfaces an in-progress career as chara_info
(no single_mode_chara_light). _load_index_has_career must catch that shape so a re-launch resumes
the career instead of dead-ending on a start the game rejects while a slot is occupied.
Shapes verified against capture 20260706_082046 (load/index -> chara_info turn=1/state=0)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import _load_index_has_career, _resumable_career


def test_detects_inprogress_career_from_chara_info():
    # the real 082046 shape: an occupied slot arrives as chara_info with a card_id, no chara_light
    assert _load_index_has_career({"chara_info": {"card_id": 103802, "turn": 1, "state": 0}}) is True
    assert _load_index_has_career({"chara_info": {"card_id": 103802, "turn": 45, "state": 0}}) is True
    assert _resumable_career({"data": {"chara_info": {
        "card_id": 103802, "turn": 1, "state": 0,
    }}}) is True
    # A legitimate slot can exist before the first turn is advanced. It is still live and must not
    # be mistaken for stale data and deleted.
    assert _resumable_career({"chara_info": {"card_id": 103802, "turn": 0, "state": 0}}) is True
    # legacy home-summary shape (no turn) still counts as an occupied slot
    assert _load_index_has_career({"single_mode_chara_light": {"card_id": 100101}}) is True


def test_finished_career_is_not_resumable():
    # THE loop bug: a JUST-FINISHED career lingers in load/index -- it must NOT be flagged resumable,
    # or the next loop career resumes the phantom and stops at turn 0. Terminal = server state 3
    # (finished) / state 2 (goal failed) / a finish block (api_library captures).
    assert _load_index_has_career({"chara_info": {"card_id": 103802, "state": 3}}) is False
    assert _load_index_has_career({"chara_info": {
        "card_id": 103802, "turn": 78, "state": 3, "playing_state": 5}}) is False
    assert _load_index_has_career({"chara_info": {
        "card_id": 103802, "turn": 54, "state": 2, "playing_state": 5}}) is False
    assert _resumable_career({"data": {"chara_info": {
        "card_id": 103802, "turn": 72, "state": 2, "playing_state": 3}}}) is False
    assert _resumable_career({
        "chara_info": {"card_id": 103802, "turn": 1},
        "single_mode_finish_common": {},
    }) is False


def test_live_event_pending_and_live_turn_78_are_resumable():
    # state 0 / playing_state 5 is the normal "event pending" live state (single_mode/load t13/16,
    # single_mode_team/load t25/55, single_mode_live/load t24 in the captures); closing it would end
    # a live career.
    assert _resumable_career({"data": {
        "chara_info": {"card_id": 103802, "turn": 16, "state": 0, "playing_state": 5},
        "unchecked_event_array": [{"event_id": 1}],
    }}) is True
    # state 0 at turn 78 = Grand Live's final race not run yet (race_entry/start/end follow).
    assert _resumable_career({"data": {"chara_info": {
        "card_id": 103802, "turn": 78, "state": 0, "playing_state": 1}}}) is True


def test_no_career_does_not_trip_resume():
    assert _load_index_has_career({}) is False
    assert _load_index_has_career({"chara_info": {}}) is False            # no card_id -> no slot
    assert _load_index_has_career({"chara_info": {"card_id": 0}}) is False
    assert _load_index_has_career({"chara_info": None}) is False
    assert _load_index_has_career(None) is False


if __name__ == "__main__":
    test_detects_inprogress_career_from_chara_info()
    test_finished_career_is_not_resumable()
    test_live_event_pending_and_live_turn_78_are_resumable()
    test_no_career_does_not_trip_resume()
    print("test_resume_career: OK")
