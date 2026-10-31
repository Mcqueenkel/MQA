"""Grand Live / "Our Grand Concert" (scenario_id 3 -- master.mdb text_data category 237 = "Grand Concert").

Global's "Our Grand Concert" == the community's "Grand Live" == JP "Make a New Track". All one scenario.

API mapped from a full 78-turn capture (UmaDumpy 20260723_070635, 412 transactions, every result_code 1).
Namespace = `single_mode_live/*` (wired in uma_api/client.py `_route_ep`). The ENTIRE core career flow --
start / load / check_event / exec_command / get_choice_reward / race_entry|start|end|out / gain_skills /
factor_select / finish -- carries payloads byte-identical to MANT/Unity/URA, so the shared training brain,
race planner, event manager and finish flow all work unchanged. Only two calls are Grand-Live-only:

  * `master_square {current_turn, square_id}` -- the Master Square board. The game offers squares in
    live_data_set.next_square_info_array and you claim one. VERIFIED: in the capture all 64 claims came
    from that offered list (64/64), and it fires many times per career (up to 8 on one turn).
  * `live_start {current_turn}`             -- the Grand Live performance. Fires at turns 24/36/48/60/72,
    i.e. the same year-boundary cadence as Unity's Cup races.

live_data_set (the scenario's state block, the analog of Unity's team_data_set):
  live_performance_info  -- the five performance stats dance/passion/vocal/visual/mental (each max 200)
  command_info_array     -- per training facility, which performance type it raises and by how much
  next_square_info_array -- the squares currently claimable ({square_id, square_num})
  next_live_id_array     -- songs learned since the last concert (they apply at the next one)
  master_live_id_array   -- every song learned so far (= effected_live_id_array + next_live_id_array)
"""
from career_bot.core.base import Decision
from career_bot.core.training_brain import BaseTrainingStrategy, TRAINING_COMMANDS, SENIOR_START_TURN, GROUP_OUTING_COMMAND_ID


