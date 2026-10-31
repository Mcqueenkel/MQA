"""Colour-weighted spark scoring: the user sets a 0-5 priority per spark colour (blue stat / pink
aptitude / green unique / white skill), and the chooser compares EVERY option it has seen -- the
original roll AND any TP reroll -- keeping the highest scorer. Covers career_bot/core/sparks.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core import sparks

# a tiny stand-in factor_map: id -> {category, stars}
FMAP = {
    "101": {"name": "Speed", "category": "stat", "stars": 3},        # blue 3*
    "102": {"name": "Guts", "category": "stat", "stars": 1},          # blue 1*
    "1101": {"name": "Turf", "category": "aptitude", "stars": 2},     # pink 2*
    "9001": {"name": "Some Unique", "category": "unique", "stars": 2},   # green 2*
    "20001": {"name": "Corner Adept", "category": "skill", "stars": 3},  # white 3*
    "1000101": {"name": "February S.", "category": "race", "stars": 1},  # race -> white 1*
}


def _opt(lottery_id, *factor_ids):
    return {"lottery_id": lottery_id, "factor_info_array": [{"factor_id": f} for f in factor_ids]}


def test_colour_mapping():
    assert sparks.factor_colour(FMAP, 101) == "blue"
    assert sparks.factor_colour(FMAP, 1101) == "pink"
    assert sparks.factor_colour(FMAP, 9001) == "green"
    assert sparks.factor_colour(FMAP, 20001) == "white"
    assert sparks.factor_colour(FMAP, 1000101) == "white"   # race sparks render white too


def test_weights_default_override_and_clamp():
    d = sparks.normalize_weights({})
    assert d == sparks.DEFAULT_WEIGHTS
    w = sparks.normalize_weights({"spark_priority_blue": 5, "spark_priority_white": 0})
    assert w["blue"] == 5 and w["white"] == 0
    clamped = sparks.normalize_weights({"spark_priority_pink": 99, "spark_priority_green": -4})
    assert clamped["pink"] == 5 and clamped["green"] == 0     # 0..5


def test_score_is_weight_times_stars():
    w = {"blue": 2, "pink": 0, "green": 0, "white": 0}
    score, breakdown = sparks.score_option(_opt(1, 101, 102), FMAP, w)
    assert score == 2 * 3 + 2 * 1                      # Speed 3* + Guts 1*
    assert breakdown["blue"] == 4


def test_zero_weight_means_ignored():
    w = {"blue": 0, "pink": 0, "green": 0, "white": 5}
    score, _ = sparks.score_option(_opt(1, 101, 102), FMAP, w)   # blue-only option
    assert score == 0                                            # 0 = don't care at all


def test_pick_best_prefers_the_wanted_colour():
    # want SKILL sparks most -> the white option wins over a fat blue one
    w = sparks.normalize_weights({"spark_priority_white": 5, "spark_priority_blue": 1,
                                  "spark_priority_pink": 0, "spark_priority_green": 0})
    options = [_opt(1, 101, 102), _opt(2, 20001)]     # 1 = blue 3*+1*, 2 = white 3*
    best = sparks.pick_best(options, FMAP, w)
    assert best["lottery_id"] == 2, best


def test_tie_keeps_the_original_roll():
    # an equal-scoring REROLL must never displace the original (listed first)
    w = {"blue": 1, "pink": 1, "green": 1, "white": 1}
    options = [_opt(1, 101), _opt(7, 101)]            # identical value
    assert sparks.pick_best(options, FMAP, w)["lottery_id"] == 1


def test_extract_options_merges_original_and_reroll():
    resp = {"data": {"single_mode_factor_select_common": {
        "factor_select_info_array": [_opt(1, 101)],
        "factor_relottery_info_array": [_opt(9, 20001)],
        "lottery_remain_num": 2,
        "tp_info": {"current_tp": 88},
    }}}
    options, meta = sparks.extract_options(resp)
    assert [o["lottery_id"] for o in options] == [1, 9]     # original THEN reroll
    assert meta["lottery_remain_num"] == 2 and meta["tp_info"]["current_tp"] == 88


def test_extract_options_tolerates_junk():
    assert sparks.extract_options({}) == ([], {})
    assert sparks.extract_options(None) == ([], {})


def test_pick_best_none_when_no_valid_option():
    assert sparks.pick_best([], FMAP, sparks.DEFAULT_WEIGHTS) is None
    assert sparks.pick_best([{"lottery_id": 0}], FMAP, sparks.DEFAULT_WEIGHTS) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_spark_score: OK")
