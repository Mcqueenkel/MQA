"""Continuous runs: the GUEST (rental) parent offer rotates per career, so the loop's 2nd+ start must
re-resolve the requested guest against the FRESH pre_single_mode offer instead of blindly re-sending
the stale first-run guest (a deterministic 102 that killed the loop). Fallback chain mirrors the
friend-card flow: exact guest -> same character -> best affinity with parent 1."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main


def _guest(vid, tcid, card, rank, name="G"):
    return {"viewer_id": vid, "trained_chara_id": tcid, "card_id": card, "rank": rank, "name": name}


def test_guest_resolve():
    offered = [_guest(9001, 111, 100200, 18, "Maruzensky"),
               _guest(9002, 222, 100300, 21, "Oguri Cap"),
               _guest(9003, 333, 100200, 20, "Maruzensky 2")]

    # 1) exact guest still offered -> unchanged, no note
    assert main.resolve_guest_parent(9002, 222, offered) == (9002, 222, None)

    # 2) stale guest whose character (card 100200) is still offered -> same-card swap, best rank (333)
    main.active_parent_rank_points = {555: {"card_id": 100200}}   # what we knew about the stale guest
    rv, rt, note = main.resolve_guest_parent(9999, 555, offered)
    assert (rv, rt) == (9003, 333) and "same character" in note, (rv, rt, note)

    # 3) stale guest, unknown character -> best affinity with parent 1 wins (not merely highest rank)
    main.active_parent_rank_points = {
        1: {"card_id": 100100, "win_saddle_id_array": [], "succession_chara_array": []},      # owned p1 = chara 1001
        111: {"card_id": 100200, "win_saddle_id_array": [], "succession_chara_array": []},    # chara 1002 (linked)
        222: {"card_id": 100300, "win_saddle_id_array": [], "succession_chara_array": []},    # chara 1003 (no link)
        333: {"card_id": 100200, "win_saddle_id_array": [], "succession_chara_array": []},    # chara 1002 (linked)
    }
    main._relation_members = {1001: {5}, 1002: {5}, 1003: set()}
    main._relation_points = {5: 10}
    rv, rt, note = main.resolve_guest_parent(9999, 777, offered, parent_id_1=1)
    # 111 and 333 tie on affinity (10); rank breaks the tie -> 333 (rank 20 > 18); 222 (rank 21) loses on affinity
    assert (rv, rt) == (9003, 333) and "best-affinity" in note, (rv, rt, note)

    # 4) no fresh offer at all (pre_single_mode failed) -> keep the request unchanged, no note
    assert main.resolve_guest_parent(9999, 555, []) == (9999, 555, None)

    print("guest resolve OK (exact kept; stale -> same character -> best affinity; empty offer kept)")



def test_a_guest_copy_parent_is_borrowed_again():
    # A career started in-game with a guest resumes with the guest's temporary roster copy (use_type 1)
    # as parent 2; the copy is deleted when that career finishes, so the next start must borrow the guest.
    from types import SimpleNamespace
    main.guest_copies = {}
    main.update_start_state({"trained_chara": [
        {"trained_chara_id": 2501, "use_type": 0, "owner_viewer_id": 0, "owner_trained_chara_id": 0},
        {"trained_chara_id": 2677, "use_type": 1, "owner_viewer_id": 5324, "owner_trained_chara_id": 2381}]})
    req = SimpleNamespace(parent_id_1=2501, parent_id_2=2677, rental_viewer_id=0, rental_trained_chara_id=0)
    assert main.guest_copy_to_rental(req)
    assert (req.parent_id_1, req.parent_id_2, req.rental_viewer_id, req.rental_trained_chara_id) == (2501, 0, 5324, 2381)
    req = SimpleNamespace(parent_id_1=2677, parent_id_2=2501, rental_viewer_id=0, rental_trained_chara_id=0)
    main.guest_copy_to_rental(req)
    assert (req.parent_id_1, req.parent_id_2, req.rental_trained_chara_id) == (2501, 0, 2381)
    owned = SimpleNamespace(parent_id_1=2501, parent_id_2=2600, rental_viewer_id=0, rental_trained_chara_id=0)
    assert main.guest_copy_to_rental(owned) is None and owned.parent_id_2 == 2600


if __name__ == "__main__":
    test_guest_resolve()
    test_a_guest_copy_parent_is_borrowed_again()
