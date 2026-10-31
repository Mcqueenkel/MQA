"""Unity / Aoharu team scenario (scenario_id 2) -- ALL Unity logic lives in this one file.

Contents (merged from the old team.py + unity_cup_team_race.py so Unity can't be broken by edits to
any other scenario):
  1. ``UnityStrategy``   -- the per-turn brain: shared training brain + the Unity-only moves
     (cup-turn detection at playing_state 7/8/9, mandatory goal races).
  2. Team-formation + opponent-picker helpers (pure, no I/O).
  3. ``UnityScenario``   -- the runner-side cup-race flow (team_edit -> opponent_list ->
     team_race_analyze -> team_race_start -> team_race_end -> team_race_out).

Cup mechanics: at each team-race turn (24/36/48/60/72) the game offers 3 NPC teams.
`single_mode_team/opponent_list` returns a favorability signal (analyze_mark_array) and
`single_mode_team/team_race_analyze` reports, per opponent, the league rank you'd move to on
win/lose/draw (`win_up_rank`/`lose_down_rank`/`draw_rank` -- LOWER is better, e.g. 30 -> 22 on a
win). Win 3 of the 5 sub-races to take the win outcome. See docs in the Icarus unity-cup-api-map.
"""
from career_bot.core.base import Decision
from career_bot.core.training_brain import BaseTrainingStrategy, DECK_PARTNERS, TRAINING_COMMANDS


