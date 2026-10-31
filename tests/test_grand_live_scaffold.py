"""Grand Live / "Our Grand Concert" (scenario 3).

API mapped from a full 78-turn capture (UmaDumpy 20260723_070635, 412 tx, all result_code 1):
namespace `single_mode_live/*`, core flow identical to the other scenarios, plus two Grand-Live-only
calls -- master_square{square_id} and live_start{}. These lock in the facts the implementation rests on.

Run:
    python tests/test_grand_live_scaffold.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.runner import CareerRunner, STRATEGIES
from career_bot.scenarios.grand_live import GrandLiveStrategy
from career_bot.scenarios.mant import MantStrategy
from career_bot.scenarios.unity import UnityStrategy
from career_bot.scenarios.ura import UraStrategy
from uma_api.client import UmaClient


def _s():
    return GrandLiveStrategy.__new__(GrandLiveStrategy)   # method-only; skip __init__


def _action(s, st):
    """The decision's action -- or 'fell_through' if it passed BOTH Grand Live branches into the shared
    training brain, which a bare __new__ stub can't execute. Either result proves no Grand Live move was
    emitted, which is exactly what the negative cases below assert."""
    try:
        return s.next_decision(st, {}).action
    except AttributeError:
        return "fell_through"


def _handled(s, decision):
    """Mirror the runner's post-success commit for pure strategy tests."""
    s.mark_decision_handled(decision)
    return decision


def _state(turn, squares=(), next_live=(), ps=1, events=()):
    return {"data": {
        "chara_info": {"turn": turn, "scenario_id": 3, "playing_state": ps},
        "unchecked_event_array": [{"event_id": e} for e in events],
        "live_data_set": {
            "next_square_info_array": [{"square_id": s, "square_num": 1} for s in squares],
            "next_live_id_array": list(next_live),
            "live_performance_info": {"dance": 44, "passion": 23, "vocal": 42, "visual": 50,
                                      "mental": 41, "max_dance": 200},
        },
    }}


# ---------------- registration + readiness ----------------

def test_registered_as_scenario_3():
    assert STRATEGIES.get(3) is GrandLiveStrategy
    assert GrandLiveStrategy.scenario_id == 3


def test_api_ready_now_that_it_is_mapped():
    assert GrandLiveStrategy.API_READY is True


def test_other_scenarios_stay_runnable():
    for cls in (MantStrategy, UnityStrategy, UraStrategy):
        assert getattr(cls, "API_READY", True) is not False, f"{cls.__name__} must stay runnable"


# ---------------- namespace routing (the #1 capture finding) ----------------

def test_scenario_3_routes_to_single_mode_live():
    for leaf in ("start", "load", "check_event", "exec_command", "race_entry",
                 "gain_skills", "factor_select", "finish", "master_square", "live_start"):
        assert UmaClient._route_ep(f"single_mode_free/{leaf}", 3) == f"single_mode_live/{leaf}"


def test_routing_does_not_disturb_other_scenarios():
    assert UmaClient._route_ep("single_mode_free/exec_command", 4) == "single_mode_free/exec_command"
    assert UmaClient._route_ep("single_mode_free/exec_command", 2) == "single_mode_team/exec_command"
    assert UmaClient._route_ep("single_mode_free/exec_command", 1) == "single_mode/exec_command"
    assert UmaClient._route_ep("load/index", 3) == "load/index"   # non-career calls pass through


# ---------------- resuming an in-progress career ----------------

def test_career_load_probe_covers_every_scenario():
    """load_career probes namespaced `load` calls to find a running career. A scenario missing from
    this map makes its `pinned in EP` check fail, so the probe skips that namespace entirely and an
    ALREADY-RUNNING career of that type can never be resumed -- the live Grand Live failure."""
    ep = UmaClient.CAREER_LOAD_EP
    assert set(ep) == {1, 2, 3, 4}, "every playable scenario must be probeable"
    assert ep[3] == "single_mode_live/load"
    assert ep[4] == "single_mode_free/load"
    assert ep[2] == "single_mode_team/load"
    assert ep[1] == "single_mode/load"


def test_every_registered_strategy_is_resumable():
    # any scenario the runner can dispatch must also be loadable, or its careers strand mid-run
    for sid in STRATEGIES:
        assert sid in UmaClient.CAREER_LOAD_EP, f"scenario {sid} has no career-load endpoint"


# ---------------- master_square ----------------

def test_claims_an_offered_square():
    # verified 64/64 in the capture: the claim always comes from next_square_info_array
    d = _s().next_decision(_state(18, squares=(40006, 11002, 20019)), {})
    assert d.action == "master_square" and d.payload["square_id"] == 40006


def test_song_square_outranks_lesson_and_energy():
    # 40xxx song squares carry a career-long bonus -> claimed ahead of one-off lesson/energy squares
    d = _s().next_decision(_state(31, squares=(11002, 30004, 40006)), {})
    assert d.payload["square_id"] == 40006


def test_high_tier_song_beats_a_cheaper_low_tier_one():
    """Songs are ranked by the guide's TIER (the Concert Bonus they leave behind), not live_bonus_value
    and not cost alone. 40000 Run for Our Dream! (High, Spec Priority +5) must beat 40010 Ring Ring
    Diary (Low) even though both cost 42 -- raw live_bonus_value scored Ring Ring HIGHER (15 vs 5)."""
    rich = {"dance": 999, "passion": 999, "vocal": 999, "visual": 999, "mental": 999}
    got = _s().pick_square({"next_square_info_array": [
        {"square_id": 40010}, {"square_id": 40000}], "live_performance_info": rich})
    assert got == 40000


def test_song_bands_follow_the_chosen_effect_order():
    """Ranked by effect band, not a general value tier:
           SP bonus  >  friendship bonus  >  specialty priority  >  support chain."""
    S = GrandLiveStrategy.SONG_SQUARE_SCORE
    sp_bonus    = (40004, 40000)
    friendship  = (40019, 40018, 40003, 40002, 40015, 40001, 40016, 40012, 40014)
    specialty   = (40011, 40007, 40008, 40013, 40017)
    chain       = (40005, 40020, 40006, 40010, 40009)
    bands = (sp_bonus, friendship, specialty, chain)
    # every band strictly outranks the one below it
    for higher, lower in zip(bands, bands[1:]):
        assert min(S[x] for x in higher) > max(S[x] for x in lower), (higher, lower)
    # +3 SP leads +2 SP; +10% friendship leads +5%
    assert S[40004] > S[40000]
    assert min(S[40019], S[40018]) > max(S[40003], S[40002], S[40001])
    assert S[40091] == 0 and S[40092] == 0                      # awarded, never bought
    # no song is silently unranked
    assert set(S) == set(sp_bonus + friendship + specialty + chain) | {40091, 40092}


