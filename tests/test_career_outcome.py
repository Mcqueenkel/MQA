"""Career log 'outcome': a clear top-level reason a career ended, so a FAILED GOAL (early finish)
is never mistaken for a clean 78-turn completion."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from career_bot.runner import CareerRunner


def _r(report, status, end_reason="", stop=False):
    r = CareerRunner.__new__(CareerRunner)   # bypass heavy __init__; only exercise _compute_outcome
    r.report = report
    r.status = status
    r._career_end_reason = end_reason
    r.stop_requested = stop
    return r


def test_outcome():
    # the exact confusing case: goal failure at turn 54 (was logged as plain "finished")
    assert _r({"final_turn": 54, "error": None}, {"turn": 54, "finished": True},
              "goal failed / career end")._compute_outcome() == "goal_failed@turn54"
    # clean completion to the finals
    assert _r({"final_turn": 78, "error": None}, {"turn": 78, "finished": True},
              "finished")._compute_outcome() == "completed"
    # crash
    assert _r({"final_turn": 16, "error": {"message": "205 boom"}},
              {"turn": 16, "finished": False})._compute_outcome() == "error"
    # circuit breaker / auto-backoff
    assert _r({"final_turn": 30, "error": None}, {"turn": 30, "finished": False, "circuit_tripped": True},
              "", stop=True)._compute_outcome().startswith("auto_backoff")
    # user/limit stop mid-run
    assert _r({"final_turn": 40, "error": None}, {"turn": 40, "finished": False},
              "", stop=True)._compute_outcome() == "stopped@turn40"
    # finished-flag but early with no goal-fail reason
    assert _r({"final_turn": 50, "error": None}, {"turn": 50, "finished": True},
              "")._compute_outcome() == "ended_early@turn50"
    print("career outcome OK (goal_failed / completed / error / auto_backoff / stopped / ended_early)")


if __name__ == "__main__":
    test_outcome()
