import json
import re
from pathlib import Path


EXCLUDED_KEYS = {
    "facility_period_configs",
    "facility_ratios",
}

RENAMES = {
    "race_list": "extra_race_list",
    "skill_priority_list": "learn_skill_list",
    "skill_blacklist": "learn_skill_blacklist",
    "blacklistedSkills": "learn_skill_blacklist",
    "extraWeight": "extra_weight",
    "scoreValue": "score_value",
    "baseScore": "base_score",
    "statValueMultiplier": "stat_value_multiplier",
    "witSpecialMultiplier": "wit_special_multiplier",
    "cureAsapConditions": "cure_asap_conditions",
}

MANT_SCENARIO_ID = 4
URA_SCENARIO_ID = 1

# Optional behavior knobs a preset file may set; passed through serialization verbatim so
# they actually reach the strategy (everything else is whitelisted). Defaults live in code.
TUNABLE_KEYS = (
    # train-vs-race gate
    "race_skip_train_stat", "race_skip_min_fans", "race_value_base", "race_value_g2_bonus",
    "race_value_camp_mult", "race_value_junior_bonus",
    "strong_train_over_race", "strong_train_rainbow_min", "strong_train_stat_total_min",
    "summer_strong_train_stat_total_min",
    # turn-quality lookahead
    "turn_quality_lookahead", "turn_quality_rest_boost", "turn_quality_weak_ratio",
    "turn_quality_strong_ratio",
    # career foresight + rainbow scoring
    "career_foresight", "aptitude_focus_grade", "goal_stamina_floor",
    "rainbow_unlock_lookahead", "rainbow_unlock_band_lo",
    "rainbow_unlock_bonus", "rainbow_unlock_cap", "rainbow_explicit", "rainbow_bonus",
    "rainbow_stack_bonus", "rainbow_useful_ref", "stat_balance", "stat_balance_threshold",
    "stat_balance_boost",
    # running style + skills
    "auto_running_style", "running_style_min_grade", "skill_fit_gate",
    "skill_fit_distance_min_grade", "skill_dump_leftover", "score_skill_points",
    "skill_point_weight",
    # skill_dump_leftover: spend remaining SP on any buyable skill at career end (default on).
    # (need_check_interval is gone: TIER 0 is now checked EVERY turn and tier 1+ is end-of-career
    # only, so there is no buy cadence left to tune. See skills.SkillBuyer.buy.)
    "skill_dump_leftover",
    # skill_buy_throughout: open the MID-RUN buy to the whole learn_skill_list, not just TIER 0.
    # For plans where a skill only pays if it is active for the races still to come (URA fan farm).
    "skill_buy_throughout",
    # (no "stat_caps": per-preset stat caps were removed with the STAT CAPS panel row on 2026-10-20.
    # Setting a cap on ONE stat replaced the scenario's whole cap profile -- e.g. stamina 400 dropped
    # Grand Live's caps for every stat and its goal-driven stamina target. Old preset files may still
    # hold the key; it is no longer loaded, so each scenario's own caps apply.)
    # ---- CORE SCORING / THRESHOLDS ------------------------------------------------------------
    # hydrate_preset supplies these as DEFAULTS (setdefault). They were previously force-assigned
    # there AND absent here, so a preset could not change any of them -- the value was dropped on
    # save and then overwritten on load. Listing them makes the scoring table itself tunable.
    "cure_asap_conditions", "score_value", "base_score", "stat_value_multiplier", "extra_weight",
    "npc_score_value", "special_training", "spirit_explosion", "wit_special_multiplier",
    "compensate_failure", "summer_score_threshold",
    "motivation_threshold_year1", "motivation_threshold_year2", "motivation_threshold_year3",
    "prioritize_recreation", "pal_thresholds", "pal_friendship_score", "pal_card_multiplier",
    "rest_threshold", "mant_config",
    # Failure pricing + the rest gate. These were read by the scorer but NOT listed here, so
    # hydrate_preset (which runs serialize_preset on the INBOUND path) dropped them at load: only
    # the shipped defaults have ever run, and max_failure_rate's code path has never executed in
    # production. failure_cost is the live failure knob (1.0 = a failure costs what a success gains;
    # lower it to push harder). score_failure_risk_weight is retained for compatibility but is now
    # inert -- the additive failure term it scaled was removed as a double charge. rest_ceiling caps
    # the energy rest gate (default 54) so the weak-board boost can't rest at vital >= 55, where
    # training provably cannot fail. Wit-over-rest per scenario: <scenario>_wit_over_rest / _rest_max.
    "failure_cost", "max_failure_rate", "score_command_v2", "score_failure_risk_weight",
    "rest_ceiling",
    # MANT item knobs. ankle_max_stock (1) caps held anklets per stat -- an anklet is a one-turn,
    # non-stacking buff, and the old deck-scaled cap bought 10.2/career while only 3.0 were used.
    # buy_training_applications is an EXPERIMENT switch (default off, unmeasured): turn it on only
    # after scripts/analyze_training_apps.py says the +1 training level beats 150 coins of Scrolls.
    "ankle_max_stock", "ankle_per_deck_card", "ankle_offdeck_stock",
    "buy_training_applications", "training_app_last_turn", "training_app_tier",
    "mant_wit_over_rest", "mant_wit_rest_max", "ura_wit_over_rest", "ura_wit_rest_max",
    "unity_wit_over_rest", "unity_wit_rest_max",
    "grand_live_wit_over_rest", "grand_live_wit_rest_max",
    # ---- SCENARIO-SPECIFIC KNOBS -------------------------------------------------------------
    # Everything below is read by exactly one scenario. They MUST be listed here even though the
    # scenario reads them straight off the preset: serialize_preset drops any key it does not know,
    # so an unlisted knob is silently erased the moment the preset is saved from the UI -- the value
    # works until first save, then vanishes. (This is why unity_config's four keys never did
    # anything: dropped here AND unread by run_cup_race.)
    # URA: mandatory-goal-race lock, versus-duel weight, and the fan-farm plan.
    "ura_force_races", "ura_versus_bonus",
    "ura_fan_farm", "ura_fan_farm_bond_bonus", "ura_fan_farm_speed_bonus",
    # Unity: team-race opponent policy + clock retry (see scenarios/unity.py).
    "unity_config",
    # Grand Live: song pacing/priority, the Master Square shop, Light Hello date timing, and the
    # scorer's card-density / training-plate weights.
    "grand_live_song_targets", "grand_live_song_target", "grand_live_chase_songs",
    "grand_live_song_priority", "grand_live_hold_for_song",
    "grand_live_hold_song_min_score", "grand_live_hold_song_max_turns",
    "grand_live_reward_priority", "grand_live_square_priority", "grand_live_cost_efficiency",
    "grand_live_card_weight", "grand_live_bonus_weight",
    "grand_live_light_hello", "grand_live_date_dead_score", "grand_live_date_energy_classic",
    "grand_live_date_energy_senior", "grand_live_date_energy_critical",
    "grand_live_wit_over_rest", "grand_live_wit_rest_max",
    # scenario_stat_caps (default True): use each scenario's TRAIN-TO stat ceilings (DEFAULT_STAT_CAPS
    # in scenarios/*.py, set at the game's absolute per-stat max) so the bot trains each stat up to its
    # live in-game cap instead of holding it low. False = foresight's aptitude aim decides instead.
    # Explicit stat_caps override it per stat.
    "scenario_stat_caps",
    # safety/energy/mood + misc
    # mood_floor: recreate to recover mood whenever motivation is at/below this (default 2 = Bad/Awful),
    # regardless of how good the training board is -- low mood's stat-gain penalty outvalues any board.
    "failure_hard_cap", "mood_target_recreate", "mood_recreate_max_score", "mood_floor",
    # Training safety/rescue controls are read by the brain and MANT item manager. Keep them in the
    # serializer allow-list or UI saves silently erase a user's values and restore code defaults.
    "wit_rest_skip_ratio", "rescue_good_training", "rescue_min_vital",
    "rescue_score_threshold", "rescue_vital_margin",
    # pre-summer mood: recreate on the pre-camp run-up (turns 35/36/59/60) until motivation reaches
    # pre_summer_target (default 5 = Great), so camp training runs at the max mood multiplier.
    # precamp_rest_vital: pre-camp energy floor (default 30) -- below it REST to bank energy; above it a
    # Wit training is a better "soft rest" (recovers ~5 energy + gives stat) so we don't rest eagerly.
    "pre_summer_mood", "pre_summer_target", "precamp_rest_vital",
    # camp_recreate_below_great: mid-Lv5-camp, only recreate when mood is BELOW Great (default on). At
    # Great (5) a camp already maxes mood, so recreating wastes the turn -- REST/Wit-train instead.
    "camp_recreate_below_great",
    "junior_bond_rush", "buy_notepads", "ura_force_races",
    # safety net (default ON): after LOSING a maiden while still winless, force a maiden race every
    # turn (ahead of training, behind mandatory goal/fan races) until the trainee's first win, then
    # resume normal training. Set false to disable.
    "force_maiden_until_win", "never_skip_scheduled", "summer_race_fallback",
    # non-MANT schedule opt-in: honor extra_race_list on top of career goals (URA/Unity)
    "use_race_schedule",
    # skip a scheduled race on bad aptitude / 3rd race in a row / near a goal race / bad mood
    # (default: on for Grand Live, off elsewhere -- see RACE_POLICY["optional_race_guard"])
    "optional_race_guard",
    # Aoharu (Unity Cup) phase-weighted training value: per-phase {arrows, building, rainbow, burst}
    # weights (early/mid/end) -- prefer rainbows/soul-bursts, de-emphasize raw stats + bond-building late.
    "unity_phase_weights",
    # Unity rest rule: only train when failure < unity_failure_max (default 8%), else rest to protect
    # energy -- with keep-training exceptions (train through the risk): after unity_keep_train_after_turn
    # (32) a Wit training with >= unity_keep_train_rainbow (2) rainbows, or any training with
    # >= unity_spirit_keep_train (2) Aoharu soul bursts. failure_rest_threshold = the base (non-Unity) ceiling.
    "unity_failure_max", "unity_keep_train_after_turn", "unity_keep_train_rainbow",
    "unity_spirit_keep_train", "failure_rest_threshold",
    # Unity Wit-over-rest: on a turn the brain would REST, train Wit instead when its failure is below
    # unity_wit_rest_max (default 10%) -- Wit recovers energy + builds Unity's 1800 Wit cap. Off via
    # unity_wit_over_rest=false.
    "unity_wit_over_rest", "unity_wit_rest_max",
    # fixed Sirius/Throne group-deck recreation schedule -- without these the knobs were silently
    # stripped here, so a preset override could never reach the strategy at runtime.
    "sirius_throne_schedule", "summer_all_out", "climax_all_out", "dump_recreation_debug", "sirius_throne_card_outing",
    "sirius_throne_junior_focus",
    # all-out summer camp on item-less scenarios (URA/Unity): train a positive Lv5 board when failure
    # is at or below this % (default 40); above it, rest to recover for the next camp turn instead.
    "camp_failure_cap",
    # skill-hint ('!') training priority: prioritise hint facilities BEFORE Senior (they discount the
    # end-career skill buy), then stop. hint_priority_until_turn (49 = Senior start = the cutoff),
    # hint_presenior_boost (2.0 = how much to weight hints pre-senior), hint_count_scale (0.5).
    "hint_priority_until_turn", "hint_presenior_boost", "hint_count_scale",
    # one mandatory pre-debut recreation (mood bank): junior_recreation on/off, max_partners (weak-board
    # threshold), last_turn (the forced fallback turn).
    "junior_recreation", "junior_recreation_max_partners", "junior_recreation_last_turn",
    # End-of-career inheritance sparks. spark_priority_* = how much each spark COLOUR is worth (0-5,
    # 0 = ignore): blue stat / pink aptitude / green unique / white skill. spark_reroll (default OFF)
    # SPENDS 30 TP per reroll -- spark_reroll_max caps how many, spark_reroll_tp_floor is TP to keep back.
    "spark_priority_blue", "spark_priority_pink", "spark_priority_green", "spark_priority_white",
    "spark_reroll", "spark_reroll_max", "spark_reroll_tp_floor",
    # Goal ENTRY-fan guard (default ON): race to earn the fans an upcoming goal race needs to ENTER,
    # but ONLY on a real deficit, only within fan_farm_window turns of that goal, and only on a race
    # the trainee can actually run (surface + distance). Set fan_eligibility_farm False to disable.
    "fan_eligibility_farm", "fan_farm_junior_g1_only", "fan_farm_window",
    # Default-on switches the code documents as preset-controlled (an explicit false turns each off):
    # Unity goal-race lock, Make Debut clock retry, the AI train-to-win nudge (+ its weight), the AI
    # race-value policy, waiting for a free mood bonus, and foresight's deck stat policy.
    "unity_force_races", "force_clock_debut", "ai_train_to_win", "ai_train_to_win_weight",
    "enable_ai_policy", "wait_for_free_bonus", "deck_stat_policy",
)