class UnityStrategy(BaseTrainingStrategy):
    """Unity per-turn brain (ex-TeamStrategy). The per-turn career loop is byte-identical to
    MANT/URA on the single_mode_team/* namespace (verified field-by-field against a full team
    capture), so the entire shared training brain -- cap-aware command scoring, bond/rainbow,
    rest/recreate, energy rescue, the shared 78-turn calendar -- is reused unchanged. UmaClient
    routes every single_mode_free/* career call to single_mode_team/* when scenario_id==2.

    The one Unity-specific move is the in-career Unity Cup team race at year boundaries, emitted
    as Decision(action="team_race"); the runner hands it to UnityScenario.run_cup_race below.
    MANT's coin-shop / hammer / megaphone machinery is gated behind scenario_id==4 in the runner,
    so a Unity career skips all of it automatically."""

    scenario_id = 2

    # Unity races ONLY its fixed mandatory goal route: career goals are the schedule, there is no
    # user schedule to swap in on forced turns, and choose() never enters optional races at all.
    RACE_POLICY = {**BaseTrainingStrategy.RACE_POLICY,
                   "goal_races_only": True, "scheduled_override": False, "optional_races": False}

    # Unity/Aoharu's own per-stat caps [SPD, STA, PWR, GUT, WIT] = game base 1200 + Unity Cup's cap
    # bonus (+100 to Spd/Sta/Pow/Guts, +600 to WIT, per master.mdb single_mode_scenario id 2 -- Unity
    # pours cap into Wit). The bot trains each stat up to min(this, the LIVE in-game cap). Override per
    # stat via stat_caps; disable via scenario_stat_caps=False.
    DEFAULT_STAT_CAPS = (1300, 1300, 1300, 1300, 1800)

    def next_decision(self, state, preset):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        # Run the Unity Cup team race whenever the game presents it (ps 7/8/9 + team_data_set) --
        # detected from state, not a hardcoded turn. UnityScenario.run_cup_race drives the full
        # sequence. Pass team_data_set + chara_info so it can build an APTITUDE-CORRECT lineup (a
        # bare or aptitude-invalid lineup 102s -- the team_data_array belongs to team_edit, not load).
        if self._cup_race_available(data):
            return Decision(action="team_race",
                            payload={"current_turn": int(chara.get("turn") or 0),
                                     "team_data_set": data.get("team_data_set") or {},
                                     "chara_info": chara},
                            reason="Unity Cup team race")
        return super().next_decision(state, preset)

    def _train_outvalues_race(self, data, chara, preset, program_id=0):
        # Like URA, Unity/Aoharu goal races are MANDATORY -- missing one fails the career -- so never
        # trade a race the planner chose for a strong training. (goal_program already runs the
        # scheduled goal race before this gate; this also keeps opportunistic chosen races from being
        # skipped.) Tunable via preset "unity_force_races" (default True).
        if (preset or {}).get("unity_force_races", True):
            return False
        return super()._train_outvalues_race(data, chara, preset, program_id)

    # Unity Cup phase-weighted training value (青春). Weight the four things a player reads off the board
    # by career phase: raw stat ARROWS (scales the shared score), partners still BUILDING their friendship
    # gauge (bond < 80), RAINBOW (maxed-bond) partners delivering a friendship training, and Aoharu soul
    # BURSTS. Rationale: building bond pays off less late (no time to cash it into rainbows); rainbows
    # compound, so they matter more late; a burst is always the top priority. Phases split on the career
    # years (Junior <=24, Classic <=48, Senior/finale after). Override per preset via "unity_phase_weights".
    # "soul_build" = the NEW soul-gauge build nudge (below): favour a facility whose teammates are close
    # to arming a burst (~4 trains fills a gauge, then it bursts). Weighted below an armed burst (3.0);
    # tapers late when there's no time left to cash a fresh gauge into a burst.
    UNITY_PHASE_WEIGHTS = {
        "early": {"arrows": 1.00, "building": 0.75, "rainbow": 1.25, "burst": 3.0, "soul_build": 0.70},
        "mid":   {"arrows": 1.00, "building": 1.00, "rainbow": 1.50, "burst": 3.0, "soul_build": 0.60},
        "end":   {"arrows": 0.75, "building": 0.25, "rainbow": 2.00, "burst": 3.0, "soul_build": 0.20},
    }

    @staticmethod
    def _unity_phase(turn):
        return "early" if turn <= 24 else ("mid" if turn <= 48 else "end")

    def _unity_phase_weights(self, preset, turn):
        phase = self._unity_phase(turn)
        override = ((preset or {}).get("unity_phase_weights") or {}).get(phase) or {}
        return {**self.UNITY_PHASE_WEIGHTS[phase], **override}

    def _partner_states(self, command, chara):
        """(building, rainbow) deck-support counts on this facility. rainbow = bond >= 80 (maxed,
        delivering a friendship training this turn); building = bond < 80 (gauge still filling toward it).
        Matches the shared scorer's own rainbow rule (training_brain.py: bond>=80 & deck slot)."""
        bonds = self._bond_map(chara)
        building = rainbow = 0
        for pid in command.get("training_partner_array") or []:
            if pid not in DECK_PARTNERS:
                continue
            if bonds.get(pid, 0) >= 80:
                rainbow += 1
            else:
                building += 1
        return building, rainbow

    @staticmethod
    def _soul_burst_count(command, data):
        """Aoharu soul-burst partners on this facility (soul + super-soul), matched by command_id --
        team_data_set.command_info_array[i].soul_event_partner_array / sp_soul_event_partner_array."""
        cid = (command or {}).get("command_id")
        for c in ((data or {}).get("team_data_set") or {}).get("command_info_array") or []:
            if c.get("command_id") == cid:
                return len(c.get("soul_event_partner_array") or []) + len(c.get("sp_soul_event_partner_array") or [])
        return 0

    @staticmethod
    def _soul_build_score(command, data):
        """Soul-gauge BUILD signal: how close a facility's NOT-yet-armed teammates are to arming a soul
        burst. Each teammate present on the facility that is still building shows in this command's
        guide_event_partner_array (by target_id); the teammate's gauge tier is soul_threshold_id 1..5 in
        team_data_set.evaluation_info_array (5 = full = armed, then it appears in soul_event_partner_array
        and _soul_burst_count scores it). So a tier-4 teammate is ~one train from arming: sum tier/5 over
        the building teammates -> favour facilities near the top, which is the ~4-train build-up that sets
        up the blue burst (and its random purple follow-up). Armed teammates are the burst term, not this."""
        tds = (data or {}).get("team_data_set") or {}
        cid = (command or {}).get("command_id")
        cinfo = next((c for c in (tds.get("command_info_array") or []) if c.get("command_id") == cid), None)
        if not cinfo:
            return 0.0
        # target_id -> gauge tier (1..5), for the player's own team members (member_state 1).
        tiers = {e.get("target_id"): int(e.get("soul_threshold_id") or 0)
                 for e in (tds.get("evaluation_info_array") or []) if int(e.get("member_state") or 0) == 1}
        return sum(min(max(tiers.get(tid, 0), 0), 5) / 5.0 for tid in (cinfo.get("guide_event_partner_array") or []))

    def _failure_forces_rest(self, best, data, chara, preset, turn, failure):
        """Unity rest rule: only TRAIN when the failure rate is low (< unity_failure_max, default 8%)
        so energy stays high and trainings don't fail -- otherwise REST. Two keep-training exceptions
        (train through the higher failure): (1) after unity_keep_train_after_turn (default 32) a WIT
        training with >= unity_keep_train_rainbow (default 2) rainbows, and (2) ANY training carrying
        a lot of Aoharu soul bursts -- 'unity spirit' -- >= unity_spirit_keep_train (default 2)."""
        cap = int(preset.get("unity_failure_max", 8))
        if int(failure or 0) < cap:
            return False
        after = int(preset.get("unity_keep_train_after_turn", 32))
        need_rb = int(preset.get("unity_keep_train_rainbow", 2))
        if int(turn or 0) > after and int((best or {}).get("command_id") or 0) == 106:   # 106 = Wit facility
            _building, rainbow = self._partner_states(best, chara)
            if rainbow >= need_rb:
                return False
        if self._soul_burst_count(best, data) >= int(preset.get("unity_spirit_keep_train", 2)):
            return False
        return True

    def _rest_alternative(self, training, chara, preset, turn):
        """Unity: on a would-rest turn, train a safe Wit instead of burning a dead 0-stat turn.
        Policy + the energy-trap guard live in the shared base (_wit_rest_alternative).
        Toggles: unity_wit_over_rest / unity_wit_rest_max / wit_rest_skip_ratio."""
        return self._wit_rest_alternative(training, chara, preset, turn, "unity")

    def _score_command(self, command, data, chara, preset):
        # Phase-weighted Unity value: the shared score (raw stat "arrows") scaled by the phase, PLUS the
        # per-teammate friendship/burst emphasis. team_data_set (soul) exists only in Unity, and this whole
        # override only applies to Unity careers, so MANT/URA are untouched.
        base = super()._score_command(command, data, chara, preset)
        if int(command.get("command_type") or 0) != 1:   # not a training facility -> leave rest/race scores alone
            return base
        w = self._unity_phase_weights(preset, int((chara or {}).get("turn") or 0))
        building, rainbow = self._partner_states(command, chara)
        burst = self._soul_burst_count(command, data)
        soul_build = self._soul_build_score(command, data)
        return (base * float(w["arrows"])
                + building * float(w["building"])
                + rainbow * float(w["rainbow"])
                + burst * float(w["burst"])
                + soul_build * float(w.get("soul_build", 0.0)))

    # The Unity Cup race day parks the career at playing_state 7 (auto-fill / opponent-select) and the
    # team race drives it 7 -> 8 -> 9 as the sub-races resolve. At turn-start the normal flow only ever
    # shows 7 (the whole 7->8->9 sequence runs inside one run_cup_race call), but a resume or a mid-race
    # exception re-entry can land the loop on 8/9 -- route all three to the cup handler so it reconciles
    # the race instead of falling through to a mis-train. opponent_info_array (populated only after
    # team_edit) is an equivalent "we are already inside the cup" marker. Matches Icarus unity_cup.py:280.
    # The game STILL returns enabled training commands in these states, so "training menu gone" is NOT a
    # valid signal -- playing_state (and the runner's matching 7/8/9 unblock) is the real marker.
    CUP_PLAYING_STATES = (7, 8, 9)

    @staticmethod
    def _cup_race_available(data):
        tds = data.get("team_data_set")
        if not tds:
            return False
        if "single_mode_finish_common" in data:          # career is finishing
            return False
        if data.get("unchecked_event_array"):             # a story event must be resolved first
            return False
        if tds.get("opponent_info_array"):                # already mid-sequence (post team_edit)
            return True
        chara = data.get("chara_info") or {}
        return int(chara.get("playing_state") or 0) in UnityStrategy.CUP_PLAYING_STATES


