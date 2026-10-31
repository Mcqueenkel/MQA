"""Clocks are ALWAYS used when available: re-run ANY losing finish (2nd..last) with a clock, looping
until she wins or the clock budget is spent. rank 1 = won (stop); the rank-99 parse-failure sentinel
must never burn a clock.

Run:
    python tests/test_burn_clocks.py
    python -m pytest tests/test_burn_clocks.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.runner import CareerRunner  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _runner():
    r = CareerRunner(ROOT)
    r.race_planner.program = {
        1: {"name": "Oka Sho"},
        9: {"name": "Tenno Sho (Spring)"},   # an ordinary (non-marquee) race
        10: {"name": "Make Debut"},
    }
    return r


def test_retries_every_loss_regardless_of_race_or_toggle():
    # ALWAYS-ON: any real losing finish (2..18) retries, marquee or not, toggle or not.
    r = _runner()
    r.burn_clocks = False                            # toggle no longer matters
    assert r._retry_on_loss(1, 2, {}) is True        # marquee G1, 2nd
    assert r._retry_on_loss(9, 3, {}) is True        # ordinary race, 3rd -> STILL retries (was False before)
    assert r._retry_on_loss(9, 18, {}) is True       # deep loss still retries (availability gates the spend)
    assert r._retry_on_loss(999, 5, {}) is True      # unknown race id, 5th


def test_won_never_retries():
    r = _runner()
    assert r._retry_on_loss(9, 1, {}) is False       # 1st place -> nothing to retry


def test_parse_failure_sentinel_never_burns_a_clock():
    # rank 99 == _parse_race_rank could-not-parse; rank 0 == unknown. Neither is a loss.
    r = _runner()
    assert r._retry_on_loss(9, 99, {}) is False
    assert r._retry_on_loss(9, 0, {}) is False
    assert r._retry_on_loss(10, 99, {"force_clock_debut": True}) is False  # even on a debut race


def test_race_clocks_reads_home_info_then_falls_back():
    # "always use clocks": the retry loop must find clocks on EVERY race-entry state shape.
    r = _runner()
    # normal home-screen entry: clocks in home_info
    st = {"data": {"home_info": {"available_continue_num": 3, "available_free_continue_num": 1}}}
    assert r._race_clocks(st) == (3, 1)
    # mid-race resume: home_info has no count, but race_start_info carries continues-used
    st2 = {"data": {"race_start_info": {"continue_num": 2}}}   # 2 used of 5 -> 3 left (as std)
    std, free = r._race_clocks(st2)
    assert std == 3 and free == 0, (std, free)
    # genuinely no clocks anywhere -> (0, 0), loop won't retry (nothing to spend)
    assert r._race_clocks({"data": {}}) == (0, 0)


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