RUNNING_STYLE_APT_KEYS = {
    1: "proper_running_style_nige",    # Front Runner
    2: "proper_running_style_senko",   # Pace Chaser
    3: "proper_running_style_sashi",   # Late Surger
    4: "proper_running_style_oikomi",  # End Closer
}


def resolve_running_style(preset, chara_info):
    """Effective race running style (1-4) for an uma.

    Honors the preset's chosen style UNLESS its aptitude is poor -- then it runs the style the
    uma is actually best at (highest proper_running_style_* grade), so a preset built for one
    uma doesn't force a bad style on a borrowed/different runner. Aptitude grades are 1(G)..8(S);
    the default threshold 6 = B keeps a B+ preset style and only switches away from C-or-worse.
    Preset value 5 = "Best": ALWAYS run the uma's strongest style, whatever it is. Values 1-4 pick a
    specific style. Set preset "auto_running_style": false to always force the preset style; tune the
    threshold with "running_style_min_grade". Falls back to the raw preset style if no aptitude data."""
    raw = preset.get("running_style") if isinstance(preset, dict) else None
    try:
        pref = int(raw)
    except (TypeError, ValueError):
        pref = 0
    chara_info = chara_info or {}
    apts = {s: as_int(chara_info.get(k), 0) for s, k in RUNNING_STYLE_APT_KEYS.items()}
    if pref == 5:
        # "Best": run the highest-aptitude style (tie-break to the lower index). No aptitude data ->
        # 0 so the game keeps whatever style is currently set.
        if not any(apts.values()):
            return 0
        return max((1, 2, 3, 4), key=lambda s: (apts.get(s, 0), -s))
    if not any(apts.values()):
        return pref if pref in (1, 2, 3, 4) else 0
    if not (preset or {}).get("auto_running_style", True):
        # Explicitly opted out of auto-pick: keep the preset style verbatim (0/invalid falls
        # through to the downstream "in (1,2,3,4)" guard, leaving the game's current style).
        return pref if pref in (1, 2, 3, 4) else 0
    min_grade = as_int((preset or {}).get("running_style_min_grade"), 6)
    if pref in (1, 2, 3, 4) and apts.get(pref, 0) >= min_grade:
        return pref
    # Pick the best-aptitude style; tie-break toward the preset preference, then lower index.
    return max((1, 2, 3, 4), key=lambda s: (apts.get(s, 0), s == pref, -s))


