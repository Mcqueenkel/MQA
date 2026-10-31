"""ALWAYS use clocks: every scenario (URA included) retries a real loss while a clock is available.
Only a win (rank 1) or the parse-fail sentinel (99) stops the retry."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from career_bot.runner import CareerRunner


def _runner(scenario):
    r = CareerRunner.__new__(CareerRunner)   # bypass heavy __init__; only exercise _retry_on_loss
    r.status = {"scenario_id": scenario}
    return r


def test_clock_retry():
    # every scenario retries a real loss (2..18) -- URA is no longer gated off
    for scen in (1, 2, 4):
        assert _runner(scen)._retry_on_loss(0, 5, {}) is True, scen
        assert _runner(scen)._retry_on_loss(0, 18, {}) is True, scen
        # a win (1) or the parse-fail sentinel (99) never retries (would otherwise burn every clock)
        assert _runner(scen)._retry_on_loss(0, 1, {}) is False, scen
        assert _runner(scen)._retry_on_loss(0, 99, {}) is False, scen
    print("clock-retry OK (all scenarios retry a real loss; win/sentinel don't)")


if __name__ == "__main__":
    test_clock_retry()
