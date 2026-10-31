"""Unit tests for the three summer-training behaviors:

A. Anklet buying        -- MantItemManager._skip_buy buys a deck-supported Ankle Weights type
   with NO per-type stock cap (the old 3-per-type cap was removed so leftover coins get spent);
   off-deck types are kept to exactly 1 "just in case".
B. Summer race fallback  -- MantStrategy._should_summer_race: on a summer turn with no
   >=2-rainbow training and no Reset Whistle to re-roll, race the best track instead.
C. Royal Kale + cupcake  -- MantItemManager._kale_mood_offset: when Royal Kale Juice is
   used (drains mood), pair a +1 Plain Cupcake (else +2 Berry Sweet) to offset it.

No game/network needed -- synthetic boards/items.

Run:
    python tests/test_summer_features.py
    python -m pytest tests/test_summer_features.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.mant_items import MantItemManager  # noqa: E402
from career_bot.scenarios.mant import MantStrategy  # noqa: E402
from career_bot.core.training_brain import RESET_WHISTLE_ITEM_ID, TRAINING_COMMANDS  # noqa: E402

_IM = MantItemManager()
_TRAIN_IDS = list(TRAINING_COMMANDS)[:3]


# ---------------- A: anklet stock capped at 1 per stat ----------------
# SUPERSEDES the old "2 anklets per support card" rule. An anklet is a ONE-TURN, non-stacking buff:
# only one can ever be spent per turn, so held stock above 1 is dead weight. Measured over 60 real
# MANT careers: 10.2 bought vs 3.0 used per career, ~350 coins burned. Deck-card count was also a
# bad proxy for "will this facility be trained" -- Stamina/Power carried 2-3 anklets on ~1.4
# matching training turns. Now: cap 1/stat (ankle_max_stock), and 0 for a stat with no deck cards
# (ankle_offdeck_stock). See tests/test_anklet_stock_and_sweep.py for the full policy.

_SPEED_DECK = {"_deck_type_counts": [4, 0, 0, 0, 0]}    # 4 Speed cards
_SPEED_DECK_2 = {"_deck_type_counts": [2, 0, 0, 0, 0]}  # 2 Speed cards


def test_anklet_buys_the_first_one():
    assert _IM._skip_buy("Speed Ankle Weights", {"Speed Ankle Weights": 0}, _SPEED_DECK_2) is False


def test_anklet_stops_at_one():
    assert _IM._skip_buy("Speed Ankle Weights", {"Speed Ankle Weights": 1}, _SPEED_DECK_2) is True


def test_more_deck_cards_do_not_raise_the_cap():
    # a heavier deck no longer buys more -- the per-card rule can only lower the cap, never raise it
    assert _IM._skip_buy("Speed Ankle Weights", {"Speed Ankle Weights": 1}, _SPEED_DECK) is True


def test_anklet_off_deck_type_is_not_stocked():
    # Power has 0 deck cards -> no "just in case" backup any more
    assert _IM._skip_buy("Power Ankle Weights", {}, _SPEED_DECK) is True


def test_anklet_per_type_independent():
    # Holding Speed must NOT block buying Power for a Power deck.
    power_deck = {"_deck_type_counts": [0, 0, 2, 0, 0]}
    assert _IM._skip_buy("Power Ankle Weights", {"Speed Ankle Weights": 3}, power_deck) is False


def test_anklet_mixed_deck_example():
    # 2 Spd / 1 Pow / 1 Guts deck -> ONE each for the on-deck stats, none for off-deck Stamina.
    deck = {"_deck_type_counts": [2, 0, 1, 1, 0]}  # spd2, sta0, pow1, guts1, wit0
    for stat in ("Speed", "Power", "Guts"):
        assert _IM._skip_buy(f"{stat} Ankle Weights", {}, deck) is False               # buy one
        assert _IM._skip_buy(f"{stat} Ankle Weights", {f"{stat} Ankle Weights": 1}, deck) is True
    assert _IM._skip_buy("Stamina Ankle Weights", {}, deck) is True                     # off-deck


# ---------------- B: summer race fallback ----------------

def _train(cmd_id, maxed_partners):
    return {"is_enable": 1, "command_type": 1, "command_id": cmd_id,
            "training_partner_array": list(maxed_partners)}


def _chara(turn, maxed):
    return {"turn": turn, "evaluation_info_array": [{"target_id": p, "evaluation": 85} for p in maxed]}


def _board(trainings, whistles=0):
    items = [{"item_id": RESET_WHISTLE_ITEM_ID, "num": whistles}] if whistles else []
    return {"home_info": {"command_info_array": trainings},
            "free_data_set": {"user_item_info_array": items}}


def test_summer_race_when_no_good_training_and_no_whistle():
    s = MantStrategy()
    board = _board([_train(_TRAIN_IDS[0], [1]), _train(_TRAIN_IDS[1], [])])  # max 1 rainbow
    assert s._should_summer_race(board, _chara(37, [1]), {}) is True


def test_summer_train_when_good_training_exists():
    s = MantStrategy()
    board = _board([_train(_TRAIN_IDS[0], [1, 2]), _train(_TRAIN_IDS[1], [])])  # 2 rainbows
    assert s._should_summer_race(board, _chara(37, [1, 2]), {}) is False


def test_summer_defers_to_whistle_when_owned():
    s = MantStrategy()
    board = _board([_train(_TRAIN_IDS[0], [1])], whistles=1)  # no good training, but a whistle
    assert s._should_summer_race(board, _chara(37, [1]), {}) is False


def test_summer_race_only_on_summer_turns():
    s = MantStrategy()
    board = _board([_train(_TRAIN_IDS[0], [1])])
    assert s._should_summer_race(board, _chara(20, [1]), {}) is False  # turn 20 not summer


def test_summer_race_disabled_by_preset():
    s = MantStrategy()
    board = _board([_train(_TRAIN_IDS[0], [1])])
    assert s._should_summer_race(board, _chara(37, [1]), {"summer_race_fallback": False}) is False


# ---------------- C: Royal Kale + cupcake pairing ----------------

def test_kale_pairs_plain_cupcake_first():
    assert _IM._kale_mood_offset({"Royal Kale Juice"},
                                 {"Plain Cupcake": 2, "Berry Sweet Cupcake": 1}) == ("Plain Cupcake", 1)


def test_kale_falls_back_to_berry_when_no_plain():
    assert _IM._kale_mood_offset({"Royal Kale Juice"}, {"Berry Sweet Cupcake": 1}) == ("Berry Sweet Cupcake", 1)


def test_kale_no_double_cupcake():
    # A cupcake is already being used this turn -> don't add another.
    assert _IM._kale_mood_offset({"Royal Kale Juice", "Berry Sweet Cupcake"}, {"Plain Cupcake": 2}) is None


def test_no_kale_no_cupcake():
    assert _IM._kale_mood_offset({"Vita 40"}, {"Plain Cupcake": 2}) is None


def test_kale_but_no_cupcakes_owned():
    assert _IM._kale_mood_offset({"Royal Kale Juice"}, {}) is None


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {fn.__name__}: {exc}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