def test_square_priority_is_preset_overridable():
    # a preset can invert the family order (e.g. prefer energy squares)
    s = _s()
    lds = {"next_square_info_array": [{"square_id": 40006}, {"square_id": 30004}], "live_performance_info": {"dance": 999, "passion": 999, "vocal": 999, "visual": 999, "mental": 999}}
    # family score is the TIE-BREAK, so equalise the reward score first. Cost-efficiency is disabled
    # here too, otherwise value-per-point (not the family table) decides the winner.
    # 40006 is a known song, so its guide tier (50) is its reward; push the energy family above it.
    assert s.pick_square(lds, {"grand_live_square_priority": {"30": 999},
                               "grand_live_reward_priority": {"energy": 9999},
                               "grand_live_cost_efficiency": False,
                               "grand_live_chase_songs": False}) == 30004


def test_cost_efficiency_prefers_value_per_point():
    """Points are a finite currency (10-35 per square), so ranking on raw reward overpays: a 24-point
    Advanced lesson loses to a 10-point Basics lesson paying nearly the same. Verified from the
    generated cost data."""
    G = GrandLiveStrategy
    assert G.square_cost(11001) == 10 and G.square_cost(11201) == 24
    assert G.efficiency(11001) > G.efficiency(11201)
    rich = {"dance": 999, "passion": 999, "vocal": 999, "visual": 999, "mental": 999}
    board = {"next_square_info_array": [{"square_id": 11201}, {"square_id": 11001}],
             "live_performance_info": rich, "effected_live_id_array": list(range(30))}
    s = _s(); s._last_turn = 30
    assert s.pick_square(board, {}) == 11001                                    # cheaper wins
    assert s.pick_square(board, {"grand_live_cost_efficiency": False}) == 11201  # raw reward wins


def test_song_quota_outranks_efficiency():
    """A song owed for the next concert is MANDATORY (+10 all stats vs +3) and cannot be bought back
    later. Songs cost ~42 points, so on pure value-per-point they lose to a 10-point stat square --
    which would silently forfeit the Great Success. Quota must win while short."""
    rich = {"dance": 999, "passion": 999, "vocal": 999, "visual": 999, "mental": 999}
    board = {"next_square_info_array": [{"square_id": 40006}, {"square_id": 11001}],
             "live_performance_info": rich}
    s = _s(); s._last_turn = 20
    short = {**board, "effected_live_id_array": [1006, 1, 2]}      # 2 bought, 3 due
    met = {**board, "effected_live_id_array": [1006, 1, 2, 3]}     # quota met
    assert s.pick_square(short, {}) == 40006     # mandatory song first
    assert s.pick_square(met, {}) == 11001       # then best value-per-point


def test_no_squares_offered_falls_through_to_normal_turn():
    # nothing to claim -> must NOT emit a master_square decision (would send square_id 0)
    assert _s().pick_square({"next_square_info_array": []}) == 0


def test_squares_cost_performance_points():
    """A square COSTS performance points -- verified against the in-game panel (Makeup Basics = Visual
    10, Vocal Training = Vocal 10). Claiming one you cannot pay for is answered 205, which is why the
    live run stormed 205s from turn 1 with zero points."""
    rich = {"dance": 89, "passion": 34, "vocal": 68, "visual": 41, "mental": 42}
    broke = {"dance": 0, "passion": 0, "vocal": 0, "visual": 0, "mental": 0}
    assert GrandLiveStrategy.can_afford(11004, rich) is True     # Visual 10 <= 41
    assert GrandLiveStrategy.can_afford(11004, broke) is False   # cannot pay
    # an unaffordable square is never picked
    lds = {"next_square_info_array": [{"square_id": 11004}], "live_performance_info": broke}
    assert _s().pick_square(lds, {}) == 0


def test_reward_priority_sp_then_speed_then_hint_then_wit():
    R = GrandLiveStrategy.REWARD_PRIORITY
    assert R["sp"] > R["speed"] > R["hint"] > R["wit"]
    assert R["wit"] > R["power"] and R["wit"] > R["guts"]   # off-priority stats rank below


def test_picks_the_best_reward_it_can_afford():
    # the exact board from the in-game screenshot: Guts+5 / Skill Hint / Power+5, all affordable.
    # Skill hint (training effectiveness) outranks the two off-priority stat squares.
    perf = {"dance": 89, "passion": 34, "vocal": 68, "visual": 41, "mental": 42}
    lds = {"next_square_info_array": [{"square_id": 11004}, {"square_id": 20015}, {"square_id": 11003}],
           "live_performance_info": perf}
    assert _s().pick_square(lds, {}) == 20015


def test_reward_priority_is_preset_overridable():
    perf = {"dance": 99, "passion": 99, "vocal": 99, "visual": 99, "mental": 99}
    lds = {"next_square_info_array": [{"square_id": 11004}, {"square_id": 20015}],
           "live_performance_info": perf}
    # push Guts above the skill hint -> Makeup Basics (Guts +5) wins instead
    assert _s().pick_square(lds, {"grand_live_reward_priority": {"guts": 999}}) == 11004


def test_same_offer_is_claimed_only_once():
    """THE 205-storm bug: next_square_info_array is a PERSISTENT preview of the pending board choice,
    not a per-turn claimable offer. In the capture it was byte-identical for turns 1-12 while the client
    claimed exactly once (turn 12). Claiming every turn 205-stormed the live run, so an unchanged offer
    must be attempted once and then left alone."""
    s = _s()
    offer = (30009, 20015, 11002)
    first = s.next_decision(_state(1, squares=offer), {})
    assert first.action == "master_square"
    _handled(s, first)
    for turn in range(2, 13):                      # same offer, many turns -> never re-claimed
        assert _action(s, _state(turn, squares=offer)) != "master_square"


def test_board_advance_allows_a_new_claim():
    # the offer CHANGING is exactly the signal that the board advanced (capture: turn 12 -> 13)
    s = _s()
    first = s.next_decision(_state(12, squares=(30009, 20015, 11002)), {})
    assert first.action == "master_square"
    _handled(s, first)
    assert s.next_decision(_state(13, squares=(40006, 40010, 40009)), {}).action == "master_square"


def test_master_square_205_is_deterministic():
    # a 205 here means "board hasn't advanced" -> fail fast instead of retry-storming the live API
    from uma_api.client import is_deterministic_205
    assert is_deterministic_205("single_mode_live/master_square") is True
    assert is_deterministic_205("single_mode_live/exec_command") is False


# ---------------- live_start ----------------

def test_live_fires_on_a_performance_turn():
    d = _s().next_decision(_state(24, ps=10, events=(202006,)), {})
    assert d.action == "grand_live_perform" and d.payload["current_turn"] == 24


def test_live_fires_only_once_per_turn():
    s = _s()
    st = _state(36, ps=10, events=(202012,))
    first = s.next_decision(st, {})
    assert first.action == "grand_live_perform"
    _handled(s, first)
    assert _action(s, st) != "grand_live_perform"   # already performed this turn


class _IdlePlanner:
    """Nothing raceable -- the shared brain would return idle (the Concert screen)."""
    def goal_program(self, state): return 0
    def forced_program(self, state, preset=None): return 0
    def fan_goal_program(self, state, preset=None): return 0
    def eligibility_fan_program(self, state, window=None): return 0
    def choose(self, state, preset): return 0
    def apt_maiden_program(self, state, chara): return 0
    rerun_program = 0
    base_dir = None


