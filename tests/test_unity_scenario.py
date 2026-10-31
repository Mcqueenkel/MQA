"""Offline unit tests for scenario 2 (Team / "Unity Cup") support.

Pure, injected-data tests (no game/network), matching the tests/ convention. They cover the
four pieces that must be right for a team career to play and LOOP:
  1. namespace routing: single_mode_free/* -> single_mode_team/* only for scenario 2, start excepted.
  2. close-out: team must NOT call change_nickname (finish alone releases the slot) -- getting this
     wrong reintroduces the finished-but-unreleased 102 loop.
  3. cup-turn detection: emit team_race only on a cup turn where the server offers it.
  4. reward-event detection for the get_choice_reward follow-up.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uma_api.client import UmaClient
from career_bot.scenarios.unity import UnityStrategy
from career_bot.scenarios.unity import UnityScenario
from career_bot.scenarios.mant import MantStrategy
from career_bot.runner import CareerRunner, STRATEGIES, resolve_scenario_id
from career_bot.core.races import RacePlanner


class _Client:
    def __init__(self, scenario):
        self.current_scenario_id = scenario


def test_scenario_follows_live_career_not_preset():
    # The live-career fix: a Unity career (client pinned scenario 2) picks UnityStrategy even when
    # the preset has no scenario_id (the Oguri-preset case that defaulted to MANT and desynced).
    assert resolve_scenario_id(_Client(2), {}) == 2
    assert resolve_scenario_id(_Client(2), {"scenario_id": 4}) == 2   # live overrides preset
    assert resolve_scenario_id(_Client(4), {}) == 4                   # MANT career unaffected
    # unknown/None live scenario -> fall back to preset, then MANT
    assert resolve_scenario_id(_Client(None), {"scenario_id": 2}) == 2
    assert resolve_scenario_id(_Client(None), {}) == 4
    assert resolve_scenario_id(_Client(99), {}) == 4                  # live scenario w/o a strategy
    assert resolve_scenario_id(None, {"scenario_id": 2}) == 2         # no client
    assert STRATEGIES[resolve_scenario_id(_Client(2), {})] is UnityStrategy


def test_namespace_routing():
    r = UmaClient._route_ep
    # scenario 2: career calls flip to single_mode_team/*
    assert r("single_mode_free/exec_command", 2) == "single_mode_team/exec_command"
    assert r("single_mode_free/check_event", 2) == "single_mode_team/check_event"
    assert r("single_mode_free/finish", 2) == "single_mode_team/finish"
    assert r("single_mode_free/load", 2) == "single_mode_team/load"
    # start IS namespaced for scenario 2 -- Unity's career start is single_mode_team/start (verified
    # rc=1 in capture 20260703_233031); sending single_mode_free/start 205'd.
    assert r("single_mode_free/start", 2) == "single_mode_team/start"
    assert r("single_mode_free/start", 4) == "single_mode_free/start"  # MANT start stays free
    # scenario 1 (URA): career calls flip to the PLAIN single_mode/* namespace (the original
    # scenario keeps the original unsuffixed prefix -- per the working "new api bot" URA fork)
    assert r("single_mode_free/exec_command", 1) == "single_mode/exec_command"
    assert r("single_mode_free/load", 1) == "single_mode/load"
    assert r("single_mode_free/start", 1) == "single_mode/start"
    assert r("single_mode_free/factor_select", 1) == "single_mode/factor_select"
    # non-single_mode endpoints pass through
    assert r("trained_chara/change_nickname", 2) == "trained_chara/change_nickname"
    assert r("friend/search", 2) == "friend/search"
    assert r("trained_chara/change_nickname", 1) == "trained_chara/change_nickname"
    # other scenarios are untouched
    assert r("single_mode_free/exec_command", 4) == "single_mode_free/exec_command"
    assert r("single_mode_free/exec_command", None) == "single_mode_free/exec_command"


class _FakeClient:
    """Records close-out calls without touching the network."""
    def __init__(self, scenario_id):
        self.current_scenario_id = scenario_id
        self.last_friend_viewer_id = 0
        self.calls = []

    def load_career(self):
        self.calls.append("load")
        return {}

    def call(self, ep, args=None, **kw):
        self.calls.append(ep)
        return {}

    def factor_select(self, current_turn=None, skill_id_array=None):
        self.calls.append("factor_select")
        return {"data": {"single_mode_finish_common": {"trained_chara_id": 1452}}}

    def finish_career(self, current_turn, is_force_delete=False, factor_lottery_id=1,
                      target_trained_chara_id=None):
        self.calls.append("finish_career")
        return {"data": {"trained_chara_info": {"trained_chara_id": 1452}}}

    def change_nickname(self, tcid, nickname_id=180):
        self.calls.append("change_nickname")

    def friend_search(self, vid):
        self.calls.append("friend_search")


def test_close_out_team_selects_factors_then_names_trainee():
    # Scenario 2 (Team/Unity) close-out per authoritative capture 20260706_101235:
    #   factor_select{current_turn} -> finish{factor_lottery_id} -> change_nickname{nickname_id:154}.
    # It runs factor_select as ONE current_turn call (NOT the free-mode open{}+confirm pair), then MUST
    # call change_nickname -- the slot-RELEASE step. The older "team skips factor_select" belief came from
    # incomplete captures and left the finish/slot wedged (finish referenced an unopened lottery).
    team = _FakeClient(scenario_id=2)
    UmaClient.close_career(team, current_turn=78)
    assert "finish_career" in team.calls, team.calls
    assert "factor_select" in team.calls, team.calls                   # the single current_turn call
    assert "single_mode_free/factor_select" not in team.calls, team.calls  # NOT the free-mode open{}
    assert "change_nickname" in team.calls, team.calls                 # RELEASES the team slot
    # ordering: factor_select must precede finish (finish consumes its lottery_id)
    assert team.calls.index("factor_select") < team.calls.index("finish_career"), team.calls


def test_close_out_mant_uses_the_single_factor_select_and_its_spark_pick():
    # MANT (scenario 4) used to send an open{} first: it answered 102 in 1,650/1,650 MANT careers, the
    # confirm then 208'd, and the spark chooser never ran (lottery 1 every time). Now: one current_turn
    # call whose options feed the chooser, then finish with the chosen lottery, then the release.
    mant = _FakeClient(scenario_id=4)
    opts = {"data": {"single_mode_factor_select_common": {"factor_select_info_array": [
        {"lottery_id": 1}, {"lottery_id": 2}]}}}
    mant.factor_select = lambda current_turn=None, skill_id_array=None: mant.calls.append("factor_select") or opts
    chosen = {}
    real_finish = mant.finish_career
    mant.finish_career = lambda **kw: chosen.update(kw) or real_finish(**kw)
    UmaClient.close_career(mant, current_turn=78, factor_chooser=lambda resp: 2)
    assert "single_mode_free/factor_select" not in mant.calls, mant.calls   # no open{} any more
    assert mant.calls.count("factor_select") == 1, mant.calls
    assert chosen["factor_lottery_id"] == 2                                 # the chooser's pick is used
    assert "change_nickname" in mant.calls, mant.calls


def test_close_out_ura_uses_single_factor_select():
    # URA (scenario 1) closes like the working fork: ONE factor_select{current_turn} (routed to
    # single_mode/factor_select), NOT MANT's free-mode open{} + confirm pair -- then finish and the
    # 1.32.8 slot-release change_nickname (generic nickname 92 for URA).
    ura = _FakeClient(scenario_id=1)
    UmaClient.close_career(ura, current_turn=78)
    assert "factor_select" in ura.calls, ura.calls                       # the single current_turn call
    assert "single_mode_free/factor_select" not in ura.calls, ura.calls  # NOT the free-mode open
    assert "finish_career" in ura.calls, ura.calls
    assert "change_nickname" in ura.calls, ura.calls
    assert ura.calls.index("factor_select") < ura.calls.index("finish_career"), ura.calls


def test_unity_goal_races_are_mandatory():
    # Unity goal races are mandatory (like URA): the train-vs-race gate must never skip a chosen race.
    strat = UnityStrategy(race_planner=None)
    assert strat._train_outvalues_race({}, {}, {}) is False                       # default forces races
    assert strat._train_outvalues_race({}, {}, {"unity_force_races": True}) is False


def test_cup_turn_detection():
    avail = UnityStrategy._cup_race_available
    tds = {"team_info": {}}
    train_cmds = {"command_info_array": [{"command_type": 1, "is_enable": 1}]}  # still present at cup
    # cup: playing_state 7 (auto-fill / opponent-select) with team_data_set -> cup offered, even
    # though the game STILL returns enabled training commands in that state (the live-capture gotcha)
    assert avail({"team_data_set": tds, "chara_info": {"playing_state": 7}, "home_info": train_cmds}) is True
    # the team race drives ps 7 -> 8 -> 9; 8 and 9 (seen on a resume / mid-race re-entry) must ALSO
    # route to the cup handler, else the loop mis-trains mid-race (the ps-8 abandon bug)
    assert avail({"team_data_set": tds, "chara_info": {"playing_state": 8}, "home_info": train_cmds}) is True
    assert avail({"team_data_set": tds, "chara_info": {"playing_state": 9}, "home_info": train_cmds}) is True
    # opponent_info_array present (post team_edit) is an equivalent "already inside the cup" marker
    assert avail({"team_data_set": {"opponent_info_array": [{"team_race_set_id": 300}]},
                  "chara_info": {"playing_state": 1}}) is True
    # normal training turn (playing_state 1) with the SAME command menu -> NOT the cup
    assert avail({"team_data_set": tds, "chara_info": {"playing_state": 1}, "home_info": train_cmds}) is False
    # no team_data_set -> not the cup
    assert avail({"chara_info": {"playing_state": 7}}) is False
    # guards: a pending event / finish at playing_state 7 must be handled first, not the cup
    assert avail({"team_data_set": tds, "chara_info": {"playing_state": 7},
                  "unchecked_event_array": [{"event_id": 1}]}) is False
    assert avail({"team_data_set": tds, "chara_info": {"playing_state": 7},
                  "single_mode_finish_common": {}}) is False


def test_team_next_decision_emits_valid_team_race():
    # Regression: at the cup, next_decision builds a COMPLETE Decision (action, payload, reason) and
    # passes the state (team_data_set + chara_info) so _team_race can build the aptitude lineup.
    strat = UnityStrategy(race_planner=None)
    tds = {"team_info": {}, "evaluation_info_array": [{"chara_id": 1010, "member_state": 1}]}
    cup_state = {"data": {"team_data_set": tds,
                          "chara_info": {"playing_state": 7, "turn": 24, "card_id": 103801}}}
    d = strat.next_decision(cup_state, {})
    assert d.action == "team_race"
    assert d.payload.get("current_turn") == 24
    assert d.payload.get("team_data_set") is tds            # state passed for lineup building
    assert d.payload.get("chara_info", {}).get("card_id") == 103801
    assert d.reason


def test_team_race_full_flow():
    # Real cup flow (capture 20260706_042752): team_edit carries the APTITUDE team_data_array ->
    # opponent_list -> team_race_analyze -> team_race_start{team_race_set_id} -> team_race_end ->
    # team_race_out. team_edit WITH a valid lineup is THE 102 fix (the lineup belongs to team_edit, not
    # load). NO gain_skills -- that was a ported-Icarus artifact not present in this game's cup.
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runner = CareerRunner(root)
    runner._log = lambda *a, **k: None
    runner._drain_events = lambda c, s, st: st
    runner._fresh_career_state = lambda c, s=None: {"data": {}}
    calls = []
    members = [1010, 1044, 1056, 1055, 1022, 1068, 1016, 1030, 1052]   # 9 teammates + the trainee
    tds = {"evaluation_info_array": [{"chara_id": c, "member_state": 1} for c in members]}
    chara = {"card_id": 103801, "turn": 24, "proper_distance_middle": 7, "proper_running_style_senko": 7}

    class FakeClient:
        def call(self, ep, args=None, **kw):
            calls.append((ep, args or {}))
            if ep == "single_mode_team/team_edit":       # team_edit returns the rank-matched opponents
                return {"data": {"team_data_set": {"opponent_info_array": [
                    {"team_race_set_id": 300, "win_up_rank": 22}, {"team_race_set_id": 203, "win_up_rank": 25}]}}}
            return {"data": {}}

    runner._unity.run_cup_race(FakeClient(), None, {"current_turn": 24, "team_data_set": tds, "chara_info": chara})
    eps = [c[0] for c in calls]
    assert eps[0] == "single_mode_team/team_edit"            # 1) team_edit FIRST, carrying the lineup
    lineup = calls[0][1].get("team_data_array")
    assert isinstance(lineup, list) and len(lineup) >= 5
    assert all("distance_type" in r and "chara_id" in r for r in lineup)
    assert "single_mode_team/opponent_list" in eps           # 2) opponents fetched directly
    assert "single_mode_team/gain_skills" not in eps          # no gain_skills (not in this game's cup)
    # 2b) pre-race matchup analysis (captured 20260706) -- required, and BEFORE team_race_start
    assert "single_mode_team/team_race_analyze" in eps
    assert eps.index("single_mode_team/team_race_analyze") < eps.index("single_mode_team/team_race_start")
    an = next(a for e, a in calls if e == "single_mode_team/team_race_analyze")
    assert an.get("team_race_set_id") == 300 or an.get("race_set_id") == 300
    ts = next(a for e, a in calls if e == "single_mode_team/team_race_start")
    assert ts.get("team_race_set_id") == 300                # 3) strongest winnable (lowest win_up_rank)
    assert "single_mode_team/team_race_end" in eps and "single_mode_team/team_race_out" in eps  # 4)


def test_team_race_fallback_set_id_when_no_opponents():
    # When opponents don't surface, fall back to the confirmed per-turn set_id (turn 24 -> 300).
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runner = CareerRunner(root)
    runner._log = lambda *a, **k: None
    runner._drain_events = lambda c, s, st: st
    runner._fresh_career_state = lambda c, s=None: {"data": {}}
    calls = []
    tds = {"evaluation_info_array": [{"chara_id": c, "member_state": 1} for c in
                                     [1010, 1044, 1056, 1055, 1022, 1068, 1016, 1030, 1052]]}

    class FakeClient:
        def call(self, ep, args=None, **kw):
            calls.append((ep, args or {}))
            return {"data": {}}   # no opponents surface anywhere

    runner._unity.run_cup_race(FakeClient(), None,
                      {"current_turn": 24, "team_data_set": tds, "chara_info": {"card_id": 103801}})
    ts = next(a for e, a in calls if e == "single_mode_team/team_race_start")
    assert ts.get("team_race_set_id") == 300   # TEAM_RACE_SET_ID_BY_TURN[24]


def test_race_entry_205_on_cup_turn_reloads_not_empty_cup():
    # Unity cup-turn goal-race collision (Curren Chan's Hakodate Sprint at t36): when race_entry 205s
    # because the mandatory team cup is the pending action, _race must REJECT the pid and RELOAD --
    # letting the state-based cup path drive it next iteration with a full payload. The old code called
    # run_cup_race with only {current_turn} (empty roster -> build_team_formation []=> _fail -> 2 fails
    # STOP the career). Regression: run_cup_race must NOT be invoked from the 205 recovery.
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runner = CareerRunner(root)
    runner._log = lambda *a, **k: None
    runner.status = {"scenario_id": 2}
    SENTINEL = {"data": {"reloaded": True}}
    runner._fresh_career_state = lambda c, s=None: SENTINEL

    rejected = []
    class _RP:
        def reject(self, turn, pid): rejected.append((turn, pid))
    runner.race_planner = _RP()

    cup_calls = []
    runner._unity.run_cup_race = lambda *a, **k: cup_calls.append((a, k))  # must NOT be called

    class _RaceEntry205:
        def race_entry(self, program_id=None, current_turn=None):
            raise Exception(f"API error 205 on single_mode_team/race_entry pid={program_id}")

    out = runner._race(_RaceEntry205(), {"data": {}}, {"scenario_id": 2},
                       {"program_id": 96, "current_turn": 36, "_strategy": None})
    assert out is SENTINEL, "205 recovery must reload fresh state"
    assert rejected == [(36, 96)], f"pid must be rejected once: {rejected}"
    assert cup_calls == [], "run_cup_race must NOT be called from the 205 recovery (empty-roster bug)"


def test_scenario_2_registered():
    assert STRATEGIES.get(2) is UnityStrategy
    assert UnityStrategy.scenario_id == 2


def test_build_team_formation_is_aptitude_valid():
    # The lineup submitted to team_edit must field 1-3 racers per distance, min 1 each -- a malformed
    # (aptitude-invalid) lineup is what 102'd. Trainee placed by aptitude, teammates by the pool.
    from career_bot.scenarios.unity import build_team_formation
    tds = {"evaluation_info_array": [{"chara_id": c, "member_state": 1} for c in
                                     [1010, 1044, 1056, 1055, 1022, 1068, 1016, 1030, 1052]]}
    f = build_team_formation(tds, 1038, trainee_aptitude={"card_id": 103801, "proper_distance_middle": 7})
    assert len(f) >= 5
    for dt in (1, 2, 3, 4, 5):                              # every distance has >=1 racer
        assert any(r["distance_type"] == dt for r in f)
    assert all(1 <= sum(1 for r in f if r["distance_type"] == dt) <= 3 for dt in (1, 2, 3, 4, 5))
    # too few members -> [] (defer cleanly instead of submitting a 102-ing lineup)
    assert build_team_formation({"evaluation_info_array": [{"chara_id": 1, "member_state": 1}]}, 1038) == []


def test_extract_opponents_from_envelope():
    # _extract_opponents pulls opponent_info_array out of either envelope depth.
    opps = [{"team_race_set_id": 300}, {"team_race_set_id": 203}]
    assert UnityScenario.extract_opponents({"data": {"data": {"team_data_set": {"opponent_info_array": opps}}}}) == opps
    assert UnityScenario.extract_opponents({"data": {"team_data_set": {"opponent_info_array": opps}}}) == opps
    assert UnityScenario.extract_opponents({"data": {}}) == []


def test_load_career_falls_back_to_team_namespace():
    # At login (scenario unknown), a team career 205s on single_mode_free/load; load_career must flip
    # to single_mode_team/load and pin scenario 2 -- this is the "can't even log in" fix.
    calls = []

    class Fake:
        current_scenario_id = None
        _pin_scenario_from = UmaClient._pin_scenario_from

        def call(self, ep, args=None, **kw):
            calls.append(ep)
            if ep == "single_mode_free/load":
                raise Exception("API error 205 on single_mode_free/load: {...}")
            if ep == "single_mode_team/load":
                return {"data": {"chara_info": {"scenario_id": 2, "turn": 5}}}
            raise AssertionError("unexpected ep " + ep)

    f = Fake()
    res = UmaClient.load_career(f)
    assert res["data"]["chara_info"]["scenario_id"] == 2
    assert f.current_scenario_id == 2                       # pinned from the loaded career
    assert calls == ["single_mode_free/load", "single_mode_team/load"]  # tried free, then team


def test_load_career_reaches_plain_namespace_for_ura():
    # THE 20260707 login-205-storm: a live URA career answers only on the PLAIN single_mode/load.
    # With the scenario unpinned, load_career must walk free -> team -> plain instead of hard_reset
    # looping between free and team forever.
    calls = []

    class Fake:
        current_scenario_id = None
        _pin_scenario_from = UmaClient._pin_scenario_from

        def call(self, ep, args=None, **kw):
            calls.append(ep)
            if ep == "single_mode/load":
                return {"data": {"chara_info": {"scenario_id": 1, "turn": 30}}}
            raise Exception(f"API error 205 on {ep}: {{...}}")

    f = Fake()
    res = UmaClient.load_career(f)
    assert res["data"]["chara_info"]["scenario_id"] == 1
    assert f.current_scenario_id == 1                       # pinned to URA from the loaded career
    assert calls == ["single_mode_free/load", "single_mode_team/load", "single_mode/load"]
    # and when the client is ALREADY pinned/hinted to URA (login seeds the locked scenario),
    # the plain namespace is probed FIRST -- no 205s at all
    calls.clear()
    f2 = Fake()
    f2.current_scenario_id = 1
    UmaClient.load_career(f2)
    assert calls == ["single_mode/load"]


def test_load_career_free_stays_free():
    # A MANT career loads via single_mode_free/load first -- no fallback probes on success.
    class Fake:
        current_scenario_id = 4
        _pin_scenario_from = UmaClient._pin_scenario_from

        def call(self, ep, args=None, **kw):
            assert ep == "single_mode_free/load", ep
            return {"data": {"chara_info": {"scenario_id": 4, "turn": 10}}}

    f = Fake()
    res = UmaClient.load_career(f)
    assert res["data"]["chara_info"]["scenario_id"] == 4
    assert f.current_scenario_id == 4


def _planner_with_scheduled():
    rp = RacePlanner("/__no_such_dir__")   # _load no-ops when the data path is missing
    rp.program = {8888: {}, 9999: {}}      # make the scheduled + default pids resolvable
    # use_race_schedule:False = explicitly OFF, so these tests exercise the goals-only path for Unity
    # (a bare populated schedule now DEFAULTS on -- that's covered in test_use_race_schedule.py).
    return rp, {"extra_race_list": [8888], "use_race_schedule": False}  # user scheduled 8888 but toggled OFF


def test_unity_choose_ignores_schedule_mant_keeps_it():
    # The planner is scenario-agnostic: the scenario class's RACE_POLICY (bound by
    # BaseTrainingStrategy.__init__ in production) is what flips these behaviors.
    rp, preset = _planner_with_scheduled()
    # training-available turn (race command + a training command enabled), scheduled race on offer
    def st():
        return {"data": {
            "chara_info": {"turn": 20},
            "home_info": {"command_info_array": [
                {"command_type": 4, "command_id": 401, "is_enable": 1},
                {"command_type": 1, "command_id": 101, "is_enable": 1}]},
            "race_condition_array": [{"program_id": 8888}, {"program_id": 9999}],
        }}
    rp.policy = dict(MantStrategy.RACE_POLICY)
    assert rp.choose(st(), preset) == 8888    # MANT: runs the scheduled race
    rp.policy = dict(UnityStrategy.RACE_POLICY)
    assert rp.choose(st(), preset) == 0       # Unity: ignores the schedule entirely


def test_unity_forced_uses_game_default_not_schedule():
    rp, preset = _planner_with_scheduled()
    # mandatory only-race turn; game default (first) is 9999, user scheduled 8888
    def st():
        return {"data": {
            "chara_info": {"turn": 20},
            "home_info": {"command_info_array": [{"command_type": 4, "command_id": 401, "is_enable": 1}]},
            "race_condition_array": [{"program_id": 9999}, {"program_id": 8888}],
        }}
    rp.policy = dict(MantStrategy.RACE_POLICY)
    assert rp.forced_program(st(), preset) == 8888   # MANT: schedule overrides the game default
    rp.policy = dict(UnityStrategy.RACE_POLICY)
    assert rp.forced_program(st(), preset) == 9999   # Unity: ignores schedule -> game's forced goal race


if __name__ == "__main__":
    test_namespace_routing()
    test_scenario_follows_live_career_not_preset()
    test_close_out_team_selects_factors_then_names_trainee()
    test_close_out_non_team_still_selects_factors_and_names_trainee()
    test_close_out_ura_uses_single_factor_select()
    test_unity_goal_races_are_mandatory()
    test_cup_turn_detection()
    test_team_next_decision_emits_valid_team_race()
    test_team_race_full_flow()
    test_team_race_fallback_set_id_when_no_opponents()
    test_race_entry_205_on_cup_turn_reloads_not_empty_cup()
    test_build_team_formation_is_aptitude_valid()
    test_extract_opponents_from_envelope()
    test_scenario_2_registered()
    test_load_career_falls_back_to_team_namespace()
    test_load_career_reaches_plain_namespace_for_ura()
    test_load_career_free_stays_free()
    test_unity_choose_ignores_schedule_mant_keeps_it()
    test_unity_forced_uses_game_default_not_schedule()
    print("test_team_scenario: OK")
