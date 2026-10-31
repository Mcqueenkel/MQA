from career_bot.core.training_brain import BaseTrainingStrategy, DECK_PARTNERS, TRAINING_COMMANDS


class UraStrategy(BaseTrainingStrategy):
    """URA Finale scenario (scenario_id 1).

    URA Finale reuses MantStrategy's entire training brain unchanged. This is sound
    because the two scenarios share the SAME 78-turn calendar byte-for-byte (verified
    against master.mdb single_mode_turn for turn_set 1 vs 4): Junior pre-debut turns
    1-12, summer camps at turns 37-40 and 61-64, and the finals period at turns 73-78
    with the 3 finals on turns 74/76/78. So every MANT calendar constant
    (SUMMER_CAMP_TURNS, the 24/48/72 year boundaries, the turn-77 stop) transfers as-is,
    and the cap-aware command scorer, bond/rainbow logic, rest/recreate/medic gates and
    energy-rescue all carry no MANT-specific data.

    The MANT-only machinery (coin shop, grade points, cleat hammers, megaphones, Glow
    Sticks, Twinkle-Climax race-overwrite) is gated behind `scenario_id == 4` in the
    runner (`_handle_items`, `_race`) and the race planner (rival overwrite), so a URA
    career skips all of it automatically with no further changes.

    The ONE URA-specific behaviour: URA goal races are MANDATORY per-character races --
    missing one fails the whole career -- unlike MANT's generic, easily-cleared goal
    markers. So URA must never trade a chosen race for a strong training. We force this
    by disabling the train-outvalues-race skip (tunable via preset `ura_force_races`).

    Flow knowledge ported from a WORKING URA fork ("new api bot", live-tested by its author):
      1. Routing: URA runs on the PLAIN single_mode/* namespace (the original scenario keeps the
         original unsuffixed prefix) -- client._route_ep remaps every career call for scenario 1.
      2. Finals (turns 74/76/78): arrive as game-forced races (race_start_info / playing_state),
         which the shared race flow already runs -- the fork does exactly the same, no special code.
      3. Close-out: ONE factor_select{current_turn} (like Unity, NOT MANT's open+confirm pair) ->
         finish{factor_lottery_id} -- the fork's sequence. We additionally keep change_nickname
         (our 1.32.8 slot-release step) with the GENERIC nickname 92 (master.mdb has no scenario-1
         nickname rows; 92 verified on a real URA-trained uma in the user's roster). Non-fatal if
         URA turns out not to need it.
      4. URA-specific training signal: state carries ura_data_set.command_info_array, whose
         entries flag facilities with a rival VERSUS duel waiting (versus_event_partner_id).
         Winning duels drives the URA finale power-ups, so a duel facility is prioritized hard
         (see _score_command below).
    Still live-unverified on OUR bot -- first URA run is the ground truth.
    """

    scenario_id = 1

    # URA's CAREER GOALS are the schedule: the planner races exactly the goal route (+ the game's
    # forced races); the preset's extra_race_list and MANT's fan/rival extras stay off (defaults).
    RACE_POLICY = {**BaseTrainingStrategy.RACE_POLICY, "goal_races_only": True}

    # URA's own per-stat caps [SPD, STA, PWR, GUT, WIT] = game base 1200 + URA's cap bonus (+200 to
    # every stat, per master.mdb single_mode_scenario id 1). The bot trains each stat up to min(this,
    # the LIVE in-game cap). Override per stat via stat_caps; disable via scenario_stat_caps=False.
    DEFAULT_STAT_CAPS = (1400, 1400, 1400, 1400, 1400)

    # Flat score bonus for a training facility with a rival VERSUS duel waiting. DOMINANT by
    # design (our tile scores live in ~0..3): the working fork uses the same always-take-the-duel
    # policy ("massive bonus to prioritize duels"). Preset-tunable via "ura_versus_bonus".
    URA_VERSUS_BONUS = 5.0

    # ---------------------------------------------------------------- URA FAN-FARM MODE
    # A deliberately narrow plan for farming FANS rather than building a strong trainee, enabled with
    # preset ura_fan_farm. The trainee only has to be good enough to WIN the fan-heavy long races in
    # year 3; every other stat point is wasted effort. The plan:
    #
    #   1. bond the SPEED cards to orange (80) as fast as possible, so friendship training starts early
    #   2. on non-race turns, train Speed (or rest) -- nothing else is worth a turn
    #   3. reach ~700 Speed and ~500 Power/Stamina for the year-3 long races
    #   4. keep buying skills throughout (skills win races, races are the fans)
    #
    # Steps 2 and 3 are one mechanism: cap the OTHER stats at the numbers the plan wants, and the
    # shared _stat_capped_trainings drops each one from the candidate list as it is reached -- so the
    # board naturally collapses to Speed, then rest. Speed itself keeps URA's normal ceiling, since
    # "700+" is a floor to clear, not a target to stop at.
    FAN_FARM_STAT_CAPS = {"speed": 1400, "stamina": 500, "power": 500, "guts": 300, "wiz": 400}
    # Score added to a Speed facility while any DECK speed card on it is still short of orange bond.
    # Sized against the normal ~0..3 tile range: enough to lead, below the versus-duel bonus so a
    # rival duel still wins the turn.
    FAN_FARM_SPEED_BOND_BONUS = 3.0
    FAN_FARM_ORANGE_BOND = 80          # the friendship-training threshold
    # STANDING Speed preference, applied every turn the mode is on -- not just while bonding. The
    # bond bonus above fades once the speed cards reach orange, after which raw stat scoring takes
    # over and the bot spreads taps again; this keeps Speed in front for the whole career, which is
    # the "always train speed" plan. Still below FAN_FARM_SPEED_BOND_BONUS + base so the opening
    # bonding phase pushes hardest, and below URA_VERSUS_BONUS so a rival duel still takes the turn.
    # Tune with ura_fan_farm_speed_bonus; set 0 to go back to bond-phase-only steering.
    FAN_FARM_SPEED_BONUS = 2.5

    @staticmethod
    def fan_farm(preset):
        return bool((preset or {}).get("ura_fan_farm", False))

    def _with_stat_caps(self, preset, chara=None):
        """Apply the fan-farm caps unless the user set their own stat_caps (those always win)."""
        p = preset or {}
        if not self.fan_farm(p):
            return preset
        user_caps = p.get("stat_caps")
        if isinstance(user_caps, dict) and any(user_caps.values()):
            return preset
        return {**p, "stat_caps": dict(self.FAN_FARM_STAT_CAPS)}

    def next_decision(self, state, preset):
        # Inject the caps before the shared brain reads them, the same way Grand Live does.
        return super().next_decision(state, self._with_stat_caps(preset))

    def _speed_cards_still_bonding(self, command, chara):
        """Deck speed-card partners on this facility that have NOT reached orange bond yet."""
        try:
            bonds = self._bond_map(chara)
            return sum(1 for pid in (command.get("training_partner_array") or [])
                       if pid in DECK_PARTNERS
                       and bonds.get(pid, 0) < self.FAN_FARM_ORANGE_BOND)
        except Exception:
            return 0

    def _train_outvalues_race(self, data, chara, preset, program_id=0):
        # URA goal races are mandatory: by default never skip a race the planner chose in
        # favour of training, or the run can fail a goal. (forced_program already covers
        # race-only turns; this covers turns that offer both race and training.)
        if (preset or {}).get("ura_force_races", True):
            return False
        return super()._train_outvalues_race(data, chara, preset, program_id)

    def _rest_alternative(self, training, chara, preset, turn):
        """URA: on a would-rest turn, train a safe Wit instead of burning a dead 0-stat turn.
        Policy + the energy-trap guard live in the shared base (_wit_rest_alternative).
        Toggles: ura_wit_over_rest / ura_wit_rest_max / wit_rest_skip_ratio."""
        return self._wit_rest_alternative(training, chara, preset, turn, "ura")

    def _score_command(self, command, data, chara, preset):
        score = super()._score_command(command, data, chara, preset)
        # FAN FARM step 1: push the Speed facility while its deck cards are still short of orange.
        # Raw stat scoring spreads taps across whatever pays most THIS turn; the plan needs the speed
        # cards bonded early instead, because friendship training is what makes the rest of the run
        # cheap. Fades to nothing once they are all orange, so it only steers the opening.
        if self.fan_farm(preset) and int((command or {}).get("command_type") or 0) == 1:
            if TRAINING_COMMANDS.get(int(command.get("command_id") or 0)) == 0:   # 0 = Speed
                # Standing preference: keep Speed in front for the WHOLE career, not just the
                # bonding phase (see FAN_FARM_SPEED_BONUS).
                score += float((preset or {}).get(
                    "ura_fan_farm_speed_bonus", self.FAN_FARM_SPEED_BONUS))
                bonding = self._speed_cards_still_bonding(command, chara)
                if bonding:
                    score += bonding * float((preset or {}).get(
                        "ura_fan_farm_bond_bonus", self.FAN_FARM_SPEED_BOND_BONUS))
        # URA versus duels: ura_data_set.command_info_array marks facilities where a rival duel
        # fires this turn. Ported from the working fork: take the duel over raw gains.
        try:
            for uc in ((data or {}).get("ura_data_set") or {}).get("command_info_array") or []:
                if (uc.get("command_type") == command.get("command_type")
                        and uc.get("command_id") == command.get("command_id")
                        and uc.get("versus_event_partner_id")):
                    score += float((preset or {}).get("ura_versus_bonus") or self.URA_VERSUS_BONUS)
                    break
        except Exception:
            pass   # malformed ura_data_set must never crash a turn -- fall back to the base score
        return score
