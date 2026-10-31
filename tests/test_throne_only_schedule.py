"""Unit tests for the Throne-ONLY deck adaptive recreation (Heirs to the Throne present, Team
Sirius absent). The user's method: deploy each Throne CHARACTER outing when its situational payoff
lands instead of on a fixed date, keep the two card-itself steps on fixed dates.

  - Rudolf (1017): prerequisite -> fired as soon as he unlocks (i.e. in junior); the card reuses
    his select_id so the card steps can't run until his own outing is done.
  - Tokai Teio (1003): MOOD lever -> held until a 3-race streak (and mood < 5).
  - Tsurumaru (1073): ENERGY lever -> held for a low-vital classic turn.
  - card-itself step 1 @ t51, step 2 @ t59 (catch up after if missed).
  - fallback: past THRONE_FALLBACK_BY (t47) a still-undone character outing is forced (not wasted).
  - throne_adaptive_schedule: false -> revert to the generic interleaved schedule.

Run:
    python tests/test_throne_only_schedule.py
    python -m pytest tests/test_throne_only_schedule.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.mant import MantStrategy  # noqa: E402
from career_bot.core.training_brain import (  # noqa: E402
    GROUP_OUTING_COMMAND_ID,
    RACE_VALUE_CAMP_TURNS,
    TEAM_SIRIUS_SUPPORT_ID,
    THRONE_SUPPORT_ID,
    THRONE_RUDOLF,
    THRONE_TOKAI,
    THRONE_TSURUMARU,
    THRONE_FALLBACK_BY,
)

_THRONE_OUTINGS = (THRONE_TOKAI, THRONE_RUDOLF, THRONE_TSURUMARU)  # 1003, 1017, 1073
_OUTING_CMD = {"command_type": 3, "command_id": GROUP_OUTING_COMMAND_ID, "is_enable": 1, "select_id": 0}
_TRAIN_CMD = {"command_type": 1, "command_id": 101, "is_enable": 1}
_ENABLED = [_OUTING_CMD, _TRAIN_CMD]


def _tchara(turn=10, vital=60, motivation=5, char_done=(), char_locked=(), throne_card=(1, 0)):
    """Throne-only deck state. char_done = chara_ids whose CHARACTER outing is done; char_locked =
    not unlocked yet; all others unlocked + not done. throne_card = (is_outing, story_step) of the
    Throne card's OWN recreation row. NO Team Sirius card in the deck."""
    done, locked = set(char_done), set(char_locked)
    rows = [{"chara_id": c, "is_outing": 0 if c in locked else 1,
             "story_step": 1 if c in done else 0} for c in _THRONE_OUTINGS]
    return {
        "turn": turn, "vital": vital, "motivation": motivation,
        "support_card_array": [{"position": 6, "support_card_id": THRONE_SUPPORT_ID}]
                              + [{"position": i, "support_card_id": 10000 + i} for i in (1, 2, 3, 4, 5)],
        "evaluation_info_array": [
            {"target_id": 6, "is_outing": throne_card[0], "story_step": throne_card[1],
             "group_outing_info_array": rows},
        ],
    }


def _do(turn, preset=None, enabled=_ENABLED, raced=(), **kw):
    """Run _scheduled_recreation (which delegates to _throne_only_recreation) on a fresh strategy with
    a seeded race history. Returns (select_id or None, is_card or None)."""
    s = MantStrategy()
    s._raced_turns = set(raced)
    rec = s._scheduled_recreation(enabled, turn, _tchara(turn, **kw), preset or {})
    if rec is None:
        return (None, None)
    return (rec.get("select_id"), s._pending_outing_is_card)


# ---------------- deck detection ----------------

def test_throne_only_detected():
    assert MantStrategy()._deck_is_throne_only(_tchara()) is True


def test_mixed_deck_not_throne_only():
    mixed = _tchara()
    mixed["support_card_array"].append({"position": 5, "support_card_id": TEAM_SIRIUS_SUPPORT_ID})
    assert MantStrategy()._deck_is_throne_only(mixed) is False


def test_plain_deck_not_throne_only():
    plain = {"support_card_array": [{"support_card_id": 10000 + i} for i in range(6)]}
    assert MantStrategy()._deck_is_throne_only(plain) is False


# ---------------- Rudolf: prerequisite, done in junior ----------------

def test_rudolf_fires_in_junior():
    # All three unlocked, nothing done, junior turn -> Rudolf (the prerequisite) goes first.
    assert _do(10) == (THRONE_RUDOLF, False)


def test_rudolf_held_when_locked():
    # Rudolf not unlocked yet, others irrelevant -> nothing fires (Tokai/Tsurumaru held) -> train.
    assert _do(10, char_locked=(THRONE_RUDOLF,), char_done=(THRONE_TOKAI, THRONE_TSURUMARU)) == (None, None)


def test_rudolf_fires_before_card_even_at_card_turn():
    # t51 but Rudolf not done -> the CHARACTER 1017 fires first (is_card False); the card step waits.
    assert _do(51, char_done=(THRONE_TOKAI, THRONE_TSURUMARU), throne_card=(1, 0)) == (THRONE_RUDOLF, False)


