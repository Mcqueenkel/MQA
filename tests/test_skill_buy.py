"""Skill buying, tier-driven. TWO distinct jobs:

  TIER 0 (learn_skill_tier0)  -- MUST-BUY, bought DURING the run, checked every turn, taken as soon
                                 as SP allows so the skill is active for the races still to come.
  TIER 1+ (learn_skill_list)  -- a PRIORITY ORDER for the career-end dump only; never bought mid-run.

The end dump then spends leftover SP on other buyable skills (skill_dump_leftover, default on -- set
false to buy ONLY the listed/tier skills).

Run:
    python tests/test_skill_buy.py
    python -m pytest tests/test_skill_buy.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.skills import SkillBuyer  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sb():
    return SkillBuyer(ROOT)   # real base_dir so _load() succeeds; buy paths are mocked below


def _state(sp=1000, turn=10):
    return {"data": {"chara_info": {"skill_point": sp, "turn": turn, "skill_array": [], "skill_tips_array": []}}}


# ---- during the run: TIER 0 ONLY, every turn ---------------------------------------------------

TIER0_AND_TIER1 = {"learn_skill_tier0": ["Zero"], "learn_skill_list": [["One"]]}


def _tiered_cand():
    """Mimic what the real _candidates does: only names reachable from _priority_rows(preset)
    survive, so emptying learn_skill_list leaves TIER 0 alone. That is exactly the mechanism
    _buy_tier0_now relies on, so the mock has to honour it or the test proves nothing."""
    t0 = {"skill_id": 1, "name": "Zero", "cost": 300, "priority": 0}
    t1 = {"skill_id": 2, "name": "One", "cost": 300, "priority": 1}

    def cand(chara, preset):
        out = []
        if preset.get("learn_skill_tier0"):
            out.append(dict(t0))
        if any(row for row in (preset.get("learn_skill_list") or [])):
            out.append(dict(t1))
        return out
    return cand


def test_tier0_bought_on_any_turn_not_a_cadence():
    """The whole point: a tier-0 skill is taken the moment SP covers it, so it is ACTIVE for the
    races still to come -- not parked until turn 24/48/72 or the finish dump."""
    for turn in (1, 7, 23, 30, 55, 71):                    # deliberately not multiples of 24
        sb = _sb()
        sb._candidates = _tiered_cand()
        captured = {}
        sb._buy_batch = lambda client, state, selected, t, **_kw: (captured.update(sel=selected) or (state, len(selected)))
        _, bought = sb.buy(None, _state(sp=1000, turn=turn), TIER0_AND_TIER1, force=False)
        assert bought == 1, (turn, bought)
        assert [c["skill_id"] for c in captured["sel"]] == [1], turn   # tier 0 only, never tier 1


def test_tier1_is_never_bought_during_the_run():
    """learn_skill_list is an end-of-career PRIORITY ORDER, not an in-run shopping list."""
    sb = _sb()
    sb._candidates = _tiered_cand()
    sb._buy_batch = lambda client, state, selected, turn, **_kw: (state, len(selected))
    # Plenty of SP for both, but only tier 0 may be taken mid-run.
    _, bought = sb.buy(None, _state(sp=100000, turn=40), TIER0_AND_TIER1, force=False)
    assert bought == 1
    assert [c["skill_id"] for c in sb.last_selected] == [1]


def test_no_tier0_means_no_in_run_buying():
    sb = _sb()
    sb._candidates = _tiered_cand()
    _, bought = sb.buy(None, _state(sp=100000, turn=40), {"learn_skill_list": [["One"]]}, force=False)
    assert bought == 0 and sb.last_result.get("skip") == "no_tier0"


def test_tier0_waits_for_sp_rather_than_part_buying_beyond_it():
    sb = _sb()
    sb._candidates = lambda chara, preset: [
        {"skill_id": 1, "name": "Zero", "cost": 300, "priority": 0},
        {"skill_id": 2, "name": "Zed", "cost": 300, "priority": 0}]
    captured = {}
    sb._buy_batch = lambda client, state, selected, t, **_kw: (captured.update(sel=selected) or (state, len(selected)))
    _, bought = sb.buy(None, _state(sp=350, turn=9), {"learn_skill_tier0": ["Zero", "Zed"]}, force=False)
    assert bought == 1 and [c["skill_id"] for c in captured["sel"]] == [1]   # 2nd waits for SP


def test_a_refused_tier0_skill_is_not_retried_every_turn():
    """REGRESSION (live 2026-07-29): tier-0 buying every turn re-attempted a skill the server keeps
    answering 205 to, because failed_this_turn is wiped by _set_turn on each new turn AND by
    reset_scoped_failures on the post-error reload. That is one doomed gain_skills per turn, which
    tripped the circuit breaker ("6 server errors within 90s") and auto-backed-off mid-career."""
    sb = _sb()
    sb._candidates = lambda chara, preset: [{"skill_id": 1, "name": "Zero", "cost": 100, "priority": 0}]
    calls = []

    def refuse(client, state, selected, turn, retry_205=3):
        calls.append(turn)
        return state, 0                                    # server says no, every time
    sb._buy_batch = refuse

    preset = {"learn_skill_tier0": ["Zero"]}
    for turn in range(1, 40):
        sb.reset_scoped_failures()                         # the reload the runner does after a failure
        sb.buy(None, _state(sp=1000, turn=turn), preset, force=False)
    assert len(calls) == 1, f"retried the refused skill {len(calls)}x (must latch after the first)"
    assert sb.last_result.get("skip") == "tier0_none_available"
    assert sb.failed_this_career == {1}                    # latch survived all 39 reloads


def test_mid_run_buy_does_not_replay_a_205():
    """A mid-run 205 means 'not sellable right now' -- replaying it 3x just burns circuit-breaker
    budget. The career-end dump keeps its retries (that 205 is usually a stale SID)."""
    sb = _sb()
    sb._candidates = lambda chara, preset: [{"skill_id": 1, "name": "Zero", "cost": 100, "priority": 0}]
    seen = {}
    sb._buy_batch = lambda client, state, selected, turn, retry_205=3: (seen.update(r=retry_205), (state, 1))[1]
    sb.buy(None, _state(sp=1000, turn=9), {"learn_skill_tier0": ["Zero"]}, force=False)
    assert seen["r"] == 0, seen


def test_tier0_listed_but_none_available_buys_nothing():
    sb = _sb()
    sb._candidates = lambda chara, preset: []              # all already owned / unhinted
    _, bought = sb.buy(None, _state(turn=24), {"learn_skill_tier0": ["Zero"]}, force=False)
    assert bought == 0 and sb.last_result.get("skip") == "tier0_none_available"


# ---- career-end dump: listed/tier first, then spend leftover SP ---------------------------------

def _listed_plus_extra_cand():
    listed = [{"skill_id": 1, "name": "A", "cost": 100, "priority": 0}]
    extra = [{"skill_id": 9, "name": "Leftover", "cost": 100, "priority": 999}]

    def cand(chara, preset):
        return [dict(c) for c in listed] if preset.get("learn_skill_only_user_provided") \
            else [dict(c) for c in (listed + extra)]
    return cand


def test_end_dump_spends_leftover_by_default():
    sb = _sb()
    sb._candidates = _listed_plus_extra_cand()
    sb._buy_batch = lambda client, state, selected, turn, **_kw: (state, len(selected))
    sb.buy(None, _state(sp=99999, turn=78), {}, force=True)
    ids = [c["skill_id"] for c in sb.last_candidates]
    assert ids[0] == 1 and 9 in ids                       # listed first, leftover appended


def test_end_dump_only_listed_when_opted_out():
    sb = _sb()
    sb._candidates = _listed_plus_extra_cand()
    sb._buy_batch = lambda client, state, selected, turn, **_kw: (state, len(selected))
    sb.buy(None, _state(sp=99999, turn=78), {"skill_dump_leftover": False}, force=True)
    assert [c["skill_id"] for c in sb.last_candidates] == [1]   # only the listed/tier skill


def test_end_dump_empty_list_still_spends_leftover():
    sb = _sb()
    extra = [{"skill_id": 9, "name": "Leftover", "cost": 100, "priority": 999}]
    sb._candidates = lambda chara, preset: (
        [] if preset.get("learn_skill_only_user_provided") else [dict(c) for c in extra])
    sb._buy_batch = lambda client, state, selected, turn, **_kw: (state, len(selected))
    _, bought = sb.buy(None, _state(sp=1000, turn=78), {}, force=True)
    assert bought == 1 and [c["skill_id"] for c in sb.last_candidates] == [9]


# ---- after the listed skills: GOLD skills, then everything else (user's order, 2026-10-20) ------

TOP_RUNNER, LEADERS_PRIDE = 201271, 201272        # real Front Runner gold and its white


def _gold_order_sb(extra):
    sb = _sb()
    listed = [{"skill_id": 1, "name": "Listed", "cost": 100, "priority": 0}]
    sb._candidates = lambda chara, preset: [dict(c) for c in listed] if preset.get(
        "learn_skill_only_user_provided") else [dict(c) for c in listed + extra]
    sb._buy_batch = lambda client, state, selected, turn, **_kw: (state, len(selected))
    return sb


def test_golds_come_right_after_the_listed_skills():
    # The leftover sort ranks an unlisted ○ (priority 500) and a cheap white (best grade per SP) above
    # a gold; Top Runner sat unbought in 7 of 10 careers that way.
    sb = _gold_order_sb([
        {"skill_id": 9, "name": "Right-Handed ○", "cost": 80, "priority": 500},
        {"skill_id": 8, "name": "White", "cost": 80, "priority": 999},
        {"skill_id": TOP_RUNNER, "name": "Top Runner", "cost": 160, "priority": 999},
        {"skill_id": 200571, "name": "Race Planner", "cost": 160, "priority": 999, "fits": False}])
    sb.buy(None, _state(sp=99999, turn=78), {}, force=True)
    assert [c["skill_id"] for c in sb.last_candidates] == [1, TOP_RUNNER, 9, 8, 200571]
    sb.buy(None, _state(sp=260, turn=78), {}, force=True)
    assert [c["skill_id"] for c in sb.last_selected] == [1, TOP_RUNNER]   # the gold before the ○


def test_a_gold_whose_white_is_already_in_the_batch_costs_only_the_gold():
    # Top Runner's estimate bundles Leader's Pride; buying the listed Leader's Pride first must not
    # charge it a second time (342 -> 162), and the white is not sent twice.
    sb = _sb()
    white = sb._estimate_cost({"skill_id": LEADERS_PRIDE, "hint_level": 0})
    listed = [{"skill_id": LEADERS_PRIDE, "name": "Leader's Pride", "cost": white, "priority": 0}]
    gold = {"skill_id": TOP_RUNNER, "name": "Top Runner", "cost": 162 + white, "priority": 999,
            "bundled_skill_ids": [LEADERS_PRIDE]}
    sb._candidates = lambda chara, preset: [dict(c) for c in listed] + ([] if preset.get(
        "learn_skill_only_user_provided") else [dict(gold)])
    sb._buy_batch = lambda client, state, selected, turn, **_kw: (state, len(selected))
    sb.buy(None, _state(sp=white + 162, turn=78), {}, force=True)
    got = {c["skill_id"]: c for c in sb.last_selected}
    assert set(got) == {LEADERS_PRIDE, TOP_RUNNER}, got
    assert got[TOP_RUNNER]["cost"] == 162 and got[TOP_RUNNER]["bundled_skill_ids"] == []


def test_a_white_already_bundled_with_a_gold_is_not_bought_again():
    sb = _gold_order_sb([
        {"skill_id": 200331, "name": "Professor of Curvature", "cost": 342, "priority": 999,
         "bundled_skill_ids": [200332]},
        {"skill_id": 200332, "name": "Corner Adept ○", "cost": 162, "priority": 500}])
    sb.buy(None, _state(sp=99999, turn=78), {}, force=True)
    assert [c["skill_id"] for c in sb.last_selected] == [1, 200331]


# ---- TIER 0 still outranks every numbered tier in the end-of-career ordering -------------------

def test_tier0_ranks_above_listed_tiers():
    sb = _sb()
    preset = {"learn_skill_tier0": ["Zero"], "learn_skill_list": [["One"], ["Two"]]}
    pri = sb._priority(sb._priority_rows(preset))
    assert pri["zero"] == 0 and pri["one"] == 1 and pri["two"] == 2


def test_end_dump_still_buys_both_tiers_tier0_first():
    sb = _sb()
    sb._candidates = _tiered_cand()
    sb._buy_batch = lambda client, state, selected, turn, **_kw: (state, len(selected))
    _, bought = sb.buy(None, _state(sp=100000, turn=78), TIER0_AND_TIER1, force=True)
    assert bought == 2                                     # tier 1 finally lands here...
    assert [c["skill_id"] for c in sb.last_selected] == [1, 2]   # ...behind tier 0


# --- a skill bought this career is NEVER re-sent -------------------------------------------------

def test_bought_skills_are_not_re_sent_in_a_later_pass():
    """REGRESSION (live career_log_20260730_232514, t78): the end dump bought 14 skills (rc=1), then
    _spend_remaining_sp ran another pass and re-sent THE SAME 14 -- the server 205s them because they
    are already owned. _owns_equal_or_better cannot catch this: gain_skills returns no refreshed
    skill_array, so the just-bought skills still read as unowned."""
    sb = _sb()
    tips = [{"group_id": 2001, "rarity": 1, "level": 1}]
    chara = {"skill_point": 9999, "turn": 78, "skill_array": [], "skill_tips_array": tips}
    state = {"data": {"chara_info": chara}}
    cands = [{"skill_id": 200101, "name": "A", "cost": 100, "priority": 0},
             {"skill_id": 200201, "name": "B", "cost": 100, "priority": 0}]
    sb._candidates = lambda c, preset: [dict(x) for x in cands]   # server state never refreshes
    sb.group_to_skill_ids = {2001: [200101, 200201]}
    chara["skill_tips_array"] = [{"group_id": 2001, "rarity": 1, "level": 1}]
    sent = []
    sb._merge_state = lambda st, res: st

    def fake_gain(payload, turn, retry_205=3):
        sent.append([p["skill_id"] for p in payload])
        return {"data": {}}
    client = type("C", (), {"gain_skills": staticmethod(fake_gain)})()

    # Make both candidates pass preflight: they must be in the tips-derived valid set.
    sb.buy(client, state, {}, force=True)
    first = list(sent)
    sb.buy(client, state, {}, force=True)          # the _spend_remaining_sp second pass
    assert len(first) == 1 and first[0], first
    assert len(sent) == 1, f"re-sent an already-bought batch: {sent}"
    assert sb.last_result.get("skip") == "preflight_failed", sb.last_result
    for sid in first[0]:
        assert sid in sb.bought_this_career


def test_bought_latch_survives_a_recovery_reload():
    sb = _sb()
    sb.bought_this_career.add(200101)
    sb.reset_scoped_failures()          # the post-error reload
    assert 200101 in sb.bought_this_career, "reload must not un-latch a landed purchase"


# ---- a listed skill for another running style never fires: treat it as unlisted (2026-10-27) ---

def test_a_listed_skill_for_another_running_style_is_treated_as_unlisted():
    # A Front Runner preset on a Pace Chaser bought 3-5 Front Runner skills per career that never activate.
    sb = _sb()
    fr = 201252                                           # Front Runner Corners ○, tagged Front Runner
    tip = {"group_id": sb.skill_to_group_id.get(fr, fr // 10), "rarity": 1, "level": 0}
    chara = {"skill_array": [], "skill_tips_array": [tip]}
    preset = {"learn_skill_list": [["Front Runner Corners ○"]]}
    as_front = sb._candidates(chara, {**preset, "running_style": 1})
    as_pace = sb._candidates(chara, {**preset, "running_style": 2})
    assert [(c["skill_id"], c["priority"]) for c in as_front] == [(fr, 0)]
    assert [(c["skill_id"], c["priority"], c["fits"]) for c in as_pace] == [(fr, 999, False)]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("skill buy OK")
