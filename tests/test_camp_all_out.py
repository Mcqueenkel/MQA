"""All-out summer camp for EVERY deck (not just Sirius/Throne group decks): on a Lv5 camp turn with a
positive board the bot trains instead of resting. In MANT (scenario 4) it commits any positive board
(the item manager tops up energy after); item-less scenarios (URA/Unity/Grand Live) commit only when
failure is already <= camp_failure_cap (default 40), else rest. Verified by stubbing _best_command's
helpers so only the camp branch under test decides.

Run:
    python tests/test_camp_all_out.py
    python -m pytest tests/test_camp_all_out.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.grand_live import GrandLiveStrategy  # noqa: E402
from career_bot.scenarios.mant import MantStrategy  # noqa: E402
from career_bot.scenarios.unity import UnityStrategy  # noqa: E402
from career_bot.scenarios.ura import UraStrategy  # noqa: E402

REST = {"command_id": "REST"}
REC = {"command_id": "REC"}

# The camp branch reads the STRATEGY's scenario_id, not the preset's, so the test builds the real
# dispatched class (as runner.STRATEGIES does) rather than the abstract base.
_STRATEGY = {1: UraStrategy, 2: UnityStrategy, 3: GrandLiveStrategy, 4: MantStrategy}


def _decide(scenario, turn, failure, best_score=0.3, vital=30, camp_cap=None, items=None, eff_rest=40):
    """items=None stubs the item rescue off; items={item_id: num} runs the REAL _can_rescue_training
    against that bag. eff_rest is the (banked) turn-quality rest threshold; rest_threshold stays 48."""
    cls = _STRATEGY[scenario]
    b = cls.__new__(cls)
    train = {"command_type": 1, "command_id": 101, "is_enable": 1, "failure_rate": failure}
    b._rest_command = lambda *a, **k: REST
    b._recreation_command = lambda *a, **k: REC
    b._medic_command = lambda *a, **k: None
    b._has_curable_bad_status = lambda *a, **k: False
    b._scheduled_recreation = lambda *a, **k: None
    b._deck_has_group_cards = lambda *a, **k: False        # NON-group deck -- the whole point
    b._turn_quality_threshold = lambda *a, **k: eff_rest
    b._record_turn_quality = lambda *a, **k: None
    b._junior_recreation = lambda *a, **k: None
    b._should_recreate = lambda *a, **k: False
    if items is None:
        b._can_rescue_training = lambda *a, **k: False
    b._summer_conserve_command = lambda *a, **k: None
    b._pick_scored_training = lambda tr, d, c, p, t: (best_score, train)
    data = {"home_info": {"command_info_array": [train]},
            "free_data_set": {"user_item_info_array": [{"item_id": i, "num": n} for i, n in (items or {}).items()]}}
    chara = {"turn": turn, "vital": vital, "motivation": 3, "max_vital": 100}
    preset = {"scenario_id": scenario}
    if camp_cap is not None:
        preset["camp_failure_cap"] = camp_cap
    cmd = b._best_command(data, chara, preset, record=False)
    return (cmd or {}).get("command_id")


def test_camp_all_out_every_deck():
    CAMP = 37  # a real Lv5 camp turn (RACE_VALUE_CAMP_TURNS)

    # MANT, non-group deck, positive board -> TRAIN even at high failure (item manager rescues after).
    assert _decide(scenario=4, turn=CAMP, failure=60) == 101
    # ...which is the fix: the OLD group gate would have rested/recreated this non-group camp turn.

    # URA (item-less), positive board, tolerable failure -> TRAIN (no items needed to commit a safe board).
    assert _decide(scenario=1, turn=CAMP, failure=25) == 101
    # URA, positive board, RECKLESS failure (> cap 40) -> do NOT train; rest/recover for the next camp turn.
    assert _decide(scenario=1, turn=CAMP, failure=60) in ("REST", "REC")
    # Unity (2) and Grand Live (3) are item-less too, so they get the SAME cap as URA -- they must not
    # be mistaken for MANT. Guards the scenario source: presets resolve only to 1 or 4, so reading the
    # scenario off the preset instead of the strategy silently made these two commit like MANT.
    assert _decide(scenario=2, turn=CAMP, failure=60) in ("REST", "REC")
    assert _decide(scenario=3, turn=CAMP, failure=60) in ("REST", "REC")
    # ...and a custom camp_failure_cap opens that up.
    assert _decide(scenario=1, turn=CAMP, failure=60, camp_cap=70) == 101

    # Negative board on a camp turn is never force-trained (recreate).
    assert _decide(scenario=1, turn=CAMP, failure=10, best_score=-0.2) in ("REST", "REC")

    # NON-camp low-energy turn is unaffected -> normal rest, not a camp force-train.
    assert _decide(scenario=1, turn=20, failure=10, vital=25) in ("REST", "REC")

    print("camp-all-out OK (every deck trains positive camp boards; URA/Unity gated on failure; non-camp unaffected)")


def test_climax_all_out_is_mant_only_and_never_blindly_gambles():
    CLIMAX = 75

    # These are ordinary late-career turns outside MANT. They have no item manager, so the old
    # turn-number-only shortcut could force a 99% training at 5 energy and throw the career.
    for scenario in (1, 2, 3):
        assert _decide(scenario, CLIMAX, failure=99, best_score=0.4, vital=5) in ("REST", "REC")

    # MANT still goes all-out on a genuinely safe positive board...
    assert _decide(4, CLIMAX, failure=5, best_score=0.4, vital=70) == 101
    # ...but without a verified item rescue it no longer force-trains an impossible board.
    assert _decide(4, CLIMAX, failure=99, best_score=0.4, vital=5) in ("REST", "REC")


def test_mant_climax_trains_an_unsafe_board_an_owned_item_rescues():
    # Discriminating half: each board below TRAINS on a climax turn and RESTS on the same board one
    # non-climax turn earlier, so deleting the climax branch (or CLIMAX_TRAIN_TURNS) fails it.
    CLIMAX, LATE = 75, 70
    VITA_40, CHARM = 2002, 10001
    # A modest (0.4, no rainbow) board at low energy with a Vita 40 in the bag: the item manager tops
    # it up for any positive climax training, so the brain's real _can_rescue_training must agree.
    low = dict(failure=20, best_score=0.4, vital=40, items={VITA_40: 3, CHARM: 1})
    assert _decide(4, CLIMAX, **low) == 101
    assert _decide(4, LATE, **low) in ("REST", "REC")
    # Fine energy, risky failure, a charm owned -> the charm carries the climax turn.
    risky = dict(failure=40, best_score=0.4, vital=70, items={CHARM: 1})
    assert _decide(4, CLIMAX, **risky) == 101
    assert _decide(4, LATE, **risky) in ("REST", "REC")
    # Vital 50: above rest_threshold (48) but under a banked eff_rest of 54. Nothing to bank for in the
    # climax, so it trains; a normal turn still rests to bank.
    banked = dict(failure=10, best_score=0.4, vital=50, eff_rest=54)
    assert _decide(4, CLIMAX, **banked) == 101
    assert _decide(4, LATE, **banked) in ("REST", "REC")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