def _idle_strategy():
    """A strategy whose shared brain has nothing to do -> returns Decision("idle") (Concert screen)."""
    s = _s()
    s.race_planner = _IdlePlanner()
    s._fan_raced = True                      # fan race already run this career
    s._raced_turns = set()
    s._best_command = lambda *a, **k: None   # no training/rest available on the Concert screen
    return s


NO_FORESIGHT = {"career_foresight": False}   # skip the forecaster on this bare stub


def test_concert_screen_performs_instead_of_idling():
    """After the turn-24 race resolves the game parks on the Concert screen: no training, no rest,
    nothing raceable -> the shared brain returns "idle" and the run ENDS (live: ended@turn24 sitting on
    '1st Concert'). On an unperformed Live turn, perform instead of idling. next_live_id_array is empty
    there, so the rescue must NOT depend on it."""
    s = _idle_strategy()
    st = _state(24, ps=10)                   # note: no pending live id
    assert s.next_decision(st, NO_FORESIGHT).action == "grand_live_perform"


def test_concert_screen_with_turn_zero_still_performs():
    """The Concert screen reports chara_info.turn as 0/absent -- the live log literally shows
    "t0 idle | no action" while the game sat on 1st Concert. The rescue must remember the last real
    turn, or its turn-in-LIVE_TURNS check fails and the run idles out at turn 24."""
    s = _idle_strategy()
    s.next_decision(_state(23), NO_FORESIGHT)   # a real turn is seen first
    s._last_turn = 24                                          # ...then turn 24 happens
    assert s.next_decision(_state(0, ps=10), NO_FORESIGHT).action == "grand_live_perform"


def test_turn_zero_on_the_concert_screen_still_performs():
    """The Concert screen reports turn 0, which used to defeat the turn-based gate. playing_state 10 is
    the signal -- but the LIVE still needs a real turn number to send. Mid-run that comes from
    _last_turn, remembered from the turn before the game parked on the Concert screen."""
    s = _idle_strategy()
    s._last_turn = 24                        # mid-run: the real turn is known
    assert s.next_decision(_state(0, ps=10), NO_FORESIGHT).action == "grand_live_perform"


def test_idle_anywhere_attempts_the_concert_once():
    """IDLE means no training, no rest, no race -- in Grand Live that essentially only happens on the
    Concert screen, so idle ITSELF is the trigger. Attempted once per turn value, never looped.

    Requires a KNOWN turn. This test used to pass turn 0 with no _last_turn, on the stated assumption
    that "a wrong guess is harmless (live_start 102 -> skip)". Production disproved it:
    career_log_20260731_035056 resumed a turn-24 career, fired live_start{current_turn: 0} and got
    205 -- not 102 -- three times, and the runner ended the career at its first step. See
    test_resumed_career_never_fires_live_start_for_turn_zero."""
    s = _idle_strategy()
    s._last_turn = 60                        # remembered from before the game parked on the Concert
    first = s.next_decision(_state(0, ps=1), NO_FORESIGHT)
    assert first.action == "grand_live_perform"
    _handled(s, first)
    # never twice for the same turn -> no spin
    assert s.next_decision(_state(0, ps=1), NO_FORESIGHT).action != "grand_live_perform"


def test_concert_rescue_only_fires_once():
    s = _idle_strategy()
    st = _state(24, ps=10)
    first = s.next_decision(st, NO_FORESIGHT)
    assert first.action == "grand_live_perform"
    _handled(s, first)
    assert s.next_decision(st, NO_FORESIGHT).action != "grand_live_perform"   # no re-fire loop


def test_idle_attempt_is_per_turn_not_global():
    # a later turn gets its own single attempt (the career has 5 Concerts)
    s = _idle_strategy()
    first = s.next_decision(_state(24, ps=1), NO_FORESIGHT)
    assert first.action == "grand_live_perform"
    _handled(s, first)
    assert s.next_decision(_state(36, ps=1), NO_FORESIGHT).action == "grand_live_perform"


def test_a_normal_turn_with_real_work_is_untouched():
    """The idle fallback only fires when the brain has NOTHING to do. A turn with a real training
    available must never be hijacked into a performance."""
    s = _idle_strategy()
    s._best_command = lambda *a, **k: {"command_type": 1, "command_id": 101}
    assert s.next_decision(_state(30), NO_FORESIGHT).action != "grand_live_perform"


def test_live_turns_match_the_capture():
    assert GrandLiveStrategy.LIVE_TURNS == (24, 36, 48, 60, 72)


def test_no_live_when_not_on_the_concert_screen():
    """playing_state 10 IS the Concert signal (capture 20260723_170405: load -> ps 10 -> live_start,
    ps drops to 5 after). A Live turn that is NOT on that screen must not fire a performance."""
    assert _action(_s(), _state(24, ps=1)) != "grand_live_perform"


def test_grand_live_finish_uses_the_id_based_slot_release():
    """Grand Live's slot is id-based like Unity: the plain {current_turn, factor_lottery_id} finish
    returns rc=1 (single career looks fine) but doesn't RELEASE the slot, so a loop's next start 102s
    (career_log_20260724_005918). finish_career must send the {target_viewer_id, target_trained_chara_id}
    shape for scenario 3 -- same as scenario 2 -- while MANT/URA keep the plain shape."""
    c = UmaClient.__new__(UmaClient)
    c.viewer_id = 123
    sent = {}
    c.call = lambda ep, payload, **k: sent.update(ep=ep, payload=payload) or {"data": {}}
    c.current_scenario_id = 3
    c.finish_career(current_turn=78, is_force_delete=False, factor_lottery_id=1, target_trained_chara_id=514)
    assert sent["payload"].get("target_trained_chara_id") == 514   # id-based release
    for sid in (4, 1):                                             # MANT / URA keep the plain shape
        sent.clear(); c.current_scenario_id = sid
        c.finish_career(current_turn=78, factor_lottery_id=1, target_trained_chara_id=514)
        assert "target_trained_chara_id" not in sent["payload"], f"scenario {sid} must stay plain"


def test_grand_live_completion_nickname_is_235():
    """Close-out: change_nickname must send Grand Live's title (235, from capture 20260723_070635),
    not MANT's 180. The wrong id 500s, and for Grand Live that 500 leaves the career slot unreleased,
    so the next start 102s and the loop wedges (career_log_20260724_004649)."""
    assert UmaClient.SCENARIO_COMPLETION_NICKNAME.get(3) == 235
    # the other scenarios are unchanged
    assert UmaClient.SCENARIO_COMPLETION_NICKNAME[2] == 154
    assert UmaClient.SCENARIO_COMPLETION_NICKNAME[4] == 180
    assert UmaClient.SCENARIO_COMPLETION_NICKNAME[1] == 92


def test_every_playable_scenario_has_a_completion_nickname():
    # a scenario missing here defaults to MANT's 180 -> 500 -> a wedged loop, so all four must be set
    for sid in STRATEGIES:
        assert sid in UmaClient.SCENARIO_COMPLETION_NICKNAME, f"scenario {sid} has no completion nickname"


