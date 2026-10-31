from pathlib import Path

from career_bot.core.data_store import DataStore


class RacePlanner:
    def __init__(self, base_dir, data_store=None):
        self.base_dir = Path(base_dir)
        # Shared reference-data access. Falls back to a private store when constructed
        # standalone (tests, scripts); the runner injects one shared DataStore.
        self.data_store = data_store or DataStore(base_dir)
        self.meta = {}
        self.program = {}
        self.instance = {}
        self.rejected = set()
        self.rerun_program = 0   # a lost MAIDEN (Make Debut / Maiden Race) to re-race every turn until
                                 # the trainee's first win; 0 = none. Armed in runner._race, consumed by
                                 # training_brain._forced_maiden_program, cleared on the first rank-1.
        # Per-scenario race policy, bound by BaseTrainingStrategy.__init__ from the scenario class's
        # RACE_POLICY (career_bot/scenarios/*.py). Unbound (tests/standalone) = neutral defaults, which
        # match the old behavior for a state with no scenario_id. Core holds NO scenario knowledge.
        self.policy = {}
        self._load()

    def _load(self):
        # meta/program/instance stay int-keyed public attributes so callers (and tests that
        # inject `planner.program = {...}`) are unchanged; only the source moved to DataStore.
        data = self.data_store.race_map()
        self.meta = {int(k): v for k, v in (data.get("meta") or {}).items()}
        self.program = {int(k): v for k, v in (data.get("program") or {}).items()}
        self.instance = {int(k): [int(item) for item in v] for k, v in (data.get("instance") or {}).items()}

    def get_rival_race_map(self, state):
        rivals = (
            state.get("data", {})
            .get("free_data_set", {})
            .get("rival_race_info_array", [])
        )
        return {
            int(r["program_id"]): int(r["chara_id"])
            for r in rivals
            if "program_id" in r and "chara_id" in r
        }

    @staticmethod
    def _use_schedule(preset):
        """Whether to run the preset's extra_race_list in a goal-races-only scenario (URA/Unity), ON TOP
        of the mandatory career goals (opening the forced/optional-race gates so they actually run).
        The explicit 'use_race_schedule' toggle wins in BOTH directions; when it's UNSET, default to ON
        if the preset actually HAS a schedule -- a populated extra_race_list means the user built one to
        run it, so it shouldn't sit silently ignored behind a separate opt-in they forget to flip. Set
        use_race_schedule:false to keep a saved schedule but NOT run it. No effect on MANT (no
        goal_races_only policy, so it always uses the schedule)."""
        p = preset or {}
        v = p.get("use_race_schedule")
        if v is not None:
            return bool(v)
        return bool(p.get("extra_race_list"))

    def wanted_programs(self, preset, turn=None, chara=None):
        result = []
        seen = set()
        current_turn = int(turn or 0)
        # goal_races_only (URA/Unity set it): the trainee's CAREER GOALS *are* the schedule. The
        # preset's extra_race_list is a free-race concept, so it is IGNORED here -- the career races
        # exactly its goal route (+ the game's forced races) and nothing off-schedule. Scenarios
        # without the flag (MANT, unbound planners) keep the user's extra_race_list below.
        if chara is not None and self.policy.get("goal_races_only", False):
            for g in self._goals(chara):
                if g.get("kind") != "race":
                    continue
                if current_turn and int(g.get("turn") or 0) != current_turn:
                    continue
                pid = int(g.get("program_id") or 0)
                if pid and pid not in seen:
                    seen.add(pid)
                    result.append(pid)
            # Career goals ARE the schedule by default. Only when the user opts in via the preset toggle
            # 'use_race_schedule' do we ALSO honor the preset's extra_race_list below -- goals stay
            # mandatory, so it's additive (deduped via `seen`). Off -> goals only (return here).
            if not self._use_schedule(preset):
                return result
        for value in preset.get("extra_race_list") or []:
            try:
                race_id = int(value)
            except (TypeError, ValueError):
                continue
            
            pids = []
            if race_id in self.meta:
                info = self.meta[race_id]
                occurrence_turn = int(info.get("turn") or 0)
                if current_turn and occurrence_turn and occurrence_turn != current_turn:
                    continue
                pid = info.get("program_id")
                if pid:
                    pids.append(pid)
            elif race_id in self.program:
                pids.append(race_id)
            else:
                for program_id in self.instance.get(race_id, []):
                    pids.append(program_id)
            
            for pid in pids:
                if pid not in seen:
                    seen.add(pid)
                    result.append(pid)
        return result

    def available_programs(self, state):
        data = state.get("data") or {}
        rca = data.get("race_condition_array") or []
        available = set()
        for item in rca:
            pid = int(item.get("program_id") or 0)
            if pid:
                available.add(pid)
        return available

    def forced_program(self, state, preset=None):
        data = state.get("data") or {}
        # NOTE: the lost-maiden re-run (incl. the Make Debut) is no longer forced here. It's consumed
        # in the strategy AFTER the goal/fan-race gate (training_brain._forced_maiden_program) so a
        # mandatory goal/fan race is never preempted by a maiden re-race -- see is_maiden_program /
        # apt_maiden_program and the arm in runner._race.
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        race_enabled = any(cmd.get("command_type") == 4 and cmd.get("command_id") == 401 and cmd.get("is_enable", 0) for cmd in commands)
        other_enabled = any(cmd.get("command_type") != 4 and cmd.get("is_enable", 0) for cmd in commands)
        if not race_enabled or other_enabled:
            return 0
        # A user-SCHEDULED race is authoritative on a forced race turn: if any race in the preset's
        # extra_race_list is on offer, run THAT instead of the game's default first-listed race
        # (fixes e.g. running Oka Sho when Satsuki Sho -- same turn -- was scheduled). Falls back to
        # the game's order only when nothing scheduled is offered. Scenarios with NO user schedule
        # (Unity: fixed mandatory goal races) switch this off via scheduled_override=False -- unless the
        # user opts into the schedule (use_race_schedule), which re-opens it.
        if preset is not None and (self.policy.get("scheduled_override", True) or self._use_schedule(preset)):
            available = self.available_programs(state)
            turn = int((data.get("chara_info") or {}).get("turn") or 0)
            for pid in self.wanted_programs(preset, turn, data.get("chara_info")):
                if pid in available and (turn, pid) not in self.rejected:
                    return pid
        # Forced race turn with nothing scheduled on offer: racing IS mandatory here, but pick one the
        # trainee can actually RUN instead of whatever the game happened to list first. Taking the
        # first entry blindly put a turf-A / dirt-D Oguri Cap into FIVE dirt races a career (Nambu Hai,
        # Kawasaki Kinen, February S., Kashiwa Kinen) that were never on her schedule.
        # Respect the rejected set -- a race that already 205'd (e.g. a Unity team race that can't be
        # entered via race_entry) must NOT be re-offered, or the runner loops race_entry->205.
        fp_turn = int((data.get("chara_info") or {}).get("turn") or 0)
        fp_chara = data.get("chara_info") or {}
        offered = [int(i.get("program_id") or 0) for i in (data.get("race_condition_array") or [])]
        offered = [p for p in offered if p and (fp_turn, p) not in self.rejected]
        if offered:
            floor = self.FAN_RACE_MIN_GRADE
            runnable = [p for p in offered if min(self._apt_grades(fp_chara, p)) >= floor]
            # best combined aptitude among the ones she can run; else the game's first (still mandatory)
            return max(runnable, key=lambda p: sum(self._apt_grades(fp_chara, p))) if runnable else offered[0]
        # Forced race turn where the game lists NOTHING: Grand Live (scenario 3) omits
        # race_condition_array entirely on a race day and sends no race_start_info -- the live client
        # knows the program from the career route, not from the state. Without this the bot found no
        # race AND no enabled training, returned "idle", and the career stalled dead on Race Day
        # (career_log_20260723_094646, turn 31 "Place top 3 in Fukuryu S."). So fall back to THIS
        # trainee's career-goal race for the turn, offered or not -- the game is forcing it anyway.
        for g in self._goals(fp_chara):
            if g.get("kind") != "race" or int(g.get("turn") or 0) != fp_turn:
                continue
            for candidate in (g.get("program_ids") or [g.get("program_id")]):
                pid = int(candidate or 0)
                if pid and (fp_turn, pid) not in self.rejected:
                    return pid
        race = data.get("race_start_info") or {}
        pid = int(race.get("program_id") or 0)
        return pid if pid and (fp_turn, pid) not in self.rejected else 0

    def _apt_grades(self, chara, program_id):
        """(ground_aptitude, distance_aptitude) grades (1..8) for this trainee on a program's
        surface + distance band. Shared by check_aptitude and the debut aptitude picker."""
        info = self.program.get(int(program_id or 0)) or {}
        ground = int(info.get("ground") or 1)
        distance = int(info.get("distance") or 1200)
        g_apt = int(chara.get("proper_ground_dirt") or 1) if ground == 2 else int(chara.get("proper_ground_turf") or 1)
        if distance <= 1400:
            d_apt = int(chara.get("proper_distance_short") or 1)
        elif distance <= 1800:
            d_apt = int(chara.get("proper_distance_mile") or 1)
        elif distance <= 2400:
            d_apt = int(chara.get("proper_distance_middle") or 1)
        else:
            d_apt = int(chara.get("proper_distance_long") or 1)
        return g_apt, d_apt

    def check_aptitude(self, chara, program_id):
        g_apt, d_apt = self._apt_grades(chara, program_id)
        return g_apt >= 6 and d_apt >= 6

    def is_maiden_program(self, program_id):
        """True for a maiden/debut race -- the Junior 'Make Debut' and the Junior/Classic 'Maiden
        Race's. These are the ONLY races the game offers while the trainee is still winless, so the
        trainee's first win removes them from the board and ends the force-maiden-until-win re-run.
        Detected by NAME (there is no maiden flag anywhere in the data). Public so the runner's
        arming can share the exact same signal it re-races on."""
        name = str((self.program.get(int(program_id or 0)) or {}).get("name") or "").lower()
        return "make debut" in name or "maiden" in name

    def apt_maiden_program(self, state, chara):
        """When re-running a LOST maiden, the maiden race ON OFFER this turn the trainee is most
        likely to WIN: prefer one that's both ground and distance runnable (>=6), tie-broken by the
        strongest combined aptitude so a mile-A/mile-S trainee re-races a mile, not the sprint it
        keeps losing. If NO runnable maiden is offered, fall back to the best-combined-aptitude
        maiden on the board so a maiden is still entered (force-maiden-until-win must keep racing).
        Returns 0 only when no maiden is offered at all."""
        turn = int((chara or {}).get("turn") or 0)
        best_fit, best_fit_score = 0, -1
        best_any, best_any_score = 0, -1
        for pid in self.available_programs(state):
            if (turn, pid) in self.rejected or not self.is_maiden_program(pid):
                continue
            g_apt, d_apt = self._apt_grades(chara, pid)
            score = g_apt + d_apt
            if score > best_any_score:
                best_any, best_any_score = pid, score
            if g_apt >= 6 and d_apt >= 6 and score > best_fit_score:
                best_fit, best_fit_score = pid, score
        return best_fit or best_any

    # Aptitude grade integer for rank A (scale 1..8: 8=S, 7=A ...). "mile is A" == mile >= 7.
    APTITUDE_A = 7
    # A fan-farm race only needs a RUNNABLE aptitude, not A -- as long as the trainee has at least
    # one of mile/medium at B+, it can run the closer of Asahi/Hopeful. (check_aptitude uses the same
    # >=6 "runnable" bar.)
    FAN_RACE_MIN_GRADE = 6
    # Last turn a Junior fan-count goal can fall on. Such a goal is cleared by the MANDATORY Junior fan
    # race (Asahi/Hopeful/dirt) that fan_goal_program runs at turn 23/24, so it needs no pre-farming.
    JUNIOR_FAN_GOAL_LAST_TURN = 24

    # The three Junior fan G1s, matched by NAME against the master.mdb-generated race data.
    # Name matching, not distance/fan heuristics: those attributes do NOT separate a Junior G1 from a
    # Senior one. Zen-Nippon (dirt 1600, 4,200 fans) shares its band with Musashino (3,800), Unicorn
    # (3,500) and JBC Ladies' Classic (4,100); a turf "mile/medium + high fans" rule accepted 151 of
    # 387 candidates including Japan Cup, Tokyo Yushun and the URA Finals. Names are stable in the
    # generated data and are what fan_goal_program already keys on.
    JUNIOR_FAN_G1_NAMES = ("asahi hai", "hopeful stakes", "zen-nippon junior yushun")

    def _can_run_junior_fan_race(self, chara):
        """True if the trainee can actually run one of the Junior fan G1s (surface AND distance at the
        runnable floor): turf + (mile or medium) -> Asahi/Hopeful, or dirt -> Zen-Nippon Junior Yushun.
        When true, that mandatory race clears the Junior fan-count goal on its own, so the entry-fan
        guard should NOT pre-farm an off-schedule race for it -- just keep training until then."""
        B = self.FAN_RACE_MIN_GRADE
        turf = int((chara or {}).get("proper_ground_turf") or 0)
        dirt = int((chara or {}).get("proper_ground_dirt") or 0)
        mile = int((chara or {}).get("proper_distance_mile") or 0)
        medium = int((chara or {}).get("proper_distance_middle") or 0)
        return (turf >= B and (mile >= B or medium >= B)) or dirt >= B

    def fan_goal_program(self, state, preset=None):
        """MANDATORY Junior fan race. The Junior fan-count goal (~3,000 fans) is a MUST -- a trainee
        that never races FAILS the career (verified live: a mile-C Oguri that only ran its debut died
        at turn 23, "goal failed", because it never raced for fans). So run the Junior fan G1 the
        trainee is best suited to, ON THE SURFACE IT CAN ACTUALLY WIN:
          - turf mile   -> Asahi Hai             (1600m turf) -> turn 23
          - turf medium -> Hopeful Stakes        (2000m turf) -> turn 24
          - DIRT        -> Zen-Nippon Junior Yushun (1600m dirt) -> turn 24
        Surface first: a dirt-specialist (turf aptitude G/F) is routed to the dirt G1, because it cannot
        win a turf race even with endless clocks -- forcing it to Asahi/Hopeful stalled the mandatory
        fan race. Within turf, best fit: turf-A + mile-A -> Asahi; else turf-A + medium-A -> Hopeful
        (mile checked first, so Asahi wins when A at both); no clean turf-A fit -> the stronger runnable
        band (mile ties/higher -> Asahi). NOT gated on an aptitude floor -- even a poorly-suited trainee
        MUST run one for fans;
        and NOT gated on a 'fan' goal existing in career_goals.json (that data is incomplete). Fires
        only on turns 23/24 (the verified offer turns) and only when the race is actually on the board,
        so it can't jump a forecast entry; the caller runs one fan race per career (_fan_raced).
        """
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        if turn not in (23, 24):              # the two December-Junior fan-G1 turns (Asahi 23, Hopeful 24)
            return 0
        # Only run it for a trainee that actually HAS a fan-count goal. This used to be ungated because
        # career_goals.json was incomplete, but the generator now emits goals for all 62 charas (0 with
        # an empty list) and only 20 of them carry a kind='fan' goal -- so the other 42 were burning a
        # Junior turn plus the energy on a race they never needed (reported live: Sakura Bakushin O, whose
        # goals are 11 races + the finale and no fan count, was sent to Asahi Hai).
        # Fail SAFE: a trainee with NO goal data at all keeps the old always-race behaviour, because the
        # failure it guards against is fatal (a winless trainee dies at turn 23 "goal failed").
        goals = self._goals(chara)
        if goals and not any(g.get("kind") == "fan" for g in goals):
            return 0
        # A race the USER SCHEDULED for this turn wins the slot. This gate exists to stop a winless
        # trainee dying at turn 23 -- not to overrule a schedule the user built. Turn 23/24 is the
        # late-December Junior G1 slot, so the scheduled pick is the SAME slot as the aptitude pick
        # (e.g. Hanshin Juvenile Fillies instead of Asahi Hai) and clears the ~3,000-fan goal just as
        # well. Returning the scheduled id rather than 0 is deliberate: the caller runs this result
        # AUTHORITATIVELY (bypassing the train-vs-race gate) and sets _fan_raced, so the fan goal is
        # still guaranteed to be met -- standing down to 0 would let a strong training board skip the
        # race and fail the career, which is the exact failure this gate was written for.
        # Only when the race is actually ON THE BOARD; otherwise fall through to the aptitude pick.
        if preset is not None:
            available = self.available_programs(state)
            for pid in self.wanted_programs(preset, turn, chara):
                if pid in available and (turn, pid) not in self.rejected:
                    return pid
        mile = int(chara.get("proper_distance_mile") or 0)
        medium = int(chara.get("proper_distance_middle") or 0)
        turf = int(chara.get("proper_ground_turf") or 0)
        dirt = int(chara.get("proper_ground_dirt") or 0)
        A = self.APTITUDE_A
        B = self.FAN_RACE_MIN_GRADE
        # Bucket the offered Junior fan-G1s by SURFACE -- each awards enough to clear the ~3,000 goal in
        # one win: turf mile -> Asahi Hai (turn 23, 7,000); turf medium -> Hopeful Stakes (turn 24,
        # 7,000); DIRT -> Zen-Nippon Junior Yushun (turn 24, dirt 1600, 4,200). The old code only ever
        # picked the two TURF G1s, so a dirt-specialist (turf aptitude G/F) got forced onto a turf race
        # it cannot win even with endless clocks -> the mandatory fan race stalled the whole career.
        asahi = hopeful = dirt_g1 = 0
        for pid in self.available_programs(state):
            if (turn, pid) in self.rejected or self._grade_rank(pid) != 0:  # G1 only
                continue
            info = self.program.get(pid) or {}
            distance = int(info.get("distance") or 0)
            name = (info.get("name") or "").lower()
            if int(info.get("ground") or 0) == 2:          # DIRT Junior G1 (Zen-Nippon Junior Yushun)
                if not dirt_g1 or int(info.get("win_fans") or 0) > int((self.program.get(dirt_g1) or {}).get("win_fans") or 0):
                    dirt_g1 = pid
            elif 1401 <= distance <= 1800 and (not asahi or "asahi" in name):
                asahi = pid            # Asahi Hai (mile) -- prefer the named one, else any Junior mile G1
            elif 1801 <= distance <= 2400 and (not hopeful or "hopeful" in name):
                hopeful = pid          # Hopeful Stakes (medium)
        # A dirt-specialist that can't run turf (turf aptitude below the runnable floor B) must be
        # routed to the dirt G1 -- forcing it onto Asahi/Hopeful means the endless-clock retry never
        # wins and the mandatory fan race stalls the career. The lone dirt Junior G1 is on turn 24, so
        # WAIT through turn 23 (never run a turf G1 it will only lose). Versatile / turf umas (turf >= B)
        # skip this and take the higher-fan turf G1s below.
        if turf < B and dirt >= B:
            if turn != 24:
                return 0
            if dirt_g1:
                return dirt_g1                     # Zen-Nippon Junior Yushun (dirt 1600, turn 24)
            # dirt G1 not on the board on the last turn -> the turf G1 is the only mandatory option left
        if not asahi and not hopeful:
            # no turf G1 either -> a dirt G1 on the last turn is the only mandatory option left
            return dirt_g1 if (turn == 24 and dirt_g1) else 0
        # TURF routing: best fit first (turf-A + mile-A -> Asahi; else turf-A + medium-A -> Hopeful,
        # mile checked first so Asahi wins when A at both). No clean turf-A fit -> the fan goal is still
        # MANDATORY, so fall back to the stronger runnable band (mile ties/higher -> Asahi).
        if turf >= A and mile >= A:
            prefer_asahi = True
        elif turf >= A and medium >= A:
            prefer_asahi = False
        else:
            prefer_asahi = (mile >= B) or (medium < B and mile >= medium)
        if prefer_asahi:
            return asahi or (hopeful if turn == 24 else 0)   # missed Asahi -> Hopeful is the last chance
        return hopeful or (asahi if turn == 24 else 0)

    def _goals(self, chara):
        card_id = int((chara or {}).get("card_id") or 0)
        return self.data_store.career_goals_for(card_id // 100) if card_id else []

    # Stamina a trainee needs to FINISH a career-goal race, by the race's distance band. Calibrated to
    # the user's rule of thumb: a sprinter (all-sprint goals, e.g. Bakushin) is already covered by the
    # passive stamina normal training gives, so the 300 floor means the bot never prioritizes Stamina
    # for her; a stayer with a long goal lifts it -- Kikuka Sho (3000m) ~400, Tenno Sho Spring (3200m)
    # ~500. Bands are (distance_upper_bound, stamina_need); tunable.
    STAMINA_NEED_BANDS = ((1400, 300), (1800, 350), (2400, 400), (3000, 400), (99999, 500))

    def stamina_need(self, chara):
        """Peak Stamina the trainee's career-GOAL races demand (max over the goal races' distance
        bands). Stamina is trained ON DEMAND from the goals: a pure sprinter stays at the 300 floor
        (never prioritized), a long-distance goal raises it (Kikuka ~400 / Tenno Spring ~500) so the
        bot trains Stamina only up to what a goal actually needs -- never a flat blanket cap."""
        need = self.STAMINA_NEED_BANDS[0][1]
        for g in self._goals(chara):
            if str(g.get("kind")) != "race":
                continue
            info = self.program.get(int(g.get("program_id") or 0)) or {}
            dist = int(info.get("distance") or 0)
            if not dist:
                continue
            for upper, val in self.STAMINA_NEED_BANDS:
                if dist <= upper:
                    need = max(need, val)
                    break
        return need

    def _is_debut_program(self, program_id):
        """True for a Junior 'Make Debut' race -- the maiden/debut logic owns those, so the fan-gate
        farmer must never grab one."""
        name = str((self.program.get(int(program_id or 0)) or {}).get("name") or "").lower()
        return "make debut" in name

    def entry_fans(self, program_id):
        """Fans required to ENTER a program (0 = no gate). This is the wall that killed a live career:
        Copano Rickey's turn-47 goal (Champions Cup) needs 12,000 and she sat on 11,196 for 7 turns."""
        info = self.program.get(int(program_id or 0)) or {}
        return max(0, int(info.get("entry_fans") or 0))

    def next_goal_entry_requirement(self, state):
        """Fan shortfall for the next FUTURE goal, or {} when nothing is short.

        TWO kinds of fan wall, both fatal if missed and neither reachable by training:
          - kind 'fan'  -> the goal IS a fan count ("5,000 fans by turn 28"). 16 charas have one above
            the Junior 3,000 race; T.M. Opera O (Alt) failed three live careers on hers, once by 144.
          - kind 'race' -> the goal race needs entry_fans just to ENTER (Arima Kinen wants 25,000;
            Champions Cup 12,000) -- Copano Rickey died 804 short of hers.

        The current turn's goal is excluded (farming must happen BEFORE the deadline). Stops at the
        first future goal: if that one is already clear, its winnings feed every later wall."""
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        current_turn = int(chara.get("turn") or 0)
        current_fans = int(chara.get("fans") or 0)
        for goal in sorted(self._goals(chara), key=lambda g: int(g.get("turn") or 0)):
            goal_turn = int(goal.get("turn") or 0)
            if goal_turn <= current_turn:
                continue
            kind = goal.get("kind")
            if kind == "fan":
                required = int(goal.get("fans") or 0)
                program_id = 0
                # Junior fan-count goal (~3,000 by turn 24): the MANDATORY Junior fan race (Asahi/
                # Hopeful, or the dirt Zen-Nippon) that fan_goal_program runs at turn 23/24 clears it on
                # its own -- Asahi/Hopeful pay 7,000, the dirt G1 4,200. So don't pre-farm an
                # off-schedule race (a turf-A Oguri was sent to Niigata Junior Stakes at turn 16 purely
                # to top up a goal her turn-23 Asahi Hai would have cleared anyway). Keep TRAINING until
                # that race -- provided she can actually run one; if she matches no fan-race surface,
                # fall through and farm as the last resort.
                if goal_turn <= self.JUNIOR_FAN_GOAL_LAST_TURN and self._can_run_junior_fan_race(chara):
                    continue
            elif kind == "race":
                program_id = int(goal.get("program_id") or 0)
                if not program_id:
                    continue
                required = self.entry_fans(program_id)
            else:
                continue                      # finale / unknown -> no fan wall to clear
            if required > current_fans:
                return {"turn": goal_turn, "kind": kind, "program_id": program_id,
                        "entry_fans": required, "needed": required,
                        "short_by": required - current_fans}
            return {}                         # nearest fan wall already cleared
        return {}

    def junior_fan_g1_programs(self, state):
        """The Junior fan G1s currently on the board: Asahi Hai (turf mile), Hopeful Stakes (turf
        medium) and Zen-Nippon Junior Yushun (dirt). Detected structurally -- G1 grade, then surface
        and distance band -- the same way fan_goal_program routes them, so no ids are hardcoded.

        Used to keep the Junior-year fan farm ON these three races. Racing anything else in Junior
        just to top up a fan wall wastes turns on a race that pays far less: the turf pair award
        7,000 and the dirt G1 4,200, against ~1,000-2,000 for the ordinary Junior races the general
        picker was reaching for (Saudi Arabia Royal Cup, Artemis Stakes).
        """
        out = set()
        for pid in self.available_programs(state):
            name = ((self.program.get(pid) or {}).get("name") or "").lower()
            if any(key in name for key in self.JUNIOR_FAN_G1_NAMES):
                out.add(pid)
        return out

    def eligibility_fan_program(self, state, window=None):
        """Race to earn the fans needed to ENTER an upcoming goal race (or 0).

        HARD RULE: only a race the trainee can ACTUALLY RUN -- both the surface (turf/dirt) and the
        distance band must clear the runnable floor. Without that it grabs whatever is enterable and
        you get a dirt miler entered in a 3600m turf stayer race. Aptitude is a filter, never a
        tie-break. Among runnable+enterable races the biggest win_fans wins (closes the gap fastest).

        Only fires CLOSE to the deadline (fan_farm_window turns) so it can't race the whole career."""
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        current_fans = int(chara.get("fans") or 0)
        requirement = self.next_goal_entry_requirement(state)
        if turn <= 12 or not requirement or turn >= int(requirement.get("turn") or 0):
            return 0
        window = int(window or self.policy.get("fan_farm_window") or 8)   # preset wins, then policy
        if int(requirement.get("turn") or 0) - turn > window:
            return 0   # deadline still far off -> keep training

        floor = self.FAN_RACE_MIN_GRADE
        # JUNIOR YEAR: farm ONLY the Junior fan G1s (Asahi Hai / Hopeful Stakes / Zen-Nippon Junior
        # Yushun). The general picker below ranks on win_fans among everything runnable, which in
        # Junior reached for ordinary races paying ~1-2k -- live: a turn-25 Shinzan Kinen entry wall
        # sent Silence Suzuka to Saudi Arabia Royal Cup (t19) and Artemis Stakes (t20), neither of
        # which is a goal or on any schedule. The three fan G1s pay 7,000 / 7,000 / 4,200 and are the
        # races the Junior fan plan is built around, so they are the only ones worth a Junior turn.
        # SENIOR walls (Arima Kinen 25,000, Champions Cup 12,000) still use the general picker -- the
        # Junior G1s are long gone by then. Off via fan_farm_junior_g1_only: false.
        candidates = sorted(self.available_programs(state))
        if turn <= self.JUNIOR_FAN_GOAL_LAST_TURN and self.policy.get("fan_farm_junior_g1_only", True):
            allowed = self.junior_fan_g1_programs(state)
            # Only NARROW to the fan G1s when at least one is actually on the board. With none
            # offered the wall is still fatal and still has to be closed: T.M. Opera O died 144 fans
            # short of a turn-24 fan-count goal, and her board carried no fan G1 at all -- filtering
            # to an empty set there would farm nothing and re-create that failure. Preference, not a
            # prohibition.
            if allowed:
                candidates = [pid for pid in candidates if pid in allowed]
        best_program, best_score = 0, None
        for program_id in candidates:
            if (turn, program_id) in self.rejected or self._is_debut_program(program_id):
                continue
            info = self.program.get(program_id) or {}
            win_fans = max(0, int(info.get("win_fans") or 0))
            if not win_fans or self.entry_fans(program_id) > current_fans:
                continue                      # no reward, or she can't enter this one either
            ground_apt, distance_apt = self._apt_grades(chara, program_id)
            if ground_apt < floor or distance_apt < floor:
                continue                      # HARD aptitude match: never race what she can't run
            score = (win_fans, ground_apt + distance_apt, -self._grade_rank(program_id))
            if best_score is None or score > best_score:
                best_program, best_score = program_id, score
        return best_program

    def goal_program(self, state):
        """The trainee's scheduled career-goal race for THIS turn (from career_goals.json), when
        the game is offering it. Makes the per-trainee goal schedule the source of truth for entry
        rather than relying only on the game's mandatory-forcing. Returns a program_id or 0."""
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        available = self.available_programs(state)
        for g in self._goals(chara):
            if g.get("kind") == "race" and int(g.get("turn") or 0) == turn:
                # A GROUP goal (master race_type 4) is satisfied by ANY of its member races -- e.g.
                # Copano Rickey's turn-69 goal is the four JBC Classic variants. Take whichever is on
                # the board, preferring one the trainee can actually run (surface + distance).
                candidates = [int(p) for p in (g.get("program_ids") or [g.get("program_id")]) if p]
                offered = [p for p in candidates if p in available and (turn, p) not in self.rejected]
                if not offered:
                    continue
                floor = self.FAN_RACE_MIN_GRADE
                runnable = [p for p in offered
                            if min(self._apt_grades(chara, p)) >= floor]
                return (runnable or offered)[0]
        return 0

    def goal_label(self, state, program_id):
        """Log label for a scheduled goal race, e.g. "goal: Fillies' Revue (Top 5)"; falls back to
        the plain race label when the program isn't a known goal for this trainee."""
        chara = (state.get("data") or {}).get("chara_info") or {}
        pid = int(program_id or 0)
        for g in self._goals(chara):
            if int(g.get("program_id") or 0) == pid:
                return f"goal: {g.get('race')} ({g.get('require')})"
        return self.label(program_id)

    def goal_risk(self, state):
        """A one-line warning when a career goal for the CURRENT turn looks unmet, else "". Only
        fan goals are measurable up front (from chara.fans); placement goals are left to the race
        result. Used purely for logging so a missed goal is visible, not silently failed."""
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        fans = int(chara.get("fans") or 0)
        for g in self._goals(chara):
            if g.get("kind") == "fan" and int(g.get("turn") or 0) == turn and fans < int(g.get("fans") or 0):
                return f"fan goal at risk: {fans}/{g.get('fans')} fans due turn {turn}"
        return ""

    def goal_schedule_line(self, chara):
        """A compact one-line summary of the trainee's whole goal schedule for a start-of-career
        log, e.g. "Curren Chan goals -> T12 Make Debut | T23 3,000 fans | T29 Fillies' Revue ...".
        Returns "" when the trainee has no goals on file."""
        goals = self._goals(chara)
        if not goals:
            return ""
        entry = self.data_store.career_goals().get(str(int((chara or {}).get("card_id") or 0) // 100)) or {}
        name = entry.get("name") or "Trainee"
        parts = []
        for g in goals:
            if g.get("kind") == "fan":
                parts.append(f"T{g['turn']} {int(g.get('fans') or 0):,} fans")
            elif g.get("kind") == "finale":
                parts.append(f"T{g['turn']} Finale")
            else:
                parts.append(f"T{g['turn']} {g.get('race')} ({g.get('require')})")
        return f"{name} goals -> " + " | ".join(parts)

    def choose(self, state, preset):
        data = state.get("data") or {}
        # optional_races=False (Unity): never run scheduled/optional races -- only the mandatory goal
        # races surfaced by forced_program / the game's race screen -- unless the user opts into the
        # schedule (use_race_schedule), which lets choose() run the extra_race_list races.
        if not self.policy.get("optional_races", True) and not self._use_schedule(preset):
            return 0
        turn = int((data.get("chara_info") or {}).get("turn") or 0)
        
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        race_enabled = any(cmd.get("command_type") == 4 and cmd.get("command_id") == 401 and cmd.get("is_enable", 0) for cmd in commands)
        if not race_enabled:
            return 0

        available = self.available_programs(state)
        if not available:
            return 0
    
        wanted = self.wanted_programs(preset, turn, data.get("chara_info"))
        valid_wanted = [pid for pid in wanted if pid in available and (turn, pid) not in self.rejected]
        # When several wanted races land on the same turn, prefer the highest grade
        # (race_instance_id prefix 1=G1, 2=G2, 3=G3/open): G1s bypass the train-vs-race
        # gate and a G2 clears a harder bar than a G3, so grade order decides which race
        # the gate actually evaluates -- a G3 must not shadow a same-turn G2.
        valid_wanted.sort(key=self._grade_rank)
        
        if not valid_wanted:
            chara = data.get("chara_info") or {}
            fans = int(chara.get("fans") or 0)
            # fan_scramble (MANT sets it): race ANY runnable G-race for fans on a low-fan junior turn.
            # Goal-scheduled scenarios keep it off: mandatory races come from forced_program and racing
            # random UNSCHEDULED races just burns prep on races the trainee often loses.
            if self.policy.get("fan_scramble", False) and fans < 350 and turn > 11:
                for pid in available:
                    if (turn, pid) not in self.rejected and self.check_aptitude(chara, pid):
                        return pid
            return 0

        # rival_overwrite (MANT sets it): prefer the same-turn wanted race carrying a Twinkle-Climax
        # rival. Other scenarios take the top wanted race verbatim.
        if not self.policy.get("rival_overwrite", False):
            return valid_wanted[0]
            
        main_race_id = valid_wanted[0]
        rival_map = self.get_rival_race_map(state)
        
        if main_race_id in rival_map:
            return main_race_id
            
        for overwrite_pid in valid_wanted[1:]:
            if overwrite_pid in rival_map:
                return overwrite_pid
                
        return main_race_id

    def _grade_rank(self, program_id):
        """0=G1, 1=G2, 2=G3/open, 3=unknown -- from the race_instance_id first-digit
        convention used across the codebase (cleats, train-vs-race gate)."""
        info = self.program.get(int(program_id or 0)) or {}
        first = str(info.get("race_instance_id") or "")[:1]
        return {"1": 0, "2": 1, "3": 2}.get(first, 3)

    def reject(self, turn, program_id):
        self.rejected.add((int(turn or 0), int(program_id or 0)))

    def label(self, program_id):
        info = self.program.get(int(program_id or 0)) or {}
        name = info.get("name") or ""
        race_instance_id = info.get("race_instance_id") or ""
        return f"{program_id} {race_instance_id} {name}".strip()