class GrandLiveStrategy(BaseTrainingStrategy):
    scenario_id = 3

    # API layer is wired + verified against a full capture -> runner.start() will run this scenario.
    API_READY = True

    # Grand Live stat caps [SPD, STA, PWR, GUT, WIT] -- the user's chosen "reach as high as possible
    # toward these" profile: Speed 1600, Stamina 1300, Power 1300, Guts 1500, Wit 1300 (Grand Live's
    # in-scenario Stamina ceiling is 1300). Set high on purpose (matches a manual UG run: Wit is the
    # energy + skill-point engine, so it must NOT be held at a low cap or the bot rests instead of
    # training Wit). Applied as HARD caps (see GRAND_LIVE_STAT_CAPS / _with_stat_caps) so a stat that
    # overshoots stops stealing turns -- but the ceilings are generous enough that the bot trains every
    # facility freely toward them.
    DEFAULT_STAT_CAPS = (1600, 1300, 1300, 1500, 1300)

    # The same profile as a stat_caps dict (STAT_NAMES keys -- note Wit is "wiz"). Injected into the
    # preset by _with_stat_caps so _stat_capped_trainings actually HARD-drops a maxed stat. The user's
    # own stat_caps, if set, win.
    GRAND_LIVE_STAT_CAPS = {"speed": 1600, "stamina": 1300, "power": 1300, "guts": 1500, "wiz": 1300}

    def _with_stat_caps(self, preset, chara=None):
        """Return the preset with Grand Live's hard caps applied, unless the user set their own
        stat_caps (those win). Hard caps stop the bot dedicating turns to a capped stat. Stamina is
        special: it is trained ON DEMAND, so the 1300 Stamina ceiling is pulled DOWN to what the
        trainee's career-GOAL races actually need (RacePlanner.stamina_need) -- a sprinter like
        Bakushin never wastes turns on Stamina, a Kikuka/Tenno-Spring stayer trains it up to ~400/500."""
        p = preset or {}
        user_caps = p.get("stat_caps")
        if isinstance(user_caps, dict) and any(user_caps.values()):
            return preset                                    # user set their own -> respect it
        caps = dict(self.GRAND_LIVE_STAT_CAPS)
        planner = getattr(self, "race_planner", None)
        if chara and planner is not None:
            try:
                caps["stamina"] = min(int(caps["stamina"]), int(planner.stamina_need(chara)))
            except Exception:
                pass                                         # fall back to the flat 1300 ceiling
        return {**p, "stat_caps": caps}

    def _rest_alternative(self, training, chara, preset, turn):
        """Grand Live: on a would-rest turn, train a safe Wit instead of burning a dead 0-stat turn.
        Policy + the energy-trap guard live in the shared base (_wit_rest_alternative).
        Toggles: grand_live_wit_over_rest / grand_live_wit_rest_max / wit_rest_skip_ratio."""
        return self._wit_rest_alternative(training, chara, preset, turn, "grand_live")

    # Like URA/Unity, Grand Live runs its fixed career-goal route: the goals ARE the schedule, so no
    # optional/free racing unless the user explicitly opts in with use_race_schedule.
    RACE_POLICY = {**BaseTrainingStrategy.RACE_POLICY,
                   "goal_races_only": True, "scheduled_override": False, "optional_races": False,
                   # A run with a 40-race schedule (2026-10-16, preset asdad) raced 35-38 times, 7-8 in a
                   # row, entered 33 dirt races at dirt G (0 wins), took 5-12 Race Fatigue events and
                   # lost its must-win T72 goal at 0 energy in 4 of 5 careers. Goals only: A+/SS.
                   "optional_race_guard": True}

    # Grand Live performance turns. CONFIRMED from master.mdb single_mode_live_live_data.turn_num
    # (24/36/48/60/72), matching the capture exactly. The turn-72 row is live_type 10 = the GRAND LIVE
    # finale (special_music_id 1029 = the true-finale song). Lives fire on these FIXED turns; the
    # expectation gauge is a separate meter that gates the finale, NOT a per-live trigger.
    LIVE_TURNS = (24, 36, 48, 60, 72)
    # Safety net only: the capture makes 64 claims across a whole career, so this is set well clear of
    # real play. It exists so a pathological offer stream can't spin the turn loop forever.
    MAX_SQUARE_CLAIMS = 200

    def next_decision(self, state, preset):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        preset = self._with_stat_caps(preset, chara)   # HARD caps + goal-driven Stamina drive the brain
        turn = int(chara.get("turn") or 0)
        # The Concert screen reports chara_info.turn as 0/absent (live: "t0 idle | no action" while the
        # game sat on 1st Concert). Remember the last real turn so the rescue below still knows which
        # Live is owed -- without it the turn-in-LIVE_TURNS check fails and the run idles out.
        self._chara = chara          # stashed for _should_recreate, which gets no chara argument
        if turn:
            self._last_turn = turn
        else:
            # 0 here means UNKNOWN, not "turn zero". Mid-run _last_turn carries the real turn across
            # the Concert screen; on a RESUMED career the strategy object is brand new, so _last_turn
            # is unset and this stays 0. Both Live gates below therefore require a non-zero turn --
            # live_start{current_turn: 0} is never valid (concerts are 24/36/48/60/72) and the server
            # 205s it. Live: career_log_20260731_035056 resumed a turn-24 career, fired live_start with
            # current_turn 0 three times and ended the career at the first step.
            turn = int(getattr(self, "_last_turn", 0) or 0)
        lds = data.get("live_data_set") or {}

        # 1) Grand Live performance (turns 24/36/48/60/72), once each. Gated on next_live_id_array so a
        #    resumed/mid-turn state can't re-fire one that already ran.
        #    ORDER: the Live comes AFTER this turn's race. The Concert screen (ps 10) only appears once
        #    the turn's action has run, so the goal/fan race is decided at turn start (ps 1), where this
        #    branch never fires. On ps 10 no race can be pending: across 69 Grand Live career logs the
        #    server took live_start 117/117 times there and refused every race_entry (205/208). Holding
        #    the Live back for a "pending" race there is what stalled turn 72 (career_log_20261016_081215:
        #    Arima won, still on the board, race_entry 205 x13, run gave up).
        done = self._live_done()
        # The Concert screen is playing_state 10 (capture 20260723_170405: single_mode_live/load ->
        # turn 24, ps 10, then live_start; ps drops to 5 once it runs). That is the RELIABLE signal --
        # the analog of Unity's cup playing_state 7/8/9 -- so key on it rather than the turn number.
        # live_start needs the pending EVENT ID as well as the turn; sending only current_turn is what
        # the server answered 102 to.
        ps = int(chara.get("playing_state") or 0)
        # RESUMED-CAREER TURN RECOVERY. On the Concert screen chara_info.turn is 0 and a fresh strategy
        # object has no _last_turn, so every gate below (and the square claim) would be skipped and the
        # career would idle out. Derive it from the concerts already performed -- see concert_turn().
        if not turn and ps == self.CONCERT_PLAYING_STATE:
            turn = self.concert_turn(data)
            if turn:
                self._last_turn = turn

        # LESSONS FIRST. On the Concert screen the game wants the pending lesson (Master Square) claimed
        # before the performance -- the in-game UI shows Lessons carrying a "!" badge while Concert is the
        # goal, and the reference capture's turn 24 runs master_square BEFORE live_start. Claiming here
        # (rather than after the Live gate below) is what stops the bot sitting on "1st Concert" with an
        # unclaimed lesson. Same once-per-distinct-offer throttle as the normal path.
        if turn and ps == self.CONCERT_PLAYING_STATE:
            pending = self.pick_square(lds, preset)
            if pending:
                offer = self._offer_key(lds)
                if self._offer_open(offer, turn):
                    return Decision("master_square", {"square_id": pending, "current_turn": turn,
                                                       "_offer_key": offer},
                                    f"concert lesson -> master square {pending}")

        if turn and ps == self.CONCERT_PLAYING_STATE and turn not in done:
            return Decision("grand_live_perform",
                            {"current_turn": turn, "event_id": self._live_event_id(data)},
                            "Grand Live performance")

        # 2) Master Square: claim a square, at most ONCE per distinct offer.
        #    next_square_info_array is NOT a per-turn "you may claim now" list -- it is the PENDING
        #    board choice and stays byte-identical for many turns (capture: turns 1-12 all show the same
        #    three squares; the client claimed once, at turn 12, and only then did it change). Claiming
        #    on every turn that shows an offer is what 205-stormed the live run. So key on the OFFER
        #    itself: attempt each distinct offer once, and don't touch it again until the board advances
        #    (i.e. the offer changes). A 205 here is deterministic ("not claimable yet"), so the attempt
        #    is simply spent and the turn proceeds -- the next real advance presents a new offer.
        square_id = self.pick_square(lds, preset)
        if square_id:
            offer = self._offer_key(lds)
            if self._offer_open(offer, turn):
                return Decision("master_square", {"square_id": square_id, "current_turn": turn,
                                                   "_offer_key": offer},
                                f"master square {square_id}")

        decision = super().next_decision(state, preset)
        # 3) Concert-screen rescue. After the turn's race resolves, the game parks on the Concert
        #    screen: no training, no rest, nothing raceable -- so the shared brain has nothing to do and
        #    returns "idle", which ends the run (live: ended@turn24 sitting on "1st Concert"). If this is
        #    a Live turn we haven't performed yet, perform it instead of idling. next_live_id_array is
        #    deliberately NOT required here: it is a preview field and is empty on the Concert screen
        #    itself. A wrong guess is harmless -- live_start answers 102 and the runner skips it.
        # IDLE means the shared brain found no training, no rest and no race. In Grand Live that
        # essentially only happens on the Concert screen, so treat idle ITSELF as the signal and try the
        # performance -- do NOT also require the turn to be a known Live turn. A resumed process reports
        # chara_info.turn as 0 with no remembered turn, which is exactly how the bot idled out on the
        # 4th Concert (career_log_20260723_172228: "t0 idle" -> ended@turn60) even though ps/turn gating
        # was already in place. Guarded per turn value so it is attempted once, never looped; a wrong
        # guess is harmless because live_start answers 102 and the runner skips it.
        if turn and getattr(decision, "action", None) == "idle" and turn not in done:
            tried_live = self._idle_live_tried()
            if turn not in tried_live:
                return Decision("grand_live_perform",
                                {"current_turn": turn, "event_id": self._live_event_id(data)},
                                "Grand Live performance (idle -> concert screen)")
        return decision

    # Weight on live_data_set.training_bonus_array: the per-stat "Training +N" concert bonuses of the
    # songs performed so far (target 6 = SP; e.g. Grow Up and Shine! +3 and Run for Our Dream! +2 give
    # SP 5). An effect of N is worth about N stat points, so it is scored like stat points (0.01 each,
    # the base scorer's stat_value_multiplier). It was 1.5, which priced "Guts Training +3" like ~450
    # stat points: career 2026-10-28 picked a +19 Guts board over +37 Speed and ended Guts 931 /
    # Speed 820. Tunable: grand_live_bonus_weight.
    TRAINING_BONUS_WEIGHT = 0.01

    @staticmethod
    def training_bonus_map(data):
        """{target_type -> effect_value} from live_data_set.training_bonus_array (1=Spd 2=Sta 3=Pwr
        4=Guts 5=Wit). Empty early in a career, before any performance tier is reached."""
        arr = ((data or {}).get("live_data_set") or {}).get("training_bonus_array") or []
        out = {}
        for b in arr:
            try:
                out[int(b.get("target_type") or 0)] = float(b.get("effect_value") or 0)
            except (TypeError, ValueError):
                continue
        return out

    # "Train with the right support card": how much each DECK support card present on a facility adds to
    # its score. This makes the bot follow where the MAJORITY of the deck congregates, so a Speed deck
    # (3 Speed cards) trains Speed instead of chasing a lone off-type SSR rainbow (a 3-Speed/2-Wit deck
    # was producing Wit-heavy builds -- Wit trained up to 24x, Speed as few as 5). The base scorer only
    # rewarded RAINBOWS (bond>=80), so one strong SSR Wit rainbow beat three still-bonding Speed cards;
    # counting card PRESENCE (bonded or bonding) restores "go where the cards are". Tunable via
    # grand_live_card_weight; set 0 to fall back to pure base scoring.
    CARD_PRESENCE_WEIGHT = 1.5
    # Stamina toward the long goals (Kikuka Sho, Tenno Sho Spring): the shared push in
    # training_brain, with RacePlanner.STAMINA_NEED_BANDS as the targets (400 up to 3000 m, 500 above).
    STAMINA_PUSH = True

    def _score_command(self, command, data, chara, preset):
        """Shared score, plus (1) a strong preference for the facility holding the most DECK support
        cards -- 'train with the right support card' -- and (2) Grand Live's performance-driven training
        bonus for the stat this facility trains. Non-training commands (rest/recreate/race) untouched.
        (A type-aware version of (1) -- off-type maxed cards counted 0 -- was tried on 2026-10-20 and
        reverted: careers reached turn 55 ~230 stats weaker, with fewer Power trainings.)"""
        base = super()._score_command(command, data, chara, preset)
        if int((command or {}).get("command_type") or 0) != 1:
            return base
        idx = TRAINING_COMMANDS.get(int(command.get("command_id") or 0))
        # (1) deck support-card density on this facility (rainbows + still-bonding deck partners),
        # under the same Wit-over-Stamina focus as the stat score -- this term decides most boards.
        present = self._rainbow_count(command, chara) + self._bondable_count(command, chara)
        focus = self._stat_focus(idx, chara) if idx is not None else 1.0
        base += present * float((preset or {}).get("grand_live_card_weight", self.CARD_PRESENCE_WEIGHT)) * focus
        # (2) performance -> training-plate bonus for the stat this facility trains
        bonus = self.training_bonus_map(data)
        if bonus and idx is not None:
            w = float((preset or {}).get("grand_live_bonus_weight", self.TRAINING_BONUS_WEIGHT))
            base += bonus.get(idx + 1, 0.0) * w          # target_type is the 1-based stat index
        # (3) performance points toward the song the shop is waiting on
        base += self._song_points_score(command, data)
        return base

    # live_data_set.command_info_array[].performance_inc_dec_info_array performance_type -> the
    # live_performance_info key (checked against live deltas: 2 -> passion, 3 -> vocal).
    PERFORMANCE_TYPES = {1: "dance", 2: "passion", 3: "vocal", 4: "visual", 5: "mental"}
    # Score per performance point that closes the gap to the best song on the board that is not yet
    # affordable (0.03 = 3 stat points). Training ignored these points before 2026-10-30, so a Speed/Wit
    # deck waited on chance for e.g. the vocal a song needs while the shop held for up to 12 turns.
    SONG_POINT_WEIGHT = 0.03

    def _song_points_score(self, command, data):
        """Credit for the performance points this training gives that the best offered-but-unaffordable
        song still needs; only the points that close the gap count, so it switches off once affordable."""
        lds = (data or {}).get("live_data_set") or {}
        perf = lds.get("live_performance_info") or {}
        if int(getattr(self, "_last_turn", 0) or 0) > self.LIVE_TURNS[-1]:
            return 0.0                                   # after the last concert songs only pay once
        wanted = [int(sq.get("square_id") or 0) for sq in lds.get("next_square_info_array") or []]
        wanted = [sid for sid in wanted if sid in self.SONG_SQUARE_SCORE and not self.can_afford(sid, perf)]
        if not wanted:
            return 0.0
        target = max(wanted, key=lambda sid: self.SONG_SQUARE_SCORE[sid])
        cost = (self._squares_data().get(str(target)) or {}).get("cost") or {}
        short = {k: int(v or 0) - int(perf.get(k) or 0) for k, v in cost.items()}
        cid = int((command or {}).get("command_id") or 0)
        row = next((c for c in lds.get("command_info_array") or [] if int(c.get("command_id") or 0) == cid), {})
        useful = 0
        for p in row.get("performance_inc_dec_info_array") or []:
            key = self.PERFORMANCE_TYPES.get(int(p.get("performance_type") or 0))
            if short.get(key, 0) > 0:
                useful += min(int(p.get("value") or 0), short[key])
        return useful * self.SONG_POINT_WEIGHT

    # Turn-72 finale requirement, from master.mdb single_mode_live_live_data (id 5, live_type 10 =
    # GRAND_LIVE): song_num 20, special_music_id 1029 (the TRUE finale song), normal_music_id 1036.
    # Collect 20 songs by turn 72 -> the expectation gauge maxes -> the SPECIAL/"Great Hype" finale.
    # The reference capture reached turn 72 with only 15 songs, so it got the normal finale.
    # THE rule (uma.guide/guides/grand-concert, corroborated by master.mdb
    # single_mode_live_live_data.great_success_num = 3 on ALL FIVE concert rows):
    # learn THREE songs before EVERY concert to score a Great Success -- "+10 to all Stats" versus only
    # "+3" without. Cumulatively that is 3 per concert -> 15 by the turn-72 Grand Concert. 18 total
    # unlocks the gold skill and 21 unlocks bonus technique lessons (stretch goals, not requirements).
    # An earlier version chased a flat 20 by turn 72; that misread song_num as the target and ignored
    # the per-concert cadence, which is what actually pays.
    # SONG TARGETS PER CONCERT -- TOTAL songs held by each concert turn, INCLUDING the free Make Debut!.
    # Deadlines are the concert turns (master.mdb single_mode_live_live_data.turn_num):
    #     1st  Junior  Late Dec  t24 ->  4     (+4)
    #     2nd  Classic Late Jun  t36 ->  7     (+3)
    #     3rd  Classic Late Dec  t48 -> 11     (+4)
    #     4th  Senior  Late Jun  t60 -> 15     (+4)
    #     5th  Senior  Late Dec  t72 -> 19     (+4)
    # A ~3-4 per concert cadence, close to the community guidance of "4 on the first live, then about
    # three a live, then go wide once the friendship-bonus songs unlock after live 3". The previous
    # ladder (4/10/14/16/MAX) front-loaded much harder; buying that early spends points while the
    # cheap early techniques are the only ones unlocked, and the later songs are the better ones.
    # Three songs before each concert is the GAME's Great Success bar (+10 all stats vs +3), so every
    # step here clears it with room. Override wholesale with grand_live_song_targets.
    #
    # NOTE t72 is now a REAL number, not MAX: the bot stops chasing songs once it holds 19, where it
    # previously never stopped. That is 1 short of FINALE_SONG_TARGET (20, master.mdb song_num for the
    # TRUE "Great Hype" finale) -- see the comment there before treating 19 as final.
    # 72 is 20, not 19: the 20th song unlocks the TRUE finale (and its gold skill) -- stopping at 19
    # forfeited both for one song's worth of tokens.
    SONG_TARGET_BY_CONCERT = {24: 4, 36: 7, 48: 11, 60: 15, 72: 20}
    SONGS_PER_CONCERT = 3            # the game's Great Success bar, kept for reference
    SONG_MAXIMIZE_TARGET = 999       # the finale: never stop buying songs
    TRUE_FINALE_MUSIC_ID = 1029
    # Songs needed AT turn 72 for the TRUE ("Great Hype") finale -- master.mdb
    # single_mode_live_live_data id 5, song_num 20. This is the REPORTING threshold only (did the
    # career unlock the true finale); what the bot BUYS toward is SONG_TARGET_BY_CONCERT above.
    # runner._run reads it via getattr for the Discord finale embed -- it was previously undefined
    # here, so that lookup silently fell through to its hardcoded default.
    FINALE_SONG_TARGET = 20

    @classmethod
    def songs_due_by(cls, turn, preset=None):
        """Songs that must be HELD by `turn`, from SONG_TARGET_BY_CONCERT.

        Keyed on the NEXT concert, because a target must be met BY that turn -- keying on concerts
        already passed demanded the turn-36 number while still on turn 24.
        """
        table = {int(k): int(v) for k, v in
                 ((preset or {}).get("grand_live_song_targets") or cls.SONG_TARGET_BY_CONCERT).items()}
        for concert_turn in sorted(table):
            if turn <= concert_turn:
                return table[concert_turn]
        return max(table.values()) if table else 0

    @classmethod
    def songs_collected(cls, state_or_data):
        """Songs currently held, counted as a TOTAL that INCLUDES the free Make Debut! -- the basis the
        targets are written in ("I will always include make debut from here")."""
        d = (state_or_data or {}).get("data") or state_or_data or {}
        lds = (d or {}).get("live_data_set") or {}
        # master_live_id_array = every song learned so far. effected_live_id_array only catches up at
        # each concert (master = effected + next_live_id_array in 320 captured responses), so counting
        # it read every song bought since the last concert as missing.
        return len(lds.get("master_live_id_array") or lds.get("effected_live_id_array") or [])

    def song_shortfall(self, data, preset=None, turn=None):
        """Songs still owed for the NEXT concert's Great Success (0 when already banked).

        Uses the per-concert cadence, not a single end-of-career number: falling short before concert 2
        costs +10 all-stats there and cannot be made up later by over-buying before the finale.
        """
        override = (preset or {}).get("grand_live_song_target")
        if turn is None:
            turn = int(getattr(self, "_last_turn", 0) or 0)
        target = int(override) if override is not None else self.songs_due_by(turn, preset)
        return max(0, target - self.songs_collected(data))

    # "Light Hello" Friends support card (data/support_list.json): R 10083 / SSR 30052. A Friends card's
    # whole value is the RECREATION it unlocks, and the unlock rides on a friendship choice -- so the
    # branch that trades friendship away for raw stats is a trap here. Grand-Live-only by design: this
    # lives on GrandLiveStrategy, so MANT/URA/Unity keep the shared event scoring untouched.
    LIGHT_HELLO_IDS = frozenset({10083, 30052})

    @classmethod
    def has_light_hello(cls, chara):
        """True when Light Hello (R or SSR) is in the running deck."""
        ids = {int(c.get("support_card_id") or 0) for c in ((chara or {}).get("support_card_array") or [])}
        return bool(ids & cls.LIGHT_HELLO_IDS)

    @staticmethod
    def _top_choice(event):
        """0-BASED index of the TOP option (0), or None when the event has no choices. NOTE: the
        chooser contract is a 0-based index into choice_array (runner._event uses choices[choice] and
        EventManager.choose returns i) -- returning a select_index here picked the SECOND option.""" 
        choices = ((event or {}).get("event_contents_info") or {}).get("choice_array") or []
        return 0 if choices else None

    @classmethod
    def _event_source_card(cls, event):
        """The support card that triggered this event, from event_contents_info.support_card_id
        (CONFIRMED against the capture: Light Hello SSR 30052 tags all 15 of its events). 0 if absent."""
        return int(((event or {}).get("event_contents_info") or {}).get("support_card_id") or 0)

    def is_light_hello_event(self, event):
        """A Light Hello support event (R 10083 / SSR 30052), e.g. 'Embrace Those Emotions!'."""
        return self._event_source_card(event) in self.LIGHT_HELLO_IDS

    def choose_from_event(self, event, current_turn, chara=None):
        """Grand Live: on any LIGHT HELLO event -- identified by its own support_card_id, e.g. "Embrace
        Those Emotions!" -- always take the ENERGY option (the choice whose known outcomes give the most
        vital), no matter what the stat scorer would prefer. Scoped to Light Hello's OWN events, so every
        OTHER card's event still goes through the shared scorer. Off via grand_live_light_hello.
        """
        if (self._preset or {}).get("grand_live_light_hello", True) and self.is_light_hello_event(event):
            # Take the ENERGY option (the choice whose known outcomes grant the most vital). Falls back
            # to the TOP option when the per-choice energy outcomes aren't in the DB.
            mgr = getattr(self, "event_manager", None)
            if mgr is not None and hasattr(mgr, "energy_choice_index"):
                idx = mgr.energy_choice_index(event)
                if idx is not None:
                    return idx
            top = self._top_choice(event)
            if top is not None:
                return top
        return super().choose_from_event(event, current_turn, chara=chara)

    # Light Hello's own chara_id (master.mdb support_card_data, R and SSR alike) and its date count
    # (outing_max). The date is the partner outing: command 390 with select_id = the partner's chara_id
    # (single_mode_outing_set 1 = {301 solo, 390 partner}), the same request the confirmed Sirius/Throne
    # character outings use. Until 2026-10-30 every "date" went out as the solo 301, so Light Hello's
    # story_step stayed 0 all career (career_log_20261030_222823: unlocked by turn ~20, 4 recreations,
    # 0 dates). If the server ever rejects or no-ops it, the runner sets _scheduled_outing_blocked and
    # this falls back to the solo recreation.
    LIGHT_HELLO_CHARA = 9008
    LIGHT_HELLO_DATES = 5

    def _recreation_command(self, commands):
        """Any recreation is the Light Hello date while one is unlocked and left (it gives the mood of
        the solo outing plus the date's own gains); otherwise the solo recreation."""
        chara = getattr(self, "_chara", None) or {}
        if ((getattr(self, "_preset", None) or {}).get("grand_live_light_hello", True)
                and not getattr(self, "_scheduled_outing_blocked", False)
                and self.has_light_hello(chara)):
            slot = next((self._support_slot(chara, i) for i in self.LIGHT_HELLO_IDS
                         if self._support_slot(chara, i)), None)
            row = self._slot_row(chara, slot) or {}
            date = next((c for c in commands if c.get("command_type") == 3
                         and int(c.get("command_id") or 0) == GROUP_OUTING_COMMAND_ID), None)
            if (date and int(row.get("is_outing") or 0) == 1
                    and int(row.get("story_step") or 0) < self.LIGHT_HELLO_DATES):
                self._pending_outing_is_card = False
                return self._outing_command(date, self.LIGHT_HELLO_CHARA)
        return super()._recreation_command(commands)

    def _should_recreate(self, recreation, preset, turn, motivation, vital, best_score):
        """Grand Live + Light Hello: WHEN to spend a turn on the Light Hello date. Per the user's policy,
        the dates play out as: 1st/2nd (Classic year) on a DEAD turn -- no good training/no rainbow --
        with energy ~70 or lower; the energy-<30 recovery date fits the same Classic window; 4th/5th
        (Senior year) at energy ~60 or lower to spend them efficiently. The game serves the dates in
        order, so this decides the TIMING; year + energy match the user's own "4th/5th in Senior, the
        rest in Classic" grouping. A shared rule (mood floor etc.) still wins first, and every shared
        guard applies -- never on a camp turn, never at rock-bottom energy.
        Tunables: grand_live_date_energy_classic (70), _senior (60), _critical (30), _dead_score (0.3).
        """
        if super()._should_recreate(recreation, preset, turn, motivation, vital, best_score):
            return True
        if not (preset or {}).get("grand_live_light_hello", True):
            return False
        if not (recreation and self.has_light_hello(getattr(self, "_chara", None) or {})):
            return False
        p = preset or {}
        # "Dead board" = no rainbow / nothing worth training. The default 0.3 is in BASE-scorer units,
        # but this scenario's _score_command adds presence*CARD_PRESENCE_WEIGHT (1.5 per deck card on
        # the facility) and bonus*TRAINING_BONUS_WEIGHT on top -- so a facility holding a single deck
        # card already scores >=1.5, five times the threshold, and `dead` was effectively NEVER true.
        # Every branch below hung off it, so no Light Hello date ever fired: observed live with the card
        # in-deck and the friendship gauge MAXED, all five Event Progress chevrons still empty after a
        # full 76-turn career (career_log_20260801_000546: 1 recreation in 76 turns, and that one came
        # from the shared mood rule above, not from here).
        #
        # The RULE is right -- a good board should train, not date -- only the NUMBER was wrong, so the
        # default is rescaled to this scenario's units rather than dropped. 3.0 is about two deck cards'
        # worth of presence: below it the best facility is thin enough that a date is the better turn,
        # above it there is real training to do (the shared tests treat 0.0 as dead and 5.0 as a good
        # board, and this separates them). Tune with grand_live_date_dead_score.
        dead = (best_score or 0) <= float(p.get("grand_live_date_dead_score", 3.0))
        # Energy-critical recovery on a bad turn, any year (the user's "energy below 30" date).
        if dead and vital < int(p.get("grand_live_date_energy_critical", 30)):
            return True
        if not dead:
            return False
        # No date-NUMBER tracking needed: the game serves Light Hello's dates in order, so gating the
        # WINDOW by year does the pacing -- dates 1-3 land in Classic, 4-5 in Senior (the user's own
        # split: "1st until 3rd around Classic, 4-5 at Senior").
        if turn >= 49:                                     # Senior year -> dates 4-5
            return vital <= int(p.get("grand_live_date_energy_senior", 60))
        if turn >= 25:                                     # Classic year -> dates 1-3
            return vital <= int(p.get("grand_live_date_energy_classic", 70))
        return False                                       # Junior: hold dates for Classic on

    # playing_state while the game sits on the Concert screen awaiting live_start.
    CONCERT_PLAYING_STATE = 10

    @classmethod
    def concert_turn(cls, data):
        """The turn of the concert currently ON SCREEN, for a state that doesn't carry one.

        A RESUMED career parked on the Concert screen reports chara_info.turn as 0. That blocks
        everything: master_square and live_start both take current_turn, and live_start{current_turn:0}
        is exactly what the server 205'd three times in career_log_20260731_035056. With the non-zero
        guard added afterwards the bad call stopped, but the bot then had nothing to do and idled out
        of a live career (career_log_20260731_105832, stuck on "1st Concert").

        The state does carry the turn implicitly: live_data_set.live_result_array holds one entry per
        concert ALREADY performed, and concerts run on fixed turns, so the count indexes straight into
        LIVE_TURNS. Verified across two complete careers in api_library/single_mode_live/load.jsonl:
            live_result 0 -> 24, 1 -> 36, 2 -> 48, 3 -> 60, 4 -> 72   (playing_state 10 every time)
        Requires live_result_array to actually be PRESENT -- an empty/missing live_data_set means "no
        information", not "zero concerts performed", and inventing turn 24 from nothing is how a
        turn-0 live_start gets sent all over again. Every one of the 82 Concert-screen captures in
        api_library carries the key, so demanding it costs nothing real.

        Returns 0 for unknown, and for "all five already done", so callers keep their no-turn path.
        """
        lds = (data or {}).get("live_data_set")
        if not isinstance(lds, dict) or "live_result_array" not in lds:
            return 0
        performed = len(lds.get("live_result_array") or [])
        return cls.LIVE_TURNS[performed] if 0 <= performed < len(cls.LIVE_TURNS) else 0

    @staticmethod
    def _live_event_id(data):
        """The pending Concert event id for live_start. Comes from the state's unchecked event queue
        (capture: live_start{event_id: 202006, current_turn: 24}); 0 when the game hasn't queued one."""
        for ev in ((data or {}).get("unchecked_event_array") or []):
            eid = int((ev or {}).get("event_id") or 0)
            if eid:
                return eid
        return 0

    # --- Grand Live helpers -----------------------------------------------------------------------
    def _idle_live_tried(self):
        tried = getattr(self, "_grand_live_idle_tried", None)
        if tried is None:
            tried = self._grand_live_idle_tried = set()
        return tried

    def _live_done(self):
        done = getattr(self, "_grand_live_done", None)
        if done is None:
            done = self._grand_live_done = set()
        return done

    def _tried_offers(self):
        tried = getattr(self, "_grand_live_offers", None)
        if tried is None:
            tried = self._grand_live_offers = set()
        return tried

    def _claimed_offers(self):
        """{(offer, turn)} of claims the server accepted -- see mark_decision_handled."""
        claimed = getattr(self, "_grand_live_claimed", None)
        if claimed is None:
            claimed = self._grand_live_claimed = set()
        return claimed

    def _offer_open(self, offer, turn):
        """May this board be claimed now: never rejected, and not already claimed on this turn."""
        tried = self._tried_offers()
        return (bool(offer) and offer not in tried and (offer, int(turn or 0)) not in self._claimed_offers()
                and len(tried) + len(self._claimed_offers()) < self.MAX_SQUARE_CLAIMS)

    def mark_decision_handled(self, decision, accepted=False):
        """Commit the once-only guard after the server handled a Grand Live action.

        Decisions are intentionally side-effect free: a network/SID failure before the API accepts
        the request must be retryable. The runner calls this immediately after the core call succeeds
        (before event draining), and also for authoritative 102 / master-square 205 rejections so an
        unchanged invalid offer cannot form a retry storm.
        """
        payload = getattr(decision, "payload", None) or {}
        action = getattr(decision, "action", "")
        if action == "master_square":
            offer = payload.get("_offer_key")
            if offer:
                # JSON-like test data may turn tuples into lists; keep the same hashable shape as
                # _offer_key() so the next strategy pass recognises the handled board.
                offer = tuple(tuple(int(v) for v in row) for row in offer)
                if accepted:
                    # A claim the server ACCEPTED blocks this board only for this turn. Live 2026-10-31
                    # (career_log_20261031_001644): after an accepted claim at turn 59 the board kept the
                    # same three squares through turn 72, so blocking the offer for good bought nothing
                    # more while ~430 points piled up. A later turn tries once more; a 205/102 on that
                    # retry (accepted=False) blocks it for good, so at most one wasted request.
                    self._claimed_offers().add((offer, int(payload.get("current_turn") or 0)))
                else:
                    self._tried_offers().add(offer)
            return
        if action == "grand_live_perform":
            turn = int(payload.get("current_turn") or 0)
            if turn:
                self._live_done().add(turn)
                self._idle_live_tried().add(turn)

    @staticmethod
    def _offer_key(live_data_set):
        """Identity of the CURRENT board choice: the offered squares in order. Stays the same while the
        board hasn't advanced, and changes once it has -- which is exactly when a new claim is allowed."""
        squares = (live_data_set or {}).get("next_square_info_array") or []
        return tuple((int(s.get("square_id") or 0), int(s.get("square_num") or 0)) for s in squares) or None

    # Square rewards, keyed by master_bonus_gain_type (data/grand_live_squares.json, generated from
    # master.mdb). gain_type 1 = a STAT gain where gain[0] is the stat id and gain[2] the amount:
    #   1 Speed  2 Stamina  3 Power  4 Guts  5 Wit  6 SP
    # gain_type 2 = skill hint, 3 = energy recovery, 5 = song/live bonus.
    STAT_ID = {1: "speed", 2: "stamina", 3: "power", 4: "guts", 5: "wit", 6: "sp"}

    # User priority, highest first: SP bonus > Speed > training effectiveness (skill hints) > Wit.
    # Everything else still scores (claiming any affordable square beats claiming none), just lower.
    # Override per preset with "grand_live_reward_priority": {"sp": 120, ...}.
    REWARD_PRIORITY = {"sp": 100, "speed": 80, "hint": 60, "wit": 40,
                       "power": 25, "stamina": 25, "guts": 25, "energy": 20, "song": 70}

    @staticmethod
    def _squares_data():
        """{square_id: {cost, gain_type, gain}} from data/grand_live_squares.json (generated from
        master.mdb). Cached on the class; missing file -> {} so ranking degrades to offer order."""
        cache = getattr(GrandLiveStrategy, "_SQUARES_CACHE", None)
        if cache is None:
            import json, os
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "data", "grand_live_squares.json")
            try:
                with open(os.path.abspath(path), encoding="utf-8") as f:
                    cache = (json.load(f) or {}).get("squares") or {}
            except Exception:
                cache = {}
            GrandLiveStrategy._SQUARES_CACHE = cache
        return cache

    @classmethod
    def can_afford(cls, square_id, performance):
        """A square COSTS performance points (single_mode_live_square.perf_type/perf_value -- verified
        against the in-game panel: Makeup Basics = Visual 10, Vocal Training = Vocal 10). Claiming one
        you cannot pay for is what the server answers with 205, so never offer it as a candidate.
        Unknown square (not in the generated data) -> assume affordable rather than block progress."""
        info = cls._squares_data().get(str(int(square_id or 0)))
        if not info:
            return True
        for perf_type, need in (info.get("cost") or {}).items():
            if int((performance or {}).get(perf_type) or 0) < int(need or 0):
                return False
        return True

    @classmethod
    def square_cost(cls, square_id):
        """Total performance points a square costs (sum across the five types)."""
        info = cls._squares_data().get(str(int(square_id or 0)))
        return sum(int(v or 0) for v in ((info or {}).get("cost") or {}).values())

    @classmethod
    def efficiency(cls, square_id, cfg=None, preset=None, songs=True):
        """VALUE PER POINT SPENT -- the thing to maximise when the currency is finite.

        Performance points are earned slowly from training and every square costs 10-35 of them, so
        ranking on reward alone overpays: a 35-point square paying +5 Guts loses to a 10-point square
        paying the same. Dividing by cost makes the bot buy more total value per career. An unpriced
        square (absent from the generated data) falls back to raw reward so it is never mis-ranked to
        the bottom. Disable with grand_live_cost_efficiency: false to rank on raw reward.
        """
        reward = cls.reward_score(square_id, cfg, songs)
        if not (preset or {}).get("grand_live_cost_efficiency", True):
            return reward
        cost = cls.square_cost(square_id)
        return reward / cost if cost > 0 else reward

    @classmethod
    def reward_score(cls, square_id, cfg=None, songs=True):
        """Rank a square by WHAT IT PAYS, using the user's priority order."""
        sid = int(square_id or 0)
        pri = {**cls.REWARD_PRIORITY, **(cfg or {})}
        # SONG squares are scored by their guide TIER first -- they carry assorted master_bonus
        # gain_types (1 and 5 both appear), so dispatching on gain_type let some songs fall through to
        # raw-stat scoring and out-rank a High-tier song. The tier is what the Concert Bonus is worth.
        # songs=False: after the last concert a song's concert bonus never applies, so it is worth only
        # what it pays at once (a stat song's +22; an SP/friendship song nothing).
        if songs and sid in cls.SONG_SQUARE_SCORE:
            return float(cls.SONG_SQUARE_SCORE[sid])
        info = cls._squares_data().get(str(sid))
        if not info:
            return 0.0
        gt, gain = info.get("gain_type"), info.get("gain") or []
        if gt == 1:                                     # stat gain: gain[0]=stat id, gain[2]=amount
            stat = cls.STAT_ID.get(gain[0] if gain else 0, "")
            amount = float(gain[2] or 0) if len(gain) > 2 else 0.0
            return float(pri.get(stat, 10)) + amount    # amount breaks ties within a stat
        if gt == 2:
            return float(pri.get("hint", 0))
        if gt == 3:
            return float(pri.get("energy", 0))
        if gt == 5:
            return float(pri.get("song", 0)) if songs else 0.0
        return 0.0

    # Songs at or above this score are worth banking points for (SP-bonus and friendship bands).
    # Below it the payoff is too small to justify skipping a turn's purchase.
    HOLD_FOR_SONG_MIN_SCORE = 150
    # Give up after this many consecutive holds on the SAME offer. A Speed/Wit deck structurally
    # cannot generate vocal on its own (Speed rolls dance/visual, Wit rolls mental/passion) -- it
    # arrives via friendship trainings and Light Hello, both of which are chance-based. Without a
    # bound, a vocal-heavy song could park the shop for the rest of the career.
    HOLD_FOR_SONG_MAX_TURNS = 12

    def _hold_for_song(self, offered, performance, preset=None):
        """True when points should be BANKED this turn instead of spent.

        Fires only when an important song is on the board and is not yet affordable. The board keeps
        the same pending offer until it advances, so the points really do accumulate toward it rather
        than being lost to a cheap technique. Bounded by HOLD_FOR_SONG_MAX_TURNS and disabled with
        grand_live_hold_for_song: false.
        """
        p = preset or {}
        if not p.get("grand_live_hold_for_song", True):
            return False
        floor = float(p.get("grand_live_hold_song_min_score", self.HOLD_FOR_SONG_MIN_SCORE))
        wanted = [sid for sid in offered
                  if self.SONG_SQUARE_SCORE.get(sid, 0) >= floor and not self.can_afford(sid, performance)]
        held = getattr(self, "_song_hold_counts", None)
        if held is None:
            held = self._song_hold_counts = {}
        seen = getattr(self, "_song_hold_turns", None)      # target -> last turn already counted
        if seen is None:
            seen = self._song_hold_turns = {}
        if not wanted:
            for sid in list(held):          # offer changed / now affordable -> reset its counter
                if sid not in offered:
                    held.pop(sid, None)
                    seen.pop(sid, None)
            return False
        cap = int(p.get("grand_live_hold_song_max_turns", self.HOLD_FOR_SONG_MAX_TURNS))
        target = max(wanted, key=lambda sid: self.SONG_SQUARE_SCORE.get(sid, 0))
        # Count TURNS, not calls: the runner asks next_decision twice per command turn and each pass can
        # reach pick_square twice, so a per-call count spent the 12-turn cap in ~6 turns. An unknown
        # turn (0) still counts per call so the hold stays bounded.
        turn = int(getattr(self, "_last_turn", 0) or 0)
        if not turn or seen.get(target) != turn:
            seen[target] = turn
            held[target] = held.get(target, 0) + 1
        return held[target] <= cap

    def pick_square(self, live_data_set, preset=None, performance=None):
        """Which Master Square to claim, or 0 when none are offered/affordable.

        Two filters, in order:
          1. AFFORDABLE -- a square costs performance points; an unaffordable claim is answered 205.
          2. BEST REWARD -- ranked by REWARD_PRIORITY (SP > Speed > skill hint > Wit), then by the
             family score (song squares carry a career-long bonus), then the game's own offer order.
        """
        perf = performance if performance is not None else (live_data_set or {}).get("live_performance_info") or {}
        cfg = ((preset or {}).get("grand_live_square_priority") or {})
        rcfg = dict((preset or {}).get("grand_live_reward_priority") or {})
        # Skill-hint lessons get no priority in Senior year (still claimed if nothing else is
        # affordable, so the board keeps moving).
        turn = int(getattr(self, "_last_turn", 0) or 0)
        after_finale = turn > self.LIVE_TURNS[-1]
        if turn >= SENIOR_START_TURN:
            rcfg.setdefault("hint", 0.0)
        # Chase SONGS while short of the turn-72 target: 20 songs maxes the expectation gauge and
        # unlocks the TRUE (special-hype) finale, which is worth more than any single stat square.
        # Once the target is met songs drop back to their normal rank. Off via grand_live_chase_songs.
        chasing_songs = False
        if (preset or {}).get("grand_live_chase_songs", True) and not after_finale:
            chasing_songs = bool(self.song_shortfall({"live_data_set": live_data_set}, preset))
            if chasing_songs and "song" not in rcfg:
                rcfg["song"] = float((preset or {}).get("grand_live_song_priority", 150))
        # A song owed for the NEXT concert is MANDATORY, not an optimisation: three songs before each
        # concert is +10 to ALL stats versus +3, and a missed quota can't be bought back later. Songs
        # cost ~42 points, so on pure value-per-point they lose to a 10-point stat square -- which would
        # silently forfeit the Great Success. So while short, songs are chosen FIRST (most efficient
        # song among them); everything else is ranked on efficiency.
        offered = [int(sq.get("square_id") or 0) for sq in
                   ((live_data_set or {}).get("next_square_info_array") or [])]
        offered = [sid for sid in offered if sid]
        affordable = [sid for sid in offered if self.can_afford(sid, perf)]
        # SAVE UP for an important song. If a high-band song is on the board but not yet affordable,
        # claim NOTHING this turn: the points spent on a cheap technique are points that will not be
        # there when the song is reachable, and the board keeps the same offer until it advances, so
        # waiting really does bank them. Only worth doing for the bands that pay all career (SP bonus
        # and friendship) -- holding for a chain-event song would cost more than it returns.
        # Never while the next concert is still short of songs: a hold freezes the whole board, so no
        # other song can come up either (career 1509 held turns 48-58 for one song, learned 2 for the
        # turn-60 concert and lost its Great Success).
        if not (chasing_songs or after_finale) and self._hold_for_song(offered, perf, preset):
            return 0
        if not affordable:
            return 0
        if chasing_songs:
            songs = [sid for sid in affordable if str(sid).startswith("40")]
            if songs:
                return max(songs, key=lambda sid: (self.efficiency(sid, rcfg, preset),
                                                   self.square_score(sid, cfg)))
        return max(affordable, key=lambda sid: (self.efficiency(sid, rcfg, preset, songs=not after_finale),
                                                self.square_score(sid, cfg)))

    # Family score (tie-break under reward_score): song squares carry a career-long bonus, so they
    # outrank one-off lesson/energy squares when the reward priority ties.
    SQUARE_PRIORITY = {40: 100, 30: 40, 20: 50, 13: 20, 12: 20, 11: 20}

    # Per-SONG priority, from uma.guide/guides/grand-concert's own tiering (High / Great Value /
    # Good Value / Low). Ranked on the CONCERT BONUS the song leaves behind, not its live_bonus_value --
    # the raw value scored Believe in Miracles! and Run for Our Dream! at the bottom even though the
    # guide calls both High. Names mapped to square ids via master.mdb single_mode_live_song_list.
    SONG_TIER = {"high": 100, "great": 75, "good": 50, "low": 20}
    # SONG RANKING -- ordered by the effect band, not by a general "value" tier. The user's rule:
    #
    #     1. SP BONUS            always first (it multiplies through every later training)
    #     2. FRIENDSHIP BONUS    +10% ahead of +5%
    #     3. SPECIALTY PRIORITY
    #     4. SUPPORT CHAIN EVENT
    #
    # Each song carries a CONCERT bonus (applied from the next live onward) and a MASTERY bonus
    # (immediate). The band below is whichever of the two is the ranked effect; the trailing comment
    # keeps both so a song can be re-banded without re-deriving it. Within a band the numbers only
    # break ties, ordered by how much the mastery payload suits a Speed/Wit build.
    _SP_BONUS, _FRIENDSHIP_10, _FRIENDSHIP_5, _SPECIALTY, _CHAIN = 200, 160, 150, 100, 50
    SONG_SQUARE_SCORE = {
        # -- 1. SP BONUS: the only band that raises skill points on EVERY training, so it leads.
        40004: _SP_BONUS + 3,    # Grow Up and Shine!         SP Bonus +3   [chain +1]
        40000: _SP_BONUS + 2,    # Run for Our Dream!         SP Bonus +2   [spec priority +5]
        # -- 2. FRIENDSHIP BONUS: compounds into every friendship training for the rest of the run.
        40019: _FRIENDSHIP_10 + 2,   # My Favourite Treasure Box  Friendship +10%  (Speed +26)
        40018: _FRIENDSHIP_10,       # Fanfare for the Future!    Friendship +10%  (Guts +26)
        40003: _FRIENDSHIP_5 + 4,    # RUNxRUN                    Friendship +5%   (Skill Points +22)
        40002: _FRIENDSHIP_5 + 3,    # Full Speed Ahead! Umadol   Friendship +5%   (Speed +22)
        40015: _FRIENDSHIP_5 + 2,    # Dream Sky                  Friendship +5%   (Wit +22)
        40001: _FRIENDSHIP_5 + 1,    # Here Comes Our Time        Friendship +5%   (Power +22)
        40016: _FRIENDSHIP_5 + 1,    # Present March              Friendship +5%   (Power +22)
        40012: _FRIENDSHIP_5,        # The World's at Our Whim    Friendship +5%   (Stamina +22)
        40014: _FRIENDSHIP_5,        # Sky-Blue Spring            Friendship +5%   (Guts +22)
        # -- 3. SPECIALTY PRIORITY: more taps land on deck facilities -> more friendship trainings.
        40011: _SPECIALTY + 3,   # Our Blue Bird Days         Spec Priority +5  (Speed Training +2)
        40007: _SPECIALTY + 2,   # Believe in Miracles!       Spec Priority +5  (Wit Training +1)
        40008: _SPECIALTY + 1,   # Seven Colors Scenery       Spec Priority +5  (Power Training +2)
        40013: _SPECIALTY,       # A-NO-NE                    Spec Priority +5  (Guts Training +2)
        40017: _SPECIALTY,       # Hoppity Sunny Days         Spec Priority +5  (Stamina Training +2)
        # -- 4. SUPPORT CHAIN EVENT: useful, but the chain usually completes on its own.
        40005: _CHAIN + 3,       # Sunbeam Cheer              Support Chain +1  (Wit Training +2)
        40020: _CHAIN + 2,       # Zero Is Where the Center   Support Chain +1  (Speed Training +1)
        40006: _CHAIN + 1,       # Go This Way                Support Chain +1  (Power Training +1)
        40010: _CHAIN,           # Ring Ring Diary            Support Chain +1  (Stamina Training +1)
        40009: _CHAIN,           # Run Away! Fallin' Love     Support Chain +1  (Guts Training +1)
        # -- AWARDED, never bought (cost 0): Make Debut! (t4) and GIRLS' LEGEND U (Senior Early Dec,
        #    which needs 18+ songs held -- one reason the t72 target sits at 19).
        40091: 0, 40092: 0,
    }

    @classmethod
    def square_score(cls, square_id, cfg=None):
        """Rank a single square. Song squares add their per-song score on top of the family score."""
        sid = int(square_id or 0)
        prefix = int(str(sid)[:2]) if sid >= 10000 else 0
        cfg = cfg or {}
        base = cfg.get(str(prefix), cfg.get(prefix, cls.SQUARE_PRIORITY.get(prefix, 0)))
        return float(base) + float(cls.SONG_SQUARE_SCORE.get(sid, 0))

    @staticmethod
    def performance_info(state):
        """The five Grand Live performance stats (dance/passion/vocal/visual/mental) + their caps."""
        return (((state or {}).get("data") or {}).get("live_data_set") or {}).get("live_performance_info") or {}