# ============================ Team formation + opponent picker (pure) ============================

# Winnability (favorability marks) dominates raw rank gain: better to reliably win a slightly smaller
# jump than to gamble on a big one you'll lose. Weight >> any realistic rank spread.
FAVORABILITY_WEIGHT = 1000
_WORST_RANK = 9999  # a missing win_up_rank scores as the worst possible gain

# The team-race `race_set_id` for each Aoharu team-race turn, confirmed across all 5 races in the
# live capture (dumps/20260703_150022): the 3 candidate opponents surface only AFTER team_edit, so
# when the live state doesn't hand us opponent_info_array we fall back to the standard per-turn id
# (the one the captured career actually raced each turn). Used by the runner's _team_race handler.
TEAM_RACE_SET_ID_BY_TURN = {24: 300, 36: 402, 48: 600, 60: 806, 72: 1000}

# Team-race formation must be APTITUDE-CORRECT: each uma races a distance it can actually run, or the
# lineup submit 102s (verified live — El Condor Pasa, Sprint-F, placed at Sprint was rejected). Each
# distance takes 1–3 racers, min 1 each (game8 2026-07-01). TEAM_FORMATION_SLOTS is the canonical
# 10-racer shape the reference capture used (1 sprint / 2 mile / 3 medium / 3 long / 1 dirt).
TEAM_FORMATION_SLOTS = [(1, 1), (2, 2), (3, 3), (4, 3), (5, 1)]
# Running style when aptitude is unknown. 2 = Pace/Senko — the broadly-usable middle style.
DEFAULT_RUNNING_STYLE = 2
_DISTANCE_TYPES = (1, 2, 3, 4, 5)          # sprint, mile, medium, long, dirt
_FILL_PRIORITY = (3, 4, 2, 1, 5)           # medium, long, mile, sprint, dirt — where spare racers go
_MIN_PER_DISTANCE = 1
_MAX_PER_DISTANCE = 3

