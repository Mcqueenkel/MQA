"""The rental/guest succession-point cache key must be derived identically on the READ and WRITE
sides. The bug: the start-102 sweep wrote the calibrated value under (parent_id_1, owned_parent_id_2)
-- and owned_parent_id_2 is forced to 0 whenever a guest is used -- while selected_succession_rank_point
read it back under (parent_id_1, rental_trained_chara_id). So a guest career never re-hit its cached
value and re-swept every time. Both now go through main._succession_cache_pair.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main


def run():
    # GUEST parent present -> key on the rental trained_chara_id, NOT the owned parent_id_2.
    guest = SimpleNamespace(parent_id_1=10, parent_id_2=20, rental_trained_chara_id=99)
    assert main._succession_cache_pair(guest) == (10, 99), main._succession_cache_pair(guest)

    # No guest -> key on the owned parent_id_2.
    owned = SimpleNamespace(parent_id_1=10, parent_id_2=20, rental_trained_chara_id=0)
    assert main._succession_cache_pair(owned) == (10, 20), main._succession_cache_pair(owned)

    # Round-trip: a value the SWEEP caches under the guest key is re-hit by the READER. The sweep keys
    # on _succession_cache_pair(req) == (10, 99); before the fix it keyed on (10, 0) and this MISSED.
    main._succession_rank_point_cache.clear()
    main._succession_rank_point_cache[main._succession_cache_pair(guest)] = 137
    main.active_parent_rank_points = {}     # force cache path (no affinity/estimate)
    assert main.selected_succession_rank_point(guest) == 137, "guest cache lookup missed"

    # The owned slot the request actually sends (0) must NOT be what we key on for a guest.
    assert (10, 0) not in main._succession_rank_point_cache

    print("ok: succession cache key is consistent across read/write for guest + owned parents")


if __name__ == "__main__":
    run()
