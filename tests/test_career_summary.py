"""The self-contained career-log summary (_career_summary): final grade/score, stats + total, skills,
fans, and the ACTION + per-stat TRAINING breakdown that exposes a lopsided build. Built from the
report's turns; must never raise.

Run:
    python tests/test_career_summary.py
    python -m pytest tests/test_career_summary.py
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.runner import CareerRunner  # noqa: E402


def _runner(report):
    r = CareerRunner.__new__(CareerRunner)          # bypass __init__; stub only what _career_summary uses
    r.report = report
    r.lock = threading.Lock()
    r.status = {"skills_bought": 12, "clocks_used": 3, "scenario_id": 2}
    r._notify_rank = 17
    r._notify_rank_score = 19151
    r._final_skill_point = 40
    return r


def _train(turn, cid, stats):
    return {"turn": turn, "selected_action": "command",
            "current_command": {"command_type": 1, "command_id": cid}, "stats": stats}


def test_summary_breakdown():
    stats = {"speed": 1240, "stamina": 733, "power": 910, "guts": 706, "wit": 1205, "fans": 318759}
    turns = [
        _train(1, 101, stats),   # speed
        _train(2, 106, stats),   # wit
        _train(3, 106, stats),   # wit
        _train(4, 102, stats),   # power
        {"turn": 5, "selected_action": "command",
         "current_command": {"command_type": 7, "command_id": 701}, "stats": stats},   # rest
        {"turn": 6, "selected_action": "race", "current_command": {}, "stats": stats},  # race
    ]
    r = _runner({"turns": turns, "final_turn": 6})
    out = r._career_summary("completed")

    assert out["rank"] == 17 and out["rank_letter"] == "SS" and out["rank_score"] == 19151
    assert out["stat_total"] == 1240 + 733 + 910 + 706 + 1205
    assert out["final_stats"]["power"] == 910
    assert out["skills_bought"] == 12 and out["clocks_used"] == 3
    assert out["fans"] == 318759 and out["races"] == 1
    assert out["actions"] == {"train": 4, "rest": 1, "race": 1}
    assert out["training_by_stat"] == {"speed": 1, "stamina": 0, "power": 1, "guts": 0, "wit": 2}
    assert out["skill_point_left"] == 40


def test_summary_never_raises_on_empty():
    r = _runner({})                       # no turns
    out = r._career_summary("error")
    assert out["outcome"] == "error" and out["stat_total"] == 0 and out["training_by_stat"]["wit"] == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("career summary OK")
