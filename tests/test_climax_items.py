"""Climax (last-6-turns) item rules:
  - 35% Master Cleat Hammer is saved toward the biggest/latest climax: 1 -> t78 only,
    2 -> t76 + t78, 3 -> t74/76/78 (mirrors the glow-stick reserve). Artisan covers an
    earlier climax when the Master is still being held.
  - climax config constants (200-coin reserve, shop-start turn, hammer reserve map).

Run:
    python tests/test_climax_items.py
    python -m pytest tests/test_climax_items.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.mant_items import (  # noqa: E402
    MantItemManager,
    CLIMAX_COIN_RESERVE,
    CLIMAX_SHOP_START,
    MASTER_CLEAT_CLIMAX_RESERVE,
)

IM = MantItemManager()


def cleat(masters=0, artisans=0, turn=78):
    owned = {}
    if masters:
        owned["Master Cleat Hammer"] = masters
    if artisans:
        owned["Artisan Cleat Hammer"] = artisans
    return IM._old_ui_cleat_before_race(owned, turn, 0, None)


def test_one_master_only_at_t78():
    assert cleat(masters=1, turn=74) is None
    assert cleat(masters=1, turn=76) is None
    assert cleat(masters=1, turn=78) == "Master Cleat Hammer"


def test_two_masters_t76_and_t78():
    assert cleat(masters=2, turn=74) is None
    assert cleat(masters=2, turn=76) == "Master Cleat Hammer"
    assert cleat(masters=2, turn=78) == "Master Cleat Hammer"


def test_three_masters_every_climax():
    assert cleat(masters=3, turn=74) == "Master Cleat Hammer"
    assert cleat(masters=3, turn=76) == "Master Cleat Hammer"
    assert cleat(masters=3, turn=78) == "Master Cleat Hammer"


def test_artisan_covers_earlier_climax_while_master_held():
    assert cleat(masters=1, artisans=1, turn=74) == "Artisan Cleat Hammer"
    assert cleat(masters=1, artisans=1, turn=78) == "Master Cleat Hammer"


def test_none_when_no_hammers():
    assert cleat(turn=78) is None


def test_master_spent_freely_before_turn_69():
    # Before turn 69, a lone Master is spent on any (non-climax) G1 -- no saving.
    assert cleat(masters=1, turn=67) == "Master Cleat Hammer"
    assert cleat(masters=1, turn=68) == "Master Cleat Hammer"


def test_master_held_from_turn_69():
    # From turn 69 on, the LAST Master is held for the climax...
    assert cleat(masters=1, turn=69) is None
    assert cleat(masters=1, turn=72) is None   # e.g. Arima Kinen week
    # ...but a spare Master (2 held) is still spent on a turn-72 G1.
    assert cleat(masters=2, turn=72) == "Master Cleat Hammer"


def test_climax_constants():
    assert CLIMAX_COIN_RESERVE == 200
    assert CLIMAX_SHOP_START == 73
    assert MASTER_CLEAT_CLIMAX_RESERVE == {74: 2, 76: 1, 78: 0}


def test_ankle_stock_is_capped_at_one_per_stat():
    # SUPERSEDES the old "2 anklets per deck card" rule. An anklet is a one-turn, non-stacking buff,
    # so only ONE can ever be spent per turn; measured over 60 careers the deck-scaled cap bought
    # 10.2/career and used 3.0, burning ~350 coins. Stock is now capped at 1 per stat.
    preset = {"_deck_type_counts": [2, 0, 0, 0, 0]}
    assert IM._skip_buy("Speed Ankle Weights", {"Speed Ankle Weights": 0}, preset) is False  # buy one
    assert IM._skip_buy("Speed Ankle Weights", {"Speed Ankle Weights": 1}, preset) is True   # then stop


def test_ankle_off_deck_is_not_stocked():
    # Off-deck stat: no longer buys a "just in case" backup (ankle_offdeck_stock default 0 now).
    preset = {"_deck_type_counts": [2, 0, 0, 0, 0]}  # no guts cards
    assert IM._skip_buy("Guts Ankle Weights", {"Guts Ankle Weights": 0}, preset) is True


# ---------------- climax always-train (energy + charm on any deck) ----------------

def _train_cmd(gain=15, fail=0):
    return {"command_type": 1, "command_id": 101, "failure_rate": fail,
            "params_inc_dec_info_array": [{"target_type": 1, "value": gain}]}


def _chara_at(turn, vital=40, group=False):
    cards = [30081] if group else []   # 30081 = Team Sirius (a Group card)
    return {"turn": turn, "vital": vital, "evaluation_info_array": [],
            "support_card_array": [{"support_card_id": c} for c in cards]}


def test_climax_energy_rescue_any_deck():
    # Non-group deck, climax turn (73), weak positive board -> energy rescue now fires (all-out climax).
    out = IM._rescue_energy_target(_chara_at(73, vital=40, group=False), {"Vita 40": 1}, {}, _train_cmd(15))
    assert out, "climax all-out should top up energy for a positive board on any deck"


def test_non_climax_non_group_still_skips_energy():
    # Same weak board on a normal turn (30) -> no rescue (summer/climax windows unaffected here).
    out = IM._rescue_energy_target(_chara_at(30, vital=40, group=False), {"Vita 40": 1}, {}, _train_cmd(15))
    assert out == []


def test_climax_charm_for_weak_board():
    # Weak positive board in the climax window with risky failure -> charm now fires.
    got = IM._charm_target(_train_cmd(gain=15, fail=40), {"Good-Luck Charm": 1}, {}, None, chara=_chara_at(75))
    assert got == ("Good-Luck Charm", 1)


def test_charm_always_on_very_good_training_over_30_fail():
    # Very good training (gain >= 40) at >30% fail -> charm fires EVEN IF a Vita is covering it.
    got = IM._charm_target(_train_cmd(gain=45, fail=40), {"Good-Luck Charm": 1}, {}, None,
                           chara=_chara_at(30), vita_covered=True)
    assert got == ("Good-Luck Charm", 1)


def test_charm_defers_to_vita_on_mediocre_training():
    # Mediocre training (gain 20, no rainbow) at 40% fail with a Vita covering -> NOT very good,
    # so the Vita-first rule still defers the charm.
    got = IM._charm_target(_train_cmd(gain=20, fail=40), {"Good-Luck Charm": 1}, {}, None,
                           chara=_chara_at(30), vita_covered=True)
    assert got is None


def test_charm_skipped_below_30_fail():
    # Even a very good board at <30% fail doesn't need the charm.
    got = IM._charm_target(_train_cmd(gain=45, fail=20), {"Good-Luck Charm": 1}, {}, None,
                           chara=_chara_at(30), vita_covered=True)
    assert got is None


def test_rescue_stacks_two_vitas_when_one_is_short():
    # Energy 35, strong board, only Vita 20s in stock: one (->55) can't reach the safe
    # target (60), so the rescue STACKS two (35+40=75) instead of giving up and resting.
    out = IM._rescue_energy_target(_chara_at(30, vital=35), {"Vita 20": 3}, {}, _train_cmd(gain=30))
    assert out == [("Vita 20", 2)], out


def test_rescue_prefers_single_sufficient_vita():
    # Same board but a Vita 40 is in stock -> one drink covers it, so just the one (no stacking).
    out = IM._rescue_energy_target(_chara_at(30, vital=35), {"Vita 20": 3, "Vita 40": 1}, {}, _train_cmd(gain=30))
    assert out == [("Vita 40", 1)], out


def test_royal_kale_requires_a_cupcake():
    # Royal Kale Juice (+100 energy, -1 mood) only fires when a cupcake is held to offset the mood.
    chara = _chara_at(73, vital=0)   # gap 100 -> a +100 kale fits
    assert IM._energy_targets(chara, {"Royal Kale Juice": 1}, {}) == []                  # no cupcake -> skip
    assert IM._energy_targets(chara, {"Royal Kale Juice": 1, "Plain Cupcake": 1}, {}) == [("Royal Kale Juice", 1)]


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
