"""Grand Live: a RESUMED career parked on the Concert screen must not idle out.

Live failure chain this pins:
  1. career_log_20260731_035056 -- resumed a turn-24 career, chara_info.turn was 0, fired
     live_start{current_turn: 0} three times -> 205 -> career ended.
  2. A non-zero-turn guard fixed the bad call, but then NOTHING could act: master_square and
     live_start both need current_turn, so the bot idled out of a live career
     (career_log_20260731_105832, stuck on the "1st Concert" screen with an unclaimed lesson).

The turn is recoverable from the state: live_data_set.live_result_array holds one entry per concert
already performed, indexing straight into LIVE_TURNS. Verified across two complete careers in
api_library/single_mode_live/load.jsonl.

Run:
    python tests/test_grand_live_concert_resume.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.grand_live import GrandLiveStrategy  # noqa: E402

G = GrandLiveStrategy
CONCERT_PS = G.CONCERT_PLAYING_STATE     # 10


def _state(performed, squares=(), turn=0, ps=CONCERT_PS):
    """A Concert-screen state. turn=0 is what a RESUMED career actually reports."""
    return {"data": {
        "chara_info": {"turn": turn, "playing_state": ps, "card_id": 100103},
        "live_data_set": {
            "live_result_array": [{"id": i} for i in range(performed)],
            "next_square_info_array": [{"square_id": s, "square_num": 1} for s in squares],
            "live_performance_info": {"dance": 999, "passion": 999, "vocal": 999,
                                      "visual": 999, "mental": 999},
            "effected_live_id_array": [],
        },
        "unchecked_event_array": [{"event_id": 202006}],
    }}


def test_concert_turn_maps_performed_count_to_the_turn():
    # The exact table observed live, ps 10 in every row.
    for performed, want in enumerate((24, 36, 48, 60, 72)):
        assert G.concert_turn(_state(performed)["data"]) == want, performed


def test_concert_turn_is_zero_once_all_five_are_done():
    assert G.concert_turn(_state(5)["data"]) == 0


def test_concert_turn_demands_evidence_and_never_guesses():
    """UNKNOWN must stay unknown. A missing/empty live_data_set is "no information", not "zero
    concerts done" -- inventing turn 24 from nothing is how live_start{current_turn: 0} got sent in
    career_log_20260731_035056. All 82 Concert-screen captures carry live_result_array, so requiring
    it costs nothing real."""
    assert G.concert_turn({}) == 0
    assert G.concert_turn({"live_data_set": {}}) == 0
    assert G.concert_turn({"live_data_set": {"next_square_info_array": []}}) == 0
    assert G.concert_turn({"live_data_set": {"live_result_array": []}}) == 24   # present+empty = real


def _strategy():
    s = G.__new__(G)                       # skip __init__ (it wants a RacePlanner)
    s._preset = {}
    s.race_planner = None
    s._fan_raced = True
    return s


def test_resumed_concert_claims_the_lesson_first():
    """The in-game Lessons button carries a '!' badge and the reference capture runs master_square
    BEFORE live_start, so a pending lesson must be claimed before performing."""
    s = _strategy()
    d = s.next_decision(_state(0, squares=(11004,)), {})
    assert d.action == "master_square", d.action
    assert d.payload["current_turn"] == 24, d.payload     # recovered, NOT 0
    assert d.payload["square_id"] == 11004


def test_resumed_concert_performs_once_no_lesson_is_pending():
    s = _strategy()
    d = s.next_decision(_state(0, squares=()), {})
    assert d.action == "grand_live_perform", d.action
    assert d.payload["current_turn"] == 24                # the bug was 0 here
    assert d.payload["event_id"] == 202006


def test_recovered_turn_tracks_the_concert_number():
    for performed, want in ((1, 36), (2, 48), (3, 60), (4, 72)):
        d = _strategy().next_decision(_state(performed), {})
        assert d.action == "grand_live_perform"
        assert d.payload["current_turn"] == want, (performed, d.payload)


def test_recovery_only_applies_on_the_concert_screen():
    """ps != 10 -> never invent a turn. Squares ARE still claimable on ordinary turns (the capture
    claims them on turns 1-12), so the check is that the turn stayed 0 rather than being recovered."""
    s = _strategy()
    assert G.concert_turn(_state(0, ps=1)["data"]) == 24    # the helper itself is pure
    d = s.next_decision(_state(0, squares=(11004,), ps=1), {})
    assert d.payload.get("current_turn") == 0, d.payload    # NOT recovered to 24
    assert not getattr(s, "_last_turn", 0), "must not stash a turn off the Concert screen"


def test_a_live_turn_reported_normally_is_untouched():
    # When the game DOES report the turn, it wins -- recovery only fills a 0.
    s = _strategy()
    d = s.next_decision(_state(0, turn=24), {})
    assert d.action == "grand_live_perform" and d.payload["current_turn"] == 24


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("grand live concert resume OK")