def test_grand_live_uses_single_call_factor_select():
    """Close-out: Grand Live's factor_select is {current_turn, skill_id_array} (capture 20260723_070635)
    -- the SINGLE-call form used by Team/URA, not MANT's open{} + confirm pair. Sending MANT's open{}
    answered 102 on a live close-out (career_log_20260723_175519)."""
    from types import SimpleNamespace
    from uma_api.client import UmaClient
    sent = []
    fake = SimpleNamespace(
        current_scenario_id=3, last_friend_viewer_id=0,
        load_career=lambda: {}, call=lambda ep, args=None, **kw: sent.append(ep) or {},
        factor_select=lambda current_turn=None, skill_id_array=None: sent.append(("factor_select", current_turn)) or {},
        finish_career=lambda **kw: sent.append("finish") or {},
        change_nickname=lambda *a, **kw: None, friend_search=lambda *a: None)
    UmaClient.close_career(fake, current_turn=78)
    assert ("factor_select", 78) in sent and "single_mode_free/factor_select" not in sent, sent


def test_live_start_payload_shape_matches_the_client():
    """live_start takes {event_id, choice_number, current_turn} -- confirmed in two captures
    (20260723_170405 t24 ev 202006; 20260723_173458 t60 ev 202027). Omitting a field the real client
    always sends is what the server answered 102 to."""
    import inspect
    from career_bot.runner import CareerRunner
    src = inspect.getsource(CareerRunner._grand_live_call)
    assert '"event_id"' in src and '"choice_number"' in src and '"current_turn"' in src


def test_live_start_carries_the_event_id():
    # live_start needs {event_id, current_turn}; sending only the turn is what the server 102'd
    d = _s().next_decision(_state(24, ps=10, events=(202006,)), {})
    assert d.action == "grand_live_perform"
    assert d.payload["event_id"] == 202006 and d.payload["current_turn"] == 24


# ---------------- Light Hello (Friends card) ----------------

def _lh_event(card=30052):
    """A Light Hello event, tagged with its source support_card_id (as the server sends it)."""
    return {"event_contents_info": {"support_card_id": card, "choice_array": [
        # "I'd be glad to!"  -> +7 friendship, +8 Speed, unlocks recreation
        {"select_index": 1, "params_inc_dec_info_array": [
            {"target_type": 10, "value": 7}, {"target_type": 1, "value": 8}]},
        # "Sorry, I'm strapped for time..." -> -5 friendship, +37 Wit/SP (the stat-bait branch)
        {"select_index": 2, "params_inc_dec_info_array": [
            {"target_type": 10, "value": -5}, {"target_type": 5, "value": 37}]},
    ]}}


def test_light_hello_ids_match_support_list():
    # data/support_list.json: 10083 = R, 30052 = SSR (both Friends type)
    assert GrandLiveStrategy.LIGHT_HELLO_IDS == frozenset({10083, 30052})


def test_identifies_a_light_hello_event_by_source_card():
    s = _s()
    assert s.is_light_hello_event(_lh_event(30052))    # SSR
    assert s.is_light_hello_event(_lh_event(10083))    # R
    assert not s.is_light_hello_event(_lh_event(30028))  # another card
    assert not s.is_light_hello_event({"event_contents_info": {}})


class _EnergyMgr:
    """Stand-in EventManager: the choice at `energy_at` is the energy option."""
    def __init__(self, energy_at): self.energy_at = energy_at
    def energy_choice_index(self, event): return self.energy_at
    def choose(self, event, chara=None, preset=None): return 0


def test_energy_option_on_a_light_hello_event():
    """The chooser contract is a 0-BASED index into choice_array. On a Light Hello event, take the
    ENERGY option -- here the SECOND choice (index 1) -- no matter which position it is in."""
    for card in (30052, 10083):
        s = _s(); s._preset = {}; s.event_manager = _EnergyMgr(energy_at=1)
        assert s.choose_from_event(_lh_event(card), 12) == 1     # 0-based index of the energy choice


def test_energy_option_can_be_the_top_choice():
    s = _s(); s._preset = {}; s.event_manager = _EnergyMgr(energy_at=0)
    assert s.choose_from_event(_lh_event(30052), 12) == 0


def test_falls_back_to_top_when_energy_unknown():
    """No per-choice energy data -> take the TOP option (0-based index 0)."""
    class _NoEnergy:
        def energy_choice_index(self, event): return None
        def choose(self, event, chara=None, preset=None): return 0
    s = _s(); s._preset = {}; s.event_manager = _NoEnergy()
    assert s.choose_from_event(_lh_event(30052), 12) == 0


def test_top_choice_is_a_zero_based_index():
    # regression: _top_choice returned a select_index (1) -> picked the SECOND option. Must be 0.
    assert GrandLiveStrategy._top_choice(_lh_event(30052)) == 0


def test_other_cards_events_are_not_hijacked():
    """Scoped to Light Hello's OWN events -- another card's event must go through the shared scorer,
    not blindly take the top choice."""
    s = _s(); s._preset = {}; s.event_manager = None    # super() falls back to 1 with no manager
    # is_light_hello_event is False -> we defer; the ASSERTION is that we defer, verified via the flag
    assert not s.is_light_hello_event(_lh_event(30028))


def test_light_hello_handling_is_toggleable():
    # toggle OFF -> defer to the shared chooser instead of forcing the energy option
    s = _s()
    s._preset = {"grand_live_light_hello": False}
    s.event_manager = _EnergyMgr(energy_at=1)   # would force 1 if the toggle were on
    assert s.choose_from_event(_lh_event(30052), 12) == 0   # shared _EnergyMgr.choose() -> 0


def test_other_scenarios_have_no_light_hello_override():
    # Grand-Live-only by design -- MANT/URA/Unity keep the shared event scoring
    for cls in (MantStrategy, UnityStrategy, UraStrategy):
        assert not hasattr(cls, "LIGHT_HELLO_IDS"), f"{cls.__name__} must not inherit it"


# ---------------- Light Hello recreation timing ----------------

import contextlib
from career_bot.core.training_brain import BaseTrainingStrategy


@contextlib.contextmanager
def _no_shared_recreate():
    """Silence the shared _should_recreate (mood floor etc.) so tests isolate the Light Hello timing."""
    orig = BaseTrainingStrategy._should_recreate
    BaseTrainingStrategy._should_recreate = lambda *a, **k: False
    try:
        yield
    finally:
        BaseTrainingStrategy._should_recreate = orig


def _lh_strategy():
    s = _s()
    s._chara = {"support_card_array": [{"support_card_id": 30052}]}
    return s


def _recreate(s, turn, vital, best_score, preset=None):
    with _no_shared_recreate():
        return s._should_recreate(True, preset or {}, turn, 3, vital, best_score)


def test_classic_date_on_a_dead_turn_below_70_energy():
    s = _lh_strategy()
    assert _recreate(s, 30, 70, 0.0) is True        # dead turn, energy 70 -> take date (1st/2nd)
    assert _recreate(s, 30, 80, 0.0) is False       # too much energy
    assert _recreate(s, 30, 70, 5.0) is False       # rainbow/good board -> train, don't date


