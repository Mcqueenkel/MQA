"""EventManager ground-truth outcomes DB layer (data/support_event_outcomes.json, GameTora).

The bot previously could NOT know what stats an unseen event choice gives -- it guessed (curated DB,
9 learned events, else blind fallback). This layer scores every option's KNOWN effects with the same
need-aware weights as the learned scorer, so support-card events are answered from ground truth from
career 1. Pure, injected data -- no file/network.

Run: python tests/test_event_outcomes_db.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.events import EventManager  # noqa: E402


def _em(db, overrides=None):
    em = EventManager(os.path.join(os.path.dirname(__file__), "_tmp_eventmgr_nonexistent"))
    em.outcomes = {}                              # no curated entries
    em.choice_outcomes = lambda: {}               # no learned data
    em._read_overrides = lambda: overrides or {}
    em._outcome_db = db                           # inject the ground-truth DB
    return em


def _event(story_id, n):
    return {"story_id": str(story_id),
            "event_contents_info": {"choice_array": [{"select_index": i + 1} for i in range(n)]}}


def test_picks_the_higher_stat_choice():
    db = {"830001001": {"choices": [
        {"n": 1, "effects": [["sp", "+20"]]},              # Speed +20 -> 20.0
        {"n": 2, "effects": [["en", "-10"], ["mo", "-1"]]} # Energy -10, Mood -1 -> strongly negative
    ]}}
    assert _em(db).choose(_event("830001001", 2)) == 0


def test_least_bad_of_two_bad_choices():
    # the DB knows ALL options, so unlike the learned scorer it MAY pick a net-negative option
    # when the alternative is worse (that IS the right move).
    db = {"9": {"choices": [
        {"n": 1, "effects": [["mo", "-1"]]},                 # -12
        {"n": 2, "effects": [["mo", "-1"], ["en", "-20"]]},  # -12 - 32
    ]}}
    assert _em(db).choose(_event("9", 2)) == 0


def test_need_awareness_flips_the_pick_when_energy_low():
    db = {"7": {"choices": [
        {"n": 1, "effects": [["sp", "+25"]]},   # 25.0 flat
        {"n": 2, "effects": [["en", "+20"]]},   # 32 normally; 96 when energy is LOW (1.6*3.0*20)
    ]}}
    # energy fine -> option 2 still wins here (32 > 25), so make stats richer to test the flip
    db2 = {"7": {"choices": [
        {"n": 1, "effects": [["sp", "+25"], ["pt", "+10"]]},  # 38.0
        {"n": 2, "effects": [["en", "+20"]]},                  # 32 normal / 96 low-energy
    ]}}
    healthy = {"vital": 90, "max_vital": 100, "motivation": 4}
    tired = {"vital": 20, "max_vital": 100, "motivation": 4}
    assert _em(db2).choose(_event("7", 2), chara=healthy) == 0   # stats when healthy
    assert _em(db2).choose(_event("7", 2), chara=tired) == 1     # recovery when tired


def test_ties_defer_to_fallback():
    db = {"5": {"choices": [
        {"n": 1, "effects": [["sp", "+10"]]},
        {"n": 2, "effects": [["st", "+10"]]},   # same value -> no information
    ]}}
    # defers -> blind fallback (second choice, index 1)
    assert _em(db).choose(_event("5", 2)) == 1


def test_choice_count_mismatch_defers():
    db = {"6": {"choices": [{"n": 1, "effects": [["sp", "+10"]]}]}}   # DB has 1, live has 2
    assert _em(db).choose(_event("6", 2)) == 1                        # fallback, not a wrong DB pick


def test_user_override_still_beats_the_db():
    db = {"8": {"choices": [
        {"n": 1, "effects": [["sp", "+30"]]},
        {"n": 2, "effects": [["mo", "-1"]]},
    ]}}
    assert _em(db, overrides={"8": 1}).choose(_event("8", 2)) == 1   # user said option 2 -> obey


def _em_with_skills(db, overrides=None):
    # inject a skill index: skill 201661 "Playtime's Over!" -> group 20166 (like _load_skill_index builds)
    em = _em(db, overrides)
    em._skill_id_to_group = {201661: 20166, 201681: 20168, 999999: 99999}
    # keys must match _norm_skill output (lowercase, spaces/punctuation KEPT, ○◎ marks stripped)
    em._name_to_groups = {"playtime's over!": {20166}, "charming looks": {20168}}
    return em


def test_preset_skill_hint_forces_the_choice():
    # THE user's rule: preset picks skill 201661 -> the event choice KNOWN to hint 201661 is taken
    # automatically, even though its other effects (Energy -20) would LOSE the value contest.
    db = {"830070002": {"choices": [
        {"n": 1, "effects": [["in", "+15"], ["bo", "+10", 1074]]},        # nice stats, no wanted hint
        {"n": 2, "effects": [["en", "-20"], ["sk", "+3", 201661]]},       # costs energy, hints the skill
    ]}}
    em = _em_with_skills(db)
    preset = {"learn_skill_list": [["Playtime's Over!"]]}
    healthy = {"vital": 80, "max_vital": 100, "motivation": 4}
    assert em.choose(_event("830070002", 2), chara=healthy, preset=preset) == 1   # forced
    # without the skill in the preset, the value scorer decides instead (stats > energy loss)
    assert em.choose(_event("830070002", 2), chara=healthy, preset={}) == 0


def test_most_wanted_hint_levels_wins_and_unrelated_hints_dont_force():
    db = {"77": {"choices": [
        {"n": 1, "effects": [["sk", "+1", 201661]]},                       # 1 wanted level
        {"n": 2, "effects": [["sk", "+3", 201661], ["mo", "-1"]]},         # 3 wanted levels, mood cost
    ]}}
    em = _em_with_skills(db)
    preset = {"learn_skill_list": [["Playtime's Over!"]]}
    assert em.choose(_event("77", 2), preset=preset) == 1                  # more wanted levels wins
    # hints for skills the build does NOT want never force anything
    db2 = {"78": {"choices": [
        {"n": 1, "effects": [["sp", "+20"]]},
        {"n": 2, "effects": [["sk", "+3", 999999]]},                       # unwanted skill hint
    ]}}
    em2 = _em_with_skills(db2)
    assert em2.choose(_event("78", 2), preset=preset) == 0                 # value scorer decides


def test_critically_low_defers_hint_chase():
    # recovery first: a trainee on fumes must not chase hints -- the need-aware scorer takes over.
    db = {"79": {"choices": [
        {"n": 1, "effects": [["en", "+30"]]},                              # recovery
        {"n": 2, "effects": [["en", "-20"], ["sk", "+3", 201661]]},        # hint at energy cost
    ]}}
    em = _em_with_skills(db)
    preset = {"learn_skill_list": [["Playtime's Over!"]]}
    exhausted = {"vital": 5, "max_vital": 100, "motivation": 1}
    assert em.choose(_event("79", 2), chara=exhausted, preset=preset) == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_event_outcomes_db: OK")