# The FIXED Aoharu team pool -> the game's recommended race distance + running style, read off the
# reference capture (dumps/20260703_150022 req0099 = the game's own arrangement). The 9 teammates are
# scenario-fixed (identical across independent careers), so this is the correct default; the TRAINEE
# is placed by her LIVE aptitude (chara_info) instead, and any unrecognised uma fills a spare slot.
_POOL_DISTANCE = {1010: 1, 1044: 2, 1056: 3, 1055: 3, 1022: 3, 1068: 4, 1016: 4, 1030: 4, 1052: 5}
_POOL_STYLE = {1010: 2, 1044: 4, 1056: 3, 1055: 3, 1022: 2, 1068: 1, 1016: 3, 1030: 2, 1052: 3}

# chara_info aptitude keys -> distance_type (turf; dirt is handled separately) and running_style.
_APT_DISTANCE_KEYS = ((1, "proper_distance_short"), (2, "proper_distance_mile"),
                      (3, "proper_distance_middle"), (4, "proper_distance_long"))
_APT_STYLE_KEYS = ((1, "proper_running_style_nige"), (2, "proper_running_style_senko"),
                   (3, "proper_running_style_sashi"), (4, "proper_running_style_oikomi"))


# The reference capture's EXACT game-recommended formation (req0099), keyed by the full racer set
# (trainee + teammates). When the live roster matches a known set we submit this verbatim — same
# distances AND member_id slot order AND running styles — in case the server validates the lineup
# against its own auto-fill down to slot order (our aptitude build matches distances+styles but not
# always the exact slot order). Falls back to the aptitude builder for any unrecognised roster.
_KNOWN_GOOD_FORMATIONS = {
    frozenset({1010, 1014, 1016, 1022, 1030, 1044, 1052, 1055, 1056, 1068}): [
        {"distance_type": 1, "member_id": 1, "chara_id": 1010, "running_style": 2},
        {"distance_type": 2, "member_id": 1, "chara_id": 1014, "running_style": 2},
        {"distance_type": 2, "member_id": 2, "chara_id": 1044, "running_style": 4},
        {"distance_type": 3, "member_id": 1, "chara_id": 1056, "running_style": 3},
        {"distance_type": 3, "member_id": 2, "chara_id": 1055, "running_style": 3},
        {"distance_type": 3, "member_id": 3, "chara_id": 1022, "running_style": 2},
        {"distance_type": 4, "member_id": 1, "chara_id": 1068, "running_style": 1},
        {"distance_type": 4, "member_id": 2, "chara_id": 1016, "running_style": 3},
        {"distance_type": 4, "member_id": 3, "chara_id": 1030, "running_style": 2},
        {"distance_type": 5, "member_id": 1, "chara_id": 1052, "running_style": 3},
    ],
}