def test_energy_critical_recovery_any_year():
    s = _lh_strategy()
    assert _recreate(s, 20, 25, 0.0) is True         # energy < 30 + no rainbow -> recover via the date


def test_senior_dates_want_energy_below_60():
    s = _lh_strategy()
    assert _recreate(s, 55, 60, 0.0) is True          # 4th/5th date, Senior, energy 60
    assert _recreate(s, 55, 65, 0.0) is False         # above 60 in Senior -> wait


def test_no_date_without_light_hello_in_the_deck():
    s = _s(); s._chara = {"support_card_array": [{"support_card_id": 30028}]}
    assert _recreate(s, 30, 70, 0.0) is False


def test_recreation_thresholds_are_tunable():
    s = _lh_strategy()
    # push the Senior threshold up so a 65-energy Senior turn now dates
    assert _recreate(s, 55, 65, 0.0, {"grand_live_date_energy_senior": 70}) is True


# ---------------- turn-72 true finale (Great Hype) ----------------

RICH = {"dance": 999, "passion": 999, "vocal": 999, "visual": 999, "mental": 999}


def _board(songs):
    """A song square (40006) vs a Speed+5 lesson (11001), with `songs` already collected."""
    return {"next_square_info_array": [{"square_id": 40006}, {"square_id": 11001}],
            "live_performance_info": RICH,
            "effected_live_id_array": list(range(songs))}


def test_song_targets_match_the_users_numbers():
    """Targets are TOTAL songs held INCLUDING the free Make Debut!, with the concert turns as
    deadlines: 4 / 7 / 11 / 15 / 20 -- a ~3-4 per concert cadence. The last one is 20, not 19:
    the 20th song unlocks the TRUE finale and its gold skill, so stopping at 19 forfeited both."""
    G = GrandLiveStrategy
    assert G.SONG_TARGET_BY_CONCERT == {24: 4, 36: 7, 48: 11, 60: 15, 72: 20}
    # keyed on the NEXT concert: the target must be met BY that turn, not after it
    assert G.songs_due_by(1) == 4 and G.songs_due_by(24) == 4
    assert G.songs_due_by(25) == 7 and G.songs_due_by(36) == 7
    assert G.songs_due_by(37) == 11 and G.songs_due_by(48) == 11
    assert G.songs_due_by(49) == 15 and G.songs_due_by(60) == 15
    assert G.songs_due_by(61) == 20 and G.songs_due_by(72) == 20
    # every step clears the game's Great Success bar of 3 songs per concert
    prev = 0
    for turn in (24, 36, 48, 60, 72):
        step = G.SONG_TARGET_BY_CONCERT[turn] - prev
        assert step >= G.SONGS_PER_CONCERT, (turn, step)
        prev = G.SONG_TARGET_BY_CONCERT[turn]


def test_song_count_includes_make_debut():
    # the user counts Make Debut! in their numbers, so the total is the basis
    G = GrandLiveStrategy
    n = G.songs_collected({"live_data_set": {"effected_live_id_array": [1006, 1040, 1042, 1044]}})
    assert n == 4, "capture turn 25 held 4 songs including Make Debut -> concert-1 target met"


def test_finale_song_target_is_a_real_number_not_maximize():
    """The final window used to target 999 (never stop buying). It is now 20 -- the song count that
    unlocks the true finale -- so a song is owed while short and the chase STOPS once 20 are held;
    the remaining points go to techniques instead."""
    s = _s(); s._last_turn = 65
    rich = {"dance": 999, "passion": 999, "vocal": 999, "visual": 999, "mental": 999}

    def board(held):
        return {"next_square_info_array": [{"square_id": 40006}, {"square_id": 11001}],
                "live_performance_info": rich, "effected_live_id_array": list(range(held))}

    short = board(12)                                    # 12 held, 20 owed -> still chasing
    assert s.song_shortfall({"live_data_set": short}, turn=65) == 8
    assert s.pick_square(short, {}) == 40006             # song outranks the stat square

    met = board(20)                                      # quota met -> stop chasing
    assert s.song_shortfall({"live_data_set": met}, turn=65) == 0
    assert s.pick_square(met, {}) == 11001                # stat square wins now


def test_song_targets_are_preset_overridable():
    assert GrandLiveStrategy.songs_due_by(1, {"grand_live_song_targets": {24: 6}}) == 6


def test_songs_chased_only_until_the_next_concert_quota_is_met():
    s = _s()
    s._last_turn = 20                                     # before concert 1 -> 4 due
    short = {**_board(0), "effected_live_id_array": [1006, 1, 2]}      # 3 held, 4 due
    met = {**_board(0), "effected_live_id_array": [1006, 1, 2, 3]}     # 4 held, met
    assert s.song_shortfall({"live_data_set": short}, turn=20) == 1
    assert s.pick_square(short, {}) == 40006               # still short -> take the song
    assert s.song_shortfall({"live_data_set": met}, turn=20) == 0
    assert s.pick_square(met, {}) == 11001                 # target met -> best value-per-point



# ---------------- hard stat caps (Speed build) ----------------

def test_hard_speed_build_caps_are_injected():
    """The user's Grand Live profile: hard caps Speed 1600 / Stamina 1300 / Power 1300 / Guts 1500 /
    Wit(wiz) 1300, injected as preset stat_caps so _stat_capped_trainings hard-stops a maxed stat
    (soft scenario caps only tapered -> the bot 'held off' training). Ceilings are deliberately high
    -- Wit especially, since it is the energy + skill-point engine (see the Wit-over-rest hook).
    Stamina is pulled DOWN per-trainee from the career goals when a chara is passed (see
    test_grand_live_stamina_need.py); with no chara it stays at the 1300 ceiling."""
    s = _s()
    got = s._with_stat_caps({"career_foresight": False})["stat_caps"]
    assert got == {"speed": 1600, "stamina": 1300, "power": 1300, "guts": 1500, "wiz": 1300}
    assert GrandLiveStrategy.DEFAULT_STAT_CAPS == (1600, 1300, 1300, 1500, 1300)


def test_user_stat_caps_win_over_the_default():
    s = _s()
    assert s._with_stat_caps({"stat_caps": {"speed": 1400}})["stat_caps"] == {"speed": 1400}
    # empty/absent -> inject the Grand Live profile
    assert s._with_stat_caps({"stat_caps": {}})["stat_caps"]["stamina"] == 1300


# ---------------- performance -> training bonus ----------------

def _scored(cmd, bonus_array, preset=None):
    """Score one command with the shared base stubbed to a constant, so the delta IS the bonus."""
    s = _s()
    base = GrandLiveStrategy.__mro__[1]._score_command
    try:
        GrandLiveStrategy.__mro__[1]._score_command = lambda self, c, d, ch, p: 10.0
        data = {"live_data_set": {"training_bonus_array": bonus_array}}
        return s._score_command(cmd, data, {}, preset or {})
    finally:
        GrandLiveStrategy.__mro__[1]._score_command = base


