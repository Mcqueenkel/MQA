"""Finished-career webhook title shows the SCENARIO that was played (URA Finale / Aoharu / Trackblazer)
instead of the redundant status -- the status already has its own field in the embed. Falls back to the
status when the scenario is unknown (e.g. an old summary with no scenario_id).

Run:
    python tests/test_webhook_title.py
    python -m pytest tests/test_webhook_title.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.notify import _build_embed  # noqa: E402


def _title(summary):
    return _build_embed(summary)["title"]


def test_title_shows_scenario():
    assert _title({"status": "finished", "scenario_id": 1}) == "🏁 Career Finished — URA Finale"
    assert _title({"status": "finished", "scenario_id": 2}) == "🏁 Career Finished — Aoharu / Unity Cup"
    assert _title({"status": "finished", "scenario_id": 4}) == "🏁 Career Finished — Trackblazer"


def test_title_falls_back_to_status_when_scenario_unknown():
    # no scenario_id / unknown -> keep the old status suffix so nothing renders blank
    assert _title({"status": "finished"}) == "🏁 Career Finished — finished"
    assert _title({"status": "finished", "scenario_id": 99}) == "🏁 Career Finished — finished"


def test_stopped_and_error_keep_their_own_prefix_with_scenario():
    assert _title({"status": "stopped", "scenario_id": 2}) == "⏹️ Career Stopped — Aoharu / Unity Cup"
    assert _title({"status": "error", "scenario_id": 4}) == "⚠️ Career Error — Trackblazer"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("webhook_title OK")