def team_roster_chara_ids(team_data_set):
    """The player's own team members as chara_ids = evaluation_info_array entries with member_state
    == 1 (member_state 0 = empty/guest NPC slots like 900x, which never race)."""
    eia = (team_data_set or {}).get("evaluation_info_array") or []
    out = []
    for e in eia:
        if not e or int(e.get("member_state") or 0) != 1:
            continue
        cid = e.get("chara_id")
        if cid:
            out.append(int(cid))
    return out


def _trainee_distance(aptitude):
    """The trainee's best turf distance_type from her live chara_info aptitude (default medium)."""
    if not aptitude:
        return 3
    best = max(_APT_DISTANCE_KEYS, key=lambda kv: int(aptitude.get(kv[1]) or 0))
    return best[0]


def _trainee_style(aptitude):
    if not aptitude:
        return DEFAULT_RUNNING_STYLE
    return max(_APT_STYLE_KEYS, key=lambda kv: int(aptitude.get(kv[1]) or 0))[0]


def build_team_formation(team_data_set, trainee_chara_id, trainee_aptitude=None,
                         running_style=DEFAULT_RUNNING_STYLE):
    """Build the check_event{team_data_array} lineup that ENTERS the team-edit screen (capture
    req0099): the trainee + the team members, each placed at an aptitude-valid distance (1–3 per
    distance, min 1 each, ≤15 fielded). The trainee goes to her best distance from chara_info
    aptitude; the fixed Aoharu teammates use the game's recommended pool arrangement; unrecognised
    umas fill spare slots. Returns [] when fewer than 5 racers are available (can't field one per
    distance) so the caller defers cleanly rather than submit a malformed (102-ing) formation."""
    trainee = int(trainee_chara_id or 0)
    members = ([trainee] if trainee else []) + [c for c in team_roster_chara_ids(team_data_set) if c != trainee]
    if len(members) < len(_DISTANCE_TYPES):
        return []
    members = members[:len(_DISTANCE_TYPES) * _MAX_PER_DISTANCE]

    # If this exact racer set has a captured game-recommended formation, submit it verbatim (exact
    # slot order + styles) — the safest match against the server's own auto-fill.
    known = _KNOWN_GOOD_FORMATIONS.get(frozenset(members))
    if known:
        return [dict(x) for x in known]

    def want(cid):
        if cid == trainee:
            return _trainee_distance(trainee_aptitude), _trainee_style(trainee_aptitude)
        return _POOL_DISTANCE.get(cid), _POOL_STYLE.get(cid, running_style)

    style = {cid: want(cid)[1] for cid in members}
    bins = {dt: [] for dt in _DISTANCE_TYPES}
    leftovers = []
    for cid in members:
        dt = want(cid)[0]
        if dt in bins and len(bins[dt]) < _MAX_PER_DISTANCE:
            bins[dt].append(cid)
        else:
            leftovers.append(cid)
    # Guarantee the minimum one racer per distance (pull a spare, else steal from a fuller distance).
    for dt in _DISTANCE_TYPES:
        if bins[dt]:
            continue
        if leftovers:
            bins[dt].append(leftovers.pop(0))
        else:
            for src in _DISTANCE_TYPES:
                if len(bins[src]) > 1:
                    bins[dt].append(bins[src].pop())
                    break
    # Place any remaining racers into spare capacity, medium/long first.
    for cid in list(leftovers):
        for dt in _FILL_PRIORITY:
            if len(bins[dt]) < _MAX_PER_DISTANCE:
                bins[dt].append(cid)
                leftovers.remove(cid)
                break
    out = []
    for dt in _DISTANCE_TYPES:
        for member_id, cid in enumerate(bins[dt], 1):
            out.append({"distance_type": dt, "member_id": member_id,
                        "chara_id": cid, "running_style": style.get(cid, running_style)})
    return out