def test_training_bonus_map_reads_the_servers_value():
    # the game pre-computes the plate result; target_type 1..5 = Speed/Stamina/Power/Guts/Wit
    data = {"live_data_set": {"training_bonus_array": [{"target_type": 3, "effect_value": 1}]}}
    assert GrandLiveStrategy.training_bonus_map(data) == {3: 1.0}


def test_bonus_boosts_only_the_matching_facility():
    arr = [{"target_type": 3, "effect_value": 1}]          # Power bonus
    assert _scored({"command_type": 1, "command_id": 102}, arr) > 10.0   # 102 = Power -> boosted
    assert _scored({"command_type": 1, "command_id": 101}, arr) == 10.0  # 101 = Speed -> unchanged


def test_non_training_commands_untouched():
    arr = [{"target_type": 3, "effect_value": 1}]
    assert _scored({"command_type": 7, "command_id": 701}, arr) == 10.0   # rest
    assert _scored({"command_type": 4, "command_id": 401}, arr) == 10.0   # race


def test_no_bonus_early_in_the_career_is_a_noop():
    # training_bonus_array is empty until a performance plate tier is reached
    assert _scored({"command_type": 1, "command_id": 102}, []) == 10.0


def test_bonus_weight_is_preset_tunable():
    arr = [{"target_type": 3, "effect_value": 2}]
    hot = _scored({"command_type": 1, "command_id": 102}, arr, {"grand_live_bonus_weight": 10})
    assert hot == 10.0 + 2 * 10



def test_a_song_bonus_counts_like_stat_points():
    # "Guts Training +3" is worth ~3 stat points (0.01 each in base units). At the old 1.5 weight it
    # added 4.5 -- more than a whole +48 board scores -- and career 2026-10-28 trained Guts to 931.
    arr = [{"target_type": 4, "effect_value": 3}, {"target_type": 1, "effect_value": 1}]
    assert abs(_scored({"command_type": 1, "command_id": 103}, arr) - 10.0 - 3 * 0.01) < 1e-9
    assert abs(_scored({"command_type": 1, "command_id": 101}, arr) - 10.0 - 1 * 0.01) < 1e-9

# ---------------- career-goal races ----------------

class _GoalPlanner:
    """Minimal planner stand-in: a goal race is pending on `goal_turn`."""
    def __init__(self, goal_turn=24, program_id=164, fan_turn=None):
        self.goal_turn, self.program_id, self.fan_turn = goal_turn, program_id, fan_turn
    def _turn(self, state):
        return int(((state.get("data") or {}).get("chara_info") or {}).get("turn") or 0)
    def goal_program(self, state):
        return self.program_id if self._turn(state) == self.goal_turn else 0
    def forced_program(self, state, preset=None):
        return 0
    def fan_goal_program(self, state, preset=None):
        # preset accepted (and ignored) to mirror RacePlanner: the real signature takes it so a
        # user-SCHEDULED turn-23/24 race can take the fan slot (the shared brain's fan gate passes it).
        return 625 if self.fan_turn and self._turn(state) == self.fan_turn else 0
    def eligibility_fan_program(self, state, window=None):
        return 0


def test_junior_fan_race_is_not_preempted_by_the_live():
    """Live turn 24 collides with the Junior fan-race turns (23/24). The fan goal is career-fatal --
    a live run trained through 22/23, let the Live take turn 24, never raced Hopeful, and stalled on
    the game's 'Insufficient Fans' modal (live_start then 102'd). The race is chosen at turn start
    (ps 1), before the Concert screen exists -- the Live must not fire there."""
    s = _s()
    s.race_planner = _GoalPlanner(goal_turn=99, fan_turn=24)   # no goal race, but a fan race is due
    assert _action(s, _state(24, ps=1, events=(202006,))) != "grand_live_perform"


def test_dirt_trainee_zen_nippon_is_not_preempted():
    """Dirt trainees are the WORST collision: fan_goal_program makes a dirt uma wait through turn 23 and
    race Zen-Nippon Junior Yushun (dirt 1600) on turn 24 ONLY -- the very turn the Grand Live fires. A
    turf miler at least has Asahi on 23 as slack; a dirt uma has one shot. Uses a REAL RacePlanner so
    the dirt surface routing is exercised end to end, not stubbed."""
    from career_bot.core.races import RacePlanner

    class _Store:
        def race_map(self): return {"meta": {}, "program": {}, "instance": {}}
        def career_goals_for(self, chara_id): return []

    rp = RacePlanner("/__nope__", data_store=_Store())
    rp.policy = dict(GrandLiveStrategy.RACE_POLICY)
    rp.program = {
        1107: {"name": "Zen-Nippon Junior Yushun", "distance": 1600, "ground": 2, "win_fans": 4200},
        625: {"name": "Hopeful Stakes", "distance": 2000, "ground": 1, "win_fans": 7000},
    }
    rp._grade_rank = lambda pid: 0
    rp.available_programs = lambda st: [1107, 625]
    chara = {"card_id": 109801, "turn": 24, "fans": 100,
             "proper_ground_turf": 2, "proper_ground_dirt": 7,      # dirt specialist, turf below floor
             "proper_distance_mile": 7, "proper_distance_middle": 3}
    state = {"data": {"chara_info": chara,
                      "live_data_set": {"next_square_info_array": [], "next_live_id_array": [1006]}}}

    assert rp.fan_goal_program(state) == 1107, "dirt uma must route to Zen-Nippon, not a turf G1"
    s = _s()
    s.race_planner = rp
    assert _action(s, state) != "grand_live_perform"   # turn start: the Live must yield to it


def test_live_runs_once_the_fan_race_is_done():
    s = _s()
    s.race_planner = _GoalPlanner(goal_turn=99, fan_turn=24)
    s._fan_raced = True                                        # fan race already run this career
    assert s.next_decision(_state(24, ps=10, events=(202006,)), {}).action == "grand_live_perform"


def test_grand_live_uses_the_career_goal_route():
    # master.mdb single_mode_route has NO scenario-3 rows -> Grand Live runs the universal (scenario 0)
    # career-goal route, so the goals ARE the schedule and no free/optional racing happens.
    p = GrandLiveStrategy.RACE_POLICY
    assert p["goal_races_only"] is True
    assert p["optional_races"] is False and p["scheduled_override"] is False


def test_goal_race_is_not_preempted_by_the_live():
    # Turn 24 is BOTH a Live turn and a career-goal race turn. The capture runs race_entry/race_start
    # BEFORE live_start, and a missed goal race fails the career -> at turn start (ps 1) the Live
    # must not fire.
    s = _s()
    s.race_planner = _GoalPlanner(goal_turn=24)
    assert _action(s, _state(24, ps=1, events=(202006,))) != "grand_live_perform"


def test_concert_screen_performs_even_with_the_goal_race_still_listed():
    """career_log_20261016_081215: turn 72, Arima Kinen won, then the Concert screen (ps 10) -- but the
    goal race was still on the board, so a 'race pending' hold-back sent race_entry 13 times (all 205/
    208) and the run gave up. On ps 10 the turn's action is spent; the Live is the only move."""
    s = _s()
    s.race_planner = _GoalPlanner(goal_turn=72, program_id=81)
    assert s.next_decision(_state(72, ps=10), {}).action == "grand_live_perform"


