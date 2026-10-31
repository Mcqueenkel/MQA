import gzip
import base64
import msgpack
import threading
import time
import json
import os
import random
import math
from datetime import datetime
from pathlib import Path

from career_bot.scenarios.mant import MantStrategy  # noqa: E402
from career_bot.core.training_brain import GROUP_OUTING_COMMAND_ID  # noqa: E402
from career_bot.scenarios.ura import UraStrategy
from career_bot.scenarios.unity import UnityStrategy, UnityScenario
from career_bot.scenarios.grand_live import GrandLiveStrategy
from career_bot.core.presets import resolve_running_style
from career_bot.core.races import RacePlanner
from career_bot.core.skills import SkillBuyer
from career_bot.core.data_store import DataStore
from career_bot.scenarios.mant_items import MantItemManager, ITEM_NAMES, SHOP_ITEM_COSTS, DISPLAY_TO_ID, display_to_slug


from career_bot.core.report import (new_report, add_event, add_api_call, add_decision, finish_report,
                                    write_report, set_error, capture_career_identity, add_race, get_turn)
from career_bot.core.delay import dna_sleep, dna_gauss, backoff_sleep, use_dna
from career_bot.core import notify
from career_bot.core import ai_learn
from uma_api.client import CIRCUIT_COOLDOWN_STOP as COOLDOWN_STOP, StateRecoveryError, is_api_error


# SID / version desync family. These are NOT fatal: the client rotates the SID on any error, so the
# cure is to reload fresh career state and carry on. Every other turn phase already retries on them
# (see _run's per-phase handlers); the race close-out (race_end / race_out) used to omit them and
# CRASHED the career instead -- which left the career active server-side and wedged the whole loop
# on "Cannot start a new career while another is active".
RACE_DESYNC_ERRORS = (201, 205, 208, 217)


def _is_desync(exc):
    """A RACE_DESYNC_ERRORS rejection or a network failure. Matched on the result code, never a bare
    substring: the error text embeds servertime/viewer_id digits (see uma_api.client.is_api_error)."""
    return "Network error" in str(exc) or is_api_error(exc, *RACE_DESYNC_ERRORS)


STRATEGIES = {
    1: UraStrategy,   # URA Finale
    2: UnityStrategy,  # Unity / Aoharu team scenario ("Unity Cup")
    3: GrandLiveStrategy,  # Grand Live / "Grand Concert" -- LIVE and playable: single_mode_live/* routing,
                           # Master Square claiming and the Concert (live_start) are all wired and have
                           # completed real careers. See grand_live.py.
    4: MantStrategy,  # MANT / Trackblazer ("TS Climax")
}


def resolve_scenario_id(client, preset):
    """Scenario id for strategy dispatch: prefer the LIVE career's scenario (the client pins
    current_scenario_id from chara_info and routes API calls by it) when a strategy exists for it,
    else the preset's scenario_id, else MANT (4). Without this a Unity/Team career (scenario 2)
    whose preset omits scenario_id defaults to MANT and never handles the Unity Cup."""
    try:
        live = int(getattr(client, "current_scenario_id", None))
    except (TypeError, ValueError):
        live = None
    return live if live in STRATEGIES else int((preset or {}).get("scenario_id") or 4)


def runtime_output_root(base_dir):
    override = os.environ.get("UMA_RUNTIME_DIR")
    if override:
        return Path(override).expanduser().resolve()

    base = Path(base_dir).resolve()
    for candidate in (base, *base.parents):
        if (candidate / ".git").exists():
            return candidate / "uma_runtime"
    # No .git anywhere (a downloaded ZIP, not a `git clone`): put uma_runtime INSIDE base_dir, the same
    # place notify.py uses (Path(base_dir)/"uma_runtime"). The old base.parent fallback split the two:
    # career logs went to <parent>/uma_runtime/bot_logs while career_history.json went to
    # <base>/uma_runtime -- so a non-git copy's bot_logs looked empty even though logs WERE written,
    # just one folder up (diagnosed from a friend's archive: career_history present, bot_logs empty).
    return base / "uma_runtime"

TRAINING_LABELS = {
    101: "Speed",
    102: "Power",
    103: "Guts",
    105: "Stamina",
    106: "Wit",
    601: "Speed",
    602: "Stamina",
    603: "Power",
    604: "Guts",
    605: "Wit",
}