# ---------------- Tokai Teio: mood, after a 3-race streak ----------------

def test_tokai_held_without_streak():
    # Rudolf + Tsurumaru done, only Tokai left, no race streak -> held -> train.
    assert _do(30, char_done=(THRONE_RUDOLF, THRONE_TSURUMARU)) == (None, None)


def test_tokai_fires_after_three_race_streak():
    # 3 consecutive race turns (27,28,29) before turn 30, mood spent -> fire Tokai for mood.
    assert _do(30, char_done=(THRONE_RUDOLF, THRONE_TSURUMARU),
               raced=(27, 28, 29), motivation=2) == (THRONE_TOKAI, False)


def test_tokai_not_fired_when_mood_maxed():
    # Streak present but mood already 5 -> no point, keep holding (not past deadline).
    assert _do(30, char_done=(THRONE_RUDOLF, THRONE_TSURUMARU),
               raced=(27, 28, 29), motivation=5) == (None, None)


def test_tokai_streak_must_be_consecutive():
    # A gap (raced 26,27 then skipped 28, raced 29) = only 1 in a row before turn 30 -> held.
    assert _do(30, char_done=(THRONE_RUDOLF, THRONE_TSURUMARU),
               raced=(26, 27, 29), motivation=2) == (None, None)


# ---------------- Tsurumaru: energy, low-vital classic turn ----------------

def test_tsurumaru_fires_low_vital_classic():
    # Rudolf done; classic turn, vital below rest threshold -> energy outing (before Tokai).
    assert _do(30, char_done=(THRONE_RUDOLF,), vital=40) == (THRONE_TSURUMARU, False)


def test_tsurumaru_held_high_vital():
    # Vital healthy -> don't waste the energy outing; Tokai also held (no streak) -> train.
    assert _do(30, char_done=(THRONE_RUDOLF,), vital=80) == (None, None)


def test_tsurumaru_not_in_junior():
    # Junior low-vital turn is NOT the classic energy window -> held (Rudolf already done here).
    assert _do(12, char_done=(THRONE_RUDOLF,), vital=30) == (None, None)


# ---------------- fallback deadline: don't waste an outing ----------------

def test_deadline_forces_tsurumaru_even_at_high_vital():
    assert _do(THRONE_FALLBACK_BY, char_done=(THRONE_RUDOLF,), vital=90) == (THRONE_TSURUMARU, False)


def test_deadline_forces_tokai_without_streak():
    assert _do(THRONE_FALLBACK_BY, char_done=(THRONE_RUDOLF, THRONE_TSURUMARU), motivation=5) == (THRONE_TOKAI, False)


# ---------------- card-itself steps on fixed dates ----------------

def test_card_step_one_at_51():
    assert _do(51, char_done=_THRONE_OUTINGS, throne_card=(1, 0)) == (1017, True)


def test_card_step_two_at_59():
    assert _do(59, char_done=_THRONE_OUTINGS, throne_card=(1, 1)) == (1017, True)


def test_card_step_one_not_before_51():
    assert _do(49, char_done=_THRONE_OUTINGS, throne_card=(1, 0)) == (None, None)


def test_card_step_one_catches_up_after_51():
    # Missed at 51 (energy/etc) -> still does step 1 later, before step 2.
    assert _do(55, char_done=_THRONE_OUTINGS, throne_card=(1, 0)) == (1017, True)


def test_card_step_skipped_when_maxed():
    assert _do(59, char_done=_THRONE_OUTINGS, throne_card=(1, 2)) == (None, None)


def test_card_step_skipped_when_row_locked():
    assert _do(51, char_done=_THRONE_OUTINGS, throne_card=(0, 0)) == (None, None)


def test_card_opt_out_keeps_characters():
    # Card disabled: card step skipped; with all chars done -> nothing -> train.
    assert _do(51, preset={"sirius_throne_card_outing": False},
               char_done=_THRONE_OUTINGS, throne_card=(1, 0)) == (None, None)


# ---------------- guards ----------------

def test_no_fire_in_summer_camp():
    camp = sorted(RACE_VALUE_CAMP_TURNS)[0]  # 37
    assert _do(camp) == (None, None)


def test_nothing_left_trains():
    assert _do(60, char_done=_THRONE_OUTINGS, throne_card=(1, 2)) == (None, None)


def test_adaptive_off_reverts_to_generic():
    # With the adaptive flag off, the generic interleaved schedule runs: t18 is a schedule date and
    # (Sirius absent) it pulls forward the earliest available outing = Rudolf. Proves the kill switch.
    assert _do(18, preset={"throne_adaptive_schedule": False}) == (THRONE_RUDOLF, False)


# ---------------- race-streak recording helper ----------------

def test_consecutive_races_counts_back():
    s = MantStrategy()
    s._raced_turns = {28, 29, 30}
    assert s._consecutive_races_before(31) == 3
    assert s._consecutive_races_before(30) == 2  # 29, 28
    assert s._consecutive_races_before(28) == 0  # 27 not raced


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
