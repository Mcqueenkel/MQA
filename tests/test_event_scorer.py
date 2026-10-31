"""Unit tests for the learned event-choice value scorer in EventManager.

The bot already records the real stat deltas of every event choice it makes
(record_choice_outcome -> event_choice_outcomes.json). These assert that choose()
now WIRES that learned data back into the pick -- ranking options by observed value
instead of the old blind "pick option 1" -- while still deferring to user overrides
and the curated good/bad DB. No game/files needed: learned data is injected.

Run:
    python tests/test_event_scorer.py
    python -m pytest tests/test_event_scorer.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.events import EventManager  # noqa: E402


def _em(learned, outcomes=None, overrides=None):
    em = EventManager(os.path.join(os.path.dirname(__file__), "_tmp_eventmgr_nonexistent"))
    em.outcomes = outcomes or {}                 # curated good/bad DB (data/event_outcomes.json)
    em.choice_outcomes = lambda: learned         # injected learned averages
    em._read_overrides = lambda: overrides or {}  # user manual overrides
    return em


def _event(story_id, selects):
    return {"story_id": str(story_id),
            "event_contents_info": {"choice_array": [{"select_index": s} for s in selects]}}


def test_learned_scorer_beats_blind_fallback():
    # option 0 (select 1) observed +30 speed vs option 1 (select 2) +10 -> pick 0, NOT blind 1.
    learned = {"123": {"1": {"n": 3, "avg": {"speed": 30}}, "2": {"n": 3, "avg": {"speed": 10}}}}
    assert _em(learned).choose(_event("123", [1, 2])) == 0


def test_learned_scorer_picks_higher_value():
    learned = {"123": {"1": {"n": 2, "avg": {"speed": 10}}, "2": {"n": 2, "avg": {"speed": 40}}}}
    assert _em(learned).choose(_event("123", [1, 2])) == 1


def test_motivation_weighted_heavily():
    # +1 motivation (weight 12) should beat +5 speed (weight 5).
    learned = {"123": {"1": {"n": 2, "avg": {"speed": 5}}, "2": {"n": 2, "avg": {"motivation": 1}}}}
    assert _em(learned).choose(_event("123", [1, 2])) == 1


def test_skill_point_and_energy_weighted_above_stat():
    # +10 skill_point (w1.3=13) + nothing vs +10 speed (w1.0=10) -> SP option wins.
    learned = {"123": {"1": {"n": 2, "avg": {"speed": 10}}, "2": {"n": 2, "avg": {"skill_point": 10}}}}
    assert _em(learned).choose(_event("123", [1, 2])) == 1


def test_insufficient_samples_defers_to_fallback():
    # n=1 < MIN_OUTCOME_SAMPLES -> scorer abstains -> blind fallback returns index 1.
    learned = {"123": {"1": {"n": 1, "avg": {"speed": 30}}, "2": {"n": 1, "avg": {"speed": 10}}}}
    assert _em(learned).choose(_event("123", [1, 2])) == 1


def test_all_negative_defers():
    learned = {"123": {"1": {"n": 3, "avg": {"speed": -10}}, "2": {"n": 3, "avg": {"vital": -20}}}}
    em = _em(learned)
    assert em._score_choices_by_outcome("123", [{"select_index": 1}, {"select_index": 2}]) is None
    assert em.choose(_event("123", [1, 2])) == 1  # fallback


def test_no_learned_data_defers():
    assert _em({})._score_choices_by_outcome("123", [{"select_index": 1}]) is None


def test_user_override_still_wins_over_learned():
    learned = {"123": {"1": {"n": 5, "avg": {"speed": 99}}, "2": {"n": 5, "avg": {"speed": 1}}}}
    assert _em(learned, overrides={"123": 1}).choose(_event("123", [1, 2])) == 1


def test_curated_good_db_still_wins_over_learned():
    # DB marks select_index 2 ("good") -> index 1; learned favors index 0. DB takes priority.
    learned = {"123": {"1": {"n": 5, "avg": {"speed": 99}}}}
    outcomes = {"123": {"outcomes": {"2": "good"}}}
    assert _em(learned, outcomes=outcomes).choose(_event("123", [1, 2])) == 1


def test_low_energy_prefers_recovery_option():
    # option 0 (+20 speed) normally beats option 1 (+10 vital -> 16); under LOW energy the
    # vital weight triples so the recovery option wins.
    learned = {"123": {"1": {"n": 3, "avg": {"speed": 20}}, "2": {"n": 3, "avg": {"vital": 10}}}}
    em = _em(learned)
    fine = {"vital": 90, "max_vital": 100, "motivation": 4}
    low = {"vital": 30, "max_vital": 100, "motivation": 4}
    assert em.choose(_event("123", [1, 2]), chara=fine) == 0   # not low -> stat option
    assert em.choose(_event("123", [1, 2]), chara=low) == 1    # low energy -> recovery option


def test_low_mood_prefers_mood_option():
    # option 0 (+20 speed) normally beats option 1 (+1 motivation -> 12); LOW mood triples the
    # motivation weight (-> 36) so the mood option wins.
    learned = {"123": {"1": {"n": 3, "avg": {"speed": 20}}, "2": {"n": 3, "avg": {"motivation": 1}}}}
    em = _em(learned)
    fine = {"vital": 90, "max_vital": 100, "motivation": 4}
    low = {"vital": 90, "max_vital": 100, "motivation": 2}
    assert em.choose(_event("123", [1, 2]), chara=fine) == 0   # good mood -> stat option
    assert em.choose(_event("123", [1, 2]), chara=low) == 1    # low mood -> mood option


def test_chara_none_uses_base_weights():
    # No chara -> base weights, behavior identical to pre-need-awareness (stat option wins).
    learned = {"123": {"1": {"n": 3, "avg": {"speed": 20}}, "2": {"n": 3, "avg": {"vital": 10}}}}
    assert _em(learned).choose(_event("123", [1, 2])) == 0


def test_hinted_groups_diff():
    # _hinted_groups returns skill groups whose hint level ROSE (or are new) across the event.
    em = _em({})
    before = {"skill_tips_array": [{"group_id": 100, "level": 1}, {"group_id": 200, "level": 2}]}
    after = {"skill_tips_array": [{"group_id": 100, "level": 2},   # rose 1->2
                                  {"group_id": 200, "level": 2},   # unchanged
                                  {"group_id": 300, "level": 1}]}  # new
    assert set(em._hinted_groups(before, after)) == {100, 300}


def test_wanted_groups_normalizes_marks():
    em = _em({})
    em._name_to_groups = {"front runner corners": {501}}
    groups = em._wanted_skill_groups({"learn_skill_list": [["Front Runner Corners ◎"]]})
    assert 501 in groups


def test_build_relevant_hint_tips_the_pick():
    # option 1 has the higher raw stat, but option 0 hints a skill the build wants -> the
    # build-hint bonus flips the pick to option 0.
    learned = {"123": {
        "1": {"n": 3, "avg": {"speed": 10}, "hints": [500]},   # build-wanted hint
        "2": {"n": 3, "avg": {"speed": 15}, "hints": [999]},   # higher stat, irrelevant hint
    }}
    em = _em(learned)
    em._name_to_groups = {"front runner savvy": {500}}
    fine = {"vital": 90, "max_vital": 100, "motivation": 4}
    assert em.choose(_event("123", [1, 2]), chara=fine) == 1  # no preset -> higher stat wins
    assert em.choose(_event("123", [1, 2]), chara=fine,
                     preset={"learn_skill_list": [["Front Runner Savvy"]]}) == 0  # build hint wins


def test_energy_need_outweighs_hint_bonus():
    # Low energy must still win over a build-relevant hint option (energy/mood first, else build).
    learned = {"123": {
        "1": {"n": 3, "avg": {"vital": 15}, "hints": []},      # recovery
        "2": {"n": 3, "avg": {"speed": 10}, "hints": [500]},   # build hint
    }}
    em = _em(learned)
    em._name_to_groups = {"front runner savvy": {500}}
    low = {"vital": 25, "max_vital": 100, "motivation": 4}
    assert em.choose(_event("123", [1, 2]), chara=low,
                     preset={"learn_skill_list": [["Front Runner Savvy"]]}) == 0  # recovery wins


def test_tip_levels_never_raises_on_malformed():
    # A corrupt skill_tips_array must never raise (else record_choice_outcome would drop the
    # whole stat observation). Every bad shape returns {} cleanly.
    em = _em({})
    for bad in [None, "string", 5, {}, {"skill_tips_array": "abc"}, {"skill_tips_array": 5},
                {"skill_tips_array": [None, 5, "x"]}]:
        assert em._tip_levels(bad) == {}
    # valid tips among garbage are still extracted
    assert em._tip_levels({"skill_tips_array": [None, "x", {"group_id": 7, "level": 2}]}) == {7: 2}


def test_hinted_groups_malformed_after_is_safe():
    em = _em({})
    before = {"skill_tips_array": [{"group_id": 1, "level": 1}]}
    assert em._hinted_groups(before, {"skill_tips_array": "garbage"}) == []  # no raise, no hints


def test_hint_bonus_is_capped_below_a_real_need():
    # 5 build-wanted hints on option 0, but the cap keeps the bonus from overpowering a genuine
    # low-mood recovery on option 1.
    learned = {"123": {
        "1": {"n": 3, "avg": {"speed": 10}, "hints": [1, 2, 3, 4, 5]},
        "2": {"n": 3, "avg": {"motivation": 1}, "hints": []},
    }}
    em = _em(learned)
    em._name_to_groups = {f"s{i}": {i} for i in range(1, 6)}
    preset = {"learn_skill_list": [[f"s{i}" for i in range(1, 6)]]}
    low_mood = {"vital": 90, "max_vital": 100, "motivation": 2}
    # option 0: 10 + min(5,2)*8 = 26 ; option 1 (low mood): 1*12*3 = 36 -> mood recovery wins
    assert em.choose(_event("123", [1, 2]), chara=low_mood, preset=preset) == 1


def test_build_hint_is_forced_over_higher_value():
    # option 0 has higher stat value; option 1 hints a build-wanted skill (Groundwork). The
    # must-pick takes option 1 -- above the value scorer.
    learned = {"123": {"1": {"n": 3, "avg": {"speed": 50}},
                       "2": {"n": 3, "avg": {"speed": 5}, "hints": [500]}}}
    em = _em(learned)
    em._name_to_groups = {"groundwork": {500}}
    fine = {"vital": 90, "max_vital": 100, "motivation": 4}
    assert em.choose(_event("123", [1, 2]), chara=fine) == 0  # no build -> value scorer picks 0
    assert em.choose(_event("123", [1, 2]), chara=fine,
                     preset={"learn_skill_list": [["Groundwork"]]}) == 1  # build hint forced


def test_build_hint_defers_when_critically_low():
    # critically low energy -> recovery (option 0, +vital) comes first; the hint is NOT forced.
    learned = {"123": {"1": {"n": 3, "avg": {"vital": 30}},
                       "2": {"n": 3, "avg": {"speed": 5}, "hints": [500]}}}
    em = _em(learned)
    em._name_to_groups = {"groundwork": {500}}
    low = {"vital": 20, "max_vital": 100, "motivation": 4}
    assert em.choose(_event("123", [1, 2]), chara=low,
                     preset={"learn_skill_list": [["Groundwork"]]}) == 0


def test_build_hint_skipped_when_no_recorded_hint():
    learned = {"123": {"1": {"n": 3, "avg": {"speed": 50}}, "2": {"n": 3, "avg": {"speed": 5}}}}
    em = _em(learned)
    em._name_to_groups = {"groundwork": {500}}
    fine = {"vital": 90, "max_vital": 100, "motivation": 4}
    # nothing has a recorded Groundwork hint -> falls through to the value scorer (option 0)
    assert em.choose(_event("123", [1, 2]), chara=fine,
                     preset={"learn_skill_list": [["Groundwork"]]}) == 0


def test_build_hint_override_still_wins():
    learned = {"123": {"1": {"n": 3, "avg": {"speed": 5}, "hints": [500]}, "2": {"n": 3, "avg": {"speed": 5}}}}
    em = _em(learned, overrides={"123": 1})  # user forces option 1 (index 1)
    em._name_to_groups = {"groundwork": {500}}
    # option 0 hints the build skill (would be forced), but the manual override (index 1) wins
    assert em.choose(_event("123", [1, 2]), chara={"vital": 90, "max_vital": 100, "motivation": 4},
                     preset={"learn_skill_list": [["Groundwork"]]}) == 1


def test_malformed_learned_data_never_crashes():
    # Corrupt/hand-edited JSON shapes that previously crashed the scoring loop must now be
    # skipped (defer to fallback), never raise into the career loop.
    bad_shapes = [
        {"123": {"1": {"n": 3, "avg": {"speed": None}}}},        # float(None) -> TypeError
        {"123": {"1": {"n": 3, "avg": [1, 2, 3]}}},              # list.get -> AttributeError
        {"123": {"1": "not-a-dict"}},                            # str.get -> AttributeError
        {"123": {"1": {"n": "lots", "avg": {"speed": 5}}}},      # int('lots') -> ValueError
        {"123": {"1": {"n": 3, "avg": {"speed": "lots"}}}},      # float('lots') -> ValueError
    ]
    for learned in bad_shapes:
        em = _em(learned)
        # must not raise; with no usable option it defers -> blind fallback index 1
        assert em._score_choices_by_outcome("123", [{"select_index": 1}, {"select_index": 2}]) is None
        assert em.choose(_event("123", [1, 2])) == 1


def test_one_bad_entry_does_not_sink_a_good_one():
    # A malformed option 0 must be skipped while a valid option 1 still scores and wins.
    learned = {"123": {"1": {"n": 3, "avg": {"speed": None}},   # malformed -> skipped
                       "2": {"n": 3, "avg": {"speed": 30}}}}    # valid, positive
    assert _em(learned).choose(_event("123", [1, 2])) == 1


def test_unity_team_name_always_picks_team_carrot():
    # Aoharu team-name events: always take the BOTTOM option ("Team Carrot"), NOT the blind
    # fallback (middle). Both intro story_ids are handled; the deck-suggested names shuffle above it.
    for sid in ("501041101", "501041102"):
        # note: these events send select_index=1 for all 3 options -> pick must be by POSITION.
        assert _em({}).choose(_event(sid, [1, 1, 1])) == 2


def test_unity_team_name_override_still_wins():
    # A manual override for the team-name event beats the forced Team-Carrot rule.
    em = _em({}, overrides={"501041101": 0})
    assert em.choose(_event("501041101", [1, 1, 1])) == 0


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
