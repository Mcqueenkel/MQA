"""Unit tests for the Team Sirius + Heirs to the Throne ("Group" card) MANT schedule.

Covers:
  - deck detection (chara_info.support_card_array -> group card present)
  - schedule activation for the capture dump (_schedule_active)
  - GOAL-DRIVEN group outings: each scheduled outing is taken when it's DUE, NOT done, and AVAILABLE;
    a late-unlocked character is caught up as soon as it unlocks (so it never eats a card turn), and
    each card step (the card's own multi-step recreation) is taken once its signature character is
    done. Character outings use select_id = chara_id; the card-itself uses the card's signature
    chara_id (Sirius 1001 Special Week, Throne 1017 Symboli Rudolf), confirmed live via the card
    row's story_step advancing.
  - junior focus (build the group cards' bond first so outings unlock on time)
  - all-out summer energy-rescue mirror (group-deck-gated, byte-identical for non-group decks)

Run:
    python tests/test_sirius_throne_schedule.py
    python -m pytest tests/test_sirius_throne_schedule.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.mant_items import MantItemManager, SUMMER_TRAINING_TURNS  # noqa: E402
from career_bot.scenarios.mant import MantStrategy  # noqa: E402
from career_bot.core.training_brain import (  # noqa: E402
    GROUP_OUTING_COMMAND_ID,
    RACE_VALUE_CAMP_TURNS,
    SIRIUS_THRONE_RECREATION_SCHEDULE,
    TEAM_SIRIUS_SUPPORT_ID,
    THRONE_SUPPORT_ID,
)


_S = MantStrategy()
_IM = MantItemManager()


def _chara(cards=(), turn=0):
    return {"turn": turn, "support_card_array": [{"support_card_id": c} for c in cards]}


_GROUP = _chara(cards=[TEAM_SIRIUS_SUPPORT_ID, 10001, 10002, THRONE_SUPPORT_ID, 10003, 10004])
_PLAIN = _chara(cards=[10001, 10002, 10003, 10004, 10005, 10006])


# ---------------- deck detection ----------------

def test_detects_team_sirius():
    assert _S._deck_has_group_cards(_chara(cards=[TEAM_SIRIUS_SUPPORT_ID, 10001])) is True


def test_detects_throne():
    assert _S._deck_has_group_cards(_chara(cards=[THRONE_SUPPORT_ID, 10001])) is True


def test_plain_deck_not_detected():
    assert _S._deck_has_group_cards(_PLAIN) is False


# ---------------- schedule activation (gates the capture DUMP, not the outing) ----------------

def test_schedule_auto_on_for_group_deck():
    assert _S._schedule_active(_GROUP, {}) is True


def test_schedule_auto_off_for_plain_deck():
    assert _S._schedule_active(_PLAIN, {}) is False


def test_schedule_force_on():
    assert _S._schedule_active(_PLAIN, {"sirius_throne_schedule": True}) is True


def test_schedule_force_off():
    assert _S._schedule_active(_GROUP, {"sirius_throne_schedule": False}) is False


# ---------------- goal-driven group outing ----------------
# Team Sirius (slot 5): Special Week 1001, Silence Suzuka 1002, Mejiro McQueen 1013, Narita Brian
# 1016, Rice Shower 1030, Winning Ticket 1035. Heirs to the Throne (slot 6): Tokai Teio 1003,
# Symboli Rudolf 1017, Tsurumaru Tsuyoshi 1073. Card signatures: Sirius 1001, Throne 1017.
_SIRIUS_OUTINGS = (1001, 1002, 1013, 1016, 1030, 1035)
_THRONE_OUTINGS = (1003, 1017, 1073)
_ALL_OUTINGS = _SIRIUS_OUTINGS + _THRONE_OUTINGS
_OUTING_CMD = {"command_type": 3, "command_id": GROUP_OUTING_COMMAND_ID, "is_enable": 1, "select_id": 0}
_MOOD_REC = {"command_type": 3, "command_id": 301, "is_enable": 1}
_TRAIN_CMD = {"command_type": 1, "command_id": 101, "is_enable": 1}
_ENABLED = [_MOOD_REC, _OUTING_CMD, _TRAIN_CMD]
_ENABLED_NO_OUTING = [_MOOD_REC, _TRAIN_CMD]
_CARD_ON = {"sirius_throne_card_outing": True}
_NO_THRONE_CHARS = tuple(c for c in _ALL_OUTINGS if c not in _THRONE_OUTINGS)  # Sirius chars only


def _gchara(turn=18, char_done=(), char_locked=(), sirius_card=(1, 0), throne_card=(1, 0)):
    """Group-deck state for the goal-driven recreation. char_done = chara_ids whose CHARACTER outing
    is done (story_step 1); char_locked = chara_ids not unlocked yet (is_outing 0); all others are
    unlocked + not done. sirius_card / throne_card = (is_outing, story_step) of each group card's OWN
    recreation row."""
    done, locked = set(char_done), set(char_locked)

    def rows(ids):
        return [{"chara_id": c, "is_outing": 0 if c in locked else 1,
                 "story_step": 1 if c in done else 0} for c in ids]

    return {
        "turn": turn,
        "support_card_array": [
            {"position": 5, "support_card_id": TEAM_SIRIUS_SUPPORT_ID},
            {"position": 6, "support_card_id": THRONE_SUPPORT_ID},
        ] + [{"position": i, "support_card_id": 10000 + i} for i in (1, 2, 3, 4)],
        "evaluation_info_array": [
            {"target_id": 5, "is_outing": sirius_card[0], "story_step": sirius_card[1],
             "group_outing_info_array": rows(_SIRIUS_OUTINGS)},
            {"target_id": 6, "is_outing": throne_card[0], "story_step": throne_card[1],
             "group_outing_info_array": rows(_THRONE_OUTINGS)},
        ],
    }


def _do(turn, preset=None, enabled=_ENABLED, **kw):
    """Run _scheduled_recreation on a fresh strategy; return (select_id or None, is_card or None)."""
    s = MantStrategy()
    rec = s._scheduled_recreation(enabled, turn, _gchara(turn, **kw), preset or {})
    if rec is None:
        return (None, None)
    return (rec.get("select_id"), s._pending_outing_is_card)


def test_fires_first_due_character():
    # t18: only Suzuka (1002) is due -> fire it.
    assert _do(18) == (1002, False)


def test_does_earliest_pending_character_first():
    # t26 with nothing done: Suzuka (t18) is the earliest still-pending available outing -> do it
    # before the t26 entry. (Goal-driven = catch up the oldest pending first.)
    assert _do(26) == (1002, False)


def test_fires_scheduled_character_when_priors_done():
    # t26 with Suzuka + Narita done -> Symboli Rudolf (1017) is next.
    assert _do(26, char_done=(1002, 1016)) == (1017, False)


def test_pulls_forward_when_scheduled_char_locked():
    # User scenario: t18's own date (Silence Suzuka, Sirius) hasn't unlocked, but Throne is ready ->
    # use the date for the earliest available not-yet-due outing instead of wasting it. All Sirius
    # chars locked -> earliest available future = Symboli Rudolf (1017, Throne @ t26), pulled forward.
    assert _do(18, char_locked=_SIRIUS_OUTINGS) == (1017, False)


def test_no_pull_forward_on_non_scheduled_turn():
    # t20 is NOT a scheduled date. The due char (Suzuka @ t18) is locked; future chars are available,
    # but pulling them forward here would front-load outings -> must train (None). Cadence preserved.
    assert _do(20, char_locked=(1002,)) == (None, None)


def test_trains_when_no_outing_available():
    # t26, priors done, and every remaining outing locked -> nothing due AND nothing to pull
    # forward -> train (None).
    locked = tuple(c for c in _ALL_OUTINGS if c not in (1002, 1016))
    assert _do(26, char_done=(1002, 1016), char_locked=locked) == (None, None)


def test_catches_up_late_unlocked_character():
    # Rudolf unlocked late (t50): every other char done -> it's caught up immediately, freeing the
    # card turns. THIS is the fix for the "Throne card only 1/2" bug.
    others = tuple(c for c in _ALL_OUTINGS if c != 1017)
    assert _do(50, char_done=others) == (1017, False)


def test_card_step_fires_when_signature_done():
    # t58 Sirius card: all chars done, Throne card already maxed -> Sirius card step 1 (sig 1001).
    assert _do(58, char_done=_ALL_OUTINGS, throne_card=(1, 2)) == (1001, True)


def test_card_step_skipped_when_signature_not_done():
    # t58 but Special Week (Sirius signature 1001) not done -> the CHARACTER 1001 fires first (not the
    # card). select_id is the same 1001, but is_card must be False (character, not card story).
    others = tuple(c for c in _ALL_OUTINGS if c != 1001)
    assert _do(58, char_done=others, throne_card=(1, 2)) == (1001, False)


def test_throne_card_step_one():
    assert _do(51, char_done=_ALL_OUTINGS, throne_card=(1, 0)) == (1017, True)


def test_throne_card_step_two():
    # Throne is a 2-step card: with step 1 done it does step 2 (Sirius card already done so it's not
    # the earlier pending one).
    assert _do(59, char_done=_ALL_OUTINGS, throne_card=(1, 1), sirius_card=(1, 1)) == (1017, True)


def test_card_step_skipped_when_maxed():
    # Throne card at its max (2/2), Sirius done -> nothing left -> train.
    assert _do(59, char_done=_ALL_OUTINGS, throne_card=(1, 2), sirius_card=(1, 1)) == (None, None)


def test_card_step_skipped_when_card_locked():
    # The card's OWN recreation row isn't unlocked (is_outing 0) -> skip.
    assert _do(58, char_done=_ALL_OUTINGS, throne_card=(1, 2), sirius_card=(0, 0)) == (None, None)


def test_no_outing_when_everything_done():
    assert _do(70, char_done=_ALL_OUTINGS, throne_card=(1, 2), sirius_card=(1, 1)) == (None, None)


def test_no_fire_in_summer_camp():
    camp = sorted(RACE_VALUE_CAMP_TURNS)[0]  # 37 -- inside the actual Lv5 camp (36/60 are race weeks)
    assert _do(camp) == (None, None)


def test_disabled_by_preset():
    assert _do(18, preset={"sirius_throne_schedule": False}) == (None, None)


def test_no_fire_without_outing_command():
    assert _do(18, enabled=_ENABLED_NO_OUTING) == (None, None)


def test_card_outing_opt_out():
    # With the card outing disabled, the Sirius card step is skipped (characters unaffected).
    assert _do(58, preset={"sirius_throne_card_outing": False},
               char_done=_ALL_OUTINGS, throne_card=(1, 2)) == (None, None)


def test_skips_for_non_group_deck():
    plain = {"turn": 18, "support_card_array": [{"position": i + 1, "support_card_id": 10000 + i} for i in range(6)],
             "evaluation_info_array": []}
    assert _S._scheduled_recreation(_ENABLED, 18, plain, {}) is None
    assert _S._scheduled_recreation(_ENABLED, 18, plain, {"sirius_throne_schedule": True}) is None


def test_outing_blocked_flag_disables_firing():
    # Loop-breaker: after an outing exec fails/stalls, the runner sets _scheduled_outing_blocked.
    s = MantStrategy()
    assert s._scheduled_recreation(_ENABLED, 18, _gchara(18), {}) is not None
    s._scheduled_outing_blocked = True
    assert s._scheduled_recreation(_ENABLED, 18, _gchara(18), {}) is None


def test_card_block_isolates_to_card_outings():
    # A card-outing failure blocks only card steps; character outings keep firing.
    s = MantStrategy()
    s._card_outing_blocked = True
    card_state = _gchara(58, char_done=_ALL_OUTINGS, throne_card=(1, 2), sirius_card=(1, 0))
    assert s._scheduled_recreation(_ENABLED, 58, card_state, _CARD_ON) is None        # card -> blocked
    assert s._scheduled_recreation(_ENABLED, 18, _gchara(18), _CARD_ON) is not None    # character -> fires


def test_every_scheduled_turn_is_outside_lv5_camp():
    # Scheduled outings are blocked only inside the ACTUAL Lv5 camp (37-40 / 61-64); the 36/60
    # late-June race weeks are allowed (e.g. Tokai Teio on t36).
    assert not (set(SIRIUS_THRONE_RECREATION_SCHEDULE) & RACE_VALUE_CAMP_TURNS)


def test_named_schedule_chara_ids_are_real_outings():
    valid = set(_ALL_OUTINGS)
    for turn, (chara_id, _support, _label) in SIRIUS_THRONE_RECREATION_SCHEDULE.items():
        if chara_id is not None:
            assert chara_id in valid, f"turn {turn} chara_id {chara_id} not a known outing"


def test_outing_plan_has_correct_card_steps():
    # Throne contributes 2 card steps, Sirius 1 (matches master.mdb outing_max).
    plan = _S._outing_plan()
    throne_steps = [s for s in plan if s["kind"] == "card" and s["support_id"] == THRONE_SUPPORT_ID]
    sirius_steps = [s for s in plan if s["kind"] == "card" and s["support_id"] == TEAM_SIRIUS_SUPPORT_ID]
    assert [s["step"] for s in throne_steps] == [1, 2]
    assert [s["step"] for s in sirius_steps] == [1]
    assert all(s["select_id"] == 1017 for s in throne_steps)
    assert all(s["select_id"] == 1001 for s in sirius_steps)


def test_serialize_preset_keeps_schedule_knobs():
    from career_bot.core.presets import serialize_preset
    out = serialize_preset({
        "sirius_throne_schedule": False,
        "summer_all_out": False,
        "dump_recreation_debug": False,
        "sirius_throne_junior_focus": False,
    })
    assert out.get("sirius_throne_schedule") is False
    assert out.get("summer_all_out") is False
    assert out.get("dump_recreation_debug") is False
    assert out.get("sirius_throne_junior_focus") is False


# ---------------- junior focus ----------------

def test_group_card_slots_detected():
    assert sorted(_S._group_card_slots(_gchara(5))) == [5, 6]


def _train(cmd_id, partners, stat_idx):
    target = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5}[stat_idx]  # STAT_TARGETS inverse for the trained stat
    return {"command_type": 1, "command_id": cmd_id, "is_enable": 1,
            "training_partner_array": list(partners), "failure_rate": 0,
            "params_inc_dec_info_array": [{"target_type": target, "value": 10}]}


def test_junior_focus_prefers_group_card_facility():
    # In juniors, between an equal-ish board, the bot picks the training that has a GROUP-card partner
    # (slot 5/6) to build their bond and unlock outings on time.
    group_train = _train(101, partners=[5], stat_idx=0)   # has Team Sirius (slot 5)
    plain_train = _train(105, partners=[1], stat_idx=1)   # only a normal partner
    _score, picked = _S._pick_scored_training([plain_train, group_train], {}, _gchara(5), {}, 5)
    assert picked is group_train


def test_junior_focus_off_after_window():
    # Past the focus window the group-partner bias no longer forces the pick (normal scoring).
    group_train = _train(101, partners=[5], stat_idx=0)
    plain_train = _train(105, partners=[1, 2, 3], stat_idx=1)  # more bondable partners
    _score, picked = _S._pick_scored_training([plain_train, group_train], {}, _gchara(20), {}, 20)
    assert picked is plain_train


# ---------------- all-out summer (the two-module energy-rescue mirror) ----------------

def test_camp_turn_sets_match_across_modules():
    assert RACE_VALUE_CAMP_TURNS == SUMMER_TRAINING_TURNS


_CAMP_TURN = sorted(RACE_VALUE_CAMP_TURNS)[0]
_WEAK_TRAIN = {"command_type": 1, "command_id": 101, "failure_rate": 0,
               "params_inc_dec_info_array": [{"target_type": 1, "value": 15}]}


def _camp_chara(vital=40, group=True):
    cards = [TEAM_SIRIUS_SUPPORT_ID] if group else []
    return {"turn": _CAMP_TURN, "vital": vital, "evaluation_info_array": [],
            "support_card_array": [{"support_card_id": c} for c in cards]}


def test_items_tops_up_weak_camp_turn_under_all_out():
    out = _IM._rescue_energy_target(_camp_chara(), {"Vita 40": 1}, {}, _WEAK_TRAIN)
    assert out, "items.py should top up energy for a positive-gain camp turn under all-out"


def test_items_skips_weak_camp_turn_when_all_out_disabled():
    out = _IM._rescue_energy_target(_camp_chara(), {"Vita 40": 1}, {"summer_all_out": False}, _WEAK_TRAIN)
    assert out == []


def test_items_tops_up_weak_camp_turn_for_non_group_deck():
    # All-out camp is now every deck, not just Sirius/Throne: a non-group deck also tops up energy
    # to commit a positive-gain Lv5 camp turn.
    out = _IM._rescue_energy_target(_camp_chara(group=False), {"Vita 40": 1}, {}, _WEAK_TRAIN)
    assert out, "items.py should top up energy for a non-group deck's positive camp turn too"


def test_mant_rescues_weak_camp_turn_under_all_out():
    data = {"free_data_set": {"user_item_info_array": [{"item_id": 2002, "num": 1}]}}
    assert _S._can_rescue_training(data, _camp_chara(), {}, _WEAK_TRAIN, 0.1, 40, 0, 48) is True


def test_mant_skips_weak_camp_turn_when_all_out_disabled():
    data = {"free_data_set": {"user_item_info_array": [{"item_id": 2002, "num": 1}]}}
    assert _S._can_rescue_training(data, _camp_chara(), {"summer_all_out": False}, _WEAK_TRAIN, 0.1, 40, 0, 48) is False


def test_mant_rescues_weak_camp_turn_for_non_group_deck():
    # All-out camp is every deck now: a non-group deck's positive camp board is also rescuable.
    data = {"free_data_set": {"user_item_info_array": [{"item_id": 2002, "num": 1}]}}
    assert _S._can_rescue_training(data, _camp_chara(group=False), {}, _WEAK_TRAIN, 0.1, 40, 0, 48) is True


def _run():
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in funcs:
        fn()
        print(f"PASS  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(funcs)} passed")


if __name__ == "__main__":
    _run()