def _resolve_scenario_id(raw):
    """Pick a preset's scenario. Defaults to MANT (4) so existing presets are unchanged;
    a preset opts into URA Finale by setting "scenario": "ura" (or 1)."""
    val = None
    if isinstance(raw, dict):
        val = raw.get("scenario")
        if val is None:
            val = raw.get("scenario_id")
    s = str(val).strip().lower() if val is not None else ""
    if s in ("1", "ura", "ura_finale", "ura finale", "urafinale", "finale"):
        return URA_SCENARIO_ID
    return MANT_SCENARIO_ID


def slugify(value):
    text = re.sub(r"[^a-zA-Z0-9._ -]+", "", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip()
    return text or "preset"


def split_csv(value):
    if isinstance(value, list):
        return value
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def normalize_skill_list(value):
    rows = value if isinstance(value, list) else []
    result = []
    for row in rows:
        if isinstance(row, list):
            parts = []
            for item in row:
                parts.extend(split_csv(item))
        else:
            parts = split_csv(row)
        if parts:
            result.append(parts)
    return result


def as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_race_list(value):
    result = []
    for item in value if isinstance(value, list) else []:
        race_id = as_int(item, None)
        if race_id is not None:
            result.append(race_id)
    return result


def serialize_preset(raw):
    data = dict(raw or {})
    serialized = {}

    serialized["name"] = slugify(data.get("name") or "preset")
    serialized["running_style"] = as_int(data.get("running_style"), 1)
    serialized["learn_skill_list"] = normalize_skill_list(data.get("learn_skill_list"))

    blacklist = []
    blacklist.extend(split_csv(data.get("blacklistedSkills")))
    blacklist.extend(split_csv(data.get("skill_blacklist")))
    blacklist.extend(split_csv(data.get("learn_skill_blacklist")))
    serialized["learn_skill_blacklist"] = list(dict.fromkeys(blacklist))

    # TIER 0: the MUST-BUY skills -- checked every turn and bought as soon as SP allows, so they are
    # active for the races still to come. Everything in learn_skill_list (tier 1, 2, ...) is instead a
    # priority order for the end-of-career dump. A flat name list like the blacklist.
    tier0 = data.get("learn_skill_tier0")
    tier0 = split_csv(tier0) if isinstance(tier0, str) \
        else [str(s).strip() for s in (tier0 or []) if str(s).strip()]
    serialized["learn_skill_tier0"] = list(dict.fromkeys(tier0))

    # BEFORE GOAL RACES: bought right before each hard career-goal race (Top 3 or better, Classic year
    # on) instead of at the end -- a lost goal ends the career, and runs went into them holding
    # 1,400-2,150 unspent SP. Same flat name list as tier 0.
    before_goal = data.get("learn_skill_before_goal")
    before_goal = split_csv(before_goal) if isinstance(before_goal, str) \
        else [str(s).strip() for s in (before_goal or []) if str(s).strip()]
    serialized["learn_skill_before_goal"] = list(dict.fromkeys(before_goal))

    serialized["extra_race_list"] = normalize_race_list(data.get("extra_race_list", data.get("race_list", [])))

    # Behavior tunables: optional knobs the strategy/scorer reads at runtime. Persist them
    # verbatim when the preset file sets them -- serialize otherwise whitelists fields, which
    # silently stripped every such knob and made the documented preset overrides unreachable.
    for key in TUNABLE_KEYS:
        if data.get(key) is not None:
            serialized[key] = data[key]

    return serialized

def hydrate_preset(raw):
    data = serialize_preset(raw)

    scenario_id = _resolve_scenario_id(raw)
    data["scenario_id"] = scenario_id
    data["scenario"] = scenario_id
    # DEFAULTS, not overrides. These used to be plain assignments, which meant a preset could never
    # change any of them: serialize_preset dropped the key (not allow-listed) and hydrate_preset then
    # force-wrote the built-in value on top. Both halves are fixed -- the keys are in TUNABLE_KEYS
    # above, and setdefault leaves a preset-supplied value alone. Anything the preset omits still
    # gets exactly the numbers that shipped, so behaviour is unchanged for every existing preset.
    # (scenario_id/scenario stay force-assigned: they are RESOLVED from the preset, not user input.)
    _DEFAULTS = {
        "cure_asap_conditions": ["Migraine", "Night Owl", "Skin Outbreak", "Slacker",
                                 "Slow Metabolism", "(Practice poor isn't worth a turn to cure)"],
        "score_value": [[0.11, 0.1, 0.006, 0.09], [0.11, 0.1, 0.006, 0.09],
                        [0.11, 0.1, 0.006, 0.09], [0.03, 0.05, 0.006, 0.09], [0, 0, 0.006, 0]],
        "base_score": [0, 0, 0, 0, 0],
        "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
        "extra_weight": [[0, 0, 0, 0, 0]] * 4,
        "npc_score_value": [[0.05, 0.05, 0.05], [0.05, 0.05, 0.05], [0.05, 0.05, 0.05],
                            [0.03, 0.05, 0.05], [0, 0, 0.05]],
        "special_training": [0.095, 0.095, 0.095, 0.095, 0],
        "spirit_explosion": [[0.16, 0.16, 0.16, 0.06, 0.11]] * 5,
        "wit_special_multiplier": [1.57, 1.37],
        "compensate_failure": True,
        "summer_score_threshold": 0.34,
        "motivation_threshold_year1": 3,
        "motivation_threshold_year2": 4,
        "motivation_threshold_year3": 4,
        "prioritize_recreation": False,
        "pal_thresholds": [],
        "pal_friendship_score": [0.08, 0.057, 0.018],
        "pal_card_multiplier": 0.1,
        "rest_threshold": 48,
        "mant_config": {},
    }
    for key, default in _DEFAULTS.items():
        data.setdefault(key, default)

    return data

class PresetStore:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.preset_dir = self.base_dir / "data" / "presets"

    def ensure(self):
        self.preset_dir.mkdir(parents=True, exist_ok=True)

    def read_all(self):
        self.ensure()
        loaded = {}
        for path in self._source_files():
            try:
                data = hydrate_preset(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
            loaded[data["name"]] = data
        return sorted(loaded.values(), key=lambda item: item["name"].lower())

    def read_one(self, name):
        wanted = str(name or "").strip().lower()
        for preset in self.read_all():
            if preset["name"].lower() == wanted:
                return preset
        return None

    def write(self, preset):
        self.ensure()
        serialized_data = serialize_preset(preset)
        path = self.preset_dir / f"{slugify(serialized_data['name'])}.json"
        path.write_text(json.dumps(serialized_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return hydrate_preset(serialized_data)

    def delete(self, name):
        path = self.preset_dir / f"{slugify(name)}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def _source_files(self):
        if self.preset_dir.exists():
            return list(self.preset_dir.glob("*.json"))
        return []
