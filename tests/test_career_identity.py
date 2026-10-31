"""The career log records the STARTING HAND (trainee, deck, inherits, aptitudes), not just what the
bot did with it. Without this block two careers on the same preset scoring 2972 vs 4171 are
indistinguishable -- a worse decision looks exactly like a worse draw.

Field names are the real ones from a live single_mode_free/load chara_info capture.

Run:
    python tests/test_career_identity.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.report import capture_career_identity, new_report  # noqa: E402


def _state():
    return {"data": {"chara_info": {
        "card_id": 100602, "single_mode_chara_id": 196, "rarity": 3, "talent_level": 4,
        "chara_grade": 4, "race_running_style": 2,
        "proper_distance_short": 3, "proper_distance_mile": 7, "proper_distance_middle": 7,
        "proper_distance_long": 7, "proper_ground_turf": 7, "proper_ground_dirt": 6,
        "proper_running_style_nige": 2, "proper_running_style_senko": 7,
        "proper_running_style_sashi": 7, "proper_running_style_oikomi": 4,
        "support_card_array": [
            {"position": 1, "support_card_id": 30107, "limit_break_count": 1, "exp": 37785},
            {"position": 2, "support_card_id": 30028, "limit_break_count": 4, "exp": 100},
        ],
        "succession_trained_chara_id_1": 190, "succession_trained_chara_id_2": 121,
    }}}


def test_captures_the_starting_hand():
    r = new_report({"name": "p"}, 4)
    capture_career_identity(r, _state())
    ident = r["identity"]
    assert ident["card_id"] == 100602
    assert ident["chara_id"] == 1006                      # card_id // 100
    assert ident["rarity"] == 3 and ident["talent_level"] == 4
    assert ident["inherit_parent_ids"] == [190, 121]
    # Deck keeps position + limit break: the same card at LB0 vs LB4 is a different card in practice.
    assert ident["support_deck"] == [
        {"position": 1, "support_card_id": 30107, "limit_break_count": 1},
        {"position": 2, "support_card_id": 30028, "limit_break_count": 4},
    ]
    # Aptitudes are what distinguish "lost a dirt race" from "never should have entered one".
    assert ident["aptitudes"]["proper_ground_dirt"] == 6
    assert ident["aptitudes"]["proper_distance_short"] == 3
    assert len(ident["aptitudes"]) == 10


def test_idempotent_and_waits_for_a_real_card_id():
    r = new_report({"name": "p"}, 4)
    # A resumed career's first state carries no chara_info -> capture nothing, stay open.
    capture_career_identity(r, {"data": {}})
    assert "identity" not in r
    capture_career_identity(r, _state())
    assert r["identity"]["card_id"] == 100602
    # First real capture wins: a later turn must not overwrite it.
    other = _state()
    other["data"]["chara_info"]["card_id"] = 999999
    capture_career_identity(r, other)
    assert r["identity"]["card_id"] == 100602


def test_never_raises():
    r = new_report({"name": "p"}, 4)
    for bad in (None, {}, {"data": None}, {"data": {"chara_info": None}},
                {"data": {"chara_info": {"card_id": "not-a-number"}}},
                {"data": {"chara_info": {"card_id": 100602, "support_card_array": [None, "junk"]}}}):
        capture_career_identity(r, bad)          # must not raise
    capture_career_identity(None, _state())      # no report at all


if __name__ == "__main__":
    test_captures_the_starting_hand()
    test_idempotent_and_waits_for_a_real_card_id()
    test_never_raises()
    print("career-identity OK (starting hand captured, idempotent, never raises)")
