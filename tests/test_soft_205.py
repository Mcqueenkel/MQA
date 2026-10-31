"""A 205 on `continue` (clock/race-retry) or the shop multi_item_* calls is DETERMINISTIC and must
fail fast (no retry storm, no breaker note). The match is by SUFFIX so it survives per-scenario endpoint
routing (single_mode/continue for URA, single_mode_free/continue for MANT, single_mode_team/* for Unity)
-- the URA storm was exactly single_mode/continue not matching a free-only set."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from uma_api.client import is_deterministic_205


def test_soft_205():
    # every scenario routing of `continue` and the shop calls -> fail fast
    for ep in ("single_mode/continue", "single_mode_free/continue", "single_mode_team/continue",
               "single_mode_free/multi_item_exchange", "single_mode/multi_item_exchange",
               "single_mode_team/multi_item_use"):
        assert is_deterministic_205(ep), ep

    # normal race/flow endpoints must NOT be soft-205 (a real 205 there still retries/surfaces)
    for ep in ("single_mode/race_start", "single_mode_free/race_end", "single_mode/race_out",
               "load/index", "single_mode/continue_race", "single_mode_free/reserve_race"):
        assert not is_deterministic_205(ep), ep

    print("soft-205 OK (continue + multi_item_* fail fast across all scenario routings; race flow doesn't)")


if __name__ == "__main__":
    test_soft_205()