def _favorability(opp):
    return int((opp or {}).get("favorability") or 0)


def _win_up_rank(opp):
    v = (opp or {}).get("win_up_rank")
    try:
        return int(v)
    except (TypeError, ValueError):
        return _WORST_RANK


# July-1 team-race defaults (LO 2026-07-03): AGGRESSIVE opponent policy (challenge the strongest
# winnable team for max stat reward = the game8-recommended top pick), plus clock-retry a lost team
# race up to 2 times. All overridable via preset['unity_config'].
DEFAULT_OPPONENT_POLICY = "aggressive"
DEFAULT_CLOCK_RETRY_TEAM_LOSS = True
DEFAULT_CLOCK_RETRY_MAX = 2


def opponent_score(opp, policy=DEFAULT_OPPONENT_POLICY, fav_weight=FAVORABILITY_WEIGHT):
    """Higher is better. Winnability (favorability) dominates; then reward/risk by policy:
    'aggressive' (default, game8 meta) prefers the STRONGEST winnable team — lowest win_up_rank =
    biggest rank gain; 'safe' prefers the easiest — highest win_up_rank = weakest opponent."""
    fav = _favorability(opp) * fav_weight
    rank = _win_up_rank(opp)
    if str(policy).strip().lower() == "safe":
        return fav + rank
    return fav - rank


def choose_opponent(opponents, policy=DEFAULT_OPPONENT_POLICY, fav_weight=FAVORABILITY_WEIGHT):
    """Pick the best team-race opponent from a normalized list (each item carries at least
    favorability + win_up_rank). Returns the chosen opponent dict, or None if the list is empty."""
    if not opponents:
        return None
    return max(opponents, key=lambda o: opponent_score(o, policy, fav_weight))


def unity_team_race_config(preset):
    """Team-race tunables resolved from preset['unity_config'] (defaults ship LO's choices):
    opponent_policy (aggressive|safe), favorability_weight, and the July-1 clock-retry-on-loss knobs
    (clock_retry_team_loss, clock_retry_max)."""
    uc = ((preset or {}).get("unity_config") or {})

    def _num(k, d):
        try:
            return float(uc.get(k, d))
        except (TypeError, ValueError):
            return float(d)

    return {
        "opponent_policy": str(uc.get("opponent_policy", DEFAULT_OPPONENT_POLICY)).strip().lower(),
        "favorability_weight": _num("favorability_weight", FAVORABILITY_WEIGHT),
        "clock_retry_team_loss": bool(uc.get("clock_retry_team_loss", DEFAULT_CLOCK_RETRY_TEAM_LOSS)),
        "clock_retry_max": max(0, int(_num("clock_retry_max", DEFAULT_CLOCK_RETRY_MAX))),
    }


