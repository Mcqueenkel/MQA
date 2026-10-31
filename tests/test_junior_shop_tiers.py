"""Junior-year (turns 1-24) shop priority override:
  Tier 1 = energy + mood (Vita/Kale/Energy Drinks, cupcakes, Grilled Carrots).
  Tier 2 = training buffs (Empowering megaphone, Good-Luck Charm, Reset Whistle) + MAIN-stat anklet.
  Tier 3 = stat Scrolls/Manuals + OFF-stat anklets (<2 deck cards).
Lower tier number = bought first. After turn 24 it reverts to DEFAULT_ITEM_TIERS.

Run:
    python tests/test_junior_shop_tiers.py
    python -m pytest tests/test_junior_shop_tiers.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.mant_items import (  # noqa: E402
    MantItemManager, JUNIOR_ITEM_TIERS, JUNIOR_LAST_TURN, DEFAULT_ITEM_TIERS,
)

IM = MantItemManager()


def test_scroll_and_manual_never_share_a_tier():
    # Standing rule: stat Scrolls (big gain) and Manuals (lesser) are ALWAYS separated, Scrolls
    # at a higher priority (lower tier number). Checked in both the default and junior maps.
    for stat in ("speed", "stamina", "power", "guts", "wit"):
        assert DEFAULT_ITEM_TIERS[f"{stat}_scroll"] < DEFAULT_ITEM_TIERS[f"{stat}_manual"], stat
        assert JUNIOR_ITEM_TIERS[f"{stat}_scroll"] < JUNIOR_ITEM_TIERS[f"{stat}_manual"], stat


def test_junior_window_is_24():
    assert JUNIOR_LAST_TURN == 24


def test_tier1_energy_mood_and_scrolls():
    for slug in ("grilled_carrots", "vita_20", "vita_40", "vita_65", "royal_kale_juice",
                 "plain_cupcake", "berry_sweet_cupcake",
                 "speed_scroll", "stamina_scroll", "power_scroll", "guts_scroll", "wit_scroll"):
        assert JUNIOR_ITEM_TIERS[slug] == 1, slug


def test_energy_drink_max_never_bought():
    # Energy Drink MAX / MAX EX only raise the max-energy ceiling -> blocklisted, never bought.
    assert IM._skip_buy("Energy Drink MAX", {}, {}) is True
    assert IM._skip_buy("Energy Drink MAX EX", {}, {}) is True
    assert not any("energy_drink" in k for k in JUNIOR_ITEM_TIERS)


def test_tier2_buffs():
    for slug in ("empowering_megaphone", "good-luck_charm", "reset_whistle"):
        assert JUNIOR_ITEM_TIERS[slug] == 2, slug


def test_tier3_manuals():
    # Manuals (lesser stat item) at tier 3; Scrolls are tier 1, NOT here.
    for slug in ("speed_manual", "stamina_manual", "power_manual", "guts_manual", "wit_manual"):
        assert JUNIOR_ITEM_TIERS[slug] == 3, slug
    assert JUNIOR_ITEM_TIERS["speed_scroll"] == 1


def test_anklets_not_pinned_in_map():
    # Anklet tier is decided dynamically (main vs off), not via the static junior map.
    assert not any("ankle" in k for k in JUNIOR_ITEM_TIERS)


def test_junior_ankle_main_vs_off():
    assert IM._junior_ankle_tier(3) == 2   # main stat (>=2 cards) -> tier 2
    assert IM._junior_ankle_tier(2) == 2   # exactly 2 cards -> still main -> tier 2
    assert IM._junior_ankle_tier(1) == 3   # <2 cards -> off-stat -> tier 3
    assert IM._junior_ankle_tier(0) == 3


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1; print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
