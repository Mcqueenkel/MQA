import json
import os

from career_bot.core.events import EventManager
from career_bot.core.base import Decision, ScenarioStrategy
from career_bot.core.foresight import CareerForecaster
from career_bot.core import ai_learn
from career_bot.core import goal_solver


STAT_TARGETS = {
    1: 0,
    2: 1,
    3: 2,
    4: 3,
    5: 4,
    30: 5,
}

# Per-stat REAL in-game cap, sent by the game in chara_info. 1200 by default but blue
# inheritance factors / scenario bonuses raise it (1300-1600), so the scorer reads it live
# instead of assuming 1200 -- otherwise it would refuse to train a stat that can still grow.
STAT_CAP_KEYS = {0: "max_speed", 1: "max_stamina", 2: "max_power", 3: "max_guts", 4: "max_wiz"}
BASE_STAT_CAP = 1200  # fallback only, if chara_info somehow lacks the max_* field

TRAINING_COMMANDS = {101: 0, 105: 1, 102: 2, 103: 3, 106: 4, 601: 0, 602: 1, 603: 2, 604: 3, 605: 4}
# First turn of the Senior year. Skill hints get no priority from here on (training, Grand Live
# lessons, event choices): raw stats matter more by then.
SENIOR_START_TURN = 49
TRAINING_NAMES = ["Speed", "Stamina", "Power", "Guts", "Wit"]
# Stat index (0..4) -> the chara_info stat field. Used by the per-preset USER stat cap
# ("stat_caps"): once a stat reaches its cap the bot stops DEDICATING training turns to it
# (the stat can still rise from events / secondary gains of other trainings).
STAT_NAMES = ["speed", "stamina", "power", "guts", "wiz"]
SUMMER_CAMP_TURNS = {36, 37, 38, 39, 40, 60, 61, 62, 63, 64}
SUMMER_CONSERVE_TURNS = {35, 36, 59, 60}
RESET_WHISTLE_ITEM_ID = 7001  # re-rolls the training board; if none owned, summer falls back to racing
# Turn-quality lookahead: turns right before the high-yield summer camps / finals, where energy
# is banked regardless of the board so the uma enters the event near full and spends freely.
PRE_EVENT_BANK_TURNS = {33, 34, 35, 57, 58, 59, 71, 72, 73}
# Turns the train-vs-race gate discounts a race's value: the ACTUAL in-camp turns with Lv5
# facilities (verified 37-40 / 61-64 in master.mdb). Deliberately NOT SUMMER_CAMP_TURNS --
# that set also contains 36/60, which are the late-June G1 race week, not camp training.
RACE_VALUE_CAMP_TURNS = {37, 38, 39, 40, 61, 62, 63, 64}
# MANT-only all-out climax window: the last 6 turns (TS climax finale). On these MANT trains a positive
# board when it is already safe or an owned energy item / charm can rescue it (mirrors mant_items).
CLIMAX_TRAIN_TURNS = {73, 74, 75, 76, 77, 78}
# NO-HAMMER base physical-stat gain (Spd/Sta/Pow/Guts; climax gives +0 Wit) per TS climax race --
# the finale (t78) pays ~1.8x a regular climax. Measured live via the climax-gain capture
# (runner.py). The actual credit multiplies each by the cleat hammer the bot will spend there
# (see _climax_stat_credit), so it self-adjusts to the hammers actually in hand: 0 hammers ->
# 15+15+27 = 57; 1 Master + 1 Artisan -> 18+15+36 = 69; 2 Artisan + 1 Master -> 18+18+36 = 72.
CLIMAX_RACE_GAIN_BASE = {74: 15, 76: 15, 78: 27}
CLEAT_MULT_MASTER = 1.35    # 35% Master Cleat Hammer
CLEAT_MULT_ARTISAN = 1.20   # 20% Artisan Cleat Hammer
MASTER_CLEAT_ITEM_ID = 11002
ARTISAN_CLEAT_ITEM_ID = 11001
# How many 35% Master Cleat Hammers to keep IN HAND at each TS climax turn, reserved for the later
# (bigger) climaxes: 1 in hand -> spend only at t78; 2 -> t76+t78; 3 -> t74/76/78. Used by the climax
# cleat-credit scoring here AND by the MANT item manager's buy/use logic (which imports it from here).
MASTER_CLEAT_CLIMAX_RESERVE = {74: 2, 76: 1, 78: 0}
SUMMER_CONSERVE_ENERGY = 60
ENERGY_FAST_MEDIC = 80
ENERGY_MEDIC_GENERAL = 85
# Historical default for the train-vs-race gate. The comparison itself is value-based now
# (_race_value); this remains only as the enabled/disabled sentinel -- preset
# "race_skip_train_stat": 0 keeps its long-standing meaning of "never skip a race".
RACE_SKIP_TRAIN_STAT = 30
ENERGY_ITEM_VALUES = {2001: 20, 2002: 40, 2003: 65, 2101: 100}  # Vita 20/40/65, Royal Kale Juice
GOOD_LUCK_CHARM_ID = 10001
DECK_PARTNERS = {1, 2, 3, 4, 5, 6}
BAD_EFFECT_NAMES = {
    1: "Night Owl",
    2: "Slacker",
    3: "Skin Outbreak",
    4: "Slow Metabolism",
    5: "Migraine",
    6: "Practice Poor",
}

# --- Fixed Trackblazer schedule for a Team Sirius + Heirs to the Throne deck ---------------------
# Both are "Group" support cards (support_card_id matches support_list.json keys). Their
# recreations/outings are the deck's main bond + rainbow lever, so they're run on a fixed calendar.
TEAM_SIRIUS_SUPPORT_ID = 30081
THRONE_SUPPORT_ID = 30067
SIRIUS_THRONE_GROUP_IDS = (TEAM_SIRIUS_SUPPORT_ID, THRONE_SUPPORT_ID)
# Focus-train the two group cards (build their bond) before the maiden race -- the planner already
# gates auto fan-races to turn > 11, so this is the pre-debut window. The junior FOCUS itself ships
# as the existing generic junior_bond_rush ordering in _pick_scored_training; a group-card-SPECIFIC
# junior bias (e.g. preferring the facility the two Group cards sit on) is capture-blocked -- which
# facility a Group card appears on per turn is not observable from the repo, so it isn't forced.
JUNIOR_FOCUS_LAST_TURN = 11
# The "group outing" recreation command. A Group card adds a SECOND command_type==3 command
# (command_id 390) alongside the normal mood-recreation (301) and the summer-camp recreation (304);
# 390 is the one that opens the group-card character outing. Decoded from a live capture
# (uma_runtime/bot_logs/recreation_debug_t*.json): every non-camp turn offers [301, 390].
GROUP_OUTING_COMMAND_ID = 390
# The outing menu ("Choose Recreation Partner") offers the Group card's characters AND the CARD
# ITSELF (the screenshot's "Heirs to the Throne" / "Team Sirius" partner). The card-itself
# recreation is tracked by the slot's ROW-LEVEL is_outing/story_step (NOT group_outing_info_array)
# and can be done up to GROUP_CARD_OUTING_MAX times (the menu shows 2 progress pips). A character's
# select_id is its chara_id (CONFIRMED live); the card-itself select_id is a BEST GUESS pending live
# confirmation -- if a test run does the wrong thing, try another candidate (slot target_id, or the
# support_card_id). Its failure is isolated (see runner: a card-outing exec error only blocks card
# outings, never the confirmed character ones).
# The card-itself ("group") recreation select_id. Characters use their chara_id; the card uses a
# value that ISN'T in any static data, so this is a BEST GUESS to confirm live. Candidates, in
# order to try: the card's own support_card_id (current), the slot target_id, then 0.
# _card_outing_select_id(support_id, slot) returns it; change the body to try the next candidate.
GROUP_CARD_OUTING_MAX = 2
# Each group card's own signature chara_id (from master.mdb support_card_data) -- the candidate for
# the card-itself ("group") recreation's select_id. The card's outing_max there (Throne 2 / Sirius 1)
# matches this schedule's card-turn counts (Throne t51+t59, Sirius t58), so the card-itself outing
# likely reuses this chara_id, routing to the card story once that character's own outing is done.
CARD_SIGNATURE_CHARA = {TEAM_SIRIUS_SUPPORT_ID: 1001, THRONE_SUPPORT_ID: 1017}
# turn -> (chara_id, group support id, label). chara_id is the named outing target for this date
# (1001 Special Week, 1002 Silence Suzuka, 1003 Tokai Teio, 1013 Mejiro McQueen, 1016 Narita Brian,
# 1017 Symboli Rudolf, 1030 Rice Shower, 1035 Winning Ticket, 1073 Tsurumaru Tsuyoshi). chara_id
# None = the CARD-ITSELF recreation on that group card (the user's "Throne recreation" / "Team Sirius
# main recreation"). Turn numbers: turn = year_offset(0/24/48) + (month-1)*2 + half(Early=1/Late=2)
# (verified vs race_map: Senior Late Feb = turn 52). NOTE: the user called Tokai Teio a Team Sirius
# outing, but the capture lists chara 1003 under Heirs to the Throne (slot 6) -- go by chara_id.
SIRIUS_THRONE_RECREATION_SCHEDULE = {
    18: (1002, TEAM_SIRIUS_SUPPORT_ID, "Silence Suzuka"),     # Junior  Late Sep
    22: (1016, TEAM_SIRIUS_SUPPORT_ID, "Narita Brian"),       # Junior  Late Nov
    26: (1017, THRONE_SUPPORT_ID,      "Symboli Rudolf"),     # Classic Late Jan
    28: (1030, TEAM_SIRIUS_SUPPORT_ID, "Rice Shower"),        # Classic Late Feb
    32: (1001, TEAM_SIRIUS_SUPPORT_ID, "Special Week"),       # Classic Late Apr
    36: (1003, THRONE_SUPPORT_ID,      "Tokai Teio"),         # Classic Late Jun (capture: Throne)
    43: (1013, TEAM_SIRIUS_SUPPORT_ID, "Mejiro McQueen"),     # Classic Early Oct
    47: (1073, THRONE_SUPPORT_ID,      "Tsurumaru Tsuyoshi"), # Classic Early Dec
    51: (None, THRONE_SUPPORT_ID,      "Throne outing"),      # Senior  Early Feb (any Throne char)
    55: (1035, TEAM_SIRIUS_SUPPORT_ID, "Winning Ticket"),     # Senior  Early Apr
    58: (None, TEAM_SIRIUS_SUPPORT_ID, "Team Sirius outing"), # Senior  Late May (any Sirius char)
    59: (None, THRONE_SUPPORT_ID,      "Throne outing"),      # Senior  Early Jun (any Throne char)
}

# --- Throne-ONLY deck (Heirs to the Throne present, Team Sirius ABSENT) ---------------------------
# The fixed schedule above interleaves 7 Sirius dates with 5 Throne dates; with no Sirius card those
# Sirius dates are dead, and the generic pull-forward burns every Throne outing onto them in junior.
# For a Throne-only deck, deploy each CHARACTER outing when its situational payoff actually lands
# (the user's method) and keep the two card-itself steps on their fixed dates. chara_ids match
# SIRIUS_THRONE_RECREATION_SCHEDULE / _THRONE_OUTINGS.
THRONE_RUDOLF = 1017        # Symboli Rudolf -- prerequisite for the card steps (card reuses his
                            # select_id, routing to the card story only after his own outing is
                            # done). No situational hold: done as soon as he unlocks (i.e. in junior).
THRONE_TOKAI = 1003         # Tokai Teio -- the MOOD lever: held for after a race streak.
THRONE_TSURUMARU = 1073     # Tsurumaru Tsuyoshi -- the ENERGY lever: held for a low-vital classic turn.
THRONE_ONLY_CARD_TURNS = {1: 51, 2: 59}   # card-itself step -> fixed turn (catches up after if missed)
THRONE_MOOD_RACE_STREAK = 3               # consecutive race turns before the Tokai (mood) outing fires
THRONE_FALLBACK_BY = 47                   # past this turn, stop holding -> use a still-undone char
                                          # outing before senior so it isn't wasted


