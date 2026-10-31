"""URA resume stall: resuming a career whose current race the server ALREADY finished makes
race_end + race_out return 102 ("already done"). The phase=="start" resume path must then RELOAD the
real post-race state so the turn advances -- it used to `return payload` (the stale, still-in-race
state), so the loop re-decided race_progress forever and the run died as ended@turnN. (Live: a URA
career stopped at turn 30 with 102 on single_mode/race_end + single_mode/race_out.)"""
import os, sys
import threading
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from career_bot.runner import CareerRunner

FRESH = {"data": {"chara_info": {"turn": 31, "playing_state": 1}}}   # the reloaded post-race state


class DoneRaceClient:
    """A resumed race the server already settled: start ok, end/out 102."""
    def race_entry(self, **kw): return {}
    def race_start(self, **kw): return {}
    def race_end(self, **kw): raise Exception("API error 102 on single_mode/race_end")
    def race_out(self, **kw): raise Exception("API error 102 on single_mode/race_out")
    def load_career(self): return FRESH


def test_ura_resume_reloads_past_finished_race():
    r = CareerRunner.__new__(CareerRunner)          # bypass heavy __init__
    r._log = lambda *a, **k: None
    # the REAL branch under test must call _fresh_career_state -> reload, NOT return the stale payload
    r._fresh_career_state = lambda client, strategy=None: FRESH

    payload = {
        "current_turn": 30, "phase": "start",
        "chara_info": {"turn": 30, "playing_state": 2},          # 2 = mid-race resume
        "race_start_info": {"program_id": 1234, "race_horse_data": [{}]},
    }
    out = r._race_progress(DoneRaceClient(), payload, preset={})

    assert out is FRESH, "phase=start resume must RELOAD past the already-finished race"
    assert out != payload, "must not return the stale still-in-race payload (the turn-30 stall)"
    print("URA resume OK (race_end/race_out 102 on resume -> fresh reload, not stale-payload stall)")


def test_resumed_race_keeps_clock_retry_and_final_rank_history():
    class ResumeLossClient:
        api_jitter = 0

        def __init__(self):
            self.start_calls = 0
            self.continue_calls = 0

        def race_start(self, **_kw):
            self.start_calls += 1
            return {"data": {"rank": 2 if self.start_calls == 1 else 1}}

        def race_continue(self, **_kw):
            self.continue_calls += 1
            return {"data": {"home_info": {
                "available_continue_num": 0,
                "available_free_continue_num": 0,
            }}}

        def race_end(self, **_kw): return {}
        def race_out(self, **_kw): return FRESH

    r = CareerRunner.__new__(CareerRunner)
    r._log = lambda *a, **k: None
    r._parse_race_rank = lambda res: int((res.get("data") or {}).get("rank") or 99)
    recorded = []
    r._record_race_result = lambda turn, rank: recorded.append((turn, rank))
    r._drain_events = lambda client, strategy, state: state
    r.race_planner = None
    r.status = {"clocks_used": 0}
    r.lock = threading.Lock()
    r.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    source = {"data": {
        "chara_info": {"turn": 30, "playing_state": 3},
        "home_info": {"available_continue_num": 1, "available_free_continue_num": 0},
    }}
    payload = {
        "current_turn": 30,
        "phase": "start",
        "chara_info": {"turn": 30, "playing_state": 3},
        "race_start_info": {"program_id": 1234, "race_horse_data": [{}]},
    }
    client = ResumeLossClient()
    with (patch("career_bot.runner.ai_learn.log_experience", lambda *a, **k: None),
          patch("career_bot.runner.dna_sleep", lambda *a, **k: None),
          patch("career_bot.runner.dna_gauss", lambda *a, **k: 0)):
        out = r._race_progress(client, payload, preset={}, source_state=source)

    assert out is FRESH
    assert client.continue_calls == 1
    assert client.start_calls == 2
    assert recorded == [(30, 1)]
    assert r.status["clocks_used"] == 1


def test_unexpected_resume_state_reloads_instead_of_returning_decision_payload():
    r = CareerRunner.__new__(CareerRunner)
    r._log = lambda *a, **k: None
    r._fresh_career_state = lambda client, strategy=None: FRESH
    payload = {"current_turn": 30, "phase": "start",
               "chara_info": {"turn": 30, "playing_state": 1}}

    out = r._race_progress(object(), payload, preset={})

    assert out is FRESH
    assert "data" in out


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
