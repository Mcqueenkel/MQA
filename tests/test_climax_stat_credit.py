"""Climax stat credit (hammer-aware): the scorer treats each PHYSICAL stat (Spd/Sta/Pow/Guts) as
already higher by the points the remaining TS climax races will add -- computed from the cleat
hammers ACTUALLY in hand. No hammers -> the no-hammer base 15+15+27 = 57; 1 Master + 1 Artisan ->
18+15+36 = 69; 2 Artisan + 1 Master -> 18+18+36 = 72. So the bot stops piling onto a near-cap
physical stat exactly as much as the climaxes will finish it, and Wit gets nothing (climax +0 Wit).

Run:
    python tests/test_climax_stat_credit.py
    python -m pytest tests/test_climax_stat_credit.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.mant import MantStrategy  # noqa: E402
from career_bot.core.training_brain import (  # noqa: E402
    MASTER_CLEAT_ITEM_ID, ARTISAN_CLEAT_ITEM_ID,
)


def _strategy():
    s = MantStrategy()
    s._forecast = None
    return s


def _chara(**over):
    base = {
        "turn": 20, "vital": 80, "motivation": 3,
        "speed": 300, "stamina": 300, "power": 300, "guts": 300, "wiz": 300,
        "max_speed": 1200, "max_stamina": 1200, "max_power": 1200,
        "max_guts": 1200, "max_wiz": 1200,
        "skill_point": 0, "evaluation_info_array": [],
    }
    base.update(over)
    return base


def _data(master=0, artisan=0):
    items = []
    if master:
        items.append({"item_id": MASTER_CLEAT_ITEM_ID, "num": master})
    if artisan:
        items.append({"item_id": ARTISAN_CLEAT_ITEM_ID, "num": artisan})
    return {"home_info": {"command_info_array": []},
            "free_data_set": {"user_item_info_array": items}}


def _speed_cmd(gain=20):   # command_id 101 = Speed, target_type 1 = Speed stat
    return {"command_id": 101, "command_type": 1, "level": 1, "failure_rate": 0,
            "training_partner_array": [], "tips_event_partner_array": [],
            "params_inc_dec_info_array": [{"target_type": 1, "value": gain}]}


def _wit_cmd(gain=20):     # command_id 106 = Wit, target_type 5 = Wit stat
    return {"command_id": 106, "command_type": 1, "level": 1, "failure_rate": 0,
            "training_partner_array": [], "tips_event_partner_array": [],
            "params_inc_dec_info_array": [{"target_type": 5, "value": gain}]}


_PRESET = {"ai_train_to_win": False}


def _score(cmd, chara, data):
    return _strategy()._score_command(cmd, data, chara, _PRESET)


# ---------------- the hammer-aware credit values ----------------

def test_no_hammers_is_base_57():
    assert _strategy()._climax_stat_credit(0, 73, 0, 0) == 57   # 15 + 15 + 27


def test_one_master_one_artisan_69():
    # Master saved for t78 (+36), Artisan on t74 (+18), t76 bare (+15) -> 69.
    assert round(_strategy()._climax_stat_credit(0, 73, 1, 1)) == 69


def test_full_loadout_72():
    # 2 Artisan (t74,t76 -> +18 each) + 1 Master (t78 -> +36) -> 72.
    assert round(_strategy()._climax_stat_credit(0, 73, 1, 2)) == 72


def test_two_master_one_artisan_75():
    # Reserve sends Masters to the later climaxes: Artisan t74 (+18), Master t76 (+20), Master
    # t78 (+36) -> 75.
    assert round(_strategy()._climax_stat_credit(0, 73, 2, 1)) == 75


def test_three_master_77():
    # A Master on every climax: t74 +20, t76 +20, t78 +36 -> 77.
    assert round(_strategy()._climax_stat_credit(0, 73, 3, 0)) == 77


def test_excess_hammers_capped_at_three_climaxes():
    # Only 3 climaxes exist, so hammers beyond them are ignored (no overflow): 3M+2A == 3M.
    s = _strategy()
    assert s._climax_stat_credit(0, 73, 3, 2) == s._climax_stat_credit(0, 73, 3, 0)


def test_more_hammers_more_credit():
    s = _strategy()
    assert s._climax_stat_credit(0, 73, 0, 0) < s._climax_stat_credit(0, 73, 0, 1) \
        < s._climax_stat_credit(0, 73, 1, 1) < s._climax_stat_credit(0, 73, 1, 2)


def test_credit_shrinks_per_completed_climax():
    s = _strategy()
    # 1 Master + 1 Artisan: at t75 climax-1 is done, so t76+t78 remain. The Artisan now covers the
    # earliest REMAINING climax (t76 -> +18), Master holds for t78 (+36) -> 54.
    assert round(s._climax_stat_credit(0, 75, 1, 1)) == 54   # 18 + 36
    assert round(s._climax_stat_credit(0, 77, 1, 1)) == 36   # only t78 (Master) left
    assert s._climax_stat_credit(0, 78, 1, 1) == 0           # all done


def test_wit_never_credited():
    assert _strategy()._climax_stat_credit(4, 20, 1, 2) == 0   # climax adds +0 Wit


def test_credit_is_mant_only():
    # The TS climax races exist only in Trackblazer (scenario 4). Other scenarios must get ZERO
    # credit on a physical stat, so they don't hold it short of the cap for gains that never come.
    from career_bot.scenarios.ura import UraStrategy
    from career_bot.scenarios.unity import UnityStrategy
    from career_bot.scenarios.grand_live import GrandLiveStrategy
    assert MantStrategy.__new__(MantStrategy)._climax_stat_credit(0, 73, 0, 0) == 57   # MANT keeps it
    for cls in (UraStrategy, UnityStrategy, GrandLiveStrategy):
        assert cls.__new__(cls)._climax_stat_credit(0, 73, 3, 0) == 0.0                # others: none


# ---------------- effect on the training scorer ----------------

def test_more_hammers_zero_a_physical_stat_sooner():
    # Speed at 1135. No hammers (credit 57 -> 1192, still under cap) keeps some score; the full
    # loadout (credit 72 -> 1207 over cap) zeroes the gain. So holding hammers makes the bot drop
    # a near-cap physical stat earlier.
    chara = _chara(speed=1135)
    bare = _score(_speed_cmd(), chara, _data())
    loaded = _score(_speed_cmd(), chara, _data(master=1, artisan=2))
    assert loaded < bare
    assert abs(loaded) < 1e-9          # (1135 + 72) > 1200 -> zeroed


def test_wit_unaffected_by_hammers():
    # Wit gets nothing from the climax, so hammer stock must not change its near-cap score.
    chara = _chara(wiz=1135)
    assert abs(_score(_wit_cmd(), chara, _data()) - _score(_wit_cmd(), chara, _data(master=1, artisan=2))) < 1e-9


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
