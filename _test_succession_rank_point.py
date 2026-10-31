# Unit check for parent_rank_point / selected_succession_rank_point.
# Run with: python _test_succession_rank_point.py
from types import SimpleNamespace

import main


def run():
    main.active_parent_rank_points = {
        1: {'rank': 13, 'rank_score': 12400},  # A rank: hardcoded observed anchor
        2: {'rank': 14, 'rank_score': 14250},  # A+ rank
        3: {'rank': 11, 'rank_score': 9120},   # B rank
        4: {'rank': 2, 'rank_score': 507},     # starter-tier chara from captured log
        5: {'rank': 12},                       # missing rank_score
    }
    main.active_start_state = {'succession_rank_point': 999}

    # A rank keeps the exact observed value.
    assert main.parent_rank_point(1) == 62, main.parent_rank_point(1)
    # The old bug: every non-A parent returned 0. Now they score on the same scale.
    assert main.parent_rank_point(2) == 71, main.parent_rank_point(2)
    assert main.parent_rank_point(3) == 45, main.parent_rank_point(3)
    assert main.parent_rank_point(4) == 2, main.parent_rank_point(4)
    # Higher rank bands score higher.
    assert main.parent_rank_point(3) < main.parent_rank_point(1) < main.parent_rank_point(2)
    # Missing rank_score / unknown parent degrade to 0, not a crash.
    assert main.parent_rank_point(5) == 0
    assert main.parent_rank_point(99) == 0

    # Non-A parents now produce a real total instead of the item-75 fallback.
    req = SimpleNamespace(parent_id_1=2, parent_id_2=3)
    assert main.selected_succession_rank_point(req) == 116, main.selected_succession_rank_point(req)
    # No usable parents still falls back to the account's stored value.
    req = SimpleNamespace(parent_id_1=0, parent_id_2=0)
    assert main.selected_succession_rank_point(req) == 999

    print("ok: parent_rank_point / selected_succession_rank_point checks passed")


if __name__ == "__main__":
    run()