# ── runner-side Unity operations (isolated from the shared MANT brain) ────────────────────────────────
class UnityScenario:
    """Every Unity Cup (Aoharu, scenario 2) runner-side operation, in ONE place so Unity fixes never
    touch the shared MANT paths. Holds a back-reference to the CareerRunner for its logging/state helpers
    (_log, _mark, _fresh_career_state, _drain_events, stop_requested). The training brain stays shared in
    mant.py; only the Unity-specific flows live here."""

    def __init__(self, runner):
        self.runner = runner

    @staticmethod
    def extract_opponents(obj):
        """team_data_set.opponent_info_array out of any {data:{data:{...}}} or {data:{...}} envelope."""
        d = (obj or {}).get("data")
        inner = d.get("data") if isinstance(d, dict) and isinstance(d.get("data"), dict) else d
        tds = (inner or {}).get("team_data_set") if isinstance(inner, dict) else None
        return (tds or {}).get("opponent_info_array") or []

    def run_cup_race(self, client, strategy, payload):
        """Drive one Unity Cup (Aoharu) team race. Sequence on single_mode_team/*:
            team_edit{team_data_array = APTITUDE lineup} -> opponent_list -> team_race_analyze{set_id}
            -> team_race_start{team_race_set_id} -> team_race_end -> team_race_out.
        team_edit MUST carry an aptitude-correct team_data_array or it 102s. CHOSEN opponent =
        choose_opponent from the surfaced candidates, else the confirmed per-turn set_id."""
        r = self.runner
        turn = int((payload or {}).get("current_turn") or 0)
        tds = (payload or {}).get("team_data_set") or {}
        chara = (payload or {}).get("chara_info") or {}
        trainee = int(chara.get("card_id") or 0) // 100

        def _fail(where, exc):
            r._team_race_fails = getattr(r, "_team_race_fails", 0) + 1
            r._log("team_race_fail", turn, f"{where}: {exc} (fail {r._team_race_fails})")
            if r._team_race_fails >= 2:  # stop cleanly rather than hammer into the circuit breaker
                r._mark(last_error=f"team race {where} failed: {exc}", last_action="team-race-stop")
                r.stop_requested = True
            return r._fresh_career_state(client, strategy)

        # 1) Build the aptitude-correct lineup and SUBMIT it via team_edit.
        formation = build_team_formation(tds, trainee, trainee_aptitude=chara)
        if not formation:
            return _fail("build lineup", "fewer than 5 racers available for the team")
        shape = "/".join(str(sum(1 for x in formation if x["distance_type"] == dt)) for dt in (1, 2, 3, 4, 5))
        r._log("team_race", turn, f"Unity Cup team race: {len(formation)} racers ({shape})")
        try:
            edit = client.call("single_mode_team/team_edit",
                               {"team_data_array": formation, "current_turn": turn}, retry_205=1) or {}
        except Exception as e:
            return _fail("team_edit", e)
        # 2) Fetch the opponents. (No gain_skills step -- this game version's cup goes team_edit ->
        # opponent_list directly; verified gain_skills appears NOWHERE in a full team capture.)
        try:
            ol = client.call("single_mode_team/opponent_list", {"current_turn": turn}, retry_205=1) or {}
        except Exception as e:
            ol = {}
            r._log("team_race_opplist", turn, f"opponent_list skipped: {str(e)[:100]}")
        # 3) Choose the opponent from the surfaced candidates; else the confirmed per-turn fallback.
        opponents = self.extract_opponents(ol) or self.extract_opponents(edit)
        chosen = choose_opponent(opponents) if opponents else None
        if chosen and chosen.get("team_race_set_id") is not None:
            set_id = int(chosen.get("team_race_set_id"))
            r._log("team_race_pick", turn, f"opponent {set_id} (win_up {chosen.get('win_up_rank')}) of {len(opponents)}")
        else:
            set_id = TEAM_RACE_SET_ID_BY_TURN.get(int(turn))
            r._log("team_race_pick", turn, f"opponent {set_id} (per-turn fallback)")
        if not set_id:
            return _fail("no opponent", "no team_race_set_id available")
        # 3b) Analyze the matchup (the pre-race prediction screen) -- the live client always calls this
        # between opponent_list and team_race_start; the server tracks it as a required step, so
        # team_race_start rejects without it. Send both key spellings (harmless extras); best-effort.
        try:
            client.call("single_mode_team/team_race_analyze",
                        {"race_set_id": set_id, "team_race_set_id": set_id, "current_turn": turn}, retry_205=1)
            r._log("team_race_analyze", turn, f"set_id={set_id}")
        except Exception as e:
            r._log("team_race_analyze", turn, f"analyze skipped: {str(e)[:100]}")
        # 4) Run -> resolve -> clear -> drain the post-race events.
        try:
            client.call("single_mode_team/team_race_start",
                        {"team_race_set_id": set_id, "current_turn": turn}, retry_205=1)
            client.call("single_mode_team/team_race_end", {"current_turn": turn}, retry_205=1)
            state = client.call("single_mode_team/team_race_out", {"current_turn": turn}, retry_205=1) or {}
        except Exception as e:
            return _fail("run race", e)
        r._team_race_fails = 0
        r._log("team_race_done", turn, f"set_id={set_id}")
        return r._drain_events(client, strategy, state)
