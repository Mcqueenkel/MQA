"""Climax stat-gain capture: snapshot stats + hammer stock before each climax race, then log the
delta AND which cleat hammer (20% Artisan / 35% Master / none) was spent -- once the turn advances
past it (or, for climax-3, at finish from the post-race state, before the skill dump spends SP).

Run:
    python tests/test_climax_gain_capture.py
    python -m pytest tests/test_climax_gain_capture.py
"""
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.runner import CareerRunner  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 11002 = Master Cleat Hammer, 11001 = Artisan Cleat Hammer (ITEM_NAMES in items.py).


def _runner(scenario_id=4):
    r = CareerRunner(ROOT)
    r.status["scenario_id"] = scenario_id   # TS-climax capture is MANT-only (scenario 4)
    r._climax_before = {}
    r._climax_logged = set()
    r._log = lambda *a, **k: None   # no-op the career-log writer
    return r


def _state(speed=0, stamina=0, power=0, guts=0, wit=0, sp=0, master=0, artisan=0):
    items = []
    if master:
        items.append({"item_id": 11002, "num": master})
    if artisan:
        items.append({"item_id": 11001, "num": artisan})
    return {"data": {
        "chara_info": {"speed": speed, "stamina": stamina, "power": power,
                       "guts": guts, "wit": wit, "skill_point": sp},
        "free_data_set": {"user_item_info_array": items},
    }}


def test_logs_gain_and_master_hammer():
    r = _runner()
    r._capture_climax_before(74, _state(speed=600, sp=100, master=2))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        r._resolve_climax_gains(75, _state(speed=618, sp=145, master=1))  # +18 spd, +45 SP, master 2->1
    text = out.getvalue()
    assert "Climax-1 (t74)" in text and "+18 Spd" in text and "+45 SP" in text
    assert "35% Master hammer" in text
    assert 74 in r._climax_logged


def test_no_hammer_noted():
    r = _runner()
    r._capture_climax_before(76, _state(speed=600, master=1))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        r._resolve_climax_gains(77, _state(speed=620, master=1))   # master unchanged -> no hammer
    assert "no hammer" in out.getvalue()


def test_artisan_hammer_at_finish():
    r = _runner()
    r._capture_climax_before(78, _state(speed=700, artisan=1))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        r._resolve_climax_gains(999, _state(speed=724, artisan=0))   # artisan 1->0, resolved at finish
    text = out.getvalue()
    assert "Climax-3 (t78)" in text and "+24 Spd" in text and "20% Artisan hammer" in text


def test_not_logged_on_same_turn():
    r = _runner()
    r._capture_climax_before(74, _state(speed=600))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        r._resolve_climax_gains(74, _state(speed=600))   # not past the turn yet
    assert 74 not in r._climax_logged
    assert "Climax" not in out.getvalue()


def test_before_snapshot_taken_once():
    r = _runner()
    r._capture_climax_before(74, _state(speed=600))
    r._capture_climax_before(74, _state(speed=650))   # must NOT overwrite the before-race stats
    assert r._climax_before[74]["speed"] == 600


def test_unity_scenario_captures_nothing():
    # Unity (scenario 2) has no TS-climax races on 74/76/78 -> no capture, no phantom "climax" log.
    r = _runner(scenario_id=2)
    r._capture_climax_before(74, _state(speed=600, master=1))
    assert 74 not in r._climax_before                # nothing snapshotted
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        r._resolve_climax_gains(75, _state(speed=618, master=0))
    assert "Climax" not in out.getvalue() and 74 not in r._climax_logged


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
