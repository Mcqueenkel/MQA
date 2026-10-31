"""MANT coin waste: anklet over-buying, and the late-career surplus sweep.

Measured over 60 real MANT careers (uma_runtime/bot_logs): 861 coins/career never become stats
(30.5% of income). The single biggest slice is ANKLETS -- 10.2 bought vs 3.0 used per career, ~350
coins burned. An anklet is a one-turn, non-stacking buff, so at most ONE can be spent per turn and
held stock above 1 per stat is dead weight. Deck-card count was a poor proxy for "will this facility
be trained": Stamina/Power averaged ~1.4 matching training turns but carried 2-3 anklets each.

Two coupled changes (the second is mandatory, see test_single_anklet_is_not_frozen_before_camp):
  _skip_buy        -- ankle_max_stock caps held stock at 1/stat; ankle_offdeck_stock now 0.
  _hold_for_summer -- summer reserve 0, or the capped single anklet would be frozen all year.

Plus a surplus sweep from turn 65 that converts leftover coins into instant stat items (worth only
~4 coins/career -- the shelf is empty by then -- kept as free insurance, not as the fix).

Run:
    python tests/test_anklet_stock_and_sweep.py
    python -m pytest tests/test_anklet_stock_and_sweep.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.mant_items import MantItemManager, SUMMER_TRAINING_TURNS  # noqa: E402

IM = MantItemManager()

SPD = "Speed Ankle Weights"
# NOTE: there is no Wit anklet in the game -- anklets are ids 9001-9004 = Speed/Stamina/Power/Guts
# only, which is exactly why Wit (the most-trained facility at 11.3 turns/career) never gets one.
# STA stands in as the "off-deck stat" here: real item, 0 deck cards in these presets.
STA = "Stamina Ankle Weights"


def _preset(spd_cards=2, **kw):
    # _deck_type_counts is indexed by TRAINING_ITEM_DECK_TYPE_INDEX: [speed, stamina, power, guts]
    return {"_deck_type_counts": [spd_cards, 0, 0, 0, 0], **kw}


def _skip(name, owned_n, preset):
    return IM._skip_buy(name, {name: owned_n}, preset, 30)


# ---------------- anklet stock cap ----------------

def test_one_anklet_per_stat_is_the_cap():
    # 2 Speed deck cards used to authorise 4 held anklets; only one can ever be spent per turn.
    assert _skip(SPD, 0, _preset(2)) is False        # none held -> buy one
    assert _skip(SPD, 1, _preset(2)) is True         # one held -> STOP (was: keep buying to 4)


def test_offdeck_stat_is_never_stocked():
    # 0 deck cards for Stamina -> ankle_offdeck_stock is now 0, so never buy one "just in case"
    assert _skip(STA, 0, _preset(2)) is True


def test_max_stock_is_tunable():
    assert _skip(SPD, 1, _preset(2, ankle_max_stock=2)) is False   # allow a second
    assert _skip(SPD, 2, _preset(2, ankle_max_stock=2)) is True
    assert _skip(STA, 0, _preset(2, ankle_offdeck_stock=1)) is False


def test_deck_count_still_lowers_the_cap():
    # the per-card rule can only ever REDUCE below ankle_max_stock, never raise above it
    assert _skip(SPD, 0, _preset(0)) is True          # no cards -> offdeck rule (0) wins
    assert _skip(SPD, 1, _preset(9)) is True          # many cards -> still capped at 1


# ---------------- the mandatory companion ----------------

def test_single_anklet_is_not_frozen_before_camp():
    """THE LANDMINE: with stock capped at 1, a summer reserve of 1 would make every pre-camp turn
    'hold this for camp' and the only anklet would never be used all year -- a buy-side fix turning
    into a use-side regression. Reserve must be 0."""
    pre_camp = min(SUMMER_TRAINING_TURNS) - 5
    assert IM._hold_for_summer(SPD, {SPD: 1}, pre_camp, {}) is False   # spend it now
    assert IM._hold_for_summer(SPD, {SPD: 0}, pre_camp, {}) is True    # nothing to spend anyway


def test_summer_reserve_still_tunable_and_camp_spends_freely():
    pre_camp = min(SUMMER_TRAINING_TURNS) - 5
    assert IM._hold_for_summer(SPD, {SPD: 1}, pre_camp, {"mant_config": {"summer_ankle_stock": 1}}) is True
    # inside camp, and after the last camp, always spend
    assert IM._hold_for_summer(SPD, {SPD: 1}, min(SUMMER_TRAINING_TURNS), {}) is False
    assert IM._hold_for_summer(SPD, {SPD: 5}, max(SUMMER_TRAINING_TURNS) + 1, {}) is False


def test_toggle_off_disables_summer_holding():
    pre_camp = min(SUMMER_TRAINING_TURNS) - 5
    assert IM._hold_for_summer(SPD, {SPD: 3}, pre_camp, {"prioritize_summer_buffs": False}) is False


# ---------------- sweep prerequisites ----------------

def test_sweep_helpers_behave():
    # the sweep only takes instant stat items that still have headroom
    assert IM._is_instant_stat_item("Speed Scroll") is True
    assert IM._is_instant_stat_item("Empowering Megaphone") is False
    maxed = {"speed": 1200, "max_speed": 1200, "wiz": 400, "max_wiz": 1500}
    assert IM._stat_item_has_headroom("Speed Scroll", maxed) is False   # capped -> never swept
    assert IM._stat_item_has_headroom("Wit Scroll", maxed) is True


def test_sweep_ranks_the_highest_stat_first():
    """The sweep spends surplus on the HIGHEST current stat with headroom, because rank score is
    convex -- the last points of the top stat are worth ~3x the first points of a low one."""
    from career_bot.scenarios.mant_items import display_to_slug
    chara = {"speed": 1100, "max_speed": 1600, "wiz": 300, "max_wiz": 1500}

    def rank(name):
        pair = IM._STAT_ITEM_KEYS.get(display_to_slug(name).split("_")[0])
        return -int(chara.get(pair[0]) or 0) if pair else 0

    assert sorted(["Wit Scroll", "Speed Scroll"], key=rank)[0] == "Speed Scroll"


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
