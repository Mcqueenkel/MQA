"""Item gates must key off the RESOLVED scenario (self.status["scenario_id"], set from the LIVE game
in start()), not the raw preset["scenario_id"]. A Unity/Team preset commonly OMITS scenario_id and
relies on live detection (see resolve_scenario_id); the strategy dispatch resolves it to 2, but the
item gates used to re-read the raw preset -> defaulted to 4 (MANT) -> MANT's item engine fired
multi_item_exchange / multi_item_use during a Unity career. _scenario_id() closes that gap.

Run:
    python tests/test_scenario_item_gate.py
    python -m pytest tests/test_scenario_item_gate.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.runner import CareerRunner  # noqa: E402


def _runner(status_scenario):
    r = CareerRunner.__new__(CareerRunner)          # _scenario_id only reads self.status
    r.status = {"scenario_id": status_scenario}
    return r


def test_resolved_scenario_beats_omitted_preset():
    # THE BUG: Unity live (status=2), preset omits scenario_id -> must be 2, NOT the old 4 default.
    r = _runner(2)
    assert r._scenario_id({}) == 2
    assert r._scenario_id({"name": "my unity preset"}) == 2


def test_resolved_scenario_beats_mismatched_preset():
    # Even a preset that explicitly says MANT loses to the live-resolved Unity scenario.
    r = _runner(2)
    assert r._scenario_id({"scenario_id": 4}) == 2


def test_mant_stays_mant():
    r = _runner(4)
    assert r._scenario_id({}) == 4
    assert r._scenario_id({"scenario_id": 4}) == 4


def test_falls_back_to_preset_when_no_run_active():
    # status scenario_id 0 = not in a run yet -> the preset (then MANT) is the best guess.
    r = _runner(0)
    assert r._scenario_id({"scenario_id": 2}) == 2
    assert r._scenario_id({"scenario": 2}) == 2
    assert r._scenario_id({}) == 4


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("scenario item gate OK")