class BaseTrainingStrategy(ScenarioStrategy):
    """The SHARED training brain every scenario inherits (ex-MantStrategy, moved out of the MANT
    file: Unity and URA were always running this exact code via inheritance, so it was never
    MANT-only -- it just lived under MANT's name). Cap-aware command scoring, bond/rainbow,
    rest/recreate/medic gates, energy rescue, goal/fan race invocation, the shared 78-turn
    calendar, and the Sirius/Throne group-outing schedule (deck-driven, not scenario-driven).

    Subclasses set scenario_id and override only what their scenario truly changes:
    scenarios/mant.py (4), scenarios/unity.py (2), scenarios/ura.py (1). The few scenario_id
    checks kept in here (e.g. career-goal emphasis off for MANT) are cross-scenario RULES keyed
    by that attribute -- identical behavior from any file."""

    def __init__(self, race_planner=None):
        self.race_planner = race_planner
        # Bind this scenario's race policy onto the planner: RacePlanner itself is scenario-agnostic
        # (core/), so the scenario class's RACE_POLICY (career_bot/scenarios/*.py) is what turns its
        # per-scenario branches on/off. Copied so a per-career planner never aliases class state.
        if race_planner is not None:
            race_planner.policy = dict(self.RACE_POLICY)
        self.event_manager = None
        base_dir = self.race_planner.base_dir if self.race_planner else None
        # Reuse the race planner's DataStore so the whole career shares one loaded/validated
        # copy of the reference data instead of each component re-reading data/*.json.
        data_store = getattr(self.race_planner, "data_store", None) if self.race_planner else None
        if base_dir:
            self.event_manager = EventManager(base_dir, data_store=data_store)
        # Forward-looking career planner: predicts the build this career should aim for and
        # feeds per-stat targets into the scorer, so training follows the predicted direction
        # rather than raw single-turn gain. Recomputed each turn in next_decision.
        self.forecaster = CareerForecaster(base_dir, data_store=data_store)
        self._forecast = None
        # Latest preset, captured each turn so the event chooser (which runs during event
        # draining, outside next_decision) can score choices against the build (running
        # style / wanted skills) without threading the preset through every call site.
        self._preset = None
        # Turn-quality lookahead: rolling history of each turn's best training score, so the
        # rest gate can tell a weak board from a strong one and bank/spend energy accordingly.
        self._score_history = []
        self._quality_last_turn = -1
        # "Learn to win": cached per-stat emphasis from ai_learn.race_train_emphasis (which stats
        # the bot's confident losing races reward). Computed once (lazily) and reused for the whole
        # career -- the learned model only changes between careers (runner retrains after each).
        self._train_emphasis = None
        self._train_emphasis_loaded = False
        # Career-goal emphasis: this trainee's goal_solver stat_priority (the stats its unique career
        # goals demand), cached per card_id. Blended with the learned emphasis so training follows the
        # goals from turn 1 -- before any losses are recorded. ON for every scenario EXCEPT MANT (4):
        # playing MANT is the only way to disable the career-goal focus.
        self._goal_emphasis = None
        self._goal_emphasis_card = None
        # Throne-only adaptive schedule: turn numbers on which we raced, to detect a race streak for
        # the Tokai Teio (mood) outing. Deduped by turn; reset per career (runner builds a fresh
        # strategy each start()).
        self._raced_turns = set()
        # One fan-farm race per career (Asahi OR Hopeful, never both). Stores the TURN it was chosen on
        # (0 = not yet), like _junior_recreated_turn: a same-turn retry (race_entry failed, state
        # reloaded) re-offers it; only LATER turns are blocked. Resets per career with the fresh strategy.
        self._fan_raced = 0
        # One mandatory pre-debut (Junior turns 1..11) recreation per career: banks a mood boost
        # early so every later training gains more. Stores the TURN it committed on (0 = not yet), NOT
        # a boolean -- so the runner's post-item re-decide on the SAME turn still returns recreation
        # instead of falling through to training. Resets per career.
        self._junior_recreated_turn = 0

    def next_decision(self, state, preset):
        self._preset = preset
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        home = data.get("home_info") or {}
        self._dump_recreation_debug(data, chara, preset)
        if "single_mode_finish_common" in data:
            return Decision("finish", {"current_turn": chara.get("turn", 0)}, "finished")
        events = data.get("unchecked_event_array") or []
        if events:
            event = events[0] or {}
            choice = self._choice(event)
            payload = {"event_id": event.get("event_id"), "chara_id": event.get("chara_id", 0), "choice_number": choice, "current_turn": chara.get("turn", 0)}
            if choice is None:
                payload = {"event_id": event.get("event_id"), "_event": event, "_current_turn": chara.get("turn", 0)}
            return Decision("event", payload, "event")
        if chara.get("state") == 3:
            return Decision("finish", {"current_turn": chara.get("turn", 0)}, "ready to finish")
        race = data.get("race_start_info")
        playing_state = (chara.get("playing_state") or 0)
        if playing_state == 3:
            return Decision("race_progress", {"current_turn": chara.get("turn", 0), "phase": "start", "race_start_info": race, "chara_info": chara}, "resume race start")
        if playing_state == 5:
            return Decision("finish", {"current_turn": chara.get("turn", 0)}, "goal failed / career end")     
        if race and race.get("program_id") and playing_state in (2, 4):
            return Decision("race_progress", {"current_turn": chara.get("turn", 0), "phase": "start", "race_start_info": race, "chara_info": chara}, "race start")
        # Foresight is ON by default: read the trainee's distance aptitude and steer training toward a
        # SMART build for it (B/A/S distances -> the right stat profile), instead of greedily chasing
        # raw stat gain. It's a soft lean (fills only stats you didn't cap; explicit stat_caps still
        # win), fails safe to a no-op on missing data, and never spams the webhook (the Career Forecast
        # embed is separately gated by notify_forecast, default off). Disable per preset with
        # "career_foresight": false to fall back to pure raw-gain scoring.
        # Skip foresight entirely when the scenario's own stat caps are supplying the training targets:
        # foresight is already bypassed in scoring then (every stat has a cap, nothing left at 9999 for
        # it to fill), and its 🔮 forecast would show low aptitude numbers that DON'T match where the
        # scenario caps actually train each stat -- which reads as "the bot won't train past X". So
        # career_foresight (the aptitude-aim mode + its forecast) applies only when scenario_stat_caps
        # is OFF. Disable scenario caps (scenario_stat_caps=false) to get the foresight aim back.
        if preset.get("career_foresight", True) and not self._scenario_stat_caps(preset):
            self._forecast = self.forecaster.forecast(data, preset)
        else:
            self._forecast = None
        skipped_race = ""   # why the optional-race guard dropped this turn's scheduled race, for the log
        if self.race_planner:
            # Career-goal race: run THIS trainee's scheduled goal race (from career_goals.json) the
            # moment the game offers it, ahead of everything else -- the per-trainee JSON schedule is
            # the source of truth, so a goal race is entered on its turn even if the game doesn't
            # hard-force it. The "goal: <race> (<require>)" reason surfaces goal-following in the log.
            goal_program_id = self.race_planner.goal_program(state)
            if goal_program_id:
                self._raced_turns.add(int(chara.get("turn") or 0))
                return Decision("race", {"program_id": goal_program_id, "current_turn": chara.get("turn", 0), "_strategy": self},
                                self.race_planner.goal_label(state, goal_program_id))
            forced_program_id = self.race_planner.forced_program(state, preset)
            if forced_program_id:
                self._raced_turns.add(int(chara.get("turn") or 0))
                return Decision("race", {"program_id": forced_program_id, "current_turn": chara.get("turn", 0), "_strategy": self}, self.race_planner.label(forced_program_id))
            # Fan-goal race: this char has an unmet fan-count goal and the aptitude-matched fan G1
            # (Asahi/mile or Hopeful/medium) is on offer this turn. Run it authoritatively -- like a
            # forced race, bypassing the train-vs-race gate -- because failing the fan goal fails the
            # career. Applies to MANT and Unity (UnityStrategy inherits this path).
            # preset is passed so a race the user SCHEDULED for turn 23/24 takes the slot instead of
            # the aptitude-picked G1 -- still run authoritatively here, so the fan goal is still met.
            turn = int(chara.get("turn") or 0)
            fan_program_id = 0 if self._fan_race_done(state, turn) else self.race_planner.fan_goal_program(state, preset)
            if fan_program_id:
                self._raced_turns.add(turn)
                self._fan_raced = turn   # only ONE fan race per career (Asahi OR Hopeful, not both)
                return Decision("race", {"program_id": fan_program_id, "current_turn": chara.get("turn", 0), "_strategy": self},
                                "fan goal -> " + self.race_planner.label(fan_program_id))
            # Goal-ENTRY guard: a later goal race can need more fans to ENTER than the trainee has, and
            # training earns none -- a live career died sitting on 11,196 fans for 7 turns against a
            # 12,000 gate (Champions Cup), then failed. Fires only on a real deficit, only near that
            # goal's deadline, and only on a race she can actually run. Off via fan_eligibility_farm.
            eligibility_program_id = 0
            if preset.get("fan_eligibility_farm", True):
                picker = getattr(self.race_planner, "eligibility_fan_program", None)
                eligibility_program_id = picker(state, preset.get("fan_farm_window")) if callable(picker) else 0
            if eligibility_program_id:
                self._raced_turns.add(int(chara.get("turn") or 0))
                return Decision("race", {"program_id": eligibility_program_id, "current_turn": chara.get("turn", 0), "_strategy": self},
                                "goal entry-fans -> " + self.race_planner.label(eligibility_program_id))
            program_id = self.race_planner.choose(state, preset)
            # Optional-race guard: every race reaching here is optional (goal, forced, fan-goal and
            # entry-fan races returned above), so it may be dropped. Runs before the summer fallback
            # and the train-vs-race gate, which would otherwise race any G1/scheduled race regardless.
            veto = self._optional_race_veto(state, chara, preset, program_id) if program_id else ""
            if veto:
                skipped_race = f"skipped {self.race_planner.label(program_id)}: {veto}"
                program_id = 0
            # Summer race fallback: on a summer turn with no good (>=2 rainbow) training and no
            # Reset Whistle to re-roll the board, race the best available track instead of
            # wasting the camp turn on a weak training (bypasses the normal train-vs-race gate
            # precisely because there is no good training to protect).
            if program_id and self._should_summer_race(data, chara, preset):
                self._raced_turns.add(int(chara.get("turn") or 0))
                return Decision("race", {"program_id": program_id, "current_turn": chara.get("turn", 0), "_strategy": self},
                                "summer: no good training -> race " + self.race_planner.label(program_id))
            if program_id and not self._train_outvalues_race(data, chara, preset, program_id):
                self._raced_turns.add(int(chara.get("turn") or 0))
                return Decision("race", {"program_id": program_id, "current_turn": chara.get("turn", 0), "_strategy": self}, self.race_planner.label(program_id))
            # Force-maiden-until-first-win safety net: the trainee LOST a maiden while still winless
            # (arm set in runner._race) and no goal/fan/optional race above claimed this turn -- so
            # force the best maiden on offer instead of training, EVERY turn until the first win clears
            # the arm. Runs LAST in the race gate so it never preempts a mandatory race.
            maiden_pid = self._forced_maiden_program(state, chara, preset)
            if maiden_pid:
                self._raced_turns.add(int(chara.get("turn") or 0))
                return Decision("race", {"program_id": maiden_pid, "current_turn": chara.get("turn", 0), "_strategy": self},
                                "force maiden until first win")
        command = self._best_command(data, chara, preset)
        if command:
            command_type = command.get("command_type", 1)
            command_id = command.get("command_id")
            command_group_id = command.get("command_group_id", 0)
            reason = self._command_reason(command, chara)
            if skipped_race:
                reason = f"{reason} | {skipped_race}"
            if command_type == 3:
                command_group_id = command_id
                command_id = 0
            return Decision("command", {
                "command_type": command_type,
                "command_id": command_id,
                "command_group_id": command_group_id,
                "select_id": command.get("select_id", 0),
                "current_turn": chara.get("turn", 0),
                "current_vital": chara.get("vital", 0),
            }, reason)
        return Decision("idle", {}, f"no action | {skipped_race}" if skipped_race else "no action")

    # Optional-race guard limits. The game's 'Race Fatigue' / 'After Repeated Races...' events fire
    # from the 3rd race in a row (75 races at streak position 3+ drew 50 of them; positions 1-2 drew
    # 0). Aptitude floor = B, the planner's FAN_RACE_MIN_GRADE (33 dirt starts at dirt G: 0 wins).
    OPTIONAL_RACE_MAX_STREAK = 2      # races in a row allowed before this one
    OPTIONAL_RACE_GOAL_GAP = 2        # keep this many turns before a career-goal race free
    OPTIONAL_RACE_MIN_MOOD = 3        # no optional race at Bad (2) or Awful (1) mood

    def _optional_race_veto(self, state, chara, preset, program_id):
        """Why a race picked by choose() (the user's schedule) should NOT be run this turn, or "".

        On per scenario via RACE_POLICY["optional_race_guard"] (Grand Live), overridable per preset
        with "optional_race_guard". Never applied to goal, forced, fan-goal or maiden races: those
        return before choose() in next_decision."""
        on = (preset or {}).get("optional_race_guard")
        if on is None:
            on = (getattr(self.race_planner, "policy", None) or {}).get("optional_race_guard", False)
        if not on or not program_id:
            return ""
        planner = self.race_planner
        turn = int(chara.get("turn") or 0)
        pid = int(program_id)
        goals = [g for g in planner._goals(chara) if g.get("kind") == "race"]

        def goal_pids(g):
            return {int(p) for p in (g.get("program_ids") or [g.get("program_id")]) if p}

        # This turn's goal race is never optional (goal_program normally takes it first).
        if any(int(g.get("turn") or 0) == turn and (pid in goal_pids(g) or not goal_pids(g)) for g in goals):
            return ""
        if min(planner._apt_grades(chara, pid)) < planner.FAN_RACE_MIN_GRADE:
            return "aptitude below B"
        # The server's own history (load / race_end states) covers a resumed career, whose fresh
        # strategy has not seen the earlier races.
        for row in (((state or {}).get("data") or {}).get("race_history") or []):
            if int((row or {}).get("turn") or 0):
                self._raced_turns.add(int(row["turn"]))
        streak = self._consecutive_races_before(turn)
        if streak >= self.OPTIONAL_RACE_MAX_STREAK:
            return f"would be race {streak + 1} in a row"
        gaps = sorted(int(g.get("turn") or 0) - turn for g in goals
                      if 0 < int(g.get("turn") or 0) - turn <= self.OPTIONAL_RACE_GOAL_GAP)
        if gaps:
            return f"goal race in {gaps[0]} turn{'s' if gaps[0] > 1 else ''}"
        mood = int(chara.get("motivation") or 0)
        if mood and mood < self.OPTIONAL_RACE_MIN_MOOD:
            return f"mood {mood}"
        return ""

    def _forced_maiden_program(self, state, chara, preset):
        """Program to force under force-maiden-until-first-win, or 0. Active only while a maiden re-run
        is armed on the planner (runner._race arms it after the trainee LOSES a maiden and is still
        winless; the first rank-1 finish clears it). Picks the best-aptitude maiden ON OFFER. Returns
        0 -- fall through to training -- when the toggle is off, nothing is armed, or no maiden is
        offered this turn."""
        if not (preset or {}).get("force_maiden_until_win", True):
            return 0
        if not self.race_planner or not int(getattr(self.race_planner, "rerun_program", 0) or 0):
            return 0
        return self.race_planner.apt_maiden_program(state, chara)

    def _choice(self, event):
        choices = ((event.get("event_contents_info") or {}).get("choice_array") or [])
        if not choices:
            return 0
        if len(choices) > 1:
            return None
        return 0

    def choice_from_rewards(self, rewards, event):
        choices = ((event.get("event_contents_info") or {}).get("choice_array") or [])
        if not choices:
            return 0
        if not rewards:
            return choices[0].get("select_index", 1)
        best_index = 0
        best_score = None
        for i, reward in enumerate(rewards):
            score = self._reward_score(reward)
            if best_score is None or score > best_score:
                best_score = score
                best_index = i
        if best_index < len(choices):
            return choices[best_index].get("select_index", best_index + 1)
        return choices[0].get("select_index", 1)

    def _reward_score(self, reward):
        score = 0.0
        for item in reward.get("params_inc_dec_info_array") or reward.get("effected_parameter_array") or []:
            target = STAT_TARGETS.get(item.get("target_type"))
            value = float(item.get("value") or 0)
            if target is None:
                if item.get("target_type") == 10:
                    score += value * 0.03
                continue
            score += value * (0.02 if target < 5 else 0.01)
        score += float(reward.get("skill_point") or 0) * 0.01
        score += float(reward.get("vital") or 0) * 0.03
        return score

    def _best_command(self, data, chara, preset, record=True):
        # record=False makes this a side-effect-free PROBE: the strong-train-over-race gate calls
        # it before the scheduled/min-fans guards to see what the bot would do, and must NOT log a
        # turn-quality sample on a turn that ends up racing (that would skew the rolling baseline
        # the rest/energy-banking gate reads). The real decision pass (next_decision / the value
        # comparison) calls it with record=True so the baseline is logged exactly once per train.
        commands = (data.get("home_info") or {}).get("command_info_array") or []
        enabled = [cmd for cmd in commands if cmd.get("is_enable", 1)]
        rest = self._rest_command(enabled)
        recreation = self._recreation_command(enabled)
        medic = self._medic_command(enabled)
        training = [cmd for cmd in enabled if cmd.get("command_type") == 1 and cmd.get("command_id") in TRAINING_COMMANDS]
        training = self._stat_capped_trainings(training, chara, preset)   # user per-stat cap
        turn = int(chara.get("turn") or 0)
        vital = int(chara.get("vital") or 0)
        motivation = int(chara.get("motivation") or 3)
        bad_status = self._has_curable_bad_status(chara, preset)
        # Fixed Sirius/Throne schedule: on a scheduled (non-camp) turn, take the group-card outing
        # the user runs on this date. This is the deck's main bond/rainbow lever, so it overrides
        # normal training/rest. No-op for non-group decks, unscheduled turns, or when the scheduled
        # character's outing isn't actually offerable this turn (then it falls through to training).
        scheduled = self._scheduled_recreation(enabled, turn, chara, preset)
        if scheduled:
            return scheduled
        if not training:
            if medic and bad_status and vital <= ENERGY_MEDIC_GENERAL:
                return medic
            # Nothing trainable this turn (the game offered no enabled training facility, or every
            # one was stat-capped out). REST only does something when there is energy MISSING -- at
            # full vital it burns the turn for exactly zero gain. Observed live: 67 of 118 careers
            # rested inside the first 12 turns at hp>=90, six CONSECUTIVE turns at 100/100
            # (career_log_20260803_183039), because this branch returned rest without ever looking
            # at vital. Recreation at least banks mood, which is a real multiplier on later training.
            if recreation is not None and self._rest_is_wasted(chara):
                return recreation
            return rest or recreation
        best_score, best = self._pick_scored_training(training, data, chara, preset, turn)
        rest_threshold = int(preset.get("rest_threshold") or 48)
        # Turn-quality lookahead: bank energy on a weak board (rest sooner), push on a strong one.
        # Clamp below max_vital so a rest can always lift energy back above it (no rest deadlock).
        # ALSO clamp to rest_ceiling (default 54). Why: the weak-board boost (+18 on top of the 48
        # base) pushed the rest gate as high as 66, and measured across 7,566 logged rests, 891 of
        # them (11.8%) fired at vital >= 55 -- a zone where training provably CANNOT fail (0.00%
        # failure in all 2,466 observations at vital >= 55). Those turns rested against no risk at
        # all, and a rest at high vital is doubly wasteful: recovery is capped at max_vital, so most
        # of it is thrown away. Rest turns produce 0 stats and measured -94 stats each; 140 of 160
        # real rests fired on this energy gate alone. Set rest_ceiling higher to bank more eagerly.
        eff_rest = min(self._turn_quality_threshold(best_score, preset, turn),
                       int(chara.get("max_vital") or 100) - 5,
                       int(preset.get("rest_ceiling") or 54))
        if record:
            self._record_turn_quality(turn, best_score)
        failure = int(best.get("failure_rate") or 0)
        if medic and bad_status and vital <= ENERGY_FAST_MEDIC:
            return medic
        if medic and bad_status and vital <= ENERGY_MEDIC_GENERAL:
            return medic
        # TS Climax is a MANT-only phase. The old turn-number-only rule also fired in URA, Unity,
        # and Grand Live, forcing even a 99%-failure training at 5 energy because those scenarios
        # have no item manager to rescue it. In MANT, commit early only when the board is positive
        # and either already safe or backed by an actually-owned energy/charm rescue. Otherwise the
        # normal rest/failure gates below decide the turn.
        climax_all_out = (self.scenario_id == 4
                          and preset.get("climax_all_out", True)
                          and turn in CLIMAX_TRAIN_TURNS
                          and best is not None
                          and best_score is not None
                          and best_score > 0)
        if climax_all_out:
            # Plain rest_threshold, not the banked eff_rest: there is nothing left to bank energy for.
            unsafe = (vital <= rest_threshold
                      or self._failure_forces_rest(best, data, chara, preset, turn, failure))
            if not unsafe or self._can_rescue_training(
                    data, chara, preset, best, best_score, vital, failure, rest_threshold):
                return best
        # Summer Lv5 camp: ALL-OUT train on a positive board -- for EVERY deck now (the camp facilities
        # are Lv5 whatever the support cards are), not just Sirius/Throne group decks. In MANT the item
        # manager tops the turn up with an energy item afterward, so it commits any positive board
        # regardless of current failure. Item-less scenarios (URA/Unity/Grand Live) have no such safety
        # net, so there it commits only when failure is already tolerable (camp_failure_cap, default 40)
        # and otherwise falls through to rest -- banking energy for the next Lv5 turn, not coin-flipping.
        if (preset.get("summer_all_out", True) and turn in RACE_VALUE_CAMP_TURNS
                and best_score is not None and best_score > 0):
            # Must read the STRATEGY's id, not the preset's: presets._resolve_scenario_id only ever
            # returns 1 or 4, so a Unity (2) / Grand Live (3) preset read as MANT and skipped the cap.
            is_mant = self.scenario_id == 4
            if is_mant or failure <= int(preset.get("camp_failure_cap") or 40):
                return best
        # Pre-summer mood: reach GREAT (5) on the run-up BEFORE the Lv5 camp so every camp turn trains
        # at the max mood multiplier. Ahead of the pre-camp rest/conserve below: mood is banked first,
        # then energy on the remaining prep turn. (A mandatory race on 36/60 is handled upstream.)
        pre_summer = self._pre_summer_mood_command(recreation, turn, motivation, vital, preset)
        if pre_summer is not None:
            return pre_summer
        # All-out applies to the ACTUAL Lv5 camp turns (RACE_VALUE_CAMP_TURNS == items.py's
        # SUMMER_TRAINING_TURNS), NOT the broader SUMMER_CAMP_TURNS which also covers the 36/60
        # race week -- so both halves of the energy-rescue mirror reason about the same turns.
        # EVERY deck (no group gate): the positive-board case is already returned by the block above;
        # this only keeps a rescuable Lv5 camp turn off recreation. summer_all_out (default on) turns
        # the whole all-out camp behaviour off.
        camp_all_out = (preset.get("summer_all_out", True)
                        and turn in RACE_VALUE_CAMP_TURNS)
        if turn in SUMMER_CAMP_TURNS and recreation and (vital <= rest_threshold or failure >= 35 or best_score < 0):
            # All-out summer: don't spend a Lv5 camp turn on recreation when there's a positive
            # training we can rescue with energy items / charm -- fall through and train it instead.
            # Only recreate when the board is genuinely bad (best_score < 0) or nothing can rescue it.
            if not (camp_all_out and best_score is not None and best_score > 0
                    and self._can_rescue_training(data, chara, preset, best, best_score, vital, failure, rest_threshold)):
                # Recreation only lifts MOOD, and a Lv5 camp already pins mood at GREAT (5) -- so
                # recreating mid-camp is a pure wasted turn (0 mood gain, ~0 energy). At GREAT mood,
                # REST instead to bank energy for the remaining Lv5 turns; Unity trains a safe Wit here
                # first via _rest_alternative (Lv5 Wit + ~5 energy). Below GREAT, recreation still earns
                # a real multiplier, so keep it. Tunable: camp_recreate_below_great (default on).
                if int(motivation or 0) >= 5 or not preset.get("camp_recreate_below_great", True):
                    alt = self._rest_alternative(training, chara, preset, turn) or rest
                    if alt:
                        return alt
                # ponytail: recreation gives ~0 energy; on the race-week turn right before a Lv5 camp,
                # REST to actually bank energy so the camp turns can train Speed/Power, not just Wit.
                # Only when energy is genuinely critical (<= precamp_rest_vital, default 30): above that,
                # a Wit training is a better "soft rest" -- it recovers ~5 energy AND gives stat/skill
                # points, so we don't burn a full 0-stat rest turn. Tunable precamp_rest_vital.
                if rest and turn not in RACE_VALUE_CAMP_TURNS and vital <= int(preset.get("precamp_rest_vital") or 30):
                    return rest
                return recreation
        jr = self._junior_recreation(recreation, turn, training, chara, preset)
        if jr is not None:
            # Commit the TURN (not a boolean) and only on the real decision pass (record). The runner
            # re-decides once after handling items on a "command" turn; a boolean set on the first pass
            # would read as "already done" on that same-turn re-decide and fall through to TRAINING --
            # the reported bug (logged recreation, executed a speed train, mood never rose). Keying on
            # the turn makes the re-decide return the SAME recreation; only a LATER turn is blocked, so
            # it's still exactly once per career. Log once (first real pass this turn).
            if record:
                if self._junior_recreated_turn != turn:
                    self._log_junior_recreation(turn, training, chara)
                self._junior_recreated_turn = turn
            return jr
        if self._should_recreate(recreation, preset, turn, motivation, vital, best_score):
            return recreation
        if rest and (vital <= eff_rest or self._failure_forces_rest(best, data, chara, preset, turn, failure) or best_score < 0):
            if not self._can_rescue_training(data, chara, preset, best, best_score, vital, failure, rest_threshold):
                # Scenario hook: Unity trains a safe Wit here instead of resting; base rests as usual.
                return self._rest_alternative(training, chara, preset, turn) or rest
            # else: a strong/rainbow turn we can charm or energy-up into. Don't rest
            # it away -- fall through to train it. items.py tops up energy with the
            # smallest sufficient Vita (+ charm) before the command executes, and the
            # post-item re-decision then runs the training at the restored energy.
        conserve = self._summer_conserve_command(training, turn, vital, best_score, preset, rest, recreation)
        if conserve:
            return conserve
        return best

    def _fan_race_done(self, state, turn):
        """The career's one fan race is spent once it was picked on an EARLIER turn, or it already RAN
        this turn: Grand Live's Concert screen stays on turn 24 after Hopeful, so the turn alone can't
        tell. A same-turn retry after a failed race_entry (nothing in race_history yet) is re-offered."""
        fan_raced = getattr(self, "_fan_raced", 0)
        if not fan_raced:
            return False
        if fan_raced != turn:
            return True
        history = ((state or {}).get("data") or {}).get("race_history") or []
        return any(int((h or {}).get("turn") or 0) == turn for h in history)

    def _pick_scored_training(self, training, data, chara, preset, turn):
        """Score the enabled trainings and pick what the brain would train, including the
        senior-phase highest-stat nudge and the junior bond-rush ordering. Single source of
        truth shared by _best_command AND the train-vs-race gate, so both always reason from
        the SAME effective score. Returns (best_score, command)."""
        scored = [(self._score_command(cmd, data, chara, preset), cmd) for cmd in training]
        # Drop the -999 sentinels (forbidden facility / over max_failure_rate) while a viable option
        # exists: the junior orderings below rank partner count ABOVE score and would pick one.
        scored = [row for row in scored if row[0] > -900] or scored
        # NOTE: a senior-phase x0.95 penalty on whichever stat is currently HIGHEST used to sit here.
        # Removed: rank score is CONVEX in each stat (marginal value per point rises ~0.5 at 200 ->
        # 4.3 at 1000 -> ~13 at 1600), so the last points of the TOP stat are the most valuable ones
        # in the game -- penalising them in Senior pointed exactly the wrong way. Concentration beats
        # balance (1800/1100/1100/1000/1000 scores ~3.3k MORE than 1200x5 at equal total).
        # Sirius/Throne junior FOCUS: in the first turns (<= JUNIOR_FOCUS_LAST_TURN) on a group deck,
        # prioritize the training that has the most GROUP-card partners on it, to build their bond
        # fast so their recreation outings UNLOCK on schedule (a late unlock slips the whole plan --
        # see the goal-driven catch-up). Group-partner count first, then bond-rush count, then score.
        if (turn <= JUNIOR_FOCUS_LAST_TURN and preset.get("sirius_throne_junior_focus", True)
                and self._deck_has_group_cards(chara)):
            gslots = set(self._group_card_slots(chara))
            if gslots:
                return max(scored, key=lambda row: (
                    len(gslots & {int(p) for p in (row[1].get("training_partner_array") or [])}),
                    self._bondable_count(row[1], chara), row[0]))
        if turn <= 24 and preset.get("junior_bond_rush", True):
            # Junior bond-rush: on non-race training turns, prioritize the training
            # that gathers the most not-yet-maxed support partners (building toward
            # rainbow) over taking an existing rainbow, using the normal score only
            # as a tiebreak. The score magnitude is kept intact so the rest/medic/
            # recreation thresholds behave exactly as before.
            return max(scored, key=lambda row: (self._bondable_count(row[1], chara), row[0]))
        return max(scored, key=lambda row: row[0])

    def _group_card_slots(self, chara):
        """Deck positions (== training partner ids) of the Team Sirius / Throne group cards -- the
        facilities the junior focus prioritizes to build their bond and unlock outings on time."""
        return [int(c.get("position") or 0) for c in chara.get("support_card_array") or []
                if int(c.get("support_card_id") or 0) in set(SIRIUS_THRONE_GROUP_IDS)]

    def _record_turn_quality(self, turn, best_score):
        """Log this turn's best training score once per turn, for the rolling baseline. Negative
        scores (energy penalties / forbidden-facility sentinels) are skipped so they don't skew it."""
        if best_score is None or best_score < 0 or turn == getattr(self, "_quality_last_turn", -1):
            return
        self._quality_last_turn = turn
        self._score_history.append(float(best_score))
        if len(self._score_history) > 16:
            self._score_history = self._score_history[-16:]

    def _turn_quality_threshold(self, best_score, preset, turn):
        """Turn-quality lookahead -> effective rest threshold.

        The base scorer is greedy, so it would burn a weak turn on mediocre training and then be
        forced to rest on a later strong (rainbow) turn. Instead, compare this turn's best score to
        a rolling baseline of recent turns: on a clearly WEAK board, raise the rest threshold so the
        bot rests now and banks energy for a future strong turn; on a STRONG board, lower it so it
        pushes through (the charm/Vita rescue + failure cap keep that safe). Energy is also banked
        entering the summer camps / finals. Aggressive defaults (tunable via preset)."""
        base = int(preset.get("rest_threshold") or 48)
        # No banking once we're INSIDE the summer camp we banked for -- spend the camp, don't rest it.
        if not preset.get("turn_quality_lookahead", True) or turn in SUMMER_CAMP_TURNS:
            return base
        boost = int(preset.get("turn_quality_rest_boost") or 18)
        if turn in PRE_EVENT_BANK_TURNS:
            base += boost // 2
        hist = self._score_history
        if turn == self._quality_last_turn and hist:
            # _best_command can run twice on a race-candidate turn; this turn's score was already
            # recorded on the first pass, so drop it from the baseline to keep both passes consistent.
            hist = hist[:-1]
        if best_score is None or len(hist) < 4:
            return base
        recent = sorted(hist[-8:])
        baseline = recent[len(recent) // 2]  # median of recent boards
        if baseline <= 0:
            return base
        if best_score < baseline * float(preset.get("turn_quality_weak_ratio") or 0.82):
            return base + boost                      # weak board -> rest eagerly, bank energy
        if best_score > baseline * float(preset.get("turn_quality_strong_ratio") or 1.20):
            return max(30, base - boost)             # strong board -> push, spend energy
        return base

    def _rest_command(self, commands):
        for cmd in commands:
            if cmd.get("command_type") == 7 and cmd.get("command_id") == 701:
                return cmd
        return None

    def _recreation_command(self, commands):
        # The generic mood-recreation command. Skip the group-outing command (390): that one is
        # driven only by _scheduled_recreation (with a real select_id), never taken as a bare
        # mood recreation -- otherwise it would fire with select_id 0 and a stale is-card flag.
        for cmd in commands:
            if cmd.get("command_type") == 3 and int(cmd.get("command_id") or 0) != GROUP_OUTING_COMMAND_ID:
                return cmd
        return None

    def _deck_has_group_cards(self, chara):
        """True when the running deck contains Team Sirius and/or Heirs to the Throne, read from
        chara_info.support_card_array (support_card_id == support_list.json key)."""
        ids = {int(c.get("support_card_id") or 0) for c in (chara.get("support_card_array") or [])}
        return bool(ids & set(SIRIUS_THRONE_GROUP_IDS))

    def _deck_is_throne_only(self, chara):
        """True when the deck has Heirs to the Throne but NOT Team Sirius -> use the adaptive
        situational schedule (_throne_only_recreation) instead of the interleaved fixed plan."""
        ids = {int(c.get("support_card_id") or 0) for c in (chara.get("support_card_array") or [])}
        return THRONE_SUPPORT_ID in ids and TEAM_SIRIUS_SUPPORT_ID not in ids

    def _consecutive_races_before(self, turn):
        """How many of the immediately-preceding turns were races (counting back from turn-1),
        from the per-career _raced_turns set recorded in next_decision."""
        n, t = 0, int(turn) - 1
        while t in self._raced_turns:
            n += 1
            t -= 1
        return n

    def _schedule_active(self, chara, preset):
        """Whether the fixed Sirius/Throne recreation schedule applies this career. Auto-on when
        those Group cards are detected in the deck; force with preset 'sirius_throne_schedule'
        (True forces on for any deck, False disables)."""
        flag = preset.get("sirius_throne_schedule")
        if flag is not None:
            return bool(flag)
        return self._deck_has_group_cards(chara)

    def _group_outing_map(self, chara):
        """slot (support_card_array.position / evaluation target_id) -> list of (chara_id, story_step)
        for currently OFFERABLE outings on that Group card. Offerable = group_outing_info_array entry
        with is_outing == 1. Decoded from the live capture: is_outing is a sticky 'unlocked/available'
        flag the game flips to 1 once the Group card's bond is high enough (it never reverts to 0);
        story_step is the per-character DONE counter (0 = not done yet, increments when the outing is
        performed). Read live from chara_info."""
        result = {}
        for row in chara.get("evaluation_info_array") or []:
            outings = row.get("group_outing_info_array") or []
            if not outings:
                continue
            slot = int(row.get("target_id") or 0)
            result[slot] = [(int(g.get("chara_id") or 0), int(g.get("story_step") or 0))
                            for g in outings if int(g.get("is_outing") or 0) == 1]
        return result

    def _support_slot(self, chara, support_id):
        """Deck slot (position) of a given support_card_id, or None if not in the deck."""
        for c in chara.get("support_card_array") or []:
            if int(c.get("support_card_id") or 0) == int(support_id):
                return int(c.get("position") or 0)
        return None

    def _slot_row(self, chara, slot):
        """The evaluation_info_array row for a deck slot (target_id == slot), or None."""
        if slot is None:
            return None
        for row in chara.get("evaluation_info_array") or []:
            if int(row.get("target_id") or 0) == int(slot):
                return row
        return None

    def _card_outing_select_id(self, support_id, slot=None):
        """select_id for the card-itself ("group") recreation = the card's SIGNATURE chara_id (from
        master.mdb support_card_data.chara_id: Throne->1017 Rudolf, Sirius->1001 Special Week). The
        game routes this chara_id to the card's own story once that character's own outing is done,
        so characters are always done first (confirmed live: the card row's story_step advances)."""
        return int(CARD_SIGNATURE_CHARA.get(int(support_id), 0))

    def _char_outing_state(self, chara, chara_id):
        """(is_outing, story_step) for a character's group outing, or (0, 0) if not present."""
        for row in chara.get("evaluation_info_array") or []:
            for g in row.get("group_outing_info_array") or []:
                if int(g.get("chara_id") or 0) == int(chara_id):
                    return int(g.get("is_outing") or 0), int(g.get("story_step") or 0)
        return 0, 0

    def _card_row_state(self, chara, support_id):
        """(is_outing, story_step) of a group card's OWN recreation -- its evaluation slot ROW."""
        row = self._slot_row(chara, self._support_slot(chara, support_id))
        if not row:
            return 0, 0
        return int(row.get("is_outing") or 0), int(row.get("story_step") or 0)

    def _outing_plan(self):
        """The fixed schedule expanded to an ordered list of outing STEPS. A char entry = one
        character outing; a card entry = one step of that group card's own recreation (step counts
        per card, so Throne -> steps 1 and 2, Sirius -> step 1). select_id is the chara_id for a
        character, the card's signature chara_id for a card step."""
        plan = []
        card_step = {}
        for t in sorted(SIRIUS_THRONE_RECREATION_SCHEDULE):
            chara_id, support_id, _label = SIRIUS_THRONE_RECREATION_SCHEDULE[t]
            if chara_id is not None:
                plan.append({"turn": t, "kind": "char", "support_id": support_id,
                             "chara_id": int(chara_id), "select_id": int(chara_id)})
            else:
                card_step[support_id] = card_step.get(support_id, 0) + 1
                plan.append({"turn": t, "kind": "card", "support_id": support_id,
                             "step": card_step[support_id],
                             "select_id": self._card_outing_select_id(support_id)})
        return plan

    def _scheduled_recreation(self, enabled, turn, chara, preset):
        """GOAL-DRIVEN Sirius/Throne recreation. Returns the group-outing command (390) with the
        select_id of the next outing that is DUE (its scheduled turn has passed), NOT yet done, and
        currently AVAILABLE -- else None (train normally). This follows the fixed schedule AND
        catches up: a character whose outing unlocked LATE is done as soon as it's available (so it
        never eats a card turn), and each card step is taken once its signature character is done and
        the card story still has steps left. Characters are tried before card steps (earlier in the
        plan), which matters because the card reuses the signature chara_id. On a scheduled date whose
        own outing isn't available yet, it PULLS FORWARD the earliest available not-yet-due outing so
        the date isn't wasted (the schedule self-reorders to whichever card unlocked first). Never
        fires in summer camp. ON for a group deck by default (disable with 'sirius_throne_schedule': False)."""
        if getattr(self, "_scheduled_outing_blocked", False):
            return None
        if preset.get("sirius_throne_schedule", True) is False:
            return None
        if not self._deck_has_group_cards(chara) and preset.get("sirius_throne_schedule") is not True:
            return None
        # Never recreate inside the ACTUAL Lv5 summer camp (37-40 / 61-64) -- go all-out training.
        # The 36/60 late-June G1 race weeks are NOT camp, so a scheduled outing may fire there (a
        # forced race still wins: next_decision checks forced_program before _best_command).
        if turn in RACE_VALUE_CAMP_TURNS:
            return None
        outing_cmd = next((c for c in enabled if c.get("command_type") == 3
                           and int(c.get("command_id") or 0) == GROUP_OUTING_COMMAND_ID), None)
        if not outing_cmd:
            return None
        # Throne-only deck: deploy outings situationally instead of on the Sirius-interleaved plan.
        # Disable with preset 'throne_adaptive_schedule': False to fall back to the generic schedule.
        if preset.get("throne_adaptive_schedule", True) and self._deck_is_throne_only(chara):
            return self._throne_only_recreation(outing_cmd, turn, chara, preset)
        card_enabled = (preset.get("sirius_throne_card_outing", True)
                        and not getattr(self, "_card_outing_blocked", False))
        plan = self._outing_plan()
        # Pass 1 -- on-schedule / catch-up: the earliest DUE (scheduled turn already reached) outing
        # that's unlocked and not done -- the turn's own date, or an earlier one not yet done.
        due = self._first_available_outing(chara, [s for s in plan if s["turn"] <= turn],
                                           outing_cmd, card_enabled)
        if due:
            return due
        # Pass 2 -- pull-forward: on a SCHEDULED date whose own outing can't be done yet (its card
        # hasn't unlocked), don't waste the turn -- do the earliest AVAILABLE not-yet-due outing
        # instead. So if Sirius is late but Throne is ready, t18 does a Throne date (e.g. Rudolf) and
        # the displaced Sirius date (Suzuka) is caught up later. Gated to schedule turns so the outing
        # cadence (~one per scheduled date) is kept -- it never front-loads outings every turn.
        if turn in SIRIUS_THRONE_RECREATION_SCHEDULE:
            return self._first_available_outing(chara, [s for s in plan if s["turn"] > turn],
                                                outing_cmd, card_enabled)
        return None

    def _first_available_outing(self, chara, steps, outing_cmd, card_enabled):
        """First step in `steps` that's actually doable -- an unlocked, not-done character, or a card
        step whose signature char is done and whose story still has that step left -- returned as an
        outing command, else None. Sets _pending_outing_is_card for the chosen step. Shared by the
        on-schedule/catch-up pass and the pull-forward pass."""
        for step in steps:
            if step["kind"] == "char":
                io, ss = self._char_outing_state(chara, step["chara_id"])
                if ss >= 1 or io != 1:
                    continue  # already done, or not unlocked yet
                self._pending_outing_is_card = False
                return self._outing_command(outing_cmd, step["select_id"])
            if not card_enabled:
                continue
            crow_io, crow_ss = self._card_row_state(chara, step["support_id"])
            if crow_ss >= step["step"] or crow_io != 1:
                continue  # this card step already done, or the card recreation isn't unlocked
            if self._char_outing_state(chara, step["select_id"])[1] < 1:
                continue  # the card's signature character isn't done yet
            self._pending_outing_is_card = True
            return self._outing_command(outing_cmd, step["select_id"])
        return None

    def _outing_command(self, outing_cmd, select_id):
        chosen = dict(outing_cmd)
        chosen["select_id"] = int(select_id)
        return chosen

    def _throne_only_recreation(self, outing_cmd, turn, chara, preset):
        """Heirs-to-the-Throne deck WITHOUT Team Sirius: deploy each Throne CHARACTER outing when its
        situational payoff lands instead of on a fixed date, and keep the two card-itself steps on
        their fixed dates (51, 59). The card reuses Rudolf's select_id and only routes to the card
        story once HIS own outing is done, so Rudolf is the prerequisite -- done as soon as he
        unlocks (i.e. in junior). Tokai Teio's outing is the mood lever -> held for after a 3-race
        streak (when mood is spent); Tsurumaru's restores energy -> held for a low-vital classic turn.
        A fallback deadline (THRONE_FALLBACK_BY) forces any still-undone character outing before
        senior so it isn't wasted. Returns the 390 outing command (with select_id) or None to train.
        All outer guards (blocked flag, schedule-off, summer camp, outing-command present) already ran
        in the _scheduled_recreation caller."""
        vital = int(chara.get("vital") or 0)
        motivation = int(chara.get("motivation") or 3)
        rest_threshold = int(preset.get("rest_threshold") or 48)
        past_deadline = turn >= THRONE_FALLBACK_BY  # stop holding -> use it before it's wasted

        def char_ready(chara_id):
            io, ss = self._char_outing_state(chara, chara_id)
            return io == 1 and ss < 1  # unlocked and not yet done

        def fire_char(chara_id):
            self._pending_outing_is_card = False
            return self._outing_command(outing_cmd, int(chara_id))

        # Card-itself steps: fixed dates, each needs Rudolf done + the row unlocked + that step left.
        if (preset.get("sirius_throne_card_outing", True)
                and not getattr(self, "_card_outing_blocked", False)):
            rudolf_done = self._char_outing_state(chara, THRONE_RUDOLF)[1] >= 1
            crow_io, crow_ss = self._card_row_state(chara, THRONE_SUPPORT_ID)
            if rudolf_done and crow_io == 1:
                for step, due in sorted(THRONE_ONLY_CARD_TURNS.items()):
                    if turn >= due and crow_ss < step:
                        self._pending_outing_is_card = True
                        return self._outing_command(outing_cmd, self._card_outing_select_id(THRONE_SUPPORT_ID))

        # Rudolf: prerequisite for the card steps, no situational hold -> do as soon as he unlocks.
        if char_ready(THRONE_RUDOLF):
            return fire_char(THRONE_RUDOLF)

        # Tsurumaru: energy. Deploy on a low-vital classic turn (or at the deadline so it isn't wasted).
        if char_ready(THRONE_TSURUMARU):
            if (25 <= turn <= 48 and vital <= rest_threshold) or past_deadline:
                return fire_char(THRONE_TSURUMARU)

        # Tokai Teio: mood. Deploy after a race streak when mood isn't already maxed (or at deadline).
        if char_ready(THRONE_TOKAI):
            if (self._consecutive_races_before(turn) >= THRONE_MOOD_RACE_STREAK and motivation < 5) or past_deadline:
                return fire_char(THRONE_TOKAI)

        return None

    def _dump_recreation_debug(self, data, chara, preset):
        """One-shot capture aid: when a recreation (command_type==3) is offered on a Sirius/Throne
        deck, write that command's full structure + the deck's support_card_array / bond table /
        any pending event to uma_runtime/bot_logs/recreation_debug_t<turn>.json. This is what's
        needed to wire per-character selection (which select_id picks which outing). Gated by preset
        'dump_recreation_debug' (default on) AND _schedule_active -- so the schedule being active
        (auto-on for a group deck, or forced via 'sirius_throne_schedule') is what enables the DUMP,
        never the outing itself. Overwrites per run so a fresh career re-captures live state."""
        if not preset.get("dump_recreation_debug", True):
            return
        if not self.race_planner or not getattr(self.race_planner, "base_dir", None):
            return
        # _schedule_active is the single auto-on/force gate (it consults _deck_has_group_cards):
        # routing the dump through it is what makes the schedule-activation semantics actually
        # govern behavior at runtime, rather than re-deriving deck detection here.
        if not self._schedule_active(chara, preset):
            return
        home = data.get("home_info") or {}
        rec_cmds = [c for c in (home.get("command_info_array") or []) if c.get("command_type") == 3]
        if not rec_cmds:
            return
        turn = int(chara.get("turn") or 0)
        try:
            out_dir = os.path.join(str(self.race_planner.base_dir), "uma_runtime", "bot_logs")
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, f"recreation_debug_t{turn}.json")
            # Overwrite each run (latest wins) so a fresh career re-captures state -- e.g. the
            # post-outing unchecked_event_array, which confirms whether selection is select_id-based
            # or a follow-up menu event. (Old behavior kept only the first-ever capture per turn.)
            payload = {
                "turn": turn,
                "scheduled": SIRIUS_THRONE_RECREATION_SCHEDULE.get(turn),
                "recreation_commands": rec_cmds,
                "support_card_array": chara.get("support_card_array") or [],
                "evaluation_info_array": chara.get("evaluation_info_array") or [],
                "unchecked_event_array": data.get("unchecked_event_array") or [],
            }
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _medic_command(self, commands):
        for cmd in commands:
            if cmd.get("command_type") == 8 and cmd.get("command_id") == 801:
                return cmd
        return None

    def _enabled_training(self, commands, command_id):
        for cmd in commands:
            if cmd.get("command_type") == 1 and cmd.get("command_id") == command_id:
                return cmd
        return None

    def _enabled_training_idx(self, commands, idx):
        for cmd in commands:
            if cmd.get("command_type") == 1 and TRAINING_COMMANDS.get(cmd.get("command_id")) == idx:
                return cmd
        return None

    def _scenario_stat_caps(self, preset):
        """This scenario's TRAIN-TO stat ceilings [SPD, STA, PWR, GUT, WIT], or None. Read from the
        scenario class's DEFAULT_STAT_CAPS (career_bot/scenarios/*.py). Set near the game's absolute
        per-stat max so the bot trains each stat up to its LIVE in-game cap instead of holding it low;
        foresight does not pull it back down. Only explicit stat_caps hard-drop a training. Gated by
        preset scenario_stat_caps (default True)."""
        if not (preset or {}).get("scenario_stat_caps", True):
            return None
        caps = getattr(self, "DEFAULT_STAT_CAPS", None)
        if isinstance(caps, (list, tuple)) and len(caps) == 5:
            return [int(x or 0) for x in caps]
        return None

    @staticmethod
    def _rest_is_wasted(chara, margin=8):
        """True when vital sits close enough to its ceiling that a REST turn recovers ~nothing.

        max_vital is the LIVE ceiling and it grows during a career (energy-up events push it past
        100 -- seen at 104 in career_log_20260803_194739), so this compares against the reported
        maximum rather than a hardcoded 100. The margin keeps it honest: resting at 96/104 is still
        very nearly a wasted turn. Fail-safe -- an unreadable/absent max_vital returns False, which
        keeps the historical "just rest" behaviour rather than inventing a new one.
        """
        try:
            vital = int((chara or {}).get("vital") or 0)
            max_vital = int((chara or {}).get("max_vital") or 0)
        except (TypeError, ValueError):
            return False
        if max_vital <= 0:
            return False
        return vital >= max_vital - int(margin)

    def _stat_capped_trainings(self, training, chara, preset):
        """Drop trainings whose PRIMARY stat has reached the user's per-preset cap (preset
        'stat_caps' = {speed/stamina/power/guts/wiz: value}, 0/absent = no cap). This only stops
        the bot from DEDICATING a training turn to that stat -- it can still climb from events and
        the secondary gains of OTHER trainings. No-op when no caps are set; if EVERY training is
        capped it returns [] and the callers fall through to rest/race (they already handle empty)."""
        caps = (preset or {}).get("stat_caps")
        if not isinstance(caps, dict) or not any(caps.values()):
            return training
        kept = []
        for cmd in training:
            idx = TRAINING_COMMANDS.get(cmd.get("command_id"))
            name = STAT_NAMES[idx] if isinstance(idx, int) and 0 <= idx < len(STAT_NAMES) else None
            try:
                cap = int(caps.get(name) or 0)
            except (TypeError, ValueError):
                cap = 0
            if cap > 0 and int((chara or {}).get(name) or 0) >= cap:
                continue   # capped -> don't spend a training turn on this stat
            kept.append(cmd)
        return kept

    def _should_summer_race(self, data, chara, preset):
        """On a summer turn, True when NO training reaches the >=2-rainbow 'good' bar AND there
        is no Reset Whistle to re-roll the board -- so racing the best available track beats a
        weak training. Returns False on non-summer turns, when a good (>=2 rainbow) training
        exists, or when a whistle is still owned (let the re-roll try for a good board first)."""
        if not preset.get("summer_race_fallback", True):
            return False
        turn = int(chara.get("turn") or 0)
        if turn not in SUMMER_CAMP_TURNS:
            return False
        commands = (data.get("home_info") or {}).get("command_info_array") or []
        training = [c for c in commands if c.get("is_enable", 1)
                    and c.get("command_type") == 1 and c.get("command_id") in TRAINING_COMMANDS]
        training = self._stat_capped_trainings(training, chara, preset)   # user per-stat cap
        if not training:
            return False
        good_min = int(preset.get("summer_good_rainbow_min") or 2)
        if max((self._rainbow_count(c, chara) for c in training), default=0) >= good_min:
            return False  # a good (>=2 rainbow) training exists -> train it, don't race
        # No good training: defer to a Reset Whistle re-roll if one is owned; race only when
        # there's no whistle left to fix the board.
        if self._owned_item_count(data, RESET_WHISTLE_ITEM_ID) > 0:
            return False
        return True

    def _summer_conserve_command(self, training, turn, vital, best_score, preset, rest, recreation):
        # `training` is the stat-capped list from _best_command, so a capped Wit is never conserved into.
        if turn not in SUMMER_CONSERVE_TURNS:
            return None
        if best_score >= float(preset.get("summer_score_threshold") or 0.34):
            return None
        if vital < SUMMER_CONSERVE_ENERGY:
            # ponytail: same rule as the _best_command camp branch -- near-0 vital before a Lv5 camp,
            # REST not recreate (recreation = 0 energy).
            crit = int(preset.get("precamp_rest_vital") or 30)
            if turn in SUMMER_CAMP_TURNS and recreation and vital > crit:
                return recreation
            return rest
        wit = self._enabled_training_idx(training, 4)
        max_fail = preset.get("max_failure_rate")
        if wit is None or self._extra_weight(4, turn, preset) == -1 or (
                max_fail is not None and float(wit.get("failure_rate") or 0) > float(max_fail)):
            return None   # Wit capped / forbidden / over max_failure_rate (its -999 sentinels) -> train best
        return wit

    def _has_curable_bad_status(self, chara, preset):
        wanted = self._cure_condition_names(preset)
        if not wanted:
            return False
        for effect_id in chara.get("chara_effect_id_array") or []:
            try:
                effect_id = int(effect_id)
            except (TypeError, ValueError):
                continue
            name = BAD_EFFECT_NAMES.get(effect_id)
            if name and self._condition_key(name) in wanted:
                return True
        return False

    def _cure_condition_names(self, preset):
        result = set()
        names = preset.get("cure_asap_conditions") or []
        if isinstance(names, str):
            names = names.split(",")
        for name in names:
            key = self._condition_key(name)
            if key:
                result.add(key)
        return result

    def _condition_key(self, name):
        text = str(name or "").strip()
        if not text or text.startswith("("):
            return ""
        return "".join(ch.lower() for ch in text if ch.isalnum())

    def _command_reason(self, command, chara=None):
        command_type = command.get("command_type")
        command_id = command.get("command_id")
        if command_id in TRAINING_COMMANDS:
            label = f"training {TRAINING_NAMES[TRAINING_COMMANDS.get(command_id, 0)]} {command_id}"
            if chara is not None:
                rc = self._rainbow_count(command, chara)
                if rc:
                    label += f" [{rc} rainbow]"
            return label
        if command_type == 7 and command_id == 701:
            return f"rest {command_id}"
        if command_type == 3:
            return f"recreation {command_id}"
        if command_type == 8 and command_id == 801:
            return "medic 801"
        return f"command {command_type}:{command_id}"

    def _train_to_win_emphasis(self, preset):
        """Per-stat emphasis ({speed/stamina/power/guts/wit: weight}) for training the stats the
        bot keeps losing on. Combines TWO learned signals (both from ai_learn, cached for the
        career -- the model only changes between careers):
          - race_train_emphasis: the distance-implied stats of the bot's confident losing races;
          - race_mark_emphasis:  the DIRECT per-stat rank marks the game gives in lost races
            (popularity_mark_rank_array) -- which stat the field actually outclassed us in.
        Summed and renormalized so both contribute. Returns {} when disabled or no data."""
        if not preset.get("ai_train_to_win", True):
            return {}
        if not self._train_emphasis_loaded:
            self._train_emphasis_loaded = True
            try:
                if self.race_planner is not None:
                    base = ai_learn.race_train_emphasis(self.race_planner.base_dir) or {}
                    marks = ai_learn.race_mark_emphasis(self.race_planner.base_dir) or {}
                    merged = {}
                    # The mark signal is the DIRECT per-stat weakness (the game's rank marks);
                    # weight it ABOVE the coarse distance prior so, once enough marked losses
                    # accumulate, it dominates -- pulling in the stamina the distance prior used
                    # to under-count instead of letting it train the build further off-balance.
                    for signal, mult in ((base, 1.0), (marks, 2.0)):
                        for stat, w in signal.items():
                            merged[stat] = merged.get(stat, 0.0) + float(w) * mult
                    total = sum(merged.values())
                    self._train_emphasis = {s: round(w / total, 4) for s, w in merged.items()} if total > 0 else {}
            except Exception:
                self._train_emphasis = None
        return self._train_emphasis or {}

    def _goal_stat_emphasis(self, chara, preset):
        """Per-stat emphasis from THIS trainee's career-goal solver plan (goal_solver crosses the card's
        aptitudes with its character's unique career goals -> stat_priority). Nudges training toward the
        stats the goals demand from turn 1, before any learned loss data exists. Normalized to sum 1;
        cached per card_id. MANT disables this by OVERRIDING the method in scenarios/mant.py (the
        user's rule: playing MANT is the only way to switch the career-goal focus off)."""
        card_id = int((chara or {}).get("card_id") or 0)
        if not card_id:
            return {}
        if self._goal_emphasis_card != card_id:
            self._goal_emphasis_card = card_id
            self._goal_emphasis = {}
            try:
                pri = (goal_solver.solve(card_id) or {}).get("stat_priority") or []
                # ordered [most-needed .. least] -> descending weights (first stat highest), normalized
                raw = {s: float(len(pri) - i) for i, s in enumerate(pri)}
                total = sum(raw.values())
                if total > 0:
                    self._goal_emphasis = {s: round(w / total, 4) for s, w in raw.items()}
            except Exception:
                self._goal_emphasis = {}
        return self._goal_emphasis or {}

    def _merged_emphasis(self, preset, chara):
        """Learned loss emphasis + career-goal emphasis, summed then renormalized to sum 1 so the overall
        nudge strength (scaled by ai_train_to_win_weight, a deliberate small tie-breaker) is unchanged --
        only its DIRECTION becomes goal-aware. Early career (no losses yet) -> pure goal emphasis; later
        -> goal + learned blended."""
        learned = self._train_to_win_emphasis(preset)
        goal = self._goal_stat_emphasis(chara, preset)
        if not learned:
            return goal
        if not goal:
            return learned
        merged = {}
        for d in (learned, goal):
            for s, w in d.items():
                merged[s] = merged.get(s, 0.0) + float(w)
        total = sum(merged.values())
        return {s: round(w / total, 4) for s, w in merged.items()} if total > 0 else {}

    def _hint_bonus(self, hint_count, turn, w_hint, preset):
        """Reward a training that shows a skill hint (the red '!' on a support): scaled by how many
        partners hint (capped at 4). PRIORITISED BEFORE SENIOR -- a hint discounts the skill's SP cost
        at the end-career buy, so chase them early while there's a whole career to cash them in. From
        SENIOR onward (turn >= hint_priority_until_turn, default 49) the hint is NO LONGER prioritised:
        raw stats matter more by then, so the bonus drops to 0. Tunables: hint_priority_until_turn (49),
        hint_presenior_boost (2.0 = twice the base hint weight pre-senior), hint_count_scale (0.5)."""
        if hint_count <= 0:
            return 0.0
        # Never in Senior year: the setting can only END hint priority earlier, not carry it past
        # SENIOR_START_TURN. 0 now means 0 (it used to fall back to the default via `or`).
        cutoff = preset.get("hint_priority_until_turn")
        cutoff = SENIOR_START_TURN if cutoff in (None, "") else min(int(cutoff), SENIOR_START_TURN)
        if turn >= cutoff:
            return 0.0                                   # Senior+ -> stop prioritising hints
        boost = preset.get("hint_presenior_boost")
        w = w_hint * (2.0 if boost in (None, "") else float(boost))
        hint_scale = float(preset.get("hint_count_scale") or 0.5)
        return w * (1.0 + hint_scale * (min(hint_count, 4) - 1))

    def _score_command_adjustment(self, command, chara, preset):
        """Small forward-looking overlay on top of the established command score.

        The original scorer remains the authority for scenario mechanics, friendship, rainbows,
        rest gates, and item-aware behavior. This layer only adds two signals that were previously
        difficult to tune independently: how urgently this facility advances the goal build,
        and how expensive its failure risk is at the current vitality.
        """
        if int((command or {}).get("command_type") or 0) != 1:
            return {"goal_progress": 0.0, "failure_risk": 0.0, "learned": 0.0}

        preset = preset or {}
        command_id = int((command or {}).get("command_id") or 0)
        stat_key = {
            101: "speed", 102: "power", 103: "guts", 105: "stamina", 106: "wiz",
            601: "speed", 602: "stamina", 603: "power", 604: "guts", 605: "wiz",
        }.get(command_id)
        gain = max(0.0, float(self._command_stat_total(command) or 0.0))

        def number(value, default):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        goal_weight = number(preset.get("score_goal_lookahead_weight", 0.20), 0.20)
        goal_progress = 0.0
        if stat_key and gain > 0:
            # Goal emphasis only. The forecast's stat_targets already steer _score_command_base; a
            # forecast-urgency branch here keyed on a dict that stat_targets (a list) never is, so
            # it never ran and was removed.
            try:
                emphasis = self._goal_stat_emphasis(chara, preset) or {}
                emphasis_value = number(emphasis.get(stat_key), 0.0)
                if not emphasis_value and stat_key == "wiz":
                    emphasis_value = number(emphasis.get("wit"), 0.0)
                goal_progress = gain * goal_weight * min(1.0, max(0.0, emphasis_value))
            except Exception:
                goal_progress = 0.0

        # FAILURE IS PRICED ONCE, IN _score_command_base (the multiplicative EV factor
        # `score *= max(0, (1-fail) - failure_cost*fail)`). This layer used to ADD a second,
        # unbounded penalty on top -- so every risky board was charged twice. Removed because:
        #   * double-charging was never intended (the wrapper's own docstring says it "only adds"
        #     signals, and promises a clamp that was applied to goal_progress but not to this term);
        #   * it was the ONLY term that could drive a score NEGATIVE, and four gates written before
        #     it assume scores are non-negative -- notably _can_rescue_training, which bails on <= 0
        #     BEFORE checking whether a Vita/charm is even owned, killing the rescue on exactly the
        #     risky-rainbow boards it exists for;
        #   * its low_vital amplifier double-counted energy: the game's own failure_rate IS a
        #     function of vital (measured R^2 0.99 with vital+facility; 0.00% failure in all 2,466
        #     observations at vital >= 55), so energy risk was already inside `failure_rate`;
        #   * measured, it barely earned its keep anyway -- replaying 4,345 real boards through
        #     _best_command, dropping it changes the chosen ACTION on 0.7% of turns.
        # Kept as an explicit 0.0 (not deleted from the breakdown) so _last_score_breakdown keeps its
        # shape for the logs/UI. score_failure_risk_weight is consequently inert; failure_cost in the
        # base scorer is the live knob (1.0 = a failure costs what a success gains).
        failure_risk = 0.0

        learned = 0.0
        # getattr on SELF too: a strategy built without __init__ (every unit test does this, and the
        # scenario hooks that run before wiring) has no race_planner at all, and `self.race_planner`
        # raises AttributeError before the outer getattr can supply its default.
        base_dir = getattr(getattr(self, "race_planner", None), "base_dir", None)
        if stat_key and base_dir:
            try:
                learned = float((ai_learn.training_policy_adjustment(
                    base_dir,
                    command_id,
                    self.scenario_id,
                    (chara or {}).get("turn", 0),
                    vitality=(chara or {}).get("vital"),
                    failure_rate=(command or {}).get("failure_rate"),
                    rainbow_count=self._rainbow_count(command, chara),
                ) or {}).get("adjustment") or 0.0)
            except Exception:
                learned = 0.0

        return {
            "goal_progress": goal_progress,
            "failure_risk": failure_risk,
            "learned": learned,
        }

    # STAMINA FOR THE LONG GOALS (on for Grand Live only). Every failed Grand Live goal on 2026-10-20
    # was a 3000 m / 3200 m race (Kikuka Sho T44, Tenno Sho Spring T56) run on 220-350 Stamina. The
    # goal-driven Stamina CAP only LIMITS Stamina; nothing aimed for it. So in the run-up to a long goal
    # (> 2400 m) a training's Stamina gain earns score while Stamina is short of that race's need. Only
    # the gain that closes the gap counts, so it switches itself off at the need.
    # Tried on MANT 2026-10-30 (targets 450/600, 10 Kitasan careers): it traded ~7 Wit/Speed trainings
    # for Stamina, cut the stat total ~300 and the score 13,122 -> 11,778, for little gain in those races.
    STAMINA_PUSH = False
    STAMINA_PUSH_WINDOW = 16      # start this many turns before the long goal race
    STAMINA_PUSH_WEIGHT = 1.0     # score per 10 useful Stamina at the window start, x2 by the race

    def _long_goal_stamina(self, chara):
        """(Stamina need, turns left) for the nearest long career-goal race (> 2400 m) within
        STAMINA_PUSH_WINDOW turns, else (0, 0)."""
        planner = getattr(self, "race_planner", None)
        turn = int((chara or {}).get("turn") or 0)
        if not hasattr(planner, "_goals") or not turn:     # no planner (or a test stub without goals)
            return 0, 0
        bands = planner.STAMINA_NEED_BANDS
        best = (0, 0)
        for g in planner._goals(chara):
            left = int(g.get("turn") or 0) - turn
            if g.get("kind") != "race" or not 0 < left <= self.STAMINA_PUSH_WINDOW:
                continue
            pid = int(g.get("program_id") or ((g.get("program_ids") or [0])[0]) or 0)
            dist = int((planner.program.get(pid) or {}).get("distance") or 0)
            if dist <= 2400:
                continue
            need = next(v for upper, v in bands if dist <= upper)
            if not best[1] or left < best[1]:
                best = (need, left)
        return best

    def _stamina_push(self, command, chara):
        """Score for the Stamina this training adds toward the next long goal's need (see above)."""
        if not self.STAMINA_PUSH or int((command or {}).get("command_type") or 0) != 1:
            return 0.0
        need, left = self._long_goal_stamina(chara)
        short = need - int((chara or {}).get("stamina") or 0)
        if not need or short <= 0:
            return 0.0
        gain = sum(float(i.get("value") or 0) for i in (command or {}).get("params_inc_dec_info_array") or []
                   if i.get("target_type") == 2)
        if gain <= 0:
            return 0.0
        urgency = 2.0 - left / self.STAMINA_PUSH_WINDOW        # 1 at the window start -> ~2 at the race
        return self.STAMINA_PUSH_WEIGHT * min(gain, short) / 10.0 * urgency

    def _score_command(self, command, data, chara, preset):
        base = self._score_command_base(command, data, chara, preset)
        push = self._stamina_push(command, chara)
        if (preset or {}).get("score_command_v2", True) is False:
            self._last_score_breakdown = {"base": base, "goal_progress": 0.0, "failure_risk": 0.0, "learned": 0.0,
                                          "stamina_push": push, "total": base + push}
            return base + push
        adjustment = self._score_command_adjustment(command, chara, preset)
        total = base + adjustment["goal_progress"] + adjustment["failure_risk"] + adjustment["learned"] + push
        self._last_score_breakdown = {"base": base, **adjustment, "stamina_push": push, "total": total}
        return total

    def _score_command_base(self, command, data, chara, preset):
        turn = int(chara.get("turn") or 0)
        weights = self._period_row(preset.get("score_value"), turn, [0.11, 0.10, 0.006, 0.09])
        base = preset.get("base_score") or [0, 0, 0, 0, 0]
        # Per-stat SOFT training targets, index [Speed, Stamina, Power, Guts, Wit]. 9999 = "no target"
        # for that stat -> the min(game_cap, target) below falls through to the stat's live in-game cap.
        # Sourced from the per-preset stat_caps: a set cap becomes that stat's target, so the attenuation
        # ladder + balance boost taper training toward IT (and the ~660 parity boost drops to 0.55*cap,
        # so a capped/low stat no longer gets a catch-up nudge). Unset/blank/0 stays 9999. The hard drop
        # in _stat_capped_trainings still zeroes a stat once REACHED; this just tapers scoring into it.
        targets = [9999, 9999, 9999, 9999, 9999]
        # (a) Per-scenario TRAIN-TO ceiling: how high the bot trains each stat in THIS scenario, set
        # near the game's absolute per-stat max (1800). It's the training TARGET -- the bot trains UP
        # to min(this, the stat's LIVE in-game cap), so it no longer stops a stat at a conservative
        # number (the reported "won't train Wit past ~1100"). The live cap (max_speed... raised by
        # inheritance) already differs per run/scenario, so this just stops a lower soft target from
        # holding the stat below it. Overridden per stat by an explicit stat_caps; disable with
        # scenario_stat_caps=False (then foresight's aptitude aim decides, below).
        scen = self._scenario_stat_caps(preset)
        if scen:
            for i in range(5):
                if int(scen[i] or 0) > 0:
                    targets[i] = int(scen[i])
        # (b) User stat_caps: an explicit per-stat cap -- overrides the scenario ceiling (and also
        # drives the hard training drop in _stat_capped_trainings, which the scenario ceiling does not).
        caps = preset.get("stat_caps")
        if isinstance(caps, dict) and any(caps.values()):
            for i in range(5):
                try:
                    c = int(caps.get(STAT_NAMES[i]) or 0)
                except (TypeError, ValueError):
                    c = 0
                if c > 0:
                    targets[i] = c
        # (c) Career foresight: ONLY for stats left with no cap at all (still 9999 -- scenario caps off
        # AND user unset). Steer toward the predicted aptitude build, relaxed toward the game cap by
        # foresight_target_slack (0 = chase the forecast hard; 1 = ignore it; default 0.5). A
        # scenario/user cap is NOT pulled down by foresight -- the bot trains UP to it, which is what
        # lets a stat reach the scenario's real ceiling instead of a low conservative aim.
        forecast = getattr(self, "_forecast", None)
        if forecast is not None and forecast.active:
            slack = float(preset.get("foresight_target_slack", 0.5))
            for i in range(5):
                if targets[i] < 9999:
                    continue
                ft = int(forecast.stat_targets[i] or 0)
                gc = int(chara.get(STAT_CAP_KEYS.get(i)) or BASE_STAT_CAP)
                targets[i] = int(ft + slack * max(0, gc - ft))
        idx = TRAINING_COMMANDS.get(command.get("command_id"), 0)
        score = float(base[idx] if idx < len(base) else 0)
        w_lv1 = float(weights[0] if len(weights) > 0 else 0.11)
        w_lv2 = float(weights[1] if len(weights) > 1 else 0.10)
        w_energy = float(weights[2] if len(weights) > 2 else 0.006)
        w_hint = float(weights[3] if len(weights) > 3 else 0.09)
        stat_mult = preset.get("stat_value_multiplier") or [0.01, 0.01, 0.01, 0.01, 0.01, 0.005]
        bonds = self._bond_map(chara)
        partners = command.get("training_partner_array") or []
        hints = set(command.get("tips_event_partner_array") or [])
        pal_count = 0
        hint_count = 0
        rainbow_count = 0
        useful_stat_score = 0.0
        # Rainbow-unlock lookahead: one cheap step of planning past the greedy single-turn
        # score. Training a deck support that sits just under bond 80 pushes it toward the
        # rainbow (friendship-training) threshold, which then fires on EVERY future
        # appearance of that card -- the single biggest stat lever in MANT/URA. Greedy
        # scoring gives the crossing turn no credit (rainbow_count only rewards supports
        # ALREADY >=80), so the bot can spread bond thinly and reach rainbow state late.
        # This accumulates a bounded premium for crossing, strongest when the support is
        # close to 80 (one training flips it) and early (more future appearances to cash in).
        rainbow_unlock_score = 0.0
        rainbow_lookahead = preset.get("rainbow_unlock_lookahead", True)
        unlock_lo = float(preset.get("rainbow_unlock_band_lo") or 40)
        unlock_base = float(preset.get("rainbow_unlock_bonus") or 0.12)
        for partner_id in partners:
            bond = bonds.get(partner_id, 0)
            if partner_id in hints:
                hint_count += 1

            if bond >= 80:
                # Maxed support on this training is delivering a rainbow (friendship
                # training) this turn. There is no more bond to build, so it adds no
                # bond value, but we count it for the explicit rainbow reward below.
                if partner_id in DECK_PARTNERS:
                    rainbow_count += 1
                continue

            time_decay = max(0.0, (72 - turn) / 72.0)
            efficiency_boost = 1.0 + (bond / 80.0) * 0.5 if bond >= 60 else 1.0
            
            weight = time_decay * efficiency_boost

            if partner_id not in DECK_PARTNERS:
                yield_val = self._npc_score(bond, turn, preset)
                score += yield_val * weight
                continue

            if partner_id == 6:
                pal_count += 1
                yield_val = self._pal_score(bond, preset)
                score += yield_val * weight
                continue

            ratio = min(1.0, bond / 80.0)
            yield_val = w_lv1 + (w_lv2 - w_lv1) * ratio
            score += yield_val * weight
            if rainbow_lookahead and unlock_lo <= bond < 80:
                # Proximity ramps 0 (band start) -> ~1 (just under 80): the closer to the
                # threshold, the likelier this single training crosses it. time_decay (set
                # above) front-loads the bonus so we secure rainbows while they still pay off.
                proximity = (bond - unlock_lo) / max(1.0, 80.0 - unlock_lo)
                rainbow_unlock_score += unlock_base * proximity * time_decay
        # Skill-hint ('!') reward -- important BEFORE Senior, then dropped (see _hint_bonus).
        score += self._hint_bonus(hint_count, turn, w_hint, preset)
        for item in command.get("params_inc_dec_info_array") or []:
            value = float(item.get("value") or 0)
            if item.get("target_type") == 10:
                if value > 0:
                    # Only the energy that FITS is worth anything: Wit's +energy above max_vital is
                    # wasted. (This used to multiply Wit's WHOLE score by 0.75 -- 0.35 after turn 72 --
                    # whenever any of it overflowed, throwing away its stats and SP too: 33 of 224
                    # Grand Live training turns on 2026-10-20.)
                    room = max(0.0, float(chara.get("max_vital") or 100) - float(chara.get("vital") or 0))
                    value = min(value, room)
                energy_score = value * w_energy
                if int(chara.get("vital") or 0) >= 80 and value < 0:
                    energy_score *= 0.9
                score += energy_score
                continue
            target = STAT_TARGETS.get(item.get("target_type"))
            if target is None:
                continue
            if target == 5:
                # SP scored at stat_value_multiplier[5] (0.005) against 0.010 for a stat point, i.e.
                # 1 SP = 0.5 stat points. Calibrated, not guessed: across 679 career logs
                # rank_score = SUM g(stat) + SUM skill grade_value (R^2 0.995); a stat point is worth
                # 3.74 rank score at the bot's real final stats and an SP converts at 1.79
                # (481k SP of actual buys -> 861k grade_value). 1.79/3.74 = 0.48 ~= the shipped
                # 0.005/0.010, so the CONSTANTS were already right -- only the default was wrong
                # (SP counted for nothing, which quietly undervalued the SP-rich Wit facility).
                # ponytail: worth ~+4 rank score/career and flips 1.9% of real boards -- a
                # tie-breaker, not a lever. Do NOT raise the weight to make it "matter": anything
                # above ~0.005/SP pays more for an SP than an SP is worth. Wit's real edge is the
                # energy term, not this. Set "score_skill_points": false to revert.
                if preset.get("score_skill_points", True) and value > 0:
                    sp_mult = float(stat_mult[5] if len(stat_mult) > 5 else 0.005)
                    sp_score = value * sp_mult * float(preset.get("skill_point_weight") or 1.0)
                    score += sp_score
                    useful_stat_score += max(0.0, sp_score)
                continue

            stat_mult_val = float(stat_mult[target] if target < len(stat_mult) else 0.01)
            stat_gain_score = value * stat_mult_val
            # Effective ceiling = the stat's REAL in-game cap (raised by inheritance), tightened
            # by an optional per-preset soft target for focused builds. Reading the live cap is
            # what activates the attenuation ladder + balance boost below without wrongly
            # throttling a cap-raised uma at a flat 1200.
            soft = float(targets[target] if target < len(targets) else 9999)
            game_cap = float(chara.get(STAT_CAP_KEYS.get(target)) or BASE_STAT_CAP)
            cap = min(game_cap, soft)
            if cap > 0 and target < 5:
                current = self._current_stat(chara, target)
                # Climax stat credit: the TS climax races will add stats to each PHYSICAL stat over
                # t74/76/78 -- as much as the cleat hammers IN HAND boost them (no hammers -> +57
                # total, full 2-Artisan+1-Master loadout -> +72). Treat the stat as already that
                # much higher when deciding it's "done", so the bot stops piling onto a near-cap
                # physical stat and pours those turns into other stats -- the climaxes carry it the
                # rest of the way. Wit gets no credit (climax adds +0 Wit). MANT-only: the credit
                # returns 0 for other scenarios (no TS climax races), so they train each stat to cap.
                if target < 4:
                    current += self._climax_stat_credit(
                        target, turn,
                        self._owned_item_count(data, MASTER_CLEAT_ITEM_ID),
                        self._owned_item_count(data, ARTISAN_CLEAT_ITEM_ID))
                ratio = current / cap
                if ratio > 1.0:
                    stat_gain_score *= 0.0
                elif ratio > 0.97:
                    stat_gain_score *= 0.35 - ((ratio - 0.97) / 0.03) * 0.25
                elif ratio > 0.94:
                    stat_gain_score *= 0.55 - ((ratio - 0.94) / 0.03) * 0.20
                elif ratio > 0.90:
                    stat_gain_score *= 0.75 - ((ratio - 0.90) / 0.04) * 0.20
                elif ratio > 0.86:
                    stat_gain_score *= 0.85 - ((ratio - 0.86) / 0.04) * 0.10
                elif ratio > 0.82:
                    stat_gain_score *= 0.91 - ((ratio - 0.82) / 0.04) * 0.06
                elif ratio > 0.78:
                    stat_gain_score *= 0.95 - ((ratio - 0.78) / 0.04) * 0.04
                elif ratio > 0.74:
                    stat_gain_score *= 0.98 - ((ratio - 0.74) / 0.04) * 0.03
                elif ratio > 0.70:
                    stat_gain_score *= 1.00 - ((ratio - 0.70) / 0.04) * 0.02
                elif preset.get("stat_balance", True) and cap < 9000:
                    # Under-target boost: nudge the bot to FILL a stat that sits far
                    # below its target instead of piling onto near-capped stats, so the
                    # final build is balanced (not lopsided). The further under target,
                    # the bigger the nudge (capped). Active by default now that targets
                    # default to the 1200 stat cap (cap < 9000); complements the cap-based
                    # down-weighting above. Disable with preset "stat_balance": false.
                    thr = float(preset.get("stat_balance_threshold") or 0.55)
                    if ratio < thr:
                        stat_gain_score *= 1.0 + (thr - ratio) * float(preset.get("stat_balance_boost") or 0.6)
            score += stat_gain_score
            # The rainbow/unlock attenuation below keys off useful_stat_score. It must reflect
            # whether the stat is TRULY near its real in-game cap (genuinely wasted gain), NOT
            # merely de-prioritised below a tighter soft forecast/user target -- otherwise a
            # multi-rainbow turn on an off-build stat (e.g. Stamina for a sprinter) would collapse
            # to zero once that stat crept past its low soft target, throwing away the turn's
            # bond/friendship value. So when a soft target is tighter than the game cap, measure
            # headroom against the GAME cap; otherwise keep the soft-attenuated score.
            if target < 5 and cap < game_cap and game_cap > 0:
                game_headroom = max(0.0, 1.0 - self._current_stat(chara, target) / game_cap)
                useful_stat_score += max(0.0, value * stat_mult_val * game_headroom)
            else:
                useful_stat_score += max(0.0, stat_gain_score)
        # "Learn to win" emphasis (ADDITIVE, gated by preset ai_train_to_win, default on). The AI
        # has learned which stats the bot's losing races reward (race_train_emphasis +
        # race_mark_emphasis). Give this training a small bonus proportional to emphasis_weight[stat]
        # * its gain in that stat, scaled by ai_train_to_win_weight. KEPT SMALL (default 0.05, was
        # 0.15): at 0.15 this bonus was big enough to flip the pick onto a stat it was "supposed to
        # train" over the training with the best RAW gain -- measured to cost ~217 trained stat
        # points/career, the single biggest driver of a real grade dip. At 0.05 it acts as a
        # tie-breaker (nudge toward the losers' stats only when raw gains are close) without
        # sacrificing total stats. The emphasis dict is cached for the whole career. It now BLENDS the
        # career-goal solver's stat_priority (so training follows THIS trainee's goals from turn 1) with
        # the learned loss emphasis -- renormalized, so the nudge STRENGTH is unchanged, only its aim.
        emphasis = self._merged_emphasis(preset, chara)
        if emphasis:
            ttw_weight = float(preset.get("ai_train_to_win_weight") or 0.05)
            emphasis_bonus = 0.0
            for item in command.get("params_inc_dec_info_array") or []:
                target = STAT_TARGETS.get(item.get("target_type"))
                if target is None or target >= 5:
                    continue  # skill points / energy don't map to a trained stat
                stat_key = TRAINING_NAMES[target].lower()  # speed/stamina/power/guts/wit
                w = float(emphasis.get(stat_key) or 0.0)
                if w <= 0:
                    continue
                stat_mult_val = float(stat_mult[target] if target < len(stat_mult) else 0.01)
                emphasis_bonus += w * float(item.get("value") or 0) * stat_mult_val
            score += emphasis_bonus * ttw_weight
        # Shared "useful stat" attenuation: how much non-capped stat this turn actually
        # yields, relative to a reference. Both the rainbow reward and the bond-unlock
        # premium are gated by it so the bot never chases bond/rainbow on a facility whose
        # stat is already capped (zero useful gain -> zero bond/rainbow incentive).
        ref = float(preset.get("rainbow_useful_ref") or 0.12)
        atten = 1.0 if ref <= 0 else min(1.0, useful_stat_score / ref)
        if rainbow_count and preset.get("rainbow_explicit", True):
            # Explicit rainbow (friendship-training) reward. The reported stat gain
            # already includes the friendship bonus, but the bond loop gives a maxed
            # support zero value, which can make the bot pass up a multi-rainbow turn
            # to keep building bond elsewhere. Add a tunable per-rainbow bonus.
            # Failure compensation, period extra-weight and deck multipliers below apply too.
            per = float(preset.get("rainbow_bonus") or 0.12)
            stack = float(preset.get("rainbow_stack_bonus") or 0.06)
            score += (per * rainbow_count + stack * max(0, rainbow_count - 1)) * atten
        if rainbow_unlock_score:
            # Bond-crossing premium: cap it (so many in-band supports can't dominate a turn)
            # and gate by the same useful-stat factor, then add it here so the pal multiplier
            # and failure compensation below still apply -- we never force a high-failure or
            # already-capped training just because it would tip a support toward rainbow range.
            cap_premium = float(preset.get("rainbow_unlock_cap") or (unlock_base * 2.0))
            score += min(rainbow_unlock_score, cap_premium) * atten
        if pal_count:
            score *= 1.0 + max(0.0, min(1.0, float(preset.get("pal_card_multiplier") or 0.1)))
        if preset.get("compensate_failure", True):
            # Expected-value failure term. A training succeeds with P=(1 - fail) and is treated
            # as losing `failure_cost` x the would-be gain on a failure. failure_cost=1.0 (the
            # default) reproduces the old `1 - fail/50` EXACTLY (a failure as costly as success
            # is valuable); lower it (e.g. 0.6) to be less failure-averse, raise it to be more
            # cautious. Optional `max_failure_rate` hard-filters very risky trainings out
            # entirely (Icarus-style); a charm/Vita rescue can still re-enable them on the
            # post-item re-decision since that re-runs scoring at the lowered failure rate.
            fail = float(command.get("failure_rate") or 0) / 100.0
            fail_cost = float(preset.get("failure_cost", 1.0))
            score *= max(0.0, (1.0 - fail) - fail_cost * fail)
            max_fail = preset.get("max_failure_rate")
            if max_fail is not None and float(command.get("failure_rate") or 0) > float(max_fail):
                return -999.0
        if idx == 4:
            vital = int(chara.get("vital") or 0)
            # (Overflowing energy is already credited at 0 in the energy term above.)
            if vital < 85:
                # Wit also restores energy, so prefer it MORE the lower energy gets --
                # recovering via Wit (which still trains + gives skills/SP) beats wasting
                # a whole rest turn. Scales from ~1.0 near full to a tunable cap when low.
                low = (85 - vital) / 85.0
                score *= 1.0 + low * float(preset.get("wit_energy_boost") or 0.25)
        extra = self._extra_weight(idx, turn, preset)
        if extra == -1:
            return -999.0
        score *= max(0.0, min(2.0, 1.0 + extra)) * self._stat_focus(idx, chara)

        if turn < 60:
            deck_mults = preset.get("_deck_multipliers")
            if deck_mults and len(deck_mults) > idx:
                score *= float(deck_mults[idx])

        return score

    # The user's build rule (2026-10-30): Wit over Stamina for every uma -- most of them run sprint/mile
    # tracks that need little Stamina. Wit trainings score x WIT_FOCUS; Stamina trainings score
    # x STAMINA_FOCUS once Stamina covers what the career-goal races need (RacePlanner.stamina_need:
    # 300 for a sprinter, up to 500 for a Tenno Sho Spring stayer), so a stayer still gets its Stamina.
    # ponytail: code-only constants; make them preset keys if one preset needs its own values.
    WIT_FOCUS = 1.3
    STAMINA_FOCUS = 0.7

    def _stat_focus(self, idx, chara):
        """Score multiplier for the training on stat `idx` (0..4) under the Wit-over-Stamina rule."""
        if idx == 4:
            return self.WIT_FOCUS
        if idx == 1:
            planner = getattr(self, "race_planner", None)
            try:
                need = int(planner.stamina_need(chara)) if hasattr(planner, "stamina_need") else 0
            except Exception:
                need = 0
            if int((chara or {}).get("stamina") or 0) >= need:
                return self.STAMINA_FOCUS
        return 1.0

    def _current_stat(self, chara, target):
        keys = ["speed", "stamina", "power", "guts", "wiz", "skill_point"]
        return float(chara.get(keys[target], 0) or 0)

    def _climax_stat_credit(self, target, turn, master_qty=0, artisan_qty=0):
        """Physical-stat points (Spd/Sta/Pow/Guts; +0 Wit) the remaining TS climax races will add,
        computed from the cleat hammers ACTUALLY in hand -- so it self-adjusts: 0 hammers -> the
        no-hammer base (15+15+27 = 57), and it rises as the bot buys/holds hammers. Mirrors the
        climax cleat reserve rule (Master saved for the latest climax via MASTER_CLEAT_CLIMAX_RESERVE,
        Artisan covers an earlier one), so e.g. 1 Master + 1 Artisan -> 18+15+36 = 69. The scorer
        adds this to a stat's CURRENT value when judging how 'done' it is, so the bot stops training
        it ~this much short of the cap and the climaxes finish the job. Shrinks as climaxes complete.

        MANT-ONLY: the TS climax races (and the cleat hammers that boost them) exist only in
        Trackblazer. URA / Unity / Grand Live have no such races, so crediting future climax stats
        there just makes the bot hold each physical stat short of its cap for gains that never come
        -- return 0 so those scenarios train every stat all the way to its cap."""
        if self.scenario_id != 4:
            return 0.0
        if target >= 4:   # Wit (4) / SP (5) get nothing from the climax events
            return 0.0
        m, a = int(master_qty), int(artisan_qty)
        total = 0.0
        for ct in sorted(CLIMAX_RACE_GAIN_BASE):
            if turn >= ct:
                continue   # climax already fired
            if m > MASTER_CLEAT_CLIMAX_RESERVE.get(ct, 0):
                mult = CLEAT_MULT_MASTER
                m -= 1
            elif a > 0:
                mult = CLEAT_MULT_ARTISAN
                a -= 1
            else:
                mult = 1.0
            total += CLIMAX_RACE_GAIN_BASE[ct] * mult
        return total

    def _team_command(self, data, command_id):
        team_data = data.get("team_data_set") or {}
        for cmd in team_data.get("command_info_array") or []:
            if cmd.get("command_id") == command_id:
                return cmd
        return None

    def _bond_map(self, chara):
        result = {}
        for row in chara.get("evaluation_info_array") or []:
            result[row.get("target_id", 0)] = row.get("evaluation", 0)
        return result

    def _bondable_count(self, command, chara):
        """How many deck support partners on this training still need bonding.

        A partner already at max bond (>= 80) contributes a rainbow but no longer
        builds friendship, so it does not count toward the Junior bond-rush. The
        friend/pal slot (6) counts too since it also unlocks rainbow training.
        """
        bonds = self._bond_map(chara)
        count = 0
        for partner_id in command.get("training_partner_array") or []:
            if partner_id in DECK_PARTNERS and int(bonds.get(partner_id, 0) or 0) < 80:
                count += 1
        return count

    def _rainbow_count(self, command, chara):
        """How many deck supports on this training are at max bond (>=80) = rainbows.

        A maxed support present on a training delivers a friendship-training
        ("rainbow") bonus; stacking several on one training is the biggest stat turn
        in the game. NPCs (not in DECK_PARTNERS) don't trigger friendship training.
        """
        bonds = self._bond_map(chara)
        count = 0
        for partner_id in command.get("training_partner_array") or []:
            if partner_id in DECK_PARTNERS and int(bonds.get(partner_id, 0) or 0) >= 80:
                count += 1
        return count

    def _wit_rest_alternative(self, training, chara, preset, turn, prefix):
        """Shared Wit-over-rest hook. On a turn the brain would REST, train Wit instead when Wit is
        safe -- Wit RECOVERS energy while still paying stats + skill points, so it beats a dead
        0-stat rest turn. Each scenario delegates here with its own preset prefix
        (<prefix>_wit_over_rest / <prefix>_wit_rest_max), so the policy lives in ONE place.

        THE ENERGY-TRAP GUARD (learned the hard way, from a live run):
        substituting Wit unconditionally made things WORSE, not better. Wit is only mildly
        energy-positive, so on a career that already sits below the rest threshold it never climbs
        out: measured over a real MANT career, the bot spent 52 of 78 turns at HP <= 48, took 25
        rest-gate Wit substitutions, trained Speed just 9 times, and finished Speed 774 / Wit 856 --
        Wit the top stat in a SPEED build, rank A (was A+ with 15 Speed trainings). Rest turns did
        not even drop (5 -> 5). It was choosing Wit at 12 stats / 0 partners over Speed at 30 stats
        / 3 partners, purely because Speed cost energy it never rebuilt.
        So: if the board holds a training worth much more than Wit (wit_rest_skip_ratio, default
        1.5x raw stat gain), REST instead. Resting restores the 40-70 energy that unlocks that
        better board next turn, which is worth more than a small Wit now. Wit-over-rest is for
        turns where resting buys nothing -- not for outbidding a strong facility."""
        p = preset or {}
        if not p.get(f"{prefix}_wit_over_rest", True):
            return None
        cap = int(p.get(f"{prefix}_wit_rest_max", 10))
        wit = None
        for cmd in training or []:
            # TRAINING_COMMANDS maps the Wit facility (106, and summer's 605) to stat index 4.
            if TRAINING_COMMANDS.get(int(cmd.get("command_id") or 0)) == 4 and int(cmd.get("failure_rate") or 0) < cap:
                wit = cmd
                break
        if wit is None:
            return None
        ratio = float(p.get("wit_rest_skip_ratio", 1.5) or 0)
        if ratio > 0:
            wit_gain = self._command_stat_total(wit)
            best_gain = max((self._command_stat_total(c) for c in training or []
                             if int(c.get("command_type") or 0) == 1), default=0.0)
            if wit_gain > 0 and best_gain > wit_gain * ratio:
                return None                    # rest and bank the energy for the better board
        return wit

    def _command_stat_total(self, command):
        """Total board value the strong-train-over-race gate weighs = the five trainable stats
        (speed+stamina+power+guts+wit) ONLY. Skill points (idx 5) and energy (target_type 10) are
        NOT counted -- the gate trades a race for a training on RAW STAT gain alone, so an
        SP-rich-but-stat-poor board no longer counts as 'strong'. Matches _command_stat_gain, which
        also counts stats only."""
        if not command:
            return 0.0
        total = 0.0
        for item in command.get("params_inc_dec_info_array") or []:
            idx = STAT_TARGETS.get(item.get("target_type"))
            if idx is not None and idx <= 4:   # 0..4 = the five stats; skill points (5) NOT counted
                total += float(item.get("value") or 0)
        return total

    def _owned_item_count(self, data, item_id):
        total = 0
        for row in (data.get("free_data_set") or {}).get("user_item_info_array") or []:
            if int(row.get("item_id") or 0) == int(item_id):
                total += int(row.get("num") or row.get("current_num") or row.get("item_num") or 0)
        return total

    def _rescue_energy_value(self, data, vital, rest_threshold, margin):
        """Restore value of the SMALLEST owned energy item that would lift vital
        comfortably above the rest threshold, or None if none owned can do it. Used
        to decide whether a low-energy turn can be rescued into a training."""
        target = rest_threshold + margin
        # Royal Kale (2101) drains a mood tier: the item manager only drinks it with a cupcake
        # (2301/2302) to offset that, so without one it is not a rescue.
        has_cupcake = self._owned_item_count(data, 2301) + self._owned_item_count(data, 2302) > 0
        owned = {}
        for row in (data.get("free_data_set") or {}).get("user_item_info_array") or []:
            iid = int(row.get("item_id") or 0)
            if iid == 2101 and not has_cupcake:
                continue
            if iid in ENERGY_ITEM_VALUES:
                owned[iid] = owned.get(iid, 0) + int(row.get("num") or row.get("current_num") or row.get("item_num") or 0)
        best = None
        for iid, qty in owned.items():
            if qty > 0 and vital + ENERGY_ITEM_VALUES[iid] > target:
                if best is None or ENERGY_ITEM_VALUES[iid] < ENERGY_ITEM_VALUES[best]:
                    best = iid
        return ENERGY_ITEM_VALUES[best] if best is not None else None

    def _can_rescue_training(self, data, chara, preset, best, best_score, vital, failure, rest_threshold):
        """Spend a charm / energy item to RUN a strong training instead of resting it
        away for low energy or high failure? Only for a genuinely good turn (a rainbow
        or a high cap-aware score), only when energy isn't critically low, and only
        when we actually own the mitigation that can clear the blocker: an energy item
        big enough to beat the vital floor, or a charm/energy when only failure is high.
        Mirrors items.py _rescue_energy_target so the post-item re-decision agrees."""
        if not preset.get("rescue_good_training", True):
            return False
        if best is None or int(best.get("command_type") or 0) != 1:
            return False
        if best_score is None or best_score <= 0:
            return False
        if vital < int(preset.get("rescue_min_vital") or 25):
            return False
        rainbow = self._rainbow_count(best, chara)
        # All-out summer: any positive-score camp training is worth rescuing with items/charm, not
        # just rainbow/high-score turns -- the Lv5 camp facilities make every camp turn premium, for
        # EVERY deck now (mirrors _best_command and items.py: no group gate). The MANT climax counts
        # as all-out too, exactly like mant_items _rescue_energy_target / _charm_target.
        turn = int(chara.get("turn") or 0)
        camp_all_out = ((preset.get("summer_all_out", True) and turn in RACE_VALUE_CAMP_TURNS)
                        or (self.scenario_id == 4 and preset.get("climax_all_out", True)
                            and turn in CLIMAX_TRAIN_TURNS))
        strong = best_score >= float(preset.get("rescue_score_threshold") or 0.55) or camp_all_out
        if rainbow < 1 and not strong:
            return False
        margin = int(preset.get("rescue_vital_margin") or 12)
        energy_val = self._rescue_energy_value(data, vital, rest_threshold, margin)
        has_charm = self._owned_item_count(data, GOOD_LUCK_CHARM_ID) > 0
        hard_cap = int(preset.get("failure_hard_cap") or 50)
        if failure >= hard_cap:
            # Absolute failure ceiling: above the cap only a Good-Luck Charm (which forces
            # a verified 0%) may rescue the turn -- an energy bump does NOT guarantee the
            # failure drops below the cap, so we never gamble a high-intensity facility on
            # it. With no charm we rest instead. (A pro run was seen training at 99%.)
            return has_charm
        if vital <= rest_threshold:
            # only an energy item can lift vital back over the rest threshold
            return energy_val is not None
        if failure >= 35:
            # vital is fine, just the (possibly stale) failure is high -> charm/energy fixes it
            return has_charm or energy_val is not None
        return False

    def _failure_forces_rest(self, best, data, chara, preset, turn, failure):
        """Whether the best training's failure rate alone is high enough to force a REST. Base: the
        shared ~35% ceiling (tunable via failure_rest_threshold). Scenarios override to tighten it --
        Unity rests at a low failure to protect energy, with rainbow/soul-burst keep-training exceptions."""
        return int(failure or 0) >= int(preset.get("failure_rest_threshold") or 35)

    def _rest_alternative(self, training, chara, preset, turn):
        """A training to run INSTEAD of resting on a turn the brain decided to rest, or None to rest
        as usual. Base rests (None); Unity overrides to run a safe Wit train (recovers energy + builds
        its 1800 Wit cap) rather than burn a dead rest turn. `training` is the stat-capped enabled
        training list, so a Wit already at cap is absent and this falls back to rest for free."""
        return None

    def _command_stat_gain(self, command):
        """Raw stat points a training yields this turn (Speed/Stamina/Power/Guts/Wit).

        This is the "jumlah training" the player thinks in: a 2-rainbow turn lands
        around 30+. Skill points are not counted; the stat cap is not considered.
        """
        total = 0
        for item in command.get("params_inc_dec_info_array") or []:
            if item.get("target_type") in (1, 2, 3, 4, 5):
                total += int(item.get("value") or 0)
        if total == 0:
            for field in ["speed", "stamina", "power", "guts", "wiz"]:
                total += int(command.get(field) or 0)
        return total

    def _is_g1_program(self, program_id):
        """Is this race a G1? (race_instance_id starting with '1' is the codebase's
        G1 convention, same as the item/cleat logic.)"""
        if not self.race_planner or not program_id:
            return False
        info = (self.race_planner.program or {}).get(int(program_id or 0)) or {}
        return str(info.get("race_instance_id") or "").startswith("1")

    def _train_outvalues_race(self, data, chara, preset, program_id=0):
        """Should a scheduled race be skipped in favor of training this turn?

        Value-based: compare what the training brain would actually get this turn (the
        full cap/rainbow/foresight-aware command score) against the race's estimated
        worth, instead of the old flat raw-stat threshold that ignored both sides' real
        value. Hard rules first: a G1 is never skipped, and while the uma is still below
        the fan-grind threshold no race is skipped either (fans gate career goals).
        Otherwise skip only when the bot would genuinely train (not rest/recreate) AND
        that training's score beats the race value -- which is grade-aware (G2 worth
        more than G3/open) and discounted during summer camp, where Lv5 facilities make
        training the better trade for anything below G1. Applies to wanted + fan races
        via the planner's choose() path; race-only turns never reach this (no training
        exists to compare).
        """
        if self._is_g1_program(program_id):
            return False
        # Fail safe: a program we can't grade (absent from race_map) might be a G1 --
        # never trade an unknown race away.
        if not self.race_planner or int(program_id or 0) not in (self.race_planner.program or {}):
            return False
        # Strong-training override: on a G2/G3 turn (G1 is already raced above, and forced
        # career-objective races never reach this gate), a genuinely strong board out-earns the
        # race -- take the training even if the race was user-scheduled or fans are still low.
        # "Strong" = the training the bot would actually run this turn has a total stat gain >=
        # strong_train_stat_total_min (default 40), OR the board carries >= strong_train_rainbow_min
        # rainbows (default 2). The rainbow shortcut used to default to 0 (OFF), which left MANT with
        # NO working way to trade a race for training: with a 28-race schedule the raw-stat bar of 40
        # is cleared on only ~1 board in 3, so the bot raced ~30 times and trained ~30 turns of 78.
        # A 2-rainbow board is the best trade in the game -- take it. Set 0 to disable the shortcut
        # again. A rest/recreation turn never qualifies. When this fires,
        # the item manager sees the same training as best_command and uses the matching-type anklet
        # + a megaphone on it. Tunable; disable the whole override with strong_train_over_race: false.
        if preset.get("strong_train_over_race", True):
            command = self._best_command(data, chara, preset, record=False)
            if command and int(command.get("command_type") or 0) == 1:
                rmin = preset.get("strong_train_rainbow_min")
                rainbow_min = 2 if rmin is None else int(rmin)
                stat_min = float(preset.get("strong_train_stat_total_min") or 40)
                # Summer (Lv5 camp, 37-40 / 61-64) is the best stat trade in the game, so the bar to
                # train over a race drops: a raw board (stats + SP, before any megaphone/anklet) of
                # >= 30 trains, vs 40 outside summer. Tunable via summer_strong_train_stat_total_min.
                if int(chara.get("turn") or 0) in RACE_VALUE_CAMP_TURNS:
                    stat_min = float(preset.get("summer_strong_train_stat_total_min") or 30)
                if ((rainbow_min > 0 and self._rainbow_count(command, chara) >= rainbow_min)
                        or self._command_stat_total(command) >= stat_min):
                    return True
        # Never skip a USER-SCHEDULED race. A race the user put in extra_race_list is one they
        # explicitly want run; the AI must train to WIN it (see ai_learn.race_train_emphasis),
        # not trade it away for a training turn. wanted_programs() returns exactly the program_ids
        # derived from the preset's extra_race_list for this turn, so membership there == scheduled.
        # Only the planner's auto fan-grind races (NOT in wanted) remain eligible to be train-traded.
        if preset.get("never_skip_scheduled", True):
            try:
                wanted = self.race_planner.wanted_programs(preset, int(chara.get("turn") or 0))
            except Exception:
                wanted = []
            if int(program_id or 0) in (wanted or []):
                return False
        # Legacy kill-switch: race_skip_train_stat 0/None has always meant "never skip a race".
        if not preset.get("race_skip_train_stat", RACE_SKIP_TRAIN_STAT):
            return False
        # Fan-grind consistency guard: below the planner's auto fan-grind threshold the
        # planner proposes a race every turn, so skipping would just re-litigate the same
        # decision forever. Clamped to the planner's 350 so a preset can only RAISE it.
        fans = int(chara.get("fans") or 0)
        min_fans = preset.get("race_skip_min_fans")
        min_fans = 350 if min_fans is None else max(350, int(min_fans))
        if fans < min_fans:
            return False
        commands = (data.get("home_info") or {}).get("command_info_array") or []
        training = [
            cmd for cmd in commands
            if cmd.get("is_enable", 1) and cmd.get("command_type") == 1 and cmd.get("command_id") in TRAINING_COMMANDS
        ]
        training = self._stat_capped_trainings(training, chara, preset)   # user per-stat cap
        if not training:
            return False
        command = self._best_command(data, chara, preset)
        if not (command and int(command.get("command_type") or 0) == 1):
            return False  # the bot would rest/recreate anyway -> the race is the better turn
        # Same effective score the selector itself used (incl. senior nudge / bond-rush pick),
        # so the gate can never disagree with the brain about what the turn is worth.
        turn = int(chara.get("turn") or 0)
        train_score, _ = self._pick_scored_training(training, data, chara, preset, turn)
        return train_score > self._race_value(program_id, chara, preset)

    def _race_value(self, program_id, chara, preset):
        """Estimated turn-value of running a scheduled non-G1 race, in command-score
        units (a plain single training scores ~0.3, a multi-rainbow turn 0.8+). Grade
        comes from the race_instance_id convention already used by the cleat logic
        (1xxxxx=G1, 2xxxxx=G2, 3xxxxx=G3/open): a G2's stat/fan/SP reward outranks a
        G3's, so it takes a stronger board to skip. In the junior year the bar is raised
        further -- bond-rush boards score inflated bond/hint value there, and early fan
        races are cheap fans the career needs. During the in-camp turns the value is
        discounted instead: the opportunity cost of skipping a Lv5-facility turn is far
        higher, so anything below G1 must clear a much better race to be worth it."""
        def knob(key, default):
            value = preset.get(key)
            return default if value is None else float(value)
        base = knob("race_value_base", 0.50)
        info = {}
        if self.race_planner:
            info = (self.race_planner.program or {}).get(int(program_id or 0)) or {}
        if str(info.get("race_instance_id") or "").startswith("2"):
            base += knob("race_value_g2_bonus", 0.15)
        turn = int(chara.get("turn") or 0)
        if turn <= 24:
            base += knob("race_value_junior_bonus", 0.25)
        if turn in RACE_VALUE_CAMP_TURNS:
            base *= knob("race_value_camp_mult", 0.65)
        # Closed-loop AI signal (additive + confidence-gated). When enabled and the
        # learned model is confident enough, nudge this race's value by what the bot
        # has learned about its own win rate on this program. Fully guarded so a
        # missing/corrupt model never changes deterministic behavior or raises.
        if preset.get("enable_ai_policy", True) and self.race_planner:
            try:
                adj = ai_learn.race_policy_adjustment(self.race_planner.base_dir, program_id)
                if adj.get("confidence", 0.0) >= preset.get("ai_confidence_threshold", 0.6):
                    base += adj.get("adjustment", 0.0) * preset.get("ai_policy_weight", 1.0)
            except Exception:
                pass
        return base

    def _npc_score(self, bond, turn, preset):
        if bond >= 80:
            return 0.0
        row = self._period_row(preset.get("npc_score_value"), turn, [0.05, 0.05, 0.05])
        v1 = float(row[0] if len(row) > 0 else 0.05)
        v2 = float(row[1] if len(row) > 1 else v1)
        ratio = min(1.0, bond / 80.0)
        return v1 + (v2 - v1) * ratio

    def _pal_score(self, bond, preset):
        if bond >= 80:
            return 0.0
        scores = preset.get("pal_friendship_score") or [0.08, 0.057, 0.018]
        v1 = float(scores[0] if len(scores) > 0 else 0.08)
        v2 = float(scores[1] if len(scores) > 1 else v1)
        ratio = min(1.0, bond / 80.0)
        return v1 + (v2 - v1) * ratio

    def _period_index(self, turn):
        if turn <= 24:
            return 0
        if turn <= 48:
            return 1
        if turn <= 60:
            return 2
        if turn <= 72:
            return 3
        return 4

    def _period_row(self, rows, turn, fallback):
        if not isinstance(rows, list) or not rows:
            return fallback
        idx = min(self._period_index(turn), len(rows) - 1)
        row = rows[idx]
        return row if isinstance(row, list) else fallback

    def _extra_weight(self, idx, turn, preset):
        rows = preset.get("extra_weight") or [[0, 0, 0, 0, 0]] * 4
        if turn <= 24:
            row_idx = 0
        elif turn <= 48:
            row_idx = 1
        elif turn in SUMMER_CAMP_TURNS and len(rows) >= 4:
            row_idx = 3
        else:
            row_idx = 2
        if row_idx >= len(rows) or not isinstance(rows[row_idx], list) or idx >= len(rows[row_idx]):
            return 0.0
        return float(rows[row_idx][idx] or 0)

    def _mood_threshold(self, turn, preset):
        if turn <= 36:
            return int(preset.get("motivation_threshold_year1") or 3)
        if turn <= 60:
            return int(preset.get("motivation_threshold_year2") or 4)
        return int(preset.get("motivation_threshold_year3") or 4)

    def _junior_turn_friendship(self, training, chara):
        """This turn's friendship VALUE = the most deck support partners on any single facility.
        In pre-debut Junior no support is maxed yet, so _bondable_count == 'how many of my support
        cards are sitting on that facility' -- i.e. how much bond a training here would build. A turn
        whose BEST facility has few partners is a weak friendship turn (little bond to gain)."""
        return max((self._bondable_count(c, chara) for c in (training or [])), default=0)

    def _junior_recreation(self, recreation, turn, training, chara, preset):
        """Exactly ONE pre-debut (Junior turns 1..last) recreation per career -- MANDATORY, all
        scenarios. Recreation raises motivation, and motivation multiplies every later training's
        stat gain, so banking mood early pays off across the whole career. Fire it on a WEAK
        friendship turn: when the best facility has <= max_partners deck supports on it, training
        builds little bond, so the mood is worth more than the training. If no weak turn has come up
        by the last pre-debut turn, force it anyway (it's a MUST). Returns the recreation command or
        None. Tunables: junior_recreation (default on), junior_recreation_max_partners (2),
        junior_recreation_last_turn (11 = the last training turn before the turn-12 debut race)."""
        # Blocked only once a junior recreation was committed on an EARLIER turn (_best_command commits
        # the turn). A same-turn re-decide (post-item) must STILL return it, so compare turns, not a bool.
        if (self._junior_recreated_turn and self._junior_recreated_turn != turn) or not recreation or not training:
            return None
        if not preset.get("junior_recreation", True):
            return None
        last = int(preset.get("junior_recreation_last_turn") or 11)
        if turn < 1 or turn > last:
            return None
        max_partners = int(preset.get("junior_recreation_max_partners") or 2)
        friendship = self._junior_turn_friendship(training, chara)
        # weak friendship board this turn -> recreate; else keep training. Force on the last turn.
        if friendship <= max_partners or turn >= last:
            return recreation
        return None

    def _log_junior_recreation(self, turn, training, chara):
        try:
            f = self._junior_turn_friendship(training, chara)
            print(f"[junior-recreation] turn {turn}: best friendship board = {f} partner(s) "
                  f"-> spending the turn on recreation for the mood boost (once per career)", flush=True)
        except Exception:
            pass

    def _free_mood_bonus(self, turn):
        """Free scenario-calendar MOOD bonus arriving next turn. Base (and URA/Unity) have NO such
        calendar, so this returns 0; MantStrategy overrides it to read MANT's fixed-turn bonus schedule.
        Polymorphism keeps the MANT-only free-bonus data out of the shared brain -- no scenario gate."""
        return 0

    def _pre_summer_mood_command(self, recreation, turn, motivation, vital, preset):
        """Bank GREAT mood (5) BEFORE a Lv5 summer camp. Camp (RACE_VALUE_CAMP_TURNS: 37-40 / 61-64) is
        the highest-value training of the career and runs ALL-OUT with no recreation mid-camp, and the
        mood multiplier applies to every one of those turns -- so mood must already be maxed going in.
        On the pre-camp run-up (SUMMER_CONSERVE_TURNS = 35/36/59/60), when mood is below target, spend
        the turn on recreation to lift it. Called AHEAD of the pre-camp rest/conserve, so mood is banked
        FIRST and energy on the remaining prep turn(s). Defers to REST when energy is critically low --
        a Great-mood camp is worthless if you arrive with no energy to train, so bank energy first and
        top mood on a higher-vital prep turn. Skipped when a free mood bonus next turn already reaches
        target, or under a mandatory race (decided upstream in next_decision, so a goal/cup race on turn
        36/60 still runs and the push uses the earlier prep turn). Tunables: pre_summer_mood (default on),
        pre_summer_target (default 5 = Great), precamp_rest_vital (energy floor, default 30 -- above it a
        Wit training is a better "soft rest" than a full 0-stat rest, so we don't defer that eagerly)."""
        if not recreation or not preset.get("pre_summer_mood", True):
            return None
        if turn not in SUMMER_CONSERVE_TURNS:
            return None
        rest_floor = int(preset.get("precamp_rest_vital") or 30)
        if vital <= rest_floor:
            return None                      # energy critical -> let the pre-camp REST bank it first
        target = int(preset.get("pre_summer_target") or 5)
        if motivation >= target:
            return None
        # Skip if a free mood bonus next turn already reaches target. _free_mood_bonus is 0 for every
        # scenario except MANT (which overrides it with its fixed-turn calendar), so URA/Unity never
        # wait for a bonus that doesn't exist.
        if preset.get("wait_for_free_bonus", True) and \
                (motivation + self._free_mood_bonus(turn)) >= target:
            return None
        return recreation

    def _should_recreate(self, recreation, preset, turn, motivation, vital, best_score):
        if not recreation:
            return False
        if turn in SUMMER_CAMP_TURNS:
            return False
        # Wait for a free mood bonus next turn rather than spending a whole turn on recreation, when
        # that bonus already lifts mood to GREAT (5). _free_mood_bonus is 0 for every scenario except
        # MANT (which overrides it with its fixed-turn calendar), so URA/Unity never wait. Applies only
        # to the mood-recovery recreation below (pal-event recreation is left untouched).
        mood_covered_by_bonus = (
            preset.get("wait_for_free_bonus", True)
            and (motivation + self._free_mood_bonus(turn)) >= 5
        )
        # Critical mood floor: Bad(2)/Awful(1) mood applies a large NEGATIVE multiplier to EVERY
        # training's stat gain (~-10%/-20%), so once mood sinks this low, recovering it outvalues ANY
        # board -- recreate regardless of best_score. Without this, the best_score<=0.3 gate below lets
        # a steady run of decent boards (a friendship/rainbow deck is usually >0.3) keep training
        # through low mood and spiral it to Awful -- the reported bug (a friend's career bottomed out
        # at very low mood). Defer to REST only when energy is also low: the rest gate below restores
        # energy and can nudge mood, so we don't burn a recreation turn while vital is critical. Skip
        # if a free mood bonus next turn already lifts it. Tunable: mood_floor (default 2 = Bad/Awful).
        rest_floor = int(preset.get("rest_threshold") or 48)
        if motivation <= int(preset.get("mood_floor", 2)) and vital > rest_floor and not mood_covered_by_bonus:
            return True
        # Opt-in: proactively top mood up to GREAT (motivation 5) on weak, energy-spare
        # training turns -- a strong-run habit (the GREAT multiplier on the next good turn
        # outvalues a mediocre training now). Default off; never fires on a rainbow/strong
        # turn (gated by best_score) or when energy is near full.
        if preset.get("mood_target_recreate") and motivation < 5 and vital < 90 \
                and best_score <= float(preset.get("mood_recreate_max_score") or 0.30) \
                and not mood_covered_by_bonus:
            return True
        if motivation < self._mood_threshold(turn, preset) and vital < 90 and best_score <= 0.3 \
                and not mood_covered_by_bonus:
            return True
        if not preset.get("prioritize_recreation"):
            return False
        thresholds = preset.get("pal_thresholds") or []
        if not thresholds:
            return False
        stage = int(preset.get("_pal_event_stage") or 0)
        if stage >= len(thresholds):
            stage = 0
        row = thresholds[stage]
        if not isinstance(row, list) or len(row) < 2:
            return False
        mood_ok = motivation <= int(row[0])
        energy_ok = vital <= int(row[1])
        score_ok = True
        if len(row) > 2:
            score_ok = best_score <= float(row[2])
        return mood_ok and energy_ok and score_ok

    def choose_from_event(self, event, current_turn, chara=None):
        if self.event_manager:
            return self.event_manager.choose(event, chara=chara, preset=self._preset)
        return 1
