"""Small review fixes: skill hint discount, Grand Live song-hold cap, documented preset knobs.

  1. _estimate_cost priced hints at a flat 10% off per level (Lv4 = 60%, Lv5 = 50% of base). The
     captured gain_skills buys show 0/10/20/30/35/40%, so Lv4/Lv5 skills were under-priced and 205'd.
  2. The song hold counted pick_square CALLS, and a turn makes up to four of them, so the 12-turn
     cap ran out after ~3-6 turns.
  3. Knobs the code documents as preset-controlled were not allow-listed, so hydrate_preset dropped
     an explicit false and the default (on) always ran.

Run:
    python tests/test_small_review_fixes.py
    python -m pytest tests/test_small_review_fixes.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.presets import hydrate_preset  # noqa: E402
from career_bot.core.skills import SkillBuyer  # noqa: E402
from career_bot.scenarios.grand_live import GrandLiveStrategy  # noqa: E402


def test_hint_discount_follows_the_game_schedule():
    sb = SkillBuyer.__new__(SkillBuyer)   # method-only; skip __init__/_load
    sb.skill_costs, sb.skill_rarities = {200012: 180}, {}
    got = [sb._estimate_cost({"skill_id": 200012, "hint_level": lv}) for lv in range(7)]
    #        Lv0  Lv1  Lv2  Lv3  Lv4  Lv5  (Lv6 clamps to Lv5)
    assert got == [180, 162, 144, 126, 117, 108, 108], got


def test_song_hold_cap_counts_turns_not_calls():
    s = GrandLiveStrategy.__new__(GrandLiveStrategy)
    perf = {"dance": 12, "passion": 12, "vocal": 12, "visual": 12, "mental": 12}
    board = {"next_square_info_array": [{"square_id": 40004, "square_num": 1},   # top-band song
                                        {"square_id": 11001, "square_num": 1}],  # cheap lesson
             "live_performance_info": perf, "effected_live_id_array": [],
             "master_live_id_array": list(range(30))}     # songs banked: a hold is only allowed then
    held_turns = 0
    for turn in range(1, GrandLiveStrategy.HOLD_FOR_SONG_MAX_TURNS + 4):
        s._last_turn = turn
        # runner: next_decision twice per command turn, each reaching pick_square up to twice
        picks = {s.pick_square(board, {}) for _ in range(4)}
        if picks != {0}:
            break
        held_turns += 1
    assert held_turns == GrandLiveStrategy.HOLD_FOR_SONG_MAX_TURNS, held_turns
    assert s.pick_square(board, {}) == 11001


def test_documented_preset_knobs_survive_hydrate():
    knobs = {"unity_force_races": False, "force_clock_debut": False, "ai_train_to_win": False,
             "ai_train_to_win_weight": 0.1, "enable_ai_policy": False,
             "wait_for_free_bonus": False, "deck_stat_policy": False}
    d = hydrate_preset(dict(knobs, name="t"))
    assert {k: d.get(k) for k in knobs} == knobs, d


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("small review fixes OK")
