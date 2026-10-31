"""Ported inheritance-affinity succession estimate: the exact current_succession_rank_point
computed from the parent+grandparent relation graph (replaces rank_score//divisor + sweep)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main


def test_affinity():
    # real affinity tables parse from data/ (generated from master.mdb)
    main._relation_members = None
    main._relation_points = None
    mem, pts = main._load_succession_affinity()
    assert len(mem) >= 70 and len(pts) >= 900, (len(mem), len(pts))
    assert 1004 in mem, "members must be keyed by base chara_id (card_id // 100), e.g. 1004"

    # controlled math: parent1<->parent2 link only
    main._relation_members = {1001: {5}, 1002: {5}}
    main._relation_points = {5: 10}
    main.active_parent_rank_points = {
        1: {"card_id": 100100, "win_saddle_id_array": [7, 11], "succession_chara_array": []},  # chara 1001
        2: {"card_id": 100200, "win_saddle_id_array": [7, 11], "succession_chara_array": []},  # chara 1002
    }
    # (10<->20): shared relation {5}=10 pts + shared races {7,11}=+2 -> 12; no grandparents
    assert main._succession_affinity_point(1, 2) == 12, main._succession_affinity_point(1, 2)

    # a missing parent -> None (caller falls back to the rank estimate; sweep still backstops)
    assert main._succession_affinity_point(1, 999) is None

    # add a grandparent under parent1 -> its own affinity link contributes
    main.active_parent_rank_points[1]["succession_chara_array"] = [
        {"position_id": 10, "card_id": 100300, "win_saddle_id_array": []},  # chara 1003
    ]
    main._relation_members[1003] = {5}   # gp (1003) shares relation 5 with parent1 (1001)
    # now + (10<->11): 1001&1003 shared {5}=10 -> total 22
    assert main._succession_affinity_point(1, 2) == 22, main._succession_affinity_point(1, 2)

    print("succession affinity port OK (real tables + links + points + race bonus + fallback)")


def test_guest_affinity():
    # A borrowed GUEST parent (surfaced by /api/career/friends) must cache its affinity data so the
    # start's succession-rank estimate is EXACT -- a wrong value is exactly what triggers the 102 sweep.
    main._relation_members = {1001: {5}, 1002: {5}}
    main._relation_points = {5: 10}
    main.active_parent_rank_points = {
        1: {"card_id": 100100, "win_saddle_id_array": [7], "succession_chara_array": []},  # owned p1 = chara 1001
    }
    data = {"succession_trained_chara_data": {"succession_trained_chara_array": [
        {"trained_chara_id": 5495, "viewer_id": 100000000002, "card_id": 100200,  # guest = chara 1002
         "rank": 16, "win_saddle_id_array": [7], "succession_chara_array": []},
        # a dupe (same viewer+tcid) must be de-duplicated
        {"trained_chara_id": 5495, "viewer_id": 100000000002, "card_id": 100200, "rank": 16},
    ]}}
    guests = main.normalize_guest_parents(data)
    assert len(guests) == 1 and guests[0]["trained_chara_id"] == 5495, guests
    assert 5495 in main.active_parent_rank_points, "guest affinity must be cached under its tcid"

    # owned p1 (1001) <-> guest (1002): shared relation {5}=10 + shared race {7}=+1 -> 11
    assert main._succession_affinity_point(1, 5495) == 11, main._succession_affinity_point(1, 5495)

    # the request entry point routes rental_trained_chara_id into the 2nd affinity slot (not parent_id_2)
    class Req:
        parent_id_1, parent_id_2, rental_trained_chara_id = 1, 0, 5495
    main._succession_rank_point_cache = {}
    assert main.selected_succession_rank_point(Req()) == 11
    print("guest-parent affinity OK (surfaced -> cached -> exact rank point via rental slot)")


if __name__ == "__main__":
    test_affinity()
    test_guest_affinity()