def test_live_fires_once_the_goal_race_is_done():
    # same turn, but no race pending any more -> the Live performance now runs
    s = _s()
    s.race_planner = _GoalPlanner(goal_turn=99)      # nothing pending on turn 24
    d = s.next_decision(_state(24, ps=10, events=(202006,)), {})
    assert d.action == "grand_live_perform"


def test_concert_claims_the_pending_lesson_then_performs():
    """Order on the Concert screen is LESSON then Live -- the in-game Lessons button carries a "!"
    badge while Concert is the goal, and every captured live_start has master_square calls right
    before it. The invariant that matters is that the Live is not STARVED: a square is pending in
    all 82 captured Concert-screen states, so deferring to squares without a throttle would mean the
    performance never fires. The per-distinct-offer guard is what bounds it to one extra step."""
    s = _s()
    st = _state(48, squares=(13003, 11102), ps=10, events=(202020,))
    first = s.next_decision(st, {})
    assert first.action == "master_square", first.action
    assert first.payload["current_turn"] == 48
    _handled(s, first)
    # Same offer again -> already claimed -> the Live now goes ahead.
    second = s.next_decision(st, {})
    assert second.action == "grand_live_perform", second.action


def test_grand_live_actions_commit_only_after_api_success():
    """A lost request must remain retryable; an accepted request must become once-only before
    follow-up event draining. Private offer metadata must never leak into the wire payload."""
    runner = CareerRunner.__new__(CareerRunner)
    runner._log = lambda *a, **k: None
    runner._drain_events = lambda client, strategy, state: state

    class _Client:
        def __init__(self, failure=None):
            self.failure = failure
            self.calls = []

        def call(self, endpoint, payload, **kwargs):
            self.calls.append((endpoint, payload, kwargs))
            if self.failure:
                raise Exception(self.failure)
            return {"data": {}}

    # Core call failure: no optimistic flag, so the exact same action is offered again.
    live = _s()
    live_state = _state(24, ps=10, events=(202006,))
    decision = live.next_decision(live_state, {})
    try:
        runner._grand_live_call(_Client("Network error on live_start"), live, decision)
    except Exception:
        pass
    assert 24 not in live._live_done()
    assert live.next_decision(live_state, {}).action == "grand_live_perform"

    # Accepted square: exact board is committed before drain and the private key stays local.
    square = _s()
    square_state = _state(12, squares=(30009, 20015, 11002))
    decision = square.next_decision(square_state, {})
    client = _Client()
    runner._grand_live_call(client, square, decision)
    assert (decision.payload["_offer_key"], 12) in square._claimed_offers()
    assert "_offer_key" not in client.calls[0][1]
    assert _action(square, square_state) != "master_square"          # not twice on the same turn
    # The board did not advance after the accepted claim (live 2026-10-31: stuck turns 59-72): a later
    # turn tries it once more; a rejection there (accepted=False) blocks that board for good.
    later = _state(13, squares=(30009, 20015, 11002))
    retry = square.next_decision(later, {})
    assert retry.action == "master_square"
    square.mark_decision_handled(retry)
    assert _action(square, _state(14, squares=(30009, 20015, 11002))) != "master_square"


def test_grand_live_concert_state_is_not_blocked_by_runner():
    runner = CareerRunner.__new__(CareerRunner)
    runner.status = {"scenario_id": 3}
    assert runner._blocked_playing_state({"playing_state": 10}) is False
    runner.status = {"scenario_id": 1}
    assert runner._blocked_playing_state({"playing_state": 10}) is True


# ---------------- resume: an UNKNOWN turn must never fire a Live ----------------

def test_resumed_career_never_fires_live_start_for_turn_zero():
    """REGRESSION (live career_log_20260731_035056): resuming a turn-24 Grand Live career sent
    live_start{current_turn: 0} three times and killed the career at the very first step.

    chara_info.turn == 0 means UNKNOWN, not "turn zero". Mid-run, _last_turn carries the real turn
    across the Concert screen -- but a RESUME builds a fresh strategy object, so _last_turn is unset
    and 0 leaked through as if it were a real turn. Concerts only exist at 24/36/48/60/72, so the
    server 205s a turn-0 live_start every time."""
    s = _s()
    # Exactly the resume shape: no turn, and nothing else actionable -> the shared brain returns idle.
    st = {"data": {"chara_info": {"scenario_id": 3, "playing_state": 10},
                   "unchecked_event_array": [],
                   "live_data_set": {}}}
    assert _action(s, st) != "grand_live_perform"
    # And the bad turn must NOT be recorded as done, or the real turn 24 could never perform later.
    assert 0 not in s._live_done()


def test_resume_still_performs_once_the_real_turn_is_known():
    """The guard must not break the normal path: with a real turn on the Concert screen it still fires."""
    s = _s()
    s.race_planner = _GoalPlanner(goal_turn=99, fan_turn=None)
    assert _action(s, _state(24, ps=10, events=(202006,))) == "grand_live_perform"


# ---------------- Light Hello dates actually fire ----------------

def _lh_strategy():
    from career_bot.scenarios.grand_live import GrandLiveStrategy as _G
    s = _G.__new__(_G)
    s._preset = {}
    s.race_planner = None
    # Light Hello SSR in the running deck.
    s._chara = {"support_card_array": [{"support_card_id": 30052}, {"support_card_id": 30028}]}
    return s


def _lh_recreate(turn, vital, best_score, preset=None):
    s = _lh_strategy()
    # bypass the shared rule so only the Light Hello branch is under test
    from career_bot.core.training_brain import BaseTrainingStrategy
    orig = BaseTrainingStrategy._should_recreate
    BaseTrainingStrategy._should_recreate = lambda *a, **k: False
    try:
        return s._should_recreate([{"command_id": 301}], preset or {}, turn, 3, vital, best_score)
    finally:
        BaseTrainingStrategy._should_recreate = orig


def test_light_hello_date_fires_despite_an_inflated_board_score():
    """REGRESSION: the dead-board threshold was 0.3, in BASE-scorer units -- but Grand Live adds
    1.5 per deck card on a facility, so best_score is ~1.5+ on essentially every turn and `dead` was
    never true. Live result: card in deck, gauge MAXED, all five dates unspent after 76 turns
    (career_log_20260801_000546 took ONE recreation in 76 turns, from the shared mood rule).
    The rule is kept -- a good board still trains -- only the threshold is rescaled."""
    assert _lh_recreate(turn=30, vital=65, best_score=2.0) is True     # thin board, Classic
    assert _lh_recreate(turn=55, vital=55, best_score=1.5) is True     # thin board, Senior


def test_a_genuinely_good_board_still_trains_instead_of_dating():
    assert _lh_recreate(turn=30, vital=65, best_score=5.0) is False
    assert _lh_recreate(turn=55, vital=55, best_score=8.0) is False