class CareerRunner:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.report = None
        self.lock = threading.Lock()
        self.thread = None
        self.stop_requested = False
        self.pause_requested = False
        self.burn_clocks = False
        self._loop_index = 1
        self._loop_target = 1
        # One shared reference-data store for the whole runner: RacePlanner, SkillBuyer and
        # (via the strategy) EventManager/CareerForecaster all read validated data through it.
        self.data_store = DataStore(base_dir)
        self.race_planner = RacePlanner(base_dir, data_store=self.data_store)
        self.skill_buyer = SkillBuyer(base_dir, data_store=self.data_store)
        self.item_manager = MantItemManager()
        self._unity = UnityScenario(self)   # all Unity Cup (scenario 2) runner-side ops, isolated
        self.status = {
            "running": False,
            "paused": False,
            "preset": "",
            "scenario_id": 0,
            "turn": 0,
            "steps": 0,
            "last_action": "",
            "last_error": "",
            "finished": False,
            "circuit_tripped": False,
            "skills_bought": 0,
            "items_bought": 0,
            "items_used": 0,
            "clocks_used": 0,
            "log": [],
            "action_history": [],
        }

    def _init_debug_log(self, preset=None, scenario_id=4):
        self.report = new_report(preset, scenario_id)

    def _debug(self, event, state=None, data=None):
        row = {
            "event": event,
        }
        if state:
            d = state.get("data") or {}
            chara = d.get("chara_info") or {}
            free = d.get("free_data_set") or {}
            row["turn"] = int(chara.get("turn") or 0)
            row["skill_point"] = int(chara.get("skill_point") or 0)
            row["mant_coin"] = int(free.get("coin_num") if free.get("coin_num") is not None else free.get("gained_coin_num") or 0)
            row["motivation"] = int(chara.get("motivation") or 0)
            row["stats"] = self._turn_stats(chara)
            # Grand Live self-diagnosis. This scenario has several screens the shared brain has never
            # seen (Concert, Master Square, Race Day), and every stall so far was a gate reading a state
            # field whose meaning differs here -- each one needed an external UmaDumpy capture to spot.
            # Recording the live state INLINE makes a stalled career explain itself from its own log.
            if int(self.status.get("scenario_id") or 0) == 3:
                lds = d.get("live_data_set") or {}
                row["grand_live"] = {
                    "playing_state": chara.get("playing_state"),
                    "turn_field": chara.get("turn"),
                    "performance": lds.get("live_performance_info") or {},
                    "next_squares": [sq.get("square_id") for sq in (lds.get("next_square_info_array") or [])],
                    "next_live_ids": lds.get("next_live_id_array") or [],
                    "songs": len(lds.get("effected_live_id_array") or []),
                    "training_bonus": lds.get("training_bonus_array") or [],
                    "unchecked_events": [e.get("event_id") for e in (d.get("unchecked_event_array") or [])],
                    "commands": [[c.get("command_type"), c.get("command_id"), c.get("is_enable")]
                                 for c in ((d.get("home_info") or {}).get("command_info_array") or [])],
                    "race_condition": [r.get("program_id") for r in (d.get("race_condition_array") or [])],
                }
        if data:
            row.update(data)
        if self.report:
            add_event(self.report, row)

    def start(self, client, preset, initial_result, max_steps=2500, burn_clocks=False, dev_mode=False, finish_to_end=False):
        with self.lock:
            if self.status["running"]:
                raise RuntimeError("Career runner already active")
            # Strategy follows the LIVE career's scenario (Unity/Team -> UnityStrategy) even when the
            # preset omits scenario_id -- otherwise a team career is driven by MANT and the Unity Cup
            # turn desyncs. See resolve_scenario_id.
            scenario_id = resolve_scenario_id(client, preset)
            strategy_cls = STRATEGIES.get(scenario_id)
            if not strategy_cls:
                raise RuntimeError(f"No runner for scenario {scenario_id}")
            # Refuse a scenario whose API layer isn't wired yet (API_READY=False, e.g. Grand Live /
            # scenario 3): running it would drive the career on the WRONG namespace and spam the live
            # game with errors. Fail fast with a pointer instead. See scenarios/grand_live.py.
            if getattr(strategy_cls, "API_READY", True) is False:
                raise RuntimeError(
                    f"Scenario {scenario_id} ({strategy_cls.__name__}) is not playable yet: its game-API "
                    f"layer is unmapped. See career_bot/scenarios/grand_live.py for what a capture must "
                    f"provide, then set API_READY=True once verified.")
            self.stop_requested = False
            self.pause_requested = False
            self.burn_clocks = burn_clocks
            self.dev_mode = dev_mode
            # True = play the single career through to its natural finish (turn 78);
            # False = hard-stop at turn 77 (UI "FINISH" toggle). Loops always finish.
            self.finish_to_end = finish_to_end
            self.race_planner = RacePlanner(self.base_dir, data_store=self.data_store)
            self.skill_buyer = SkillBuyer(self.base_dir, data_store=self.data_store)
            self.item_manager = MantItemManager()
            # True skill_point AFTER the end-of-career skill dump. The per-turn stats
            # snapshot is taken at turn START (before the finale buy), so the notify
            # embed would otherwise report the pre-dump SP. Captured at finish below.
            self._final_skill_point = None
            # Climax stat-gain capture: per-climax-turn "before" stats + which were already logged.
            # Reset each career so loop runs don't carry over.
            self._climax_before = {}
            self._climax_logged = set()
            # Why a finish decision ended the career ("goal failed" vs a natural finish). Reset per
            # career: in a loop run a stale reason mislabelled every later career's outcome.
            self._career_end_reason = ""
            self.status = {
                "running": True,
                "paused": False,
                "preset": preset.get("name", ""),
                "scenario_id": scenario_id,
                "turn": 0,
                "steps": 0,
                "last_action": "started",
                "last_error": "",
                "finished": False,
                "circuit_tripped": False,
                "skills_bought": 0,
                "items_bought": 0,
                "items_used": 0,
                "clocks_used": 0,
                "log": [],
                "action_history": [],
            }
            self.report = new_report(preset, scenario_id)
            if client:
                client.report = self.report
                def _on_api_log(direction, ep, data, req_id=None):
                    if self.report:
                        import time
                        add_api_call(self.report, {
                            "ts": time.time(),
                            "direction": direction,
                            "endpoint": ep,
                            "data": data,
                            "req_id": req_id,
                            "turn": self.status.get("turn", 0)
                        })
                client.on_api_log = _on_api_log
                # Let Stop cut short a circuit-breaker cooldown (the client polls this while it waits)
                # instead of hanging up to 300s and then still sending one more request. Cleared when
                # the run ends so main.py's own calls between runs are never refused.
                client.should_abort = lambda: self.stop_requested
            self._log_locked("started", 0, f"preset {preset.get('name', '')} (burn_clocks={burn_clocks})")
            self.thread = threading.Thread(target=self._run, args=(client, preset, initial_result, strategy_cls(self.race_planner), max_steps), daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            self.stop_requested = True

    # --- TS climax stat-gain capture --------------------------------------------------------
    CLIMAX_RACE_TURNS = (74, 76, 78)

    def _climax_stat_snapshot(self, state):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        snap = {k: int(chara.get(k) or 0)
                for k in ("speed", "stamina", "power", "guts", "wit", "skill_point")}
        owned = {}
        try:
            if self.item_manager:
                owned = self.item_manager._owned_map(data.get("free_data_set") or {})
        except Exception:
            owned = {}
        snap["master"] = int((owned or {}).get("Master Cleat Hammer", 0) or 0)
        snap["artisan"] = int((owned or {}).get("Artisan Cleat Hammer", 0) or 0)
        return snap

    # --- Grand Live (scenario 3) ------------------------------------------------------------------
    @staticmethod
    def _keep_race_board(new_state, prev_state):
        """master_square answers WITHOUT race_condition_array (125 of 125 captured replies), so the
        next decision on the SAME turn saw no races on offer and silently skipped scheduled races
        (1 ran, 12 skipped when a lesson was claimed first). Claiming a lesson doesn't change the
        turn's race board, so carry it over -- only when missing and the turn hasn't moved on."""
        new_data = (new_state or {}).get("data")
        prev_data = (prev_state or {}).get("data") or {}
        if not isinstance(new_data, dict) or "race_condition_array" in new_data:
            return new_state
        if "race_condition_array" not in prev_data:
            return new_state
        new_turn = int((new_data.get("chara_info") or {}).get("turn") or 0)
        prev_turn = int((prev_data.get("chara_info") or {}).get("turn") or 0)
        if new_turn and prev_turn and new_turn != prev_turn:
            return new_state
        new_data["race_condition_array"] = prev_data["race_condition_array"]
        return new_state

    def _grand_live_call(self, client, strategy, decision, prev_state=None):
        """Run one Grand-Live-only call and return the refreshed state.

          master_square      -> single_mode_free/master_square {current_turn, square_id}  (claim a square)
          grand_live_perform -> single_mode_free/live_start    {current_turn}             (the Live)

        Both are namespace-routed to single_mode_live/* for scenario 3. Post-call events are drained the
        same way every other action does, so a Live/square that pops a story event resolves cleanly.
        """
        payload = decision.payload or {}
        turn = int(payload.get("current_turn") or 0)
        if decision.action == "master_square":
            square_id = int(payload.get("square_id") or 0)
            self._log("grand_live_square", turn, f"claim square {square_id}")
            state = client.call("single_mode_free/master_square",
                                {"square_id": square_id, "current_turn": turn}, retry_205=1) or {}
        else:
            # live_start needs the pending EVENT ID, not just the turn -- sending {current_turn} alone
            # is what the server answered 102 to (capture: live_start{event_id: 202006, current_turn: 24}).
            # Shape confirmed in TWO captures (20260723_170405 turn 24 event 202006; 20260723_173458
            # turn 60 event 202027): live_start takes {event_id, choice_number, current_turn}.
            # choice_number is REQUIRED -- it is present in both, and omitting a field the client always
            # sends is exactly what the server answers 102 to.
            args = {"current_turn": turn}
            event_id = int(payload.get("event_id") or 0)
            if event_id:
                args["event_id"] = event_id
                args["choice_number"] = int(payload.get("choice_number") or 0)
            self._log("grand_live_live", turn, f"Grand Live performance (event {event_id or 'n/a'})")
            state = client.call("single_mode_free/live_start", args, retry_205=1) or {}
        # Commit the once-only guard only after the action itself was accepted. Do this before event
        # draining: if a subsequent check_event loses the network response, replaying a square/Live
        # that already landed is just as unsafe as suppressing one that never landed.
        marker = getattr(strategy, "mark_decision_handled", None)
        if callable(marker):
            marker(decision, accepted=True)
        state = self._drain_events(client, strategy, state)
        if decision.action == "master_square":
            state = self._keep_race_board(state, prev_state)
        return state

    def _is_ts_climax_scenario(self):
        """The TS-Climax races (turns 74/76/78) exist ONLY in MANT/Trackblazer (scenario 4). For
        Unity/URA/Grand Live, turns 74/76/78 are ordinary senior turns -- capturing 'climax gains'
        there logs a phantom climax race the scenario never runs. Gate all capture to MANT."""
        return int((self.status or {}).get("scenario_id") or 0) == 4

    def _capture_climax_before(self, turn, state):
        """First time we reach a climax race turn, record stats + hammer stock BEFORE the race."""
        if not self._is_ts_climax_scenario():
            return
        if turn in self.CLIMAX_RACE_TURNS and turn not in getattr(self, "_climax_before", {}):
            self._climax_before[turn] = self._climax_stat_snapshot(state)

    def _resolve_climax_gains(self, current_turn, state, sp_override=None):
        """Once we're PAST a climax turn (the 'After the ... Climax Race' event has applied), log
        the stat delta AND which cleat hammer (if any) was spent on that race -- inferred from the
        drop in hammer stock. Pass current_turn > 78 (e.g. at finish) to resolve the final climax.
        sp_override pins the SP 'after' to a pre-skill-dump snapshot. Persists to the career log."""
        if not self._is_ts_climax_scenario():
            return
        after = self._climax_stat_snapshot(state)
        if sp_override is not None:
            after["skill_point"] = int(sp_override)
        keys = ("speed", "stamina", "power", "guts", "wit", "skill_point")
        labels = ("Spd", "Sta", "Pow", "Guts", "Wit", "SP")
        for ct in self.CLIMAX_RACE_TURNS:
            before = getattr(self, "_climax_before", {}).get(ct)
            if before is None or ct in getattr(self, "_climax_logged", set()) or current_turn <= ct:
                continue
            self._climax_logged.add(ct)
            delta = {k: after[k] - before[k] for k in keys}
            parts = ", ".join(f"+{delta[k]} {lbl}" for k, lbl in zip(keys, labels) if delta[k])
            if before.get("master", 0) - after.get("master", 0) >= 1:
                hammer = "35% Master hammer"
            elif before.get("artisan", 0) - after.get("artisan", 0) >= 1:
                hammer = "20% Artisan hammer"
            else:
                hammer = "no hammer"
            n = {74: 1, 76: 2, 78: 3}.get(ct, "?")
            line = f"Climax-{n} (t{ct}) stat gain: {parts or '(none)'}  [{hammer}]"
            print(line, flush=True)
            self._log("climax_gain", ct, line)
            if getattr(self, "report", None) is not None:
                self.report.setdefault("climax_gains", []).append(
                    {"climax": n, "turn": ct, "hammer": hammer, "gain": delta})

    def pause(self):
        with self.lock:
            if self.status.get("running"):
                self.pause_requested = True
                self.status["paused"] = True
                self._log_locked("pause", self.status.get("turn", 0), "career paused")

    def resume(self):
        with self.lock:
            self.pause_requested = False
            self.status["paused"] = False
            self._log_locked("resume", self.status.get("turn", 0), "career resumed")

    def _is_paused(self):
        with self.lock:
            return self.pause_requested

    def set_loop_info(self, index, target):
        # Which career this is within a loop (index) and the loop size (target,
        # 0 = infinite). Used only for the Discord notification.
        self._loop_index = int(index or 1)
        self._loop_target = int(target or 0)

    def snapshot(self):
        with self.lock:
            data = dict(self.status)
            data["burn_clocks"] = self.burn_clocks
            return data

    def set_burn_clocks(self, value):
        with self.lock:
            self.burn_clocks = value
            self._log_locked("update_setting", 0, f"burn_clocks set to {value}")

    def _run(self, client, preset, result, strategy, max_steps):
        dna = getattr(client, "_dna", None)
        if dna is not None:
            use_dna(dna)

        state = result or {}
        # The starting hand (trainee, deck, inherits, aptitudes) -- see report.capture_career_identity.
        # Idempotent, so the per-turn call below just fills it in for a RESUMED career, where `result`
        # carries no chara_info.
        capture_career_identity(self.report, state)
        self._notify_card_id = str(((state.get("data") or {}).get("chara_info") or {}).get("card_id") or "")
        self._notify_factor_ids = []
        self._notify_forecast = None
        self._notify_rank = 0
        self._notify_rank_score = 0
        self._forecast_sent = False
        self._last_forecast_summary = None
        # Per-career reset for the group-outing loop-breaker. It lives on this (singleton) runner,
        # so without a reset a prior career's last-outing turn could falsely match the next career's
        # first outing and wrongly trip the no-advance stall -> disable all scheduled outings.
        self._last_outing_turn = None
        # Goal-following: log the trainee's full career-goal schedule once, then a per-turn
        # at-risk warning. Reset per career so a loop run re-logs the new trainee's goals.
        self._goal_schedule_logged = False
        self._goal_logged_turn = None
        self._team_race_fails = 0
        # Per-career state for the race retry guard (see _race_guard_tripped).
        self._race_attempt_turn = None
        self._race_attempt_count = 0
        # Turn whose Grand Live live_start already used its one 205 retry (see the 205 branch below).
        self._live_205_turn = None
        # (turn, program_id) whose MANT pre-race items (hammer / glow stick) already landed: a retry of
        # the same race after a transient race_entry failure must not spend them again.
        self._pre_race_items_for = None
        # Turn whose BEFORE GOAL RACES skill buy already ran (once per goal race, retries included).
        self._goal_skill_turn = None
        last_turn = -1
        # Each career gets its own clock: the pause before every turn is sized so the whole career
        # lands on the Web UI's career length (delay.GateKeeper.wait_turn_delay).
        if hasattr(client, "begin_career_pacing"):
            client.begin_career_pacing()
        same_turn_count = 0
        # Stuck-turn watchdog: a single turn legitimately spans events, items, races and
        # skill checks, so allow many iterations before deciding the loop is stuck on one
        # turn. The circuit breaker only catches SERVER-error storms; this catches a SILENT
        # no-error resume/event loop that would otherwise spin until max_steps.
        stuck_turn_limit = int(os.environ.get("UMA_STUCK_TURN_LIMIT", "75") or 75)
        # ...but DON'T refresh forever: after this many fruitless career-state reloads on the same
        # turn, give up and stop cleanly instead of grinding to max_steps (which just hammers the
        # API on a genuinely stuck career). Tunable via UMA_STUCK_TURN_GIVEUP.
        stuck_giveup = int(os.environ.get("UMA_STUCK_TURN_GIVEUP", "5") or 5)
        stuck_refreshes = 0
        try:
            for i in range(max_steps):
                if self._should_stop():
                    break
                # Auto-backoff: the API client tripped its circuit breaker (too many
                # server errors in a short window -- the server is likely throttling).
                # Stop this career cleanly instead of continuing to hammer the server.
                # circuit_trip_seen is the sticky flag: the client's lazy cooldown clears
                # circuit_tripped inside the very next call (usually an error handler's reload),
                # so checking that alone almost never fired.
                if getattr(client, "circuit_trip_seen", False) or getattr(client, "circuit_tripped", False):
                    msg = ("Auto-backoff: too many server errors in a short time "
                           "(server likely throttling). Stopped to avoid hammering -- "
                           "wait a while before running again.")
                    print(f"AUTO-BACKOFF: stopping career -- {msg}", flush=True)
                    self._log("auto_backoff", self.snapshot().get("turn", 0), msg)
                    self._mark(last_error=msg, last_action="auto-backoff", circuit_tripped=True)
                    self.stop_requested = True
                    break
                # Pause: idle here (no game action taken) until resumed or stopped. The
                # career session stays alive; only the bot's moves are held.
                if self._is_paused():
                    import time
                    while self._is_paused() and not self._should_stop():
                        time.sleep(0.4)
                    if self._should_stop():
                        break
                data = state.get("data") or {}
                chara = data.get("chara_info") or {}
                turn = int(chara.get("turn") or 0)

                if turn and turn != self._goal_logged_turn:
                    self._goal_logged_turn = turn
                    self._log_goal_progress(state, turn)

                # TS climax stat-gain capture: snapshot before each climax race, then log the gain
                # (and which hammer was used) once the turn advances past it.
                # Grand Live: track songs banked (live_data_set.effected_live_id_array) so the finale
                # summary survives into the notify embed even after the career state is torn down.
                if int(self.status.get("scenario_id") or 0) == 3:
                    _lds = ((state.get("data") or {}).get("live_data_set") or {})
                    if _lds:
                        self._grand_live_summary = {
                            "songs": len(_lds.get("effected_live_id_array") or []),
                            "song_target": getattr(strategy, "FINALE_SONG_TARGET", 20),
                        }
                self._capture_climax_before(turn, state)
                self._resolve_climax_gains(turn, state)

                if turn != last_turn:
                    if hasattr(client, "wait_turn_delay"):
                        client.wait_turn_delay(turn)
                    last_turn = turn
                    same_turn_count = 0
                    stuck_refreshes = 0
                elif turn > 0:
                    # Same turn seen again with no advance. After the limit, periodically
                    # re-pull the live career state to break a silent (no-error) resume/event
                    # loop instead of re-issuing the same decision until max_steps.
                    same_turn_count += 1
                    if same_turn_count >= stuck_turn_limit and same_turn_count % 15 == 0:
                        stuck_refreshes += 1
                        if stuck_refreshes > stuck_giveup:
                            # Reloading the career hasn't unstuck the turn -- it's genuinely stuck.
                            # Stop cleanly (same path as the circuit breaker) so the finally-block
                            # still writes the report; don't grind to max_steps hammering the API.
                            msg = (f"turn {turn} stuck after {stuck_giveup} state refreshes -- "
                                   f"stopping cleanly to avoid pointless API hammering")
                            self._log("stuck_turn_giveup", turn, msg)
                            self._mark(last_error=msg, last_action="stuck-stop")
                            self.stop_requested = True
                            break
                        self._log("stuck_turn", turn,
                                  f"same turn {turn} seen {same_turn_count}x -> career-state refresh ({stuck_refreshes}/{stuck_giveup})")
                        try:
                            refreshed = client.load_career()
                            if (refreshed or {}).get("data"):
                                state = refreshed
                                continue
                        except Exception as exc:
                            self._log("stuck_turn_refresh_failed", turn, str(exc))

                self._mark(turn=turn)
                self._track_turn_scores(state)

                # Hard stop at turn 77: halt before playing turn 77 and leave the career
                # unfinished (no finish_career / final-skill buy). Controlled by the UI
                # "FINISH" toggle (finish_to_end): ON plays through to the natural turn-78
                # end, OFF stops here. dev_mode (loop runs) always plays through.
                if turn >= 77 and not getattr(self, "dev_mode", False) and not getattr(self, "finish_to_end", False):
                    print("Turn 77 reached -- hard stop (career left unfinished)", flush=True)
                    self.stop()
                    break
                
                self.skill_buyer.last_attempt = []
                self.skill_buyer.last_result = {}
                self.item_manager.last_buy_attempt = []
                self.item_manager.last_buy_result = {}
                self.item_manager.last_use_attempt = []
                self.item_manager.last_use_result = {}
                self.skill_buyer.attempt_events = []
                self.item_manager.buy_attempt_events = []
                self.item_manager.use_attempt_events = []

                if data.get("unchecked_event_array"):

                    state = self._drain_events(client, strategy, state)
                    data = state.get("data") or {}
                    chara = data.get("chara_info") or {}
                    self._track_turn_scores(state)
                
                if self._blocked_playing_state(chara):

                    state = self._recover_blocked_state(client, strategy, state)
                    data = state.get("data") or {}
                    chara = data.get("chara_info") or {}
                    if self._blocked_playing_state(chara):

                        self._mark(last_action=f"blocked state {chara.get('playing_state')}")
                        break
                
                self._debug_turn(state, preset)
                capture_career_identity(self.report, state)   # no-op once captured
                decision = strategy.next_decision(state, preset)

                # Surface the bot's predicted career direction: log it whenever it shifts, keep
                # the latest for the end-of-career summary, and push a one-time "Career Forecast"
                # panel to the Discord webhook the first time it's available this career.
                fc = getattr(strategy, "_forecast", None)
                if fc is not None and fc.active:
                    self._notify_forecast = fc.to_dict()
                    if fc.summary != getattr(self, "_last_forecast_summary", None):
                        self._last_forecast_summary = fc.summary
                        self._log("career_forecast", fc.turn, fc.summary)
                    if not self._forecast_sent:
                        self._forecast_sent = True
                        _meta = {
                            "account": os.environ.get("SWEEPY_ACCOUNT") or "",
                            "uma_name": notify.uma_name(self.base_dir, self._notify_card_id) or "",
                            "preset": (preset.get("name") if isinstance(preset, dict) else "") or "",
                        }
                        # Fire the webhook in the background so a slow/failed POST never stalls
                        # the career loop (send_forecast swallows its own errors).
                        threading.Thread(target=notify.send_forecast,
                                         args=(self.base_dir, self._notify_forecast, _meta),
                                         daemon=True).start()

                if self.report:
                    add_decision(self.report, state, decision)
                
                if decision.action == "command":

                    state = self._handle_items(client, state, preset, self._command_from_decision(state, decision))
                    data = state.get("data") or {}
                    if data.get("unchecked_event_array"):

                        state = self._drain_events(client, strategy, state)
                    data = state.get("data") or {}
                    chara = data.get("chara_info") or {}
                    self._mark(turn=chara.get("turn", 0))
                    decision = strategy.next_decision(state, preset)

                    if self.report:
                        add_decision(self.report, state, decision)
                    # A Reset Whistle is used alone and reshuffles the board, so the charm / Vita for
                    # the NEW pick were never considered (live 2026-10-29 turn 63: Speed trained at 95%
                    # failure with 2 charms owned). Run the item step once more for the new pick.
                    turn_now = int(chara.get("turn") or 0)
                    if (decision.action == "command" and turn_now
                            and getattr(self.item_manager, "whistled_turn", None) == turn_now):
                        state = self._handle_items(client, state, preset, self._command_from_decision(state, decision))
                        chara = (state.get("data") or {}).get("chara_info") or {}
                        decision = strategy.next_decision(state, preset)
                        if self.report:
                            add_decision(self.report, state, decision)
                
                self._log(decision.action, chara.get("turn", 0), decision.reason)
                if decision.action == "idle":
                    self._mark(last_action=decision.reason)
                    break
                if decision.action == "done":
                    self._mark(last_action=decision.reason, finished=True)
                    break
                
                if decision.action == "event":
                    try:
                        state = self._event(client, strategy, decision.payload)
                    except Exception as exc:
                        if _is_desync(exc):
                            state = self._fresh_career_state(client, strategy)
                            continue
                        raise
                elif decision.action == "team_race":
                    try:
                        state = self._unity.run_cup_race(client, strategy, decision.payload)
                    except Exception as exc:
                        if _is_desync(exc):
                            state = self._fresh_career_state(client, strategy)
                            continue
                        raise
                elif decision.action in ("master_square", "grand_live_perform"):
                    # Grand Live (scenario 3) only. Both are written on the single_mode_free/* namespace
                    # and routed to single_mode_live/* by UmaClient._route_ep.
                    try:
                        state = self._grand_live_call(client, strategy, decision, prev_state=state)
                    except Exception as exc:
                        # 102 = "not valid for the current state": the Live/square isn't available right
                        # now (already performed, or the career is parked on a game modal such as the
                        # Insufficient-Fans prompt). That is a NO-OP, never fatal -- a live run crashed
                        # the whole runner on it. Drop the move, refresh, and let the turn proceed.
                        if is_api_error(exc, 102):
                            marker = getattr(strategy, "mark_decision_handled", None)
                            if callable(marker):
                                marker(decision)
                            self._log("grand_live_skip", int((decision.payload or {}).get("current_turn") or 0),
                                      f"{decision.action} not available (102) -> skipping")
                            state = self._fresh_career_state(client, strategy)
                            continue
                        if _is_desync(exc):
                            # master_square/205 is authoritative and persistent for an unchanged
                            # board preview, so consume that offer to avoid a 205 loop. A Live 205 gets
                            # ONE retry per turn after the fresh reload, then is consumed the same way
                            # (otherwise the strategy re-emits it every pass). Session/network failures
                            # stay retryable.
                            if is_api_error(exc, 205):
                                live_turn = int((decision.payload or {}).get("current_turn") or 0)
                                if decision.action == "grand_live_perform" and self._live_205_turn != live_turn:
                                    self._live_205_turn = live_turn
                                else:
                                    marker = getattr(strategy, "mark_decision_handled", None)
                                    if callable(marker):
                                        marker(decision)
                            state = self._fresh_career_state(client, strategy)
                            continue
                        raise
                elif decision.action == "command":
                    self._log("command_exec", decision.payload["current_turn"], f"{decision.payload.get('command_type')}:{decision.payload.get('command_id')}:{decision.payload.get('command_group_id')}")
                    self._record_action(decision, chara)
                    # Loop breaker for scheduled group outings: a wrong card select_id is a no-op
                    # (server returns the SAME turn, no error) and would loop forever. If we're about
                    # to execute an outing on a turn we ALREADY executed one on (i.e. it didn't
                    # advance), block that path and fall back to training -- robust because it doesn't
                    # depend on reading the post-command turn from a possibly-odd no-op state.
                    if (int(decision.payload.get("command_type") or 0) == 3
                            and int(decision.payload.get("command_group_id") or 0) == GROUP_OUTING_COMMAND_ID):
                        cur_turn = int(decision.payload.get("current_turn") or 0)
                        if getattr(self, "_last_outing_turn", None) == cur_turn:
                            is_card = bool(getattr(strategy, "_pending_outing_is_card", False))
                            attr = "_card_outing_blocked" if is_card else "_scheduled_outing_blocked"
                            self._log("outing_stalled", cur_turn, f"card={is_card} sel={decision.payload.get('select_id')} no-advance -> blocked")
                            setattr(strategy, attr, True)
                            self._last_outing_turn = None
                            continue
                        self._last_outing_turn = cur_turn
                    try:
                        before_command_state = state
                        state = client.exec_command(**decision.payload)
                        ai_learn.log_training_outcome(
                            self.base_dir,
                            before_command_state,
                            state,
                            decision.payload,
                            self.status.get("scenario_id"),
                        )
                        data = state.get("data") or {}
                        if data.get("unchecked_event_array"):
                            state = self._drain_events(client, strategy, state)
                    except Exception as exc:
                        if _is_desync(exc):
                            state = self._fresh_career_state(client, strategy)
                            continue
                        # Scheduled Sirius/Throne group outing: a bad outing request must NEVER kill
                        # the career -- disable and fall back to normal play (the loop re-decides from
                        # the unchanged pre-command state -> training/rest). Isolate the two paths via
                        # the strategy's _pending_outing_is_card flag: a CARD-itself recreation (still
                        # an experimental select_id) failure blocks only card outings; a CONFIRMED
                        # character-outing failure is systemic -> block all scheduled outings.
                        if (int(decision.payload.get("command_type") or 0) == 3
                                and int(decision.payload.get("command_group_id") or 0) == GROUP_OUTING_COMMAND_ID):
                            sel = int(decision.payload.get("select_id") or 0)
                            is_card = bool(getattr(strategy, "_pending_outing_is_card", False))
                            attr = "_card_outing_blocked" if is_card else "_scheduled_outing_blocked"
                            self._log("outing_exec_failed", int(decision.payload.get("current_turn") or 0), f"card={is_card} sel={sel} {str(exc)[:130]}")
                            setattr(strategy, attr, True)
                            continue
                        if not is_api_error(exc, 102, 1503):
                            raise
                        state = self._recover_blocked_state(client, strategy, state)
                        data = state.get("data") or {}
                        chara = data.get("chara_info") or {}
                        if self._blocked_playing_state(chara):
                            self._mark(last_action=f"blocked state {chara.get('playing_state')}")
                            break
                        continue
                elif decision.action == "race":

                    self._record_action(decision, chara)
                    state = self._buy_before_goal(client, state, preset, decision.payload)
                    state = self._race(client, state, preset, decision.payload)
                elif decision.action == "race_progress":

                    self._record_action(decision, chara)
                    state = self._race_progress(client, decision.payload, preset,
                                                source_state=state, strategy=strategy)
                elif decision.action == "finish":

                    self._record_action(decision, chara)
                    self._career_end_reason = decision.reason or ""   # "goal failed" vs a natural finish

                    # Climax-3 SP is read BEFORE the end-of-career skill dump spends it; its STATS
                    # are resolved post-event-drain below, so the per-stat gain is clean.
                    climax3_sp = int((((state.get("data") or {}).get("chara_info")) or {}).get("skill_point") or 0)

                    # Grab the finished uma's trained_chara_id NOW, while the state still carries
                    # single_mode_finish_common / trained_chara_info -- the skill buy + finish below drop
                    # it, and the team finish 102s (returns nothing). This id is what change_nickname needs
                    # to RELEASE the career slot; without it the finished career stays wedged and the loop
                    # can't start the next one.
                    _fd = (state.get("data") or {})
                    _finish_tcid = None
                    for _blk in (_fd.get("single_mode_finish_common"), _fd.get("trained_chara_info"),
                                 _fd.get("chara_info")):
                        if isinstance(_blk, dict) and _blk.get("trained_chara_id"):
                            _finish_tcid = int(_blk["trained_chara_id"]); break

                    # Grand Live: the Grand Concert finale queues several pending events, and gain_skills
                    # 205s while ANY is still in unchecked_event_array. The capture drains them FIRST
                    # (race_out -> check_event x4 -> gain_skills); the bot bought BEFORE draining, so the
                    # finale skill dump 205-stormed and left ~1,500 SP unspent (career_log_20260723_175519,
                    # intermittent because sometimes the events were already gone). Drain before the buy.
                    # Scenario 3 only -- MANT/URA/Unity keep their proven buy-then-drain order; _drain_events
                    # no-ops when nothing is queued.
                    if int(self.status.get("scenario_id") or 0) == 3:
                        state = self._drain_events(client, strategy, state, limit=50)

                    state = self._buy_skills(client, state, preset, True)

                    data = state.get("data") or {}
                    if data.get("race_start_info"):
                        self._log("race_out", decision.payload["current_turn"], "clearing active race")
                        try:
                            state = client.race_out(current_turn=decision.payload["current_turn"])
                        except Exception as e:
                            if is_api_error(e, 102) or isinstance(e, StateRecoveryError) or _is_desync(e):
                                self._log("race_out_reconciled", decision.payload["current_turn"], f"graceful exit: {e}")
                            else:
                                raise
                    state = self._drain_events(client, strategy, state, limit=50)

                    state = self._spend_remaining_sp(client, state, preset)

                    # Record the leftover SP AFTER the finale dump so the notify embed
                    # reports the real remaining points, not the pre-dump turn snapshot.
                    final_chara = (state.get("data") or {}).get("chara_info") or {}
                    if final_chara.get("skill_point") is not None:
                        self._final_skill_point = int(final_chara.get("skill_point") or 0)

                    # Climax-3 resolved here: stats are final (post-event drain above), SP from the
                    # pre-dump snapshot. Hammer use is still detected via the consumed-item count.
                    self._resolve_climax_gains(999, state, sp_override=climax3_sp)

                    # 1.32.8 close-out: factor_select (x2) THEN finish. Calling finish alone 102s and
                    # never releases the slot, so the loop resumes the finished career forever. The
                    # returned state carries single_mode_finish_common (grade + sparks) from the
                    # confirm factor_select, which fixes the old rank_unknown/no-sparks gap too.
                    try:
                        finish_state = client.close_career(current_turn=decision.payload["current_turn"],
                                                           trained_chara_id=_finish_tcid,
                                                           factor_chooser=self._spark_factor_chooser(client, preset))
                        if finish_state:
                            state = finish_state
                    except Exception as e:
                        if is_api_error(e, 102) or isinstance(e, StateRecoveryError) or _is_desync(e):
                            self._log("finish_reconciled", decision.payload["current_turn"], f"graceful exit: {e}")
                        else:
                            raise
                    self._capture_sparks(state)
                    if not getattr(self, "_notify_rank_score", 0):
                        # A reconciled finish (102/desync graceful exit) leaves no
                        # single_mode_finish_common in `state`, so the final grade is
                        # unknown and this career won't enter the all-time ranking.
                        # Log it so the gap is diagnosable rather than silent.
                        self._log("rank_unknown", decision.payload["current_turn"],
                                  "finish response carried no evaluation; career left out of total ranking")
                    self._mark(last_action="finish", finished=True)
                    break
                else:

                    self._mark(last_action=decision.action)
                    break
                
                if decision.action not in {"finish"}:
                    state = self._buy_skills(client, state, preset, False)
                
                self._advance(decision.action)
        except Exception as exc:
            if self._should_stop() and COOLDOWN_STOP in str(exc):
                # Stop pressed while the client sat in a breaker cooldown: the request was never sent.
                # A normal user stop (finally writes the "stopped" report), not a crash.
                print("Stop requested during circuit-breaker cooldown -- career stopped", flush=True)
                return
            import traceback
            trace_str = traceback.format_exc()
            traceback.print_exc()
            print(f"RUNNER CRASH: {exc}")
            
            crash_log_path = runtime_output_root(self.base_dir) / "crash_trace.txt"
            try:
                crash_log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(crash_log_path, "a", encoding="utf-8") as f:
                    f.write(f"--- CRASH AT {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                    f.write(trace_str)
                    f.write("\n\n")
            except Exception:
                pass

            self._log("error", self.snapshot().get("turn", 0), str(exc))
            self._mark(last_error=str(exc))
            if self.report:
                set_error(self.report, exc)
        finally:
            outcome = self._compute_outcome()
            if self._should_stop():
                self._log("stop", self.snapshot().get("turn", 0), f"stop requested ({outcome})")
                if self.report:
                    finish_report(self.report, "stopped", outcome=outcome)
            else:
                if self.report:
                    finish_report(self.report, "finished" if self.status["finished"] else "error", outcome=outcome)
            # Before running=False, so a new start() (which re-wires it) can't race this clear.
            if client:
                client.should_abort = None
                # A trip after the last loop-top check (e.g. 205s in the finish skill dump) never reached
                # the sticky check above; surface it so manage_career_loop stops before the next start.
                if getattr(client, "circuit_trip_seen", False):
                    self._mark(circuit_tripped=True)
            self._mark(running=False)
            if self.report:
                try:
                    self.report["summary"] = self._career_summary(outcome)
                except Exception as e:
                    print(f"career summary build failed: {e}", flush=True)
                try:
                    root_trace_dir = runtime_output_root(self.base_dir) / "bot_logs"
                    out = write_report(self.report, root_trace_dir)
                    print(f"career report written: {out}", flush=True)
                except Exception as e:
                    print(f"failed to write report: {e}", flush=True)
                try:
                    summary = self._build_notify_summary()
                    # For the history row: without these a goal-failed career looked like a normal finish
                    # and rows of different scenarios couldn't be told apart.
                    summary["outcome"] = outcome or ""
                    summary["scenario_id"] = int(self.status.get("scenario_id") or 0)
                    # Closed-loop AI learning: log this finished career as an
                    # experience record, then retrain the model so the next
                    # career's race decisions can use the updated signal. Fully
                    # guarded so a telemetry/learning failure never breaks the run.
                    try:
                        ai_learn.log_experience(self.base_dir, {
                            "type": "career",
                            "status": summary.get("status") or "",
                            "rank": int(summary.get("rank") or 0),
                            "fans": int(summary.get("fans") or 0),
                            "turn": int(summary.get("final_turn") or 0),
                            "preset": summary.get("preset") or "",
                        })
                        ai_learn.train(self.base_dir)
                    except Exception as exc:
                        print(f"ai learn record/train failed: {exc}", flush=True)
                    # Record this career into the all-time history FIRST (works with or
                    # without a webhook), then attach the resulting total ranking
                    # (placement + top list) so the finished embed can show it.
                    try:
                        summary["ranking"] = notify.record_career_history(self.base_dir, summary)
                    except Exception as exc:
                        print(f"career history record failed: {exc}", flush=True)
                    # Add this career's fans to the account's daily total (resets 22:00 WIB)
                    # and attach the cross-account summary for the embed.
                    try:
                        if str(summary.get("status")) == "finished":
                            # Bucket under the SAME label the embed shows (UI name override first,
                            # then the --account/env label) so the total can't diverge from display.
                            account = (notify.get_account_name(self.base_dir)
                                       or summary.get("account") or os.environ.get("SWEEPY_ACCOUNT") or "")
                            summary["fan_summary"] = notify.record_account_fans(
                                self.base_dir, account, summary.get("fans"),
                                server_ts=getattr(client, "last_servertime", 0))
                    except Exception as exc:
                        print(f"daily fan record failed: {exc}", flush=True)
                    notify.send_career_summary(self.base_dir, summary)
                except Exception as e:
                    print(f"discord notify failed: {e}", flush=True)

    def _should_stop(self):
        with self.lock:
            return self.stop_requested

    def _capture_sparks(self, state):
        # The just-finished uma's inheritance factors (sparks) AND final evaluation
        # (rank grade + rank score) ride on the factor_select CONFIRM response under
        # single_mode_finish_common (NOT the finish response, which only carries
        # trained_chara_info): the trained_chara entry whose trained_chara_id matches.
        try:
            # res['data'] (single level) per the live 1.32.8 capture -- NOT res['data']['data'].
            sfc = ((state or {}).get("data") or {}).get("single_mode_finish_common") or {}
            tcid = sfc.get("trained_chara_id")
            for row in sfc.get("trained_chara") or []:
                if row.get("trained_chara_id") == tcid:
                    # sparks live in factor_info_array = [{factor_id, level}, ...], NOT factor_id_array.
                    self._notify_factor_ids = [f.get("factor_id") for f in (row.get("factor_info_array") or []) if f.get("factor_id")]
                    self._notify_rank = int(row.get("rank") or 0)
                    self._notify_rank_score = int(row.get("rank_score") or 0)
                    return
        except Exception:
            pass

    # command_id -> which stat a training raises (both the standard 101.. and MANT's 601.. ids).
    _TRAIN_STAT = {101: "speed", 105: "stamina", 102: "power", 103: "guts", 106: "wit",
                   601: "speed", 602: "stamina", 603: "power", 604: "guts", 605: "wit"}

    def _career_summary(self, outcome):
        """A SELF-CONTAINED analysis block written at the top of every career log, so 'why did this run
        score X' is answerable from the log alone (no cross-referencing career_history). Carries the
        final grade/score, final stats + total, skills bought, fans, races, AND the action + per-stat
        TRAINING breakdown -- which is what exposes a lopsided build (e.g. 20 Wit turns, 4 Power).
        Fail-safe: any error here must never block writing the log."""
        report = self.report or {}
        turns = sorted(report.get("turns") or [], key=lambda t: int(t.get("turn") or 0))
        races_log = report.get("races")      # one row per race run (None in logs written before it)
        actions = {}
        training_by_stat = {"speed": 0, "stamina": 0, "power": 0, "guts": 0, "wit": 0}
        last_stats = {}
        for t in turns:
            if t.get("stats"):
                last_stats = t["stats"]
            # Every decision of the turn, not just the last: a Grand Live concert / the final finish
            # used to overwrite the race or training done first, undercounting races by 5-6 a career.
            decisions = t.get("decisions")
            if decisions is None:
                act = t.get("selected_action") or ""
                decisions = [{"action": act, **(t.get("current_command") or {})}] if act else []
            seen = set()
            for dec in decisions:
                act = dec.get("action") or ""
                if not act or (races_log is not None and act in ("race", "race_progress")):
                    continue                  # races are counted from races_log below
                key = (act, dec.get("command_type"), dec.get("command_id"), dec.get("square_id"))
                if key in seen:
                    continue                  # the same move re-decided after a retry
                seen.add(key)
                if act == "command":
                    cid = int(dec.get("command_id") or 0)
                    ctype = int(dec.get("command_type") or 0)
                    if cid in self._TRAIN_STAT:
                        actions["train"] = actions.get("train", 0) + 1
                        training_by_stat[self._TRAIN_STAT[cid]] += 1
                    elif ctype == 7:
                        actions["rest"] = actions.get("rest", 0) + 1
                    elif ctype == 3:
                        actions["recreation"] = actions.get("recreation", 0) + 1
                    elif ctype == 8:
                        actions["medic"] = actions.get("medic", 0) + 1
                    else:
                        actions["other_command"] = actions.get("other_command", 0) + 1
                else:
                    actions[act] = actions.get(act, 0) + 1
        if races_log is not None:
            actions["race"] = len(races_log)
        stats = dict(last_stats or {})
        final_sp = getattr(self, "_final_skill_point", None)
        if final_sp is not None:
            stats["skill_point"] = final_sp
        rank = int(getattr(self, "_notify_rank", 0) or 0)
        with self.lock:
            skills_bought = int(self.status.get("skills_bought") or 0)
            clocks = int(self.status.get("clocks_used") or 0)
        final = {k: int(stats.get(k) or 0) for k in ("speed", "stamina", "power", "guts", "wit")}
        return {
            "outcome": outcome,
            "rank": rank,
            "rank_letter": notify.rank_letter(rank) if rank else "",
            "rank_score": int(getattr(self, "_notify_rank_score", 0) or 0),
            "final_stats": final,
            "stat_total": sum(final.values()),
            "skill_point_left": int(final_sp) if final_sp is not None else None,
            "skills_bought": skills_bought,
            "fans": int(stats.get("fans") or 0),
            "races": actions.get("race", 0),
            # Wins, from the per-race records (final finish after any clock retries). Older logs fall
            # back to action_history's {rank, won}; team_race (Unity Cup) rows carry no rank.
            "races_won": (sum(1 for r in races_log if r.get("final_rank") == 1) if races_log is not None
                          else min(actions.get("race", 0),
                                   sum(1 for r in (self.status.get("action_history") or [])
                                       if r.get("action") == "race" and (r.get("result") or {}).get("won")))),
            "clocks_used": clocks,
            "actions": actions,
            "training_by_stat": training_by_stat,
            "final_turn": int(report.get("final_turn") or 0),
            "scenario_id": int(self.status.get("scenario_id") or 0),
        }

    def _build_notify_summary(self):
        report = self.report or {}
        turns = sorted(report.get("turns") or [], key=lambda t: int(t.get("turn") or 0))
        last_stats = {}
        races = 0
        for t in turns:
            if t.get("stats"):
                last_stats = t["stats"]
            if t.get("selected_action") == "race":
                races += 1
        races_log = report.get("races")
        if races_log is not None:            # exact: concert/finish turns no longer hide a race
            races = len(races_log)
        duration = "?"
        st, en = report.get("started_at"), report.get("ended_at")
        if st and en:
            try:
                secs = int((datetime.fromisoformat(en) - datetime.fromisoformat(st)).total_seconds())
                h, rem = divmod(max(secs, 0), 3600)
                m, s = divmod(rem, 60)
                duration = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"   # e.g. 11:00, or 1:05:30
            except Exception:
                pass
        with self.lock:
            skills_bought = int(self.status.get("skills_bought") or 0)
        # Prefer the post-dump skill_point captured at finish; the per-turn stats
        # snapshot is from turn START (before the finale skill purchase) and would
        # otherwise over-report leftover SP (e.g. 843 shown when only ~56 remained).
        final_sp = getattr(self, "_final_skill_point", None)
        if final_sp is not None and isinstance(last_stats, dict):
            last_stats = {**last_stats, "skill_point": final_sp}
        return {
            "status": report.get("status") or "",
            "account": os.environ.get("SWEEPY_ACCOUNT") or "",
            "final_turn": report.get("final_turn") or 0,
            "preset": report.get("preset_name") or "",
            "stats": last_stats,
            "duration": duration,
            "skills_bought": skills_bought,
            "races": races,
            "races_won": (sum(1 for r in races_log if r.get("final_rank") == 1) if races_log is not None
                          else min(races,
                                   sum(1 for r in (self.status.get("action_history") or [])
                                       if r.get("action") == "race" and (r.get("result") or {}).get("won")))),
            "fans": int(last_stats.get("fans") or 0),
            "card_id": getattr(self, "_notify_card_id", ""),
            "factor_ids": list(getattr(self, "_notify_factor_ids", []) or []),
            "loop_index": int(getattr(self, "_loop_index", 1) or 1),
            "loop_target": int(getattr(self, "_loop_target", 1) or 0),
            "forecast": getattr(self, "_notify_forecast", None),
            "rank": int(getattr(self, "_notify_rank", 0) or 0),
            "rank_score": int(getattr(self, "_notify_rank_score", 0) or 0),
            "scenario_id": int(self.status.get("scenario_id") or 0),   # -> embed title (URA/Aoharu/Trackblazer)
            # Grand Live: songs banked vs the turn-72 true-finale target, for the notify embed.
            "grand_live": getattr(self, "_grand_live_summary", None) or {},
        }

    def _advance(self, action):
        with self.lock:
            self.status["steps"] += 1
            self.status["last_action"] = action

    def _mark(self, **values):
        with self.lock:
            self.status.update(values)

    def _log_locked(self, action, turn, detail):
        items = self.status.setdefault("log", [])
        items.append({
            "id": len(items) + 1,
            "action": action,
            "turn": int(turn or 0),
            "detail": str(detail or ""),
            "time": time.strftime("%H:%M:%S"),
        })
        if len(items) > 120:
            del items[:len(items) - 120]

    def _log(self, action, turn, detail):
        with self.lock:
            self._log_locked(action, turn, detail)

    def _record_action(self, decision, chara=None):
        payload = decision.payload or {}
        action = decision.action
        turn = int(payload["current_turn"])
        stats = self._turn_stats(chara or {})
        detail = self._format_turn_stats(stats) or str(decision.reason or "")
        facility = ""
        if action == "command":
            command_type = int(payload.get("command_type") or 0)
            command_id = int(payload.get("command_id") or 0)
            command_group_id = int(payload.get("command_group_id") or 0)
            if command_type == 1:
                action = "train"
                facility = TRAINING_LABELS.get(command_id, str(command_id))
            elif command_type == 8:
                action = "medic"
            elif command_type == 7:
                action = "rest"
                facility = str(command_group_id or command_id)
            elif command_type == 3:
                action = "recreation"
                facility = str(command_group_id or command_id)
            else:
                action = f"command {command_type}"
                facility = str(command_id or command_group_id)
        elif action in {"race", "race_progress"}:
            action = "race"
            program_id = int(payload.get("program_id") or 0)
            if program_id and self.race_planner:
                facility = self.race_planner.label(program_id)
            else:
                facility = str(program_id or "")
        elif action == "finish":
            action = "finish"
        row = {
            "turn": turn,
            "action": action,
            "facility": facility,
            "detail": detail,
            "stats": stats,
            "time": time.strftime("%H:%M:%S"),
        }
        with self.lock:
            history = self.status.setdefault("action_history", [])
            if history and history[-1].get("turn") == row["turn"] and history[-1].get("action") == row["action"] and history[-1].get("facility") == row["facility"]:
                history[-1] = row
            else:
                history.append(row)

    def _spark_factor_chooser(self, client, preset):
        """Chooser for the end-of-career inheritance-spark pick.

        Scores every offered factor option by the preset's per-colour priorities (blue/pink/green/white,
        0-5) and -- when spark_reroll is ON -- spends TP to reroll. Each reroll response carries BOTH the
        original and the rerolled option sets, so we re-pick across the whole authoritative set: a reroll
        can never cost you a better original roll. Returns None to leave close_career's default pick
        alone. Every failure path is non-fatal: the career still finishes on the default roll."""
        try:
            from career_bot.core import sparks
            factor_map = self.data_store.factor_map()
        except Exception as e:
            self._log("spark_scorer_unavailable", 0, str(e)[:120])
            return None
        preset = preset or {}
        weights = sparks.normalize_weights(preset)
        reroll_on = bool(preset.get("spark_reroll", False))
        max_rerolls = max(0, int(preset.get("spark_reroll_max") or 2))
        tp_floor = max(0, int(preset.get("spark_reroll_tp_floor") or 0))
        TP_COST = 30

        def _choose(response):
            options, meta = sparks.extract_options(response)
            if not options:
                return None
            best = sparks.pick_best(options, factor_map, weights)
            if not reroll_on or max_rerolls <= 0:
                if best:
                    self._log("spark_pick", 0, f"lottery {best['lottery_id']} score {best['score']} {best['breakdown']}")
                return best["lottery_id"] if best else None
            remain = int(meta.get("lottery_remain_num") or 0)
            tp_info = meta.get("tp_info") or {}
            done = 0
            while done < max_rerolls and remain > 0:
                cur_tp = int((client.current_tp_snapshot(tp_info) or {}).get("current_tp") or 0)
                if cur_tp < TP_COST + tp_floor:
                    self._log("spark_reroll_stop", 0, f"TP {cur_tp} below {TP_COST}+floor {tp_floor}")
                    break
                try:
                    res = client.factor_lottery(lottery_count=1, tp_info=tp_info, use_tp=TP_COST)
                except Exception as e:
                    self._log("spark_reroll_failed", 0, str(e)[:120])
                    break                      # fail-safe: keep the best option we already have
                done += 1
                new_options, new_meta = sparks.extract_options(res)
                if new_options:                # authoritative set = original + rerolled
                    cand = sparks.pick_best(new_options, factor_map, weights)
                    if cand:
                        best = cand
                remain = int(new_meta.get("lottery_remain_num") or 0)
                tp_info = new_meta.get("tp_info") or tp_info
                self._log("spark_reroll", 0,
                          f"reroll {done}/{max_rerolls} (-{TP_COST} TP) -> best score "
                          f"{best['score'] if best else 0} lottery {best['lottery_id'] if best else '?'}")
            if best:
                self._log("spark_pick", 0, f"lottery {best['lottery_id']} score {best['score']} {best['breakdown']}")
            return best["lottery_id"] if best else None
        return _choose

    def _record_race_result(self, turn, rank):
        """Attach the finish position to this turn's race row in action_history (the web UI reads it as
        row.result). rank 1 = won; 2..18 = placed; 99 is the _parse_race_rank parse-failure sentinel ->
        recorded as 0 = unknown so the UI shows a neutral marker, not a fake loss."""
        rank = int(rank or 0)
        result = {"rank": rank if 1 <= rank <= 18 else 0, "won": rank == 1}
        with self.lock:
            for row in reversed(self.status.get("action_history") or []):
                if int(row.get("turn") or 0) == int(turn or 0) and row.get("action") == "race":
                    row["result"] = result
                    break

    def _turn_stats(self, chara):
        if not chara:
            return {}
        return {
            "hp": int(chara.get("vital") or 0),
            "max_hp": int(chara.get("max_vital") or 100),
            "motivation": int(chara.get("motivation") or 0),
            "speed": int(chara.get("speed") or 0),
            "stamina": int(chara.get("stamina") or 0),
            "power": int(chara.get("power") or 0),
            "guts": int(chara.get("guts") or 0),
            "wit": int(chara.get("wiz") or 0),
            "skill_point": int(chara.get("skill_point") or 0),
            "fans": int(chara.get("fans") or 0),
        }

    def _format_turn_stats(self, stats):
        if not stats:
            return ""
        return (
            f"HP {stats['hp']}/{stats['max_hp']} | "
            f"MOOD {stats['motivation']} | "
            f"SPD {stats['speed']} STA {stats['stamina']} PWR {stats['power']} "
            f"GUT {stats['guts']} WIT {stats['wit']} SP {stats['skill_point']}"
        )

    def _log_goal_progress(self, state, turn):
        """Once per career, log the trainee's full career-goal schedule; each turn, warn if a goal
        looks at risk. Makes the JSON-driven goal following visible in the career log / console."""
        if not self.race_planner:
            return
        chara = (state.get("data") or {}).get("chara_info") or {}
        if not self._goal_schedule_logged:
            line = self.race_planner.goal_schedule_line(chara)
            if line:
                self._goal_schedule_logged = True
                self._log("career_goals", turn, line)
        risk = self.race_planner.goal_risk(state)
        if risk:
            self._log("goal_risk", turn, risk)

    def _blocked_playing_state(self, chara):
        playing_state = int((chara or {}).get("playing_state") or 1)
        allowed = {1, 2, 3, 4, 5}
        # A Team/Unity career parks on the Unity Cup race day in playing_state 7 (auto-fill /
        # opponent-select) and drives 7 -> 8 -> 9 while the team race resolves -- all three are
        # legitimate states the cup handler drives, NOT stuck states. 8 was missing, so a career that
        # resumed / re-entered mid-race at ps 8 was mistaken for a stall, relogged, and abandoned
        # before the cup finished (Icarus unity-cup-api-map: ps 8/9 occur INSIDE the team-race
        # sequence; it unblocks 7/8/9). UnityStrategy._cup_race_available routes 7/8/9 to team_race.
        if int(self.status.get("scenario_id") or 0) == 2:
            allowed = allowed | {7, 8, 9}
        # Grand Live parks on playing_state 10 while a Concert is waiting. The scenario strategy
        # deliberately handles that state by claiming the pending lesson and calling live_start.
        # Treating it as blocked here prevents the strategy from ever seeing it and can abandon a
        # perfectly recoverable career during relog/resume.
        if int(self.status.get("scenario_id") or 0) == 3:
            allowed = allowed | {10}
        return playing_state not in allowed

    def _recover_blocked_state(self, client, strategy, state):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        if int(chara.get("playing_state") or 0) == 6:
            turn = chara.get("turn", 1)
            if hasattr(client, "minigame_end"):
                state = client.minigame_end(current_turn=turn)
            else:
                state = client.call("single_mode_free/minigame_end", {
                    "result": {
                        "result_state": 1,
                        "result_value": 0,
                        "result_detail_array": None,
                    },
                    "current_turn": turn,
                })
            data = state.get("data") or {}
            if data.get("unchecked_event_array"):
                state = self._drain_events(client, strategy, state)
            return state
        try:
            if hasattr(client, "hard_reset"):
                state = client.hard_reset()
            else:
                state = self._fresh_career_state(client, strategy)
        except Exception as e:
            print(f"Blocked State Recovery Failure: {e}")
            return state
        return state

    def _debug_turn(self, state, preset):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        free = data.get("free_data_set") or {}
        self.skill_buyer.preview(state, preset)
        self._debug("turn", state, {
            "server_command_board": self._debug_command_board(data),
            # Bond table the scorer reads (chara_info.evaluation_info_array keyed by target_id --
            # the same map training_brain builds). target_id >= 1000 are scenario guest partners
            # whose evaluation is always 0, so they are dropped; a missing id reads as 0 offline,
            # exactly like the scorer's .get(pid, 0). Joined with the board's `partners` this is
            # what makes rainbow/bondable counts recomputable after the fact.
            "bond": {int(r.get("target_id") or 0): int(r.get("evaluation") or 0)
                     for r in (chara.get("evaluation_info_array") or [])
                     if int(r.get("target_id") or 0) < 1000 and r.get("is_appear")},
            # LIVE per-stat caps. Not career-constant: inheritance drifts them mid-career, and the
            # scorer's near-cap attenuation ladder is unreproducible without them.
            "stat_caps": {k: int(chara.get(k) or 0) for k in
                          ("max_speed", "max_stamina", "max_power", "max_guts", "max_wiz")},
            "owned_skills": self._debug_owned_skills(state),
            "inventory": self._debug_inventory(state),
            # NOTE: server_skill_tips_raw was dropped here (~113 KB/career of {group_id, rarity,
            # level}) -- every field of it is already in skill_rows_enriched as group_id/tip_rarity/
            # hint_level. That saving is what pays for the richer board above.
            "server_owned_skill_raw": chara.get("skill_array") or [],
            "skill_rows_enriched": self._debug_skill_options(state, preset),
            "bot_skill_candidates": list(self.skill_buyer.last_candidates),
            "bot_skill_selected": list(self.skill_buyer.last_selected),
            "bot_skill_attempt": list(self.skill_buyer.last_attempt),
            "bot_skill_result": dict(self.skill_buyer.last_result),
            "server_shop_rows_raw": free.get("pick_up_item_info_array") or [],
            "shop_rows_enriched": self._debug_item_buy_options(state, preset),
            "bot_shop_candidates": list(self.item_manager.last_buy_options),
            "bot_shop_selected": list(self.item_manager.last_buy_selected),
            "bot_shop_attempt": list(self.item_manager.last_buy_attempt),
            "bot_shop_result": dict(self.item_manager.last_buy_result),
            "decision_item_use_rows": list(self.item_manager.last_use_options),
            "bot_item_use_selected": list(self.item_manager.last_use_selected),
            "bot_item_use_attempt": list(self.item_manager.last_use_attempt),
            "bot_item_use_result": dict(self.item_manager.last_use_result),
        })

    def _debug_skill_options(self, state, preset):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        points = int(chara.get("skill_point") or 0)
        owned = {int(item.get("skill_id") or 0) for item in chara.get("skill_array") or []}
        owned_groups = {self.skill_buyer.skill_to_group_id.get(skill_id, skill_id // 10) for skill_id in owned}
        priority = self.skill_buyer._priority_context(preset)
        blacklist = self.skill_buyer._blacklist(preset)
        selected = {item["skill_id"]: item for item in self.skill_buyer._candidates(chara, preset)}
        result = []
        for tip in chara.get("skill_tips_array") or []:
            resolved = self.skill_buyer.resolve_skill_tip(tip, owned, owned_groups, priority, blacklist, preset)
            skill_id = int((resolved or {}).get("resolved_skill_id") or 0)
            cost = int((resolved or {}).get("cost") or 0)
            selected_flag = skill_id in selected
            skip_reason = (resolved or {}).get("skip_reason")
            if not skip_reason and cost > points:
                skip_reason = "unaffordable"
            elif not skip_reason and not selected_flag:
                skip_reason = "rule_rejected"
            result.append({
                "skill_id": skill_id,
                "group_id": int((resolved or {}).get("group_id") or tip.get("group_id") or 0),
                "tip_rarity": int((resolved or {}).get("tip_rarity") or tip.get("rarity") or 0),
                "hint_level": int((resolved or {}).get("hint_level") or tip.get("level") or 0),
                "candidate_skill_ids": (resolved or {}).get("candidate_skill_ids") or [],
                "name": (resolved or {}).get("resolved_name") or "",
                "cost": cost,
                "affordable": cost <= points,
                "owned_group": (resolved or {}).get("skip_reason") == "owned_group",
                "known": bool((resolved or {}).get("master_exists")),
                "failed_scope": (resolved or {}).get("failed_scope"),
                "selected": selected_flag,
                "resolution_reason": (resolved or {}).get("resolution_reason") or "",
                "skip_reason": skip_reason,
            })
        return result

    # params_inc_dec_info_array target_type -> readable name (10 = energy, 30 = skill points).
    _GAIN_NAMES = {1: "speed", 2: "stamina", 3: "power", 4: "guts", 5: "wit",
                   30: "skill_point", 10: "energy"}

    def _debug_command_board(self, data):
        """The BOARD the brain decided from, with every input its scorer actually reads.

        This used to log 4 fields (type/id/enable/failure) -- enough to tell an empty board from a
        high-failure one and nothing more, which made facility CHOICE unfalsifiable: a turn that
        wrongly took Guts over a 3-rainbow Power logged identically to the correct pick. Every field
        added here is a direct input of _score_command_base:

          level    -- facility level 1-5; explains gain magnitude, and shows whether the bot is
                      levelling facilities or spreading thin across them.
          partners -- training_partner_array. 1-6 are deck slots (== support_card_array.position, so
                      the career identity block already names the card -- ids are not re-logged per
                      turn), 100-999 story NPCs, 1000+ scenario guests. Joined against `bond` this
                      is what makes the rainbow and bondable counts recomputable offline.
          hints    -- tips_event_partner_array (the '!' skill-hint bonus). Omitted when empty.
          gains    -- params_inc_dec_info_array as {stat: value}, including energy and skill points:
                      the actual yield the score is built from.
        """
        board = []
        for c in ((data.get("home_info") or {}).get("command_info_array") or []):
            row = {"command_type": c.get("command_type"), "command_id": c.get("command_id"),
                   "is_enable": c.get("is_enable"), "failure_rate": c.get("failure_rate"),
                   "level": c.get("level")}
            partners = [int(p) for p in (c.get("training_partner_array") or [])]
            if partners:
                row["partners"] = partners
            hints = [int(p) for p in (c.get("tips_event_partner_array") or [])]
            if hints:
                row["hints"] = hints
            gains = {}
            for g in (c.get("params_inc_dec_info_array") or []):
                name = self._GAIN_NAMES.get(int(g.get("target_type") or 0))
                if name:
                    gains[name] = int(g.get("value") or 0)
            if gains:
                row["gains"] = gains
            board.append(row)
        return board

    def _debug_owned_skills(self, state):
        chara = (state.get("data") or {}).get("chara_info") or {}
        result = []
        for row in chara.get("skill_array") or []:
            skill_id = int(row.get("skill_id") or 0)
            result.append({
                "skill_id": skill_id,
                "group_id": self.skill_buyer.skill_to_group_id.get(skill_id, skill_id // 10),
                "name": self.skill_buyer.skill_names.get(skill_id, ""),
            })
        return result

    def _debug_inventory(self, state):
        free = (state.get("data") or {}).get("free_data_set") or {}
        result = []
        for name, count in sorted(self.item_manager._owned_map(free).items()):
            item_id = DISPLAY_TO_ID.get(name)
            if not item_id:
                continue
            result.append({
                "name": name,
                "item_id": item_id,
                "current_num": int(count),
                "failed_scope": "this_turn" if item_id in self.item_manager.failed_use_this_turn else None,
            })
        return result

    def _debug_item_buy_options(self, state, preset):
        data = state.get("data") or {}
        free = data.get("free_data_set") or {}
        current_turn = int((data.get("chara_info") or {}).get("turn") or 0)
        coin_val = free.get("coin_num")
        if coin_val is None:
            coin_val = free.get("gained_coin_num")
        budget = int(coin_val or 0)
        owned = self.item_manager._owned_map(free)
        result = []
        for row in free.get("pick_up_item_info_array") or []:
            shop_item_id = int(row.get("shop_item_id") or 0)
            item_id = int(row.get("item_id") or 0)
            name = ITEM_NAMES.get(item_id)
            if not name:
                continue
            limit_turn = int(row.get("limit_turn") or 0)
            cost = int(row.get("coin_num") or 0)
            original_cost = int(row.get("original_coin_num") or cost)
            bought = int(row.get("item_buy_num") or 0)
            limit = int(row.get("limit_buy_count") or 1)
            expired = limit_turn > 0 and current_turn > limit_turn
            rejected = shop_item_id in self.item_manager.failed_exchange_this_snapshot
            skip_buy = self.item_manager._skip_buy(name, owned, preset)
            skip_reason = None
            if expired:
                skip_reason = "expired"
            elif bought >= limit:
                skip_reason = "limit_reached"
            elif rejected:
                skip_reason = "rejected"
            elif skip_buy:
                skip_reason = "skip_buy"
            elif cost > budget:
                skip_reason = "unaffordable"
            result.append({
                "shop_item_id": shop_item_id,
                "item_id": item_id,
                "name": name,
                "cost": cost,
                "original_cost": original_cost,
                "mant_coin": budget,
                "affordable": cost <= budget,
                "current_num": bought,
                "limit": limit,
                "absolute_limit_turn": limit_turn,
                "server_turn_delta": (limit_turn - current_turn) if limit_turn > 0 else None,
                "ui_turns_left": None,
                "limit_reached": bought >= limit,
                "expired": expired,
                "rejected": rejected,
                "skip_buy": skip_buy,
                "selected": False,
                "skip_reason": skip_reason,
            })
        cfg = self.item_manager._mant_cfg(preset)
        tiers = cfg.get("item_tiers") or {}
        tier_count = int(cfg.get("tier_count") or 8)
        remaining_budget = budget
        for tier in range(1, tier_count + 1):
            tier_rows = [
                row for row in result
                if row.get("skip_reason") is None
                and not row.get("selected")
                and int(tiers.get(display_to_slug(row.get("name")), 999)) == tier
            ]
            tier_rows.sort(key=lambda row: (int(row.get("absolute_limit_turn") or 99), int(row.get("cost") or 9999)))
            for row in tier_rows:
                cost = int(row.get("cost") or 0)
                remaining = remaining_budget - cost
                if remaining < 0:
                    row["skip_reason"] = "unaffordable"
                    continue
                threshold = 0
                thresholds = cfg.get("tier_thresholds") or {}
                if tier > 1 and current_turn <= 64:
                    threshold = int(thresholds.get(str(tier), thresholds.get(tier, (tier - 1) * 50)) or 0)
                if threshold > 0 and remaining < threshold:
                    row["skip_reason"] = "rule_rejected"
                    continue
                row["selected"] = True
                remaining_budget = remaining
        return result

    def _api_result(self, result):
        result = dict(result or {})
        error = str(result.get("error") or "")
        code = None
        for token in error.replace(":", " ").replace(",", " ").split():
            if token.isdigit():
                value = int(token)
                if value in {201, 202, 205, 208, 394, 709}:
                    code = value
                    break
        if result.get("result") == "ok":
            code = 1
        return {
            "ok": result.get("result") == "ok",
            "result_code": code,
            "error": error or None,
        }

    def _sum_cost(self, rows):
        return sum(int((row or {}).get("cost") or 0) for row in rows or [])

    def _shop_attempt_cost(self, attempt, selected):
        costs = {int(row.get("shop_item_id") or 0): int(row.get("cost") or 0) for row in selected or []}
        return sum(costs.get(int(row.get("shop_item_id") or 0), 0) for row in attempt or [])

    def _fresh_career_state(self, client, strategy=None):
        import time
        errors = []
        max_retries = 8
        for attempt in range(max_retries):
            relogin = attempt > 0
            try:
                if relogin:
                    if not hasattr(client, "login"):
                        break
                    client.login()
                if hasattr(client, "load_career"):
                    state = client.load_career()
                else:
                    state = client.call("single_mode_free/load", {})
                if strategy and (state.get("data") or {}).get("unchecked_event_array"):
                    state = self._drain_events(client, strategy, state)
                self.skill_buyer.reset_scoped_failures()
                self.item_manager.reset_scoped_failures()
                return state
            except Exception as exc:
                if self._should_stop() and COOLDOWN_STOP in str(exc):
                    raise   # Stop pressed during a breaker cooldown: don't relogin/reload 8x first
                err_str = str(exc)
                errors.append(err_str)
                if attempt < max_retries - 1:
                    backoff_sleep(attempt, base=6.0, cap=20.0)
        if hasattr(client, "hard_reset"):
            return client.hard_reset()
        raise RuntimeError("career recovery failed: " + " | ".join(errors[-2:]))

    def _event(self, client, strategy, payload):
        data = dict(payload)
        event = data.pop("_event", None)
        current_turn = data.pop("_current_turn", 0)
        before_chara = data.pop("_before_chara", None)
        if event:
            # Pass the pre-event chara so the chooser can be need-aware (pick energy/mood
            # recovery options exactly when the trainee is low on them).
            choice = strategy.choose_from_event(event, current_turn, chara=before_chara)
            # force=True: this branch is only reached for events that OFFER choices, so even a chooser
            # default of 0 must be snapped to a valid offered reward index (else check_event 205s).
            choice = self._reward_choice(client, data["event_id"], event.get("chara_id", 0), choice, current_turn, force=True)
            self._log("event_choice", current_turn, f"{data.get('event_id')} -> {choice}")
            result = client.check_event(
                event_id=data["event_id"],
                chara_id=event.get("chara_id", 0),
                choice_number=choice,
                current_turn=current_turn
            )
            # Learn what this choice actually did (stat/energy/mood delta) so the EVENT
            # CHOICES panel can describe each option from real observations. Recorded by
            # the game's select_index (stable meaning), not the position (varies per sighting).
            manager = getattr(strategy, "event_manager", None)
            if manager is not None and before_chara:
                choices = (event.get("event_contents_info") or {}).get("choice_array") or []
                select_index = 0
                if isinstance(choice, int) and 0 <= choice < len(choices):
                    select_index = int((choices[choice] or {}).get("select_index") or 0)
                after_chara = ((result or {}).get("data") or {}).get("chara_info") or {}
                manager.record_choice_outcome(event.get("story_id"), select_index, before_chara, after_chara)
            return result
        if "event_id" not in data:
            self._log("recover", current_turn, "event requested without event_id, forcing state refresh")
            return self._fresh_career_state(client, strategy)
        data["choice_number"] = self._reward_choice(client, data.get("event_id"), data.get("chara_id", 0),
                                                     data.get("choice_number"), data.get("current_turn"))
        return client.check_event(**data)

    def _reward_choice(self, client, event_id, chara_id, choice, current_turn, force=False):
        """URA reward-selection events: get_choice_reward returns the offered rewards, each tagged with
        a select_index; check_event MUST send one of THOSE values. Any value that isn't offered is
        rejected with 205 -- forever (verified live: event 102001 offered [4,5,6]; the chooser sent 1,
        then on resume sent 0 -> 205 crash). So claim the preview, then RETURN a valid choice: honour
        the strategy's pick if it's offered, else snap to the highest-gain offered index (effect_value_0).

        `force=True` (the _event multi-choice path) fires regardless of the chooser's value -- that path
        is only reached for events that DO offer choices, so a chooser default of 0 must still be snapped.
        Otherwise it fires only when the chooser already picked >=1. get_choice_reward runs BEFORE
        check_event (the game's order; after, it 102s). URA only (scenario 1); MANT/Unity untouched, and
        a non-reward event returns no reward_array so the pick is kept unchanged."""
        if getattr(client, "current_scenario_id", None) != 1 or not event_id:
            return choice
        if not force and int(choice or 0) < 1:
            return choice
        try:
            res = client.get_choice_reward(event_id=event_id, chara_id=chara_id or 0,
                                           choice_number=int(choice or 0), current_turn=current_turn)
        except Exception as e:
            self._log("reward_claim_skip", current_turn, f"{event_id}: {e}")
            return choice
        gain = {}
        for a in (((res or {}).get("data") or {}).get("choice_reward_array")) or []:
            si = a.get("select_index")
            if si is None:
                continue
            gain[si] = gain.get(si, 0) + sum(
                int((p or {}).get("effect_value_0") or 0) for p in (a.get("gain_param_array") or []))
        if not gain:
            return choice   # not a reward event (no reward list) -> keep the strategy's pick
        if int(choice or 0) in gain:
            self._log("reward_claim", current_turn, f"{event_id} choice={choice} (offered)")
            return int(choice or 0)
        picked = max(gain, key=lambda k: (gain[k], -k))   # best-gain offered index, tie-break lowest
        self._log("reward_choice_fix", current_turn,
                  f"{event_id}: choice {choice} not offered {sorted(gain)} -> {picked}")
        return picked

    def _drain_events(self, client, strategy, state, limit=20):
        current = state
        resynced = False
        for _ in range(limit):
            data = current.get("data") or {}
            events = data.get("unchecked_event_array") or []
            if not events:
                return current
            event = events[0] or {}
            choice = strategy._choice(event)
            chara_turn = (data.get("chara_info") or {}).get("turn")
            turn = chara_turn if chara_turn is not None else self.status["turn"]
            payload = {"event_id": event.get("event_id"), "chara_id": event.get("chara_id", 0), "choice_number": choice, "current_turn": turn}
            if choice is None:
                # Multi-choice event: pass the pre-event chara stats so the picked choice's
                # observed outcome (stat delta) can be recorded for the EVENT CHOICES panel.
                payload = {"event_id": event.get("event_id"), "_event": event, "_current_turn": turn,
                           "_before_chara": dict(data.get("chara_info") or {})}
            try:
                current = self._event(client, strategy, payload)
            except Exception as exc:
                # A session desync (217 etc.) answering an event used to end the career (live
                # 2026-10-30, career_log_20261030_225954: 217 on check_event at turn 13). Resync
                # once, reload the career and keep draining from the server's own state, as the
                # race and command paths already do. (A 217's viewer_id header is a fixed
                # placeholder, 6553960516532 on every 217 since July, not the account in use.)
                if resynced or not _is_desync(exc):
                    raise
                resynced = True
                self._log("event_desync", turn, f"{str(exc)[:120]} -> resync + reload")
                if is_api_error(exc, 217) and hasattr(client, "resync_session"):
                    client.resync_session()
                current = self._fresh_career_state(client)
        return current
        # NOTE: scenario-2 reward-choice claiming (single_mode_team/get_choice_reward) is intentionally
        # NOT wired here. The live capture shows the game calls get_choice_reward BEFORE check_event for
        # a reward event (0023 get_choice_reward -> 0024 check_event); calling it AFTER (as a check_event
        # follow-up) returns 102 "already done" and, fired broadly, trips the circuit breaker. check_event
        # alone resolves the events and advances the career fine -- the reward sub-step is optional. Wire
        # it later once the exact pre-check_event trigger + reward index are confirmed from the capture.

    def _race_clocks(self, state):
        """(std, free) clocks available to retry the race RIGHT NOW. Reads home_info first; if that
        carries no count -- which happens on a mid-race resume state, where the count rides in
        race_start_info instead -- fall back to _get_clocks_left so the retry loop still fires
        instead of reading 0 and giving up. This is what makes "always use clocks to win" hold on
        EVERY race entry path, not just a fresh home-screen entry."""
        home = (state.get("data") or {}).get("home_info") or {}
        std = int(home.get("available_continue_num") or 0)
        free = int(home.get("available_free_continue_num") or 0)
        if std == 0 and free == 0:
            total = int((self._get_clocks_left(state) or {}).get("clocks_left") or 0)
            std = max(0, total)  # fallback total counts as standard; the continue RESPONSE re-splits std/free next iteration
        return std, free

    def _get_clocks_left(self, root, max_clocks=5):
        data = root.get("data") or {}

        home_info = data.get("home_info")
        if isinstance(home_info, dict) and "available_continue_num" in home_info:
            std = int(home_info.get("available_continue_num", 0))
            free = int(home_info.get("available_free_continue_num", 0))
            continue_type = 1 if free > 0 else 2
            return {
                "source": "data.home_info.available_continue_num",
                "clocks_left": std + free,
                "continue_type": continue_type,
            }

        race_start_info = data.get("race_start_info")
        if isinstance(race_start_info, dict) and "continue_num" in race_start_info:
            used = int(race_start_info["continue_num"])
            return {
                "source": "data.race_start_info.continue_num",
                "clocks_used": used,
                "clocks_left": max_clocks - used,
                "continue_type": 2,
            }

        return {"source": "unknown", "clocks_left": 0, "continue_type": 2}

    def _parse_race_rank(self, res):
        import base64
        import gzip
        import struct

        data = res.get("data", {})
        headers = res.get("data_headers", {})
        viewer_id = int(headers.get("viewer_id") or 0)

        race_start_info = data.get("race_start_info", {})
        horses = race_start_info.get("race_horse_data", [])

        player = next((horse for horse in horses if int(horse.get("viewer_id") or 0) == viewer_id), None)
        if not player:
            return 99

        frame_order = player.get("frame_order")
        if not frame_order:
            return 99

        result_index = frame_order - 1

        scenario_b64 = data.get("race_scenario")
        if not scenario_b64:
            return 99

        try:
            blob = gzip.decompress(base64.b64decode(scenario_b64))
        except Exception:
            return 99

        offset = 0

        if len(blob) < offset + 4: return 99
        header_len = struct.unpack_from("<i", blob, offset)[0]
        offset += 4 + header_len

        if len(blob) < offset + 16: return 99
        distance_diff_max, horse_num, horse_frame_size, horse_result_size = struct.unpack_from("<fiii", blob, offset)
        offset += 16

        if len(blob) < offset + 4: return 99
        pad_len = struct.unpack_from("<i", blob, offset)[0]
        offset += 4 + pad_len

        if len(blob) < offset + 8: return 99
        frame_count, frame_size = struct.unpack_from("<ii", blob, offset)
        offset += 8 + frame_count * frame_size

        if len(blob) < offset + 4: return 99
        pad_len = struct.unpack_from("<i", blob, offset)[0]
        offset += 4 + pad_len

        if not (0 <= result_index < horse_num):
            return 99

        if len(blob) < offset + (result_index + 1) * horse_result_size:
            return 99

        finish_order = struct.unpack_from("<i", blob, offset + result_index * horse_result_size)[0]

        return finish_order + 1

    def _should_force_clocks(self, program_id, preset):
        """Always retry (burn clocks) to win the Junior Make Debut, even if the
        global burn-clocks toggle is off. Controlled by preset 'force_clock_debut'
        (default True)."""
        if not (preset or {}).get("force_clock_debut", True):
            return False
        planner = getattr(self, "race_planner", None)
        if not planner:
            return False
        info = (planner.program or {}).get(int(program_id or 0)) or {}
        return "make debut" in str(info.get("name") or "").lower()

    def _compute_outcome(self):
        """A clear, top-level 'why did this career end' for the log -- so an early finish (a FAILED
        GOAL at, say, turn 54) is never mistaken for a clean 78-turn completion. One of:
        completed / goal_failed@turnN / error / auto_backoff / ended_early@turnN / stopped@turnN."""
        turn = int((self.report or {}).get("final_turn") or self.status.get("turn") or 0)
        if self.report and (self.report.get("error") or {}).get("message"):
            return "error"
        reason = str(getattr(self, "_career_end_reason", "") or "").lower()
        if "goal" in reason and "fail" in reason:
            return f"goal_failed@turn{turn}"
        if self.status.get("finished"):
            return "completed" if turn >= 73 else f"ended_early@turn{turn}"
        if self.status.get("circuit_tripped"):
            return "auto_backoff (server errors)"
        if self.stop_requested:
            return f"stopped@turn{turn}"
        return f"ended@turn{turn}"

    def _retry_on_loss(self, program_id, rank, preset, force_clocks=None):
        """ALWAYS spend a clock to re-run a losing finish, whenever one is available. The caller loops
        this while clocks remain (std or free), so a clock is used on EVERY loss until she wins or the
        budget is spent -- "use a clock whenever it can be used". rank 1 = won (stop); rank 99 is the
        _parse_race_rank parse-failure sentinel and must NOT count as a loss (a bad parse would burn
        every clock); real finishes are 1..18, so a loss is exactly 2..18. program_id/preset/force_clocks
        are kept for the caller's signature (debut logging still uses _should_force_clocks)."""
        # ALWAYS use clocks: retry ANY lost finish (rank 2..18) while a clock is available, in EVERY
        # scenario (URA included). If URA's race_continue happens to 205, the retry loop just breaks on
        # the exception (a few wasted calls, no infinite thrash) -- the user wants clocks always on.
        return 2 <= int(rank or 0) <= 18

    def _goal_race(self, program_id, turn, chara):
        """(this turn's career-goal entry if program_id is it else None, whether the trainee's goals
        are known at all)."""
        planner = getattr(self, "race_planner", None)
        if planner is None:
            return None, False
        if not (chara or {}).get("card_id"):
            card_id = ((getattr(self, "report", None) or {}).get("identity") or {}).get("card_id")
            chara = {"card_id": card_id} if card_id else {}
        goals = planner._goals(chara)
        for g in goals:
            if g.get("kind") != "race" or int(g.get("turn") or 0) != int(turn or 0):
                continue
            pids = {int(p) for p in (g.get("program_ids") or [g.get("program_id")]) if p}
            if not pids or int(program_id or 0) in pids:
                return g, True
        return None, bool(goals)

    @staticmethod
    def _rank_needed(goal):
        """Worst finish that still meets a goal: 'WIN (1st)' -> 1, 'Top 3' -> 3, 'Complete' -> 18."""
        req = str((goal or {}).get("require") or "").upper()
        if req.startswith("WIN"):
            return 1
        digits = "".join(ch for ch in req if ch.isdigit())
        return int(digits) if req.startswith("TOP") and digits else 18

    def _clock_retry_allowed(self, goal, goals_known, rank, preset):
        """Grand Live takes a clock only to re-run a career-goal race that missed its requirement:
        every other continue was answered 205 (77 of 92 in five careers, 2026-10-16), 13-18 rejected
        calls per career. Other scenarios accept clocks on any race (MANT: 1,242 non-goal continues
        accepted), so they keep retrying every loss -- and so does a trainee with no goal data."""
        try:
            scenario = self._scenario_id(preset)
        except AttributeError:          # bare runner (tests): no resolved scenario yet
            scenario = int((preset or {}).get("scenario_id") or 4)
        if scenario != 3 or not goals_known:
            return True
        return goal is not None and int(rank or 0) > self._rank_needed(goal)

    def _process_race_result(self, client, result_state, clock_state, preset, program_id,
                             current_turn, strategy=None, is_short=1):
        """Apply result-only race effects to both newly entered and resumed races.

        Entry and MANT pre-race item use deliberately stay in ``_race``: replaying either for an
        already-active race is unsafe. Rank/history capture, clock retries, learning and maiden
        state are safe to share once ``race_start`` has returned a result.
        """
        res = result_state or {}
        rank = self._parse_race_rank(res)
        self._log("race_rank", current_turn, f"rank {rank}")

        try:
            ai_learn.log_experience(self.base_dir, {
                "type": "race",
                "program_id": int(program_id or 0),
                "turn": int(current_turn or 0),
                "rank": int(rank or 0),
                "won": int(rank or 0) == 1,
                # The game's per-stat rank of our uma among the field [speed,stamina,power]
                # (1 = best, higher = outclassed). On a loss this tells ai_learn exactly which
                # stat the bot was short on, so it can train that up next career.
                "stat_marks": ai_learn.player_stat_marks(res),
            })
        except Exception:
            pass

        std_clocks, free_clocks = self._race_clocks(clock_state or {})
        force_clocks = self._should_force_clocks(program_id, preset)
        chara = ((clock_state or {}).get("data") or {}).get("chara_info") or {}
        goal, goals_known = self._goal_race(program_id, current_turn, chara)
        ranks = [rank]
        if 2 <= rank <= 18:
            if not self._clock_retry_allowed(goal, goals_known, rank, preset):
                self._log("race_loss", current_turn,
                          f"rank {rank}: no clock (Grand Live only allows one after a missed goal)")
            elif force_clocks:
                self._log("race_clock_force", current_turn, f"forcing 1st place on debut (rank {rank})")
            else:
                self._log("race_clock_burn", current_turn,
                          f"loss (rank {rank}) -> using clocks while available")

        while (self._retry_on_loss(program_id, rank, preset, force_clocks)
               and self._clock_retry_allowed(goal, goals_known, rank, preset)
               and (std_clocks > 0 or free_clocks > 0)):
            clocks_left = std_clocks + free_clocks
            continue_type = 1 if free_clocks > 0 else 2

            self._log("race_clock", current_turn,
                      f"rank {rank}, using clock ({clocks_left} left, type {continue_type})...")
            try:
                cont_res = client.race_continue(current_turn=current_turn, continue_type=continue_type)

                cont_data = cont_res.get("data") or {}
                new_home_info = cont_data.get("home_info")
                if isinstance(new_home_info, dict):
                    std_clocks = int(new_home_info.get("available_continue_num", 0))
                    free_clocks = int(new_home_info.get("available_free_continue_num", 0))
                else:
                    if free_clocks > 0:
                        free_clocks -= 1
                    else:
                        std_clocks -= 1

                if strategy and cont_data.get("unchecked_event_array"):
                    self._drain_events(client, strategy, cont_res)

                dna_gauss(0.166 + client.api_jitter, 0.05)
                dna_sleep(0.1, 0.45, 0.166 + client.api_jitter, 0.05)
                res = client.race_start(is_short=is_short, current_turn=current_turn)
                rank = self._parse_race_rank(res)
                ranks.append(rank)
                self._log("race_rank_retry", current_turn, f"rank {rank} after clock")
                with self.lock:
                    self.status["clocks_used"] = int(self.status.get("clocks_used") or 0) + 1
            except Exception as e:
                self._log("race_clock_failed", current_turn, str(e))
                break

        # Attach the final finish position to the action-history row for this turn.
        self._record_race_result(current_turn, rank)
        # ...and to the career log, which kept no finishing positions at all (a run's 16th places
        # on dirt could only be dug out of the raw captures).
        if getattr(self, "report", None) is not None:
            try:
                planner = getattr(self, "race_planner", None)
                ok = [r for r in ranks if 1 <= int(r or 0) <= 18]
                add_race(self.report, {
                    "turn": int(current_turn or 0),
                    "program_id": int(program_id or 0),
                    "race": planner.label(program_id) if planner else "",
                    "reason": get_turn(self.report, current_turn).get("decision_reason") or "",
                    "ranks": [int(r or 0) for r in ranks],
                    "final_rank": int(rank) if 1 <= int(rank or 0) <= 18 else 0,
                    "clocks": len(ranks) - 1,
                    "goal": (goal or {}).get("require"),       # None = not a career-goal race
                    "goal_met": (int(ok[-1]) <= self._rank_needed(goal)) if goal and ok else None,
                })
            except Exception:
                pass

        # A lost maiden stays armed for another attempt until the first win. Parse failures (99) must
        # never change that flag.
        planner = getattr(self, "race_planner", None)
        if planner is not None and (preset or {}).get("force_maiden_until_win", True):
            if int(rank or 0) == 1:
                if planner.rerun_program:
                    self._log("maiden_won", current_turn, "first win -> maiden re-run cleared")
                planner.rerun_program = 0
            elif 2 <= int(rank or 0) <= 18 and planner.is_maiden_program(program_id):
                planner.rerun_program = int(program_id or 0)
                self._log("maiden_rerun_armed", current_turn,
                          f"maiden lost (rank {rank}) -> re-race every turn until first win")

        if strategy:
            res_data = res.get("data") or {}
            if res_data.get("unchecked_event_array"):
                res = self._drain_events(client, strategy, res)

        return res, rank

    def _race_guard_tripped(self, race_turn):
        # RACE RETRY GUARD. A race that the server will not let us finish used to spin forever:
        # race_start -> race_end (1503) -> race_out -> load_career -> race_start -> ... Each pass is
        # ~4 API calls, the generic stuck-turn watchdog only reacts after ~150 iterations, and the
        # circuit breaker just cools 300s and hands the loop straight back. Observed live as an
        # endless "API error 1503 on single_mode_free/race_end" cycle.
        # Treating 102/1503/desync as non-fatal (so a genuine mid-race hiccup can reconcile) is
        # right; retrying the SAME race indefinitely is not. Give it a few attempts, then stop
        # cleanly -- the report still gets written and the career can be resumed by hand.
        # Shared by _race AND _race_progress: a failed _race reloads into a still-mid-race state,
        # which the brain routes to race_progress, so every later pass of the loop runs there.
        # A legit race takes 1-2 passes (_race, maybe one resume), well under the limit.
        if race_turn and race_turn == getattr(self, "_race_attempt_turn", None):
            self._race_attempt_count = getattr(self, "_race_attempt_count", 0) + 1
        else:
            self._race_attempt_turn = race_turn
            self._race_attempt_count = 1
        max_attempts = int(os.environ.get("UMA_RACE_MAX_ATTEMPTS", "4") or 4)
        if self._race_attempt_count <= max_attempts:
            return False
        msg = (f"race on turn {race_turn} would not complete after {max_attempts} attempts "
               f"(server keeps rejecting race_end/race_out) -- stopping cleanly instead of "
               f"looping. Finish or delete this career in-game, then re-run.")
        self._log("race_stuck_giveup", race_turn, msg)
        self._mark(last_error=msg, last_action="race-stuck-stop")
        self.stop_requested = True
        return True

    def _race(self, client, state, preset, payload):
        if self._race_guard_tripped(int(payload.get("current_turn") or 0)):
            return state
        race_key = (int(payload.get("current_turn") or 0), int(payload.get("program_id") or 0))
        if self._scenario_id(preset) == 4 and getattr(self, "_pre_race_items_for", None) != race_key:
            self.item_manager.recover_after_use_error = False
            state, used = self.item_manager.handle_pre_race(client, state, preset, payload, self.status, self.race_planner)
            for event in self.item_manager.use_attempt_events:
                self._debug("items_use_attempt", state, {
                    "selected": event.get("selected") or [],
                    "attempt": event.get("attempt") or [],
                    "payload": event.get("payload") or [],
                    "result": self._api_result(event.get("result") or {}),
                })
            if self.item_manager.recover_after_use_error:
                state = self._fresh_career_state(client, payload.get("_strategy"))
                self._debug_turn(state, preset)
                return state
            self._pre_race_items_for = race_key
            if used > 0:
                with self.lock:
                    self.status["items_used"] += used
                    self._log_locked("items_use", payload["current_turn"], f"pre-race {used}")

        program_id = payload.get("program_id")
        current_turn = payload["current_turn"]
        strategy = payload.get("_strategy")

        try:
            entry = client.race_entry(program_id=program_id, current_turn=current_turn)
        except Exception as exc:
            print(f"Race Entry Error at turn {current_turn}: {exc}")
            # Recover from the same transient session errors the command/event paths do -- crucially
            # 217/201 (invalid/expired SID, the post-update desync cascade): the client rotates the SID
            # on error, so reloading fresh career state fixes it. Without 217 here a race-turn desync
            # CRASHED the runner mid-career and wedged the slot ("another career is active"). Only a
            # non-recoverable error (e.g. 214 res_ver) still raises.
            if not _is_desync(exc):
                raise
            # Reject only a deterministic 205 (the server says this race is not valid for the
            # current game state, notably a Unity Cup collision). A network failure, busy response,
            # or expired SID says nothing about the race itself: permanently rejecting a mandatory
            # goal race after one transient fault can fail the whole career.
            if is_api_error(exc, 205):
                self.race_planner.reject(current_turn, program_id)
                self._log("race_reject", current_turn, program_id)
            else:
                self._log("race_entry_retry", current_turn,
                          f"transient entry failure; keeping race {program_id}: {exc}")
            # Unity Cup collision: on a cup turn where THIS trainee ALSO has a career-goal race (e.g.
            # Curren Chan's Hakodate Sprint at t36), race_entry for the individual race can 205 when the
            # game's pending action is the mandatory team cup. Do NOT drive the cup from here with a bare
            # {current_turn} -- that hands run_cup_race an empty team_data_set, so build_team_formation
            # returns [] and it _fails the lineup (and two such fails STOP the career). Just reload: the
            # fresh state carries the live playing_state (==7 when the cup is pending), so the next
            # next_decision routes through _cup_race_available -> team_race with the FULL team_data_set +
            # chara_info payload. The pid is already rejected above, so goal/forced_program won't re-offer
            # it and loop. (Non-cup 205/208s just reload too, exactly as before.)
            return self._fresh_career_state(client, strategy)
        self._log("race_entry", current_turn, program_id)
        entry_data = entry.get("data") or {}
        chara_info = entry_data.get("chara_info") or {}
        if strategy:
            if entry_data.get("unchecked_event_array"):
                entry = self._drain_events(client, strategy, entry)
                entry_data = entry.get("data") or {}
                chara_info = entry_data.get("chara_info") or {}

        # Resolve the effective running style from aptitude now that chara_info is loaded:
        # honor the preset style unless its aptitude is poor, then run what the uma is best at.
        running_style = resolve_running_style(preset, chara_info)
        try:
            _pref_style = int(preset.get("running_style")) if isinstance(preset, dict) else 0
        except (TypeError, ValueError):
            _pref_style = 0
        if running_style in (1, 2, 3, 4) and running_style != _pref_style:
            # Make the aptitude-driven divergence from the configured style visible.
            if _pref_style == 5:
                self._log("running_style_best", current_turn, f"best-aptitude style -> {running_style}")
            else:
                self._log("running_style_auto", current_turn, f"aptitude override: preset {_pref_style} -> {running_style}")
        try:
            current_running_style = int(chara_info.get("race_running_style") or 0)
        except (TypeError, ValueError):
            current_running_style = 0
        is_short = 1
        try:
            if running_style in (1, 2, 3, 4) and current_running_style != running_style:
                entry = client.race_entry(
                    program_id=program_id,
                    current_turn=current_turn,
                    running_style=running_style,
                    retry_208=0,
                    retry_205=0,
                )
            res = client.race_start(is_short=is_short, current_turn=current_turn)
        except Exception as e:
            # An HTTP 504 can land server-side, so its retry goes out on a now-stale session and gets
            # 217 -- the race may already be running (live 2026-10-20: "HTTP 504 on race_start" -> 217
            # -> RUNNER CRASH). Like the race_entry / race_end / race_out paths: reload (it re-logs in
            # on 217) and let the next pass resume the race from the server's own state (race_progress).
            # 102/1503 = already started. _race_guard_tripped bounds the retries per turn.
            if not (_is_desync(e) or is_api_error(e, 102, 1503)):
                raise
            self._log("race_start_desync", current_turn, f"reloading to resume the race: {e}")
            return self._fresh_career_state(client, strategy)
        self._log("race_start", current_turn, f"short {is_short}")
        res, _rank = self._process_race_result(
            client, res, state, preset, program_id, current_turn, strategy, is_short=is_short
        )

        out = res
        out_refreshed = False
        try:
            client.race_end(current_turn=current_turn)
            self._log("race_end", current_turn, "")
        except Exception as e:
            if is_api_error(e, 102, 1503):
                self._log("race_end_reconciled", current_turn, "server already done (102)")
            elif _is_desync(e):
                # SID/version desync (201/205/208/217). The client rotates the SID on error, so this
                # is recoverable exactly like every other turn phase treats it (see the 217 handling
                # in _run and _race_progress) -- do NOT crash the career here. race_out below, and
                # the fresh-state reload after it, reconcile the actual race result.
                self._log("race_end_desync", current_turn, f"desync, continuing: {e}")
            else:
                raise

        try:
            out_res = client.race_out(current_turn=current_turn)
            out = out_res
            out_refreshed = True
            if strategy:
                out_data = out.get("data") or {}
                if out_data.get("unchecked_event_array"):
                    out = self._drain_events(client, strategy, out)
        except Exception as e:
            if is_api_error(e, 102, 1503):
                self._log("race_out_reconciled", current_turn, "server already done (102)")
            elif _is_desync(e):
                # SID/version desync (201/205/208/217) -- the post-update cascade. This used to CRASH
                # the whole career ("RUNNER CRASH: API error 217 on single_mode_free/race_out"), which
                # left the career active server-side and wedged the loop. It is recoverable: the
                # client rotates the SID on error, so fall through with out_refreshed False and let
                # the reload below fetch the real post-race state.
                self._log("race_out_desync", current_turn, f"desync, reloading: {e}")
            else:
                raise

        # If race_out returned 102 ("already done") we never got a fresh post-race state, so
        # `out` is still the stale race_start state with the race active -- which makes
        # next_decision loop on the same race. Reload the real current state so the turn
        # advances (the common "resume a career mid/just-after a race" case).
        if not out_refreshed:
            try:
                out = self._fresh_career_state(client, strategy)
                self._log("race_reconcile_refresh", current_turn, "reloaded state after 102")
            except Exception as e:
                self._log("race_reconcile_refresh_failed", current_turn, str(e))

        # Re-check the shop AFTER the race: finishing a race can drop new shop items, and the
        # only other shop checks are per-turn and PRE-race -- so without this, items that appear
        # from completing the race are missed (entirely if it was the final race). Buy any new
        # ones now on the fresh post-race state. Fail-silent: a shop hiccup must not kill the run.
        if self._scenario_id(preset) == 4:
            try:
                out, post_bought = self.item_manager.buy_shop_items(client, out, preset, self.race_planner)
                if post_bought:
                    with self.lock:
                        self._log_locked("items_buy", current_turn, f"post-race {post_bought}")
            except Exception as e:
                self._log("post_race_shop_failed", current_turn, str(e))

        return out

    def _race_progress(self, client, payload, preset=None, source_state=None, strategy=None):
        """Finish a race that was already active when the career state was loaded.

        The resume path must not repeat race_entry or MANT pre-race item use, but once race_start
        returns a result it shares the normal rank/clock/history processing. Any ambiguous session
        state is reconciled from the authoritative career load instead of returning this method's
        internal decision payload to the main loop.
        """
        current_turn = payload["current_turn"]
        if self._race_guard_tripped(int(current_turn or 0)):
            return source_state or {}
        phase = payload.get("phase")
        chara = (payload.get("chara_info") or {})
        strategy = strategy or payload.get("_strategy")
        playing_state = chara.get("playing_state") or 0
        # ps 7 = an ARMED Unity Cup race (race_start_info with a program_id present, opponent already
        # selected). It runs through the same race_start/race_end/race_out flow as a normal race.
        if playing_state not in {2, 3, 4, 5, 7}:
            self._log("race_skip", current_turn, f"not in race (state={playing_state})")
            return self._fresh_career_state(client, strategy)
        
        if phase == "end":
            if playing_state in {1}:
                self._log("race_end_skip", current_turn, "resume already home")
            else:
                try:
                    client.race_end(current_turn=current_turn)
                    self._log("race_end", current_turn, "resume")
                except Exception as e:
                    if is_api_error(e, 102, 1503):
                        self._log("race_end_reconciled", current_turn, "resume already done (102)")
                    elif _is_desync(e):
                        self._log("race_end_desync", current_turn, f"resume desync, continuing: {e}")
                    else:
                        raise
            try:
                return client.race_out(current_turn=current_turn)
            except Exception as e:
                if (is_api_error(e, 102, 1503) or isinstance(e, StateRecoveryError)
                        or _is_desync(e)):
                    self._log("race_out_reconciled", current_turn, f"graceful exit: {e}")
                    # 102/already-done on resume -> reload the real state so the turn
                    # advances, instead of looping on the stale (still-in-race) payload.
                    return self._fresh_career_state(client, strategy)
                raise
        if phase == "out":
            self._log("race_out", current_turn, "resume")
            try:
                return client.race_out(current_turn=current_turn)
            except Exception as e:
                if (is_api_error(e, 102, 1503) or isinstance(e, StateRecoveryError)
                        or _is_desync(e)):
                    self._log("race_out_reconciled", current_turn, f"graceful exit: {e}")
                    # 102/already-done on resume -> reload the real state so the turn
                    # advances, instead of looping on the stale (still-in-race) payload.
                    return self._fresh_career_state(client, strategy)
                raise
        race_start_info = payload.get("race_start_info") or {}
        program_id = race_start_info.get("program_id")
        running_style = resolve_running_style(preset, chara)
        horse = ((race_start_info.get("race_horse_data") or []) + [{}])[0]
        try:
            current_running_style = int(chara.get("race_running_style") or horse.get("running_style") or 0)
        except (TypeError, ValueError):
            current_running_style = 0
        if playing_state in {2, 4} and program_id and running_style in (1, 2, 3, 4) and current_running_style != running_style:
            try:
                client.race_entry(
                    program_id=program_id,
                    current_turn=current_turn,
                    running_style=running_style,
                    retry_208=0,
                    retry_205=0,
                )
            except Exception as e:
                if _is_desync(e):
                    self._log("race_style_desync", current_turn, f"resume style change failed: {e}")
                    return self._fresh_career_state(client, strategy)
                raise
        result = None
        try:
            result = client.race_start(is_short=1, current_turn=current_turn)
            self._log("race_start", current_turn, "resume")
        except Exception as e:
            # 102 = the race already started (armed cup already run / resumed mid-race). Not fatal:
            # fall through to race_end/race_out to resolve + exit instead of crashing the runner.
            if is_api_error(e, 102, 1503):
                self._log("race_start_reconciled", current_turn, "already started (102)")
            elif _is_desync(e):
                self._log("race_start_desync", current_turn, f"resume desync, reloading: {e}")
                return self._fresh_career_state(client, strategy)
            else:
                raise
        if isinstance(result, dict) and isinstance(result.get("data"), dict) and result.get("data"):
            result, _rank = self._process_race_result(
                client, result, source_state or result, preset, program_id, current_turn,
                strategy, is_short=1,
            )
        if playing_state in {1}:
            self._log("race_end_skip", current_turn, "resume already home")
        else:
            try:
                client.race_end(current_turn=current_turn)
                self._log("race_end", current_turn, "resume")
            except Exception as e:
                if is_api_error(e, 102, 1503):
                    self._log("race_end_reconciled", current_turn, "resume already done (102)")
                elif _is_desync(e):
                    self._log("race_end_desync", current_turn, f"resume desync, continuing: {e}")
                else:
                    raise
        try:
            return client.race_out(current_turn=current_turn)
        except Exception as e:
            if (is_api_error(e, 102, 1503) or isinstance(e, StateRecoveryError)
                    or _is_desync(e)):
                self._log("race_out_reconciled", current_turn, f"graceful exit: {e}")
                # 102/already-done on a RESUMED race -> reload the real post-race state so the turn
                # advances, instead of returning the stale (still-in-race) payload and re-deciding
                # race_progress forever (which stalled URA resumes -> ended@turnN). Mirrors the
                # phase=="end"/"out" branches above.
                return self._fresh_career_state(client, strategy)
            raise

    def _spend_remaining_sp(self, client, state, preset, max_passes=8):
        """Keep buying skills until nothing more can be bought -- SP below the cheapest affordable skill,
        or a pass purchases nothing (no candidates left). Replaces the old single 'if SP > 200' retry,
        which left ~250 SP unspent; now it spends down to the floor. Capped so a stuck/205 buy (no
        progress) can't loop forever."""
        for _ in range(max_passes):
            sp_before = int(((state.get("data") or {}).get("chara_info") or {}).get("skill_point") or 0)
            if sp_before <= 0:
                break
            print(f"buying down leftover SP ({sp_before})...")
            state = self._buy_skills(client, state, preset, True, retry=False)
            sp_after = int(((state.get("data") or {}).get("chara_info") or {}).get("skill_point") or 0)
            if sp_after >= sp_before:   # bought nothing this pass -> can't buy any more
                break
        return state

    # A goal is "hard" when it needs Top 3 or better from the Classic year on: on 2026-10-20 the
    # Top 5 goals were won 1st, while the 3000 m / 3200 m Top 3 goals needed clocks in 2 of 5 careers
    # and ended one (6th, 10th, 4th, 11th) with 1,462 SP unspent and no skill bought.
    HARD_GOAL_RANK = 3
    HARD_GOAL_FROM_TURN = 25

    def _buy_before_goal(self, client, state, preset, payload):
        """Before a hard career-goal race, buy the preset's BEFORE GOAL RACES skills (Skills tab)."""
        turn = int((payload or {}).get("current_turn") or 0)
        if not (preset or {}).get("learn_skill_before_goal") or getattr(self, "_goal_skill_turn", None) == turn:
            return state
        chara = ((state or {}).get("data") or {}).get("chara_info") or {}
        goal, _known = self._goal_race((payload or {}).get("program_id"), turn, chara)
        if not goal or turn < self.HARD_GOAL_FROM_TURN or self._rank_needed(goal) > self.HARD_GOAL_RANK:
            return state
        self._goal_skill_turn = turn
        try:
            state, bought = self.skill_buyer.buy_before_goal(client, state, preset)
        except Exception as exc:          # a failed buy must never cost the race itself
            self._log("skills_before_goal_failed", turn, str(exc)[:120])
            return state
        for event in self.skill_buyer.attempt_events:
            self._debug("skills_attempt", state, {
                "selected": event.get("selected") or [],
                "attempt": event.get("attempt") or [],
                "selected_total_cost": self._sum_cost(event.get("selected") or []),
                "attempt_total_cost": self._sum_cost(event.get("attempt") or []),
                "payload": event.get("payload") or [],
                "result": self._api_result(event.get("result") or {}),
                "before_goal": goal.get("race") or "",
            })
        if bought:
            with self.lock:
                self.status["skills_bought"] += bought
                self._log_locked("skills_before_goal", turn,
                                 f"{bought} before {goal.get('race')} ({goal.get('require')})")
        return state

    def _buy_skills(self, client, state, preset, force, retry=True):
        # A career-end (force) buy that hits a 201/205/208 SID DESYNC must reload AND RETRY, not just
        # reload: at the Unity finish the buy runs on the post-race state whose SID is stale, so every
        # gain_skills 205s -- and the old code reloaded but never retried, so the career ended with all
        # SP UNSPENT and zero skills bought. Reload refreshes the SID; retry lands the purchase on it.
        # Bounded to a few passes so a genuinely stuck buy can't loop. Per-turn (non-force) buys keep
        # the single-attempt behavior (a 205 there is harmlessly deferred to this end-of-career dump).
        # retry=False (leftover-SP dump): the MAIN buy already landed, so a 205 here means the finish
        # won't take a 2nd batch -- one reload still recovers state for finish, but re-buying is a
        # pointless 205 storm against the server, so cap it at a single attempt.
        bought = 0
        for attempt in range((3 if force else 1) if retry else 1):
            self.skill_buyer.recover_after_error = False
            state, got = self.skill_buyer.buy(client, state, preset, force)
            bought += got
            for event in self.skill_buyer.attempt_events:
                self._debug("skills_attempt", state, {
                    "selected": event.get("selected") or [],
                    "attempt": event.get("attempt") or [],
                    "selected_total_cost": self._sum_cost(event.get("selected") or []),
                    "attempt_total_cost": self._sum_cost(event.get("attempt") or []),
                    "payload": event.get("payload") or [],
                    "result": self._api_result(event.get("result") or {}),
                })
            if not self.skill_buyer.recover_after_error:
                break
            try:
                state = self._fresh_career_state(client)
                self._debug_turn(state, preset)
                if force and retry and attempt + 1 < 3:
                    self._log("skills_desync_retry",
                              (state.get("data") or {}).get("chara_info", {}).get("turn", 0),
                              f"gain_skills 205/201/208 -> reload+retry (attempt {attempt + 1})")
            except Exception as e:
                print(f"Skill phase reload failure: {e}")
                break
        if bought:
            with self.lock:
                self.status["skills_bought"] += bought
                self.status["last_action"] = f"skills {bought}"
                self._log_locked("skills", (state.get("data") or {}).get("chara_info", {}).get("turn", 0), bought)
        return state

    def _scenario_id(self, preset):
        """The RESOLVED scenario id for this run (live-aware, set in start() via resolve_scenario_id),
        NOT the raw preset value. A Unity/Team preset that omits scenario_id resolves to 2 from the
        live game -- so the MANT item gates MUST read this, not preset["scenario_id"] (which defaults
        to 4). Reading the raw preset made MANT's item engine fire during a Unity career
        (multi_item_exchange / multi_item_use on team turns). Falls back to the preset only when no
        run is active (status scenario_id still 0)."""
        return int(self.status.get("scenario_id")
                   or (preset or {}).get("scenario_id") or (preset or {}).get("scenario") or 4)

    def _handle_items(self, client, state, preset, best_command):
        if self._scenario_id(preset) != 4:
            return state
        self.item_manager.recover_after_exchange_error = False
        self.item_manager.recover_after_use_error = False
        state, bought, used = self.item_manager.handle(client, state, preset, best_command, self.status, self.race_planner)
        for event in self.item_manager.buy_attempt_events:
            self._debug("items_buy_attempt", state, {
                "selected": event.get("selected") or [],
                "attempt": event.get("attempt") or [],
                "selected_total_cost": self._sum_cost(event.get("selected") or []),
                "attempt_total_cost": self._shop_attempt_cost(event.get("attempt") or [], event.get("selected") or []),
                "payload": event.get("payload") or [],
                "result": self._api_result(event.get("result") or {}),
            })
        for event in self.item_manager.use_attempt_events:
            self._debug("items_use_attempt", state, {
                "selected": event.get("selected") or [],
                "attempt": event.get("attempt") or [],
                "payload": event.get("payload") or [],
                "result": self._api_result(event.get("result") or {}),
            })
        if self.item_manager.recover_after_exchange_error or self.item_manager.recover_after_use_error:
            try:
                state = self._fresh_career_state(client)
                self._debug_turn(state, preset)
            except Exception as e:
                print(f"Item phase reload failure: {e}")
                pass
        if bought or used:
            turn = (state.get("data") or {}).get("chara_info", {}).get("turn", 0)
            with self.lock:
                self.status["items_bought"] += bought
                self.status["items_used"] += used
                if bought:
                    self._log_locked("items_buy", turn, bought)
                if used:
                    self._log_locked("items_use", turn, used)
        return state

    def _merge_state(self, old_state, new_state):
        if not old_state:
            return new_state
        merged = dict(old_state)
        merged["data"] = dict(old_state.get("data") or {})
        for k, v in (new_state.get("data") or {}).items():
            if isinstance(v, dict) and k in merged["data"] and isinstance(merged["data"][k], dict):
                merged_sub = dict(merged["data"][k])
                for sub_k, sub_v in v.items():
                    if sub_v is not None:
                        merged_sub[sub_k] = sub_v
                merged["data"][k] = merged_sub
            else:
                merged["data"][k] = v
        return merged

    def _command_from_decision(self, state, decision):
        payload = decision.payload or {}
        command_type = int(payload["command_type"])
        command_id = int(payload["command_id"])
        command_group_id = int(payload.get("command_group_id", 0))
        for cmd in ((state.get("data") or {}).get("home_info") or {}).get("command_info_array") or []:
            if int(cmd.get("command_type") or 0) != command_type:
                continue
            if command_type == 3 and int(cmd.get("command_id") or 0) == command_group_id:
                return cmd
            if int(cmd.get("command_id") or 0) == command_id:
                return cmd
        return payload

    def _track_turn_scores(self, state):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        max_score = 0
        has_training = False
        for cmd in commands:
            if int(cmd.get("command_type") or 0) == 1:
                has_training = True
                score = self.item_manager._command_stat_gain(cmd)
                if score > max_score:
                    max_score = score
        if has_training:
            with self.lock:
                dh = self.status.setdefault("date_history", [])
                sh = self.status.setdefault("score_history", [])
                if not dh or dh[-1] != turn:
                    dh.append(turn)
                    sh.append(max_score)
                    if len(dh) > 48:
                        dh.pop(0)
                        sh.pop(0)