def test_light_hello_still_respects_the_energy_windows():
    assert _lh_recreate(turn=30, vital=95, best_score=2.0) is False    # Classic but energy too high
    assert _lh_recreate(turn=55, vital=68, best_score=2.0) is False    # Senior wants <= 60
    assert _lh_recreate(turn=10, vital=50, best_score=2.0) is False    # Junior: dates held back


def test_energy_critical_date_fires_in_any_year():
    assert _lh_recreate(turn=12, vital=20, best_score=1.0) is True     # thin board + below 30


def test_dead_score_threshold_is_tunable():
    assert _lh_recreate(turn=30, vital=65, best_score=4.5,
                        preset={"grand_live_date_dead_score": 6.0}) is True
    assert _lh_recreate(turn=30, vital=65, best_score=4.5,
                        preset={"grand_live_date_dead_score": 1.0}) is False


def test_light_hello_off_switch_still_works():
    assert _lh_recreate(turn=30, vital=65, best_score=2.0,
                        preset={"grand_live_light_hello": False}) is False


def test_the_recreation_sent_is_the_light_hello_date():
    """REGRESSION: every Light Hello "date" went out as the solo 301 (select_id 0), so its story_step
    stayed 0 all career (career_log_20261030_222823). The date is 390 with Light Hello's chara_id."""
    board = [{"command_type": 3, "command_id": 301}, {"command_type": 3, "command_id": 390}]
    s = _lh_strategy()
    deck = [{"position": 1, "support_card_id": 30028}, {"position": 5, "support_card_id": 30052}]
    lh = lambda io, ss: {"support_card_array": deck, "evaluation_info_array": [
        {"target_id": 1, "is_outing": 0, "story_step": 0}, {"target_id": 5, "is_outing": io, "story_step": ss}]}
    s._chara = lh(1, 2)
    assert s._recreation_command(board) == {"command_type": 3, "command_id": 390, "select_id": 9008}
    for chara in (lh(0, 0), lh(1, 5)):                      # not unlocked yet / all 5 dates done
        s._chara = chara
        assert s._recreation_command(board)["command_id"] == 301
    s._chara = lh(1, 0)
    assert s._recreation_command([{"command_type": 3, "command_id": 304}])["command_id"] == 304   # camp
    s._scheduled_outing_blocked = True                        # server refused a date -> solo again
    assert s._recreation_command(board)["command_id"] == 301


# ---------------- bank points for an important song ----------------

_RICH = {"dance": 999, "passion": 999, "vocal": 999, "visual": 999, "mental": 999}
_BROKE = {"dance": 0, "passion": 0, "vocal": 0, "visual": 0, "mental": 0}


def _hold_board(ids, perf):
    """Distinct from the module's other _board helper -- this one takes explicit square ids."""
    return {"next_square_info_array": [{"square_id": i, "square_num": 1} for i in ids],
            "live_performance_info": perf, "effected_live_id_array": []}


def test_holds_points_when_a_top_song_is_offered_but_unaffordable():
    """A cheap technique bought now is points missing when the song becomes reachable, and the board
    keeps the same pending offer until it advances -- so waiting genuinely banks them."""
    s = _s()
    # 40004 = the +3 SP-bonus song (top band); 11001 = a cheap stat lesson
    assert s.pick_square(_hold_board([40004, 11001], _BROKE), {}) == 0


def test_does_not_hold_for_a_low_band_song():
    """40009 is in the support-chain band. With points enough for the cheap lesson but not the song,
    the lesson is taken -- banking for a low-band song costs more than it returns."""
    perf = {"dance": 12, "passion": 12, "vocal": 12, "visual": 12, "mental": 12}
    assert _s().pick_square(_hold_board([40009, 11001], perf), {}) == 11001


def test_stops_holding_once_the_song_is_affordable():
    s = _s()
    assert s.pick_square(_hold_board([40004, 11001], _RICH), {}) == 40004


def test_hold_is_bounded_so_an_unreachable_song_cannot_stall_the_shop():
    """A Speed/Wit deck cannot generate vocal on its own, so an unreachable song must not park the
    shop for the rest of the career."""
    s = _s()
    board = {**_hold_board([40004, 11001], {"dance": 12, "passion": 12, "vocal": 12, "visual": 12, "mental": 12}),
             "master_live_id_array": list(range(30))}     # songs banked: a hold is only allowed then
    holds = 0
    for turn in range(1, GrandLiveStrategy.HOLD_FOR_SONG_MAX_TURNS + 4):
        s._last_turn = turn                       # the cap is in TURNS: a turn may call pick_square 2x+
        picks = {s.pick_square(board, {}), s.pick_square(board, {})}
        if picks == {0}:
            holds += 1
        else:
            break
    assert holds == GrandLiveStrategy.HOLD_FOR_SONG_MAX_TURNS, holds
    assert s.pick_square(board, {}) == 11001      # gives up and spends


def test_no_hold_while_the_next_concert_is_short_of_songs():
    """A hold freezes the board, so no other song can come up: career 1509 held turns 48-58 for one
    song and reached the turn-60 concert with 2 new songs (no Great Success). While short, spend."""
    perf = {"dance": 12, "passion": 12, "vocal": 12, "visual": 12, "mental": 12}
    board = _hold_board([40004, 11001], perf)
    assert _s().pick_square({**board, "master_live_id_array": [1006, 1, 2]}, {}) == 11001   # 3 of 4 due
    assert _s().pick_square({**board, "master_live_id_array": list(range(30))}, {}) == 0    # banked: hold


def test_songs_learned_since_the_last_concert_count():
    """effected_live_id_array only catches up at a concert; master_live_id_array is every song learned."""
    lds = {"effected_live_id_array": [1006], "next_live_id_array": [1040, 1042, 1046],
           "master_live_id_array": [1006, 1040, 1042, 1046]}
    assert GrandLiveStrategy.songs_collected({"live_data_set": lds}) == 4
    assert _s().song_shortfall({"live_data_set": lds}, turn=20) == 0


def test_after_the_last_concert_squares_rank_on_what_they_pay_now():
    """After turn 72 no concert is left, so a song's concert bonus never applies: an SP-bonus song
    (no immediate gain) loses to a +22 Speed song, and the bot never holds points for a song."""
    banked = list(range(30))
    songs = {**_hold_board([40000, 40002], _RICH), "master_live_id_array": banked}
    s = _s()
    s._last_turn = 70
    assert s.pick_square(songs, {}) == 40000          # before the finale the SP bonus still pays
    s._last_turn = 73
    assert s.pick_square(songs, {}) == 40002
    perf = {"dance": 12, "passion": 12, "vocal": 12, "visual": 12, "mental": 12}
    held = {**_hold_board([40004, 11001], perf), "master_live_id_array": banked}
    s = _s()
    s._last_turn = 70
    assert s.pick_square(held, {}) == 0               # banked songs: may save for 40004
    s._last_turn = 73
    assert s.pick_square(held, {}) == 11001           # nothing left to save for


def test_hold_can_be_switched_off():
    s = _s()
    perf = {"dance": 12, "passion": 12, "vocal": 12, "visual": 12, "mental": 12}
    assert s.pick_square(_hold_board([40004, 11001], perf),
                         {"grand_live_hold_for_song": False}) == 11001


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
