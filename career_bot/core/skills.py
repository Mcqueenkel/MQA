import json
import re
from pathlib import Path
from career_bot.core.presets import resolve_running_style
from career_bot.core.data_store import DataStore
from career_bot.core.delay import server_sleep

# Skill tag taxonomy (decoded from skill_data.json 'tags'): 101-104 = running style
# (Front/Pace/Late/End), 201-204 = distance (sprint/mile/middle/long). A skill carrying a
# style or distance tag only activates for that style/distance; effect-only skills (4xx) are
# style/distance-agnostic and always fit. Used to avoid spending SP on skills that can't fire.
STYLE_TAG = {1: 101, 2: 102, 3: 103, 4: 104}
DISTANCE_TAG_KEYS = {
    "proper_distance_short": 201,
    "proper_distance_mile": 202,
    "proper_distance_middle": 203,
    "proper_distance_long": 204,
}
STYLE_TAGS_ALL = frozenset(STYLE_TAG.values())
DISTANCE_TAGS_ALL = frozenset(DISTANCE_TAG_KEYS.values())

MARK_WHITE_CIRCLE = "○"
MARK_DOUBLE_CIRCLE = "◎"
MARK_X = "×"
MARK_LARGE_CIRCLE = "◯"
MOJI_WHITE_CIRCLE = "â—‹"
MOJI_LARGE_CIRCLE = "â—¯"
MOJI_DOUBLE_CIRCLE = "â—Ž"
MOJI_X = "Ã—"

SKILL_LEARN_PRIORITY_LIST = [
    [
        'Corner Acceleration ○', 'Corner Adept ○', 'Slipstream', 'Tail Held High',
        'Straightaway Spurt', 'Ramp Up', 'Inside Scoop', 'Passing Pro', 'Homestretch Haste',
        'Fast-Paced', 'Outer Swell', 'Sprinting Gear', 'Slick Surge', 'Corner Recovery ○',
        'Hydrate', 'After-School Stroll', 'Clean Heart', 'Dominator', 'All-Seeing Eyes', 'Mystifying Murmur'
    ],
    [
        'Acceleration', 'Focus', 'Go with the Flow', 'I Can See Right Through You',
        'Nimble Navigator', 'Straightaway Recovery', 'Deep Breaths', 'Preferred Position',
        'Groundwork', 'Up-Tempo', 'Unyielding Spirit', 'Pressure', 'Strategist', 'Triple 7s',
        'Shake It Out', 'Intimidate', 'Stamina Eater', 'Intense Gaze', 'Speed Star',
        'Staggering Lead', 'Blinding Flash', 'Restless', 'Trackblazer', 'Meticulous Measures',
        'Keeping the Lead', 'Leader\'s Pride', 'Wait-and-See', 'A Small Breather'
    ],
    [
        'Levelheaded', 'Stop Right There!', 'Super Lucky Seven', 'Maverick ○', 'Sympathy',
        'Long Shot ○', 'Inner Post Proficiency ○', 'Outer Post Proficiency ○', 'Right-Handed ○',
        'Left-Handed ○', 'Firm Conditions ○', 'Wet Conditions ○', 'Standard Distance ○',
        'Non-Standard Distance ○', 'Competitive Spirit ○', 'Target in Sight ○', 'Lone Wolf'
    ]
]


def norm(text):
    return re.sub(r'[^a-z0-9]+', '', str(text or '').lower())


def strip_mark(text):
    if not text:
        return ""
    for m in [MARK_WHITE_CIRCLE, MARK_DOUBLE_CIRCLE, MARK_X, MARK_LARGE_CIRCLE,
              MOJI_WHITE_CIRCLE, MOJI_DOUBLE_CIRCLE, MOJI_X, MOJI_LARGE_CIRCLE]:
        text = text.replace(m, "")
    return text.strip()


class SkillBuyer:
    def __init__(self, base_dir, data_store=None):
        self.base_dir = Path(base_dir)
        self.data_store = data_store or DataStore(base_dir)
        self.skill_names = {}
        self.skill_rarities = {}
        self.skill_costs = {}
        self.skill_grade_values = {}
        self.skill_tags = {}
        self.skill_id_exists = set()
        self.group_to_skill_ids = {}
        self.skill_to_group_id = {}
        self.failed_this_turn = {}
        # Skills SUCCESSFULLY bought this career. The state-based owned check (_owns_equal_or_better
        # reading chara_info.skill_array) cannot see them: gain_skills' response does not return an
        # updated skill_array, so after a successful batch the very same skills still look unowned and
        # the next pass re-sends them -- the server then 205s the whole batch because they ARE owned.
        # Observed live (career_log_20260730_232514 t78): batch 1 = 14 skills rc=1, batch 2 = the same
        # 14 skills rc=205. Career-scoped, same as failed_this_career.
        self.bought_this_career = set()
        # Skills the server REFUSED during this career's mid-run buys. Career-scoped on purpose:
        # failed_this_turn is wiped by _set_turn on every turn change AND by reset_scoped_failures on
        # every post-error reload, so neither can stop a doomed skill being retried turn after turn.
        # The runner builds a fresh SkillBuyer per career (runner.start), so this set is per-career.
        # The end-of-career dump ignores it.
        self.failed_this_career = set()
        self.current_turn = None
        self.last_candidates = []
        self.last_selected = []
        self.last_attempt = []
        self.last_result = {}
        self.recover_after_error = False
        self.attempt_events = []
        self._load()

    def _load(self):
        data = self.data_store.skill_data()
        if not data:
            return
        try:
            self.skill_names = {}
            self.skill_rarities = {}
            self.skill_costs = {}
            self.skill_grade_values = {}
            self.skill_tags = {}
            self.skill_to_group_id = {}
            for raw_id, raw_info in data.items():
                skill_id = int(raw_id)
                if isinstance(raw_info, dict):
                    self.skill_names[skill_id] = raw_info.get("name") or str(skill_id)
                    self.skill_rarities[skill_id] = int(raw_info.get("rarity") or 0)
                    self.skill_costs[skill_id] = int(raw_info.get("need_skill_point") or 0)
                    self.skill_grade_values[skill_id] = int(raw_info.get("grade_value") or 0)
                    tags = raw_info.get("tags")
                    self.skill_tags[skill_id] = [int(t) for t in tags] if isinstance(tags, list) else []
                    group_id = int(raw_info.get("group_id") or 0)
                    if group_id:
                        self.skill_to_group_id[skill_id] = group_id
                else:
                    self.skill_names[skill_id] = raw_info
        except Exception:
            return
        self.skill_id_exists = set(self.skill_names)
        self.group_to_skill_ids = {}
        for skill_id in self.skill_names:
            group_id = self.skill_to_group_id.get(skill_id) or (skill_id if skill_id < 100000 else skill_id // 10)
            self.skill_to_group_id[skill_id] = group_id
            self.group_to_skill_ids.setdefault(group_id, []).append(skill_id)
        
        for group_id, ids in self.group_to_skill_ids.items():
            children = [sid for sid in ids if sid >= 100000]
            if children:
                self.group_to_skill_ids[group_id] = sorted(children, key=self._tier_sort_key)
            else:
                self.group_to_skill_ids[group_id] = sorted(ids, key=self._tier_sort_key)

    def _tier_sort_key(self, skill_id):
        grade_value = int(self.skill_grade_values.get(skill_id) or 0)
        return (
            int(self.skill_rarities.get(skill_id) or 99),
            1 if grade_value <= 0 else 0,
            grade_value if grade_value > 0 else 999999,
            int(skill_id),
        )

    def _tier_ids(self, group_id, rarity):
        ids = [
            sid for sid in self.group_to_skill_ids.get(group_id, [])
            if self.skill_rarities.get(sid, 0) == rarity and self.skill_grade_values.get(sid, 0) > 0
        ]
        return sorted(ids, key=self._tier_sort_key)

    def _max_owned_grade_in_group(self, group_id, owned_skill_ids):
        """Highest grade_value the uma already owns within this skill group, or -1 if none.
        A skill group is one logical skill with upgrade tiers (e.g. ○ -> ◎); owning a tier
        means everything at that grade or lower is already covered."""
        grades = [
            self.skill_grade_values.get(sid, 0)
            for sid in self.group_to_skill_ids.get(group_id, [])
            if sid in owned_skill_ids
        ]
        return max(grades) if grades else -1

    def _owns_equal_or_better(self, skill_id, owned_skill_ids):
        """True if the uma already owns this skill's group at an equal-or-higher tier (>= grade).
        Re-buying a lower/equal tier is a no-op the game still CHARGES SP for, so it must never
        be attempted -- this was silently draining nearly all SP on already-owned skills."""
        skill_id = int(skill_id or 0)
        group_id = self.skill_to_group_id.get(skill_id)
        if not group_id:
            return False
        return self.skill_grade_values.get(skill_id, 0) <= self._max_owned_grade_in_group(group_id, owned_skill_ids)

    def _resolve_buyable_tier(self, group_id, rarity, owned_skill_ids):
        tiers = self._tier_ids(group_id, rarity)
        if not tiers:
            candidates = [
                sid for sid in self.group_to_skill_ids.get(group_id, [])
                if self.skill_rarities.get(sid, 0) == rarity and sid not in owned_skill_ids
            ]
            return sorted(candidates, key=self._tier_sort_key)[0] if candidates else 0
        # Offer the lowest unowned tier that is a genuine UPGRADE over what's already owned
        # (grade strictly above the best owned tier in this group). Tiers at or below the owned
        # grade are skipped -- buying them does nothing but still spends SP.
        max_owned_grade = self._max_owned_grade_in_group(group_id, owned_skill_ids)
        for sid in tiers:
            if sid in owned_skill_ids:
                continue
            if self.skill_grade_values.get(sid, 0) <= max_owned_grade:
                continue
            return sid
        return 0

    def _unowned_white_tiers(self, group_id, owned_skill_ids):
        return [sid for sid in self._tier_ids(group_id, 1) if sid not in owned_skill_ids]

    def reset_scoped_failures(self):
        # Called on a post-error RELOAD, not per career -- so failed_this_career is deliberately NOT
        # cleared here. Clearing it would un-latch the skill the reload was triggered by and put the
        # retry storm straight back.
        self.failed_this_turn = {}
        self.current_turn = None
        self.last_candidates = []
        self.last_selected = []
        self.last_attempt = []
        self.last_result = {}

    def _set_turn(self, turn):
        turn = int(turn or 0)
        if self.current_turn != turn:
            self.current_turn = turn
            self.failed_this_turn = {turn: set()}
        self.failed_this_turn.setdefault(turn, set())

    def _failed_for_turn(self, turn=None):
        turn = int(turn if turn is not None else self.current_turn or 0)
        return self.failed_this_turn.setdefault(turn, set())

    def _buy_tier0_now(self, client, state, chara, preset, points, turn):
        """TIER 0 ("must buy") purchases, made DURING the career as soon as SP allows.

        Deliberately restricted to learn_skill_tier0. The whole point of a tier-0 pick is that the
        skill is ACTIVE for the races the rest of the career still has to run, so it must not wait for
        the finish dump. learn_skill_list (tier 1, 2, ...) is excluded here on purpose: that list is a
        PRIORITY ORDER for the end-of-career dump, not an in-run shopping list, and deferring it lets
        SP pool while hint levels climb and skills get cheaper.

        No SP reservation: everything here is user-flagged must-buy, so take whatever is affordable
        now and let the rest land on a later turn as SP accrues.
        """
        # BUY-THROUGHOUT mode (URA fan farm): the plan is "buy skills all the time" -- skills win the
        # races, and the races ARE the fans, so a skill sitting unbought until turn 78 has done
        # nothing. This opens the mid-run buy to the user's whole list (tier 0 AND learn_skill_list)
        # instead of tier 0 only. Off by default: every other run still banks SP for the end dump.
        buy_all = bool((preset or {}).get("skill_buy_throughout", False))
        if not buy_all and not self._tier0(preset):
            self.last_candidates = []
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "no_tier0", "turn": turn}
            return state, 0
        # Empty learn_skill_list => _priority_rows is [tier0] alone, so _candidates keeps ONLY tier-0
        # names (everything else scores priority 999 and is filtered out by only_user_provided).
        scope = {**preset, "learn_skill_only_user_provided": True}
        if not buy_all:
            scope["learn_skill_list"] = []
        listed = [c for c in self._candidates(chara, scope)
                  if int(c.get("skill_id") or 0) not in self.failed_this_career]
        self.last_candidates = [dict(c) for c in listed]
        self.last_attempt = []
        if not listed:
            self.last_selected = []
            self.last_result = {"skip": "tier0_none_available", "points": points, "turn": turn}
            return state, 0
        selected, spent = [], 0
        for c in listed:
            cost = int(c.get("cost") or self._estimate_cost(c))
            if spent + cost <= points:
                selected.append(c)
                spent += cost
        self.last_selected = [dict(c) for c in selected]
        if not selected:
            self.last_result = {"skip": "tier0_not_enough_points", "points": points, "turn": turn}
            return state, 0
        # retry_205=0: a mid-run 205 is "not sellable right now", not a transient fault.
        state, bought = self._buy_batch(client, state, selected, turn, retry_205=0)
        if not bought:
            # LATCH THE FAILURE FOR THE REST OF THE CAREER. failed_this_turn is wiped by _set_turn on
            # every new turn, so without this the same refused skill is re-attempted every single turn
            # -- 78 doomed gain_skills calls instead of 1, which trips the circuit breaker outright
            # (observed live: "6 server errors within 90s" -> auto-backoff mid-career).
            # The career-END dump ignores this latch and still tries everything, so nothing is lost:
            # by then SP is higher and the state is freshly reloaded.
            self.failed_this_career.update(int(c.get("skill_id") or 0) for c in selected)
        return state, bought

    @staticmethod
    def _before_goal(preset):
        """The preset's BEFORE GOAL RACES skill names (Skills tab section)."""
        return [s for s in ((preset or {}).get("learn_skill_before_goal") or []) if s]

    def buy_before_goal(self, client, state, preset):
        """Buy the BEFORE GOAL RACES skills that fit this trainee and are affordable now. The runner
        calls it right before a hard career-goal race, so they are active for that race (and every
        race after it) while hints kept lowering their cost until then. Returns (state, bought)."""
        self.attempt_events = []
        self.recover_after_error = False
        names = self._before_goal(preset)
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        if not names or not chara:
            return state, 0
        points = int(chara.get("skill_point") or 0)
        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)
        scope = {**preset, "learn_skill_only_user_provided": True, "learn_skill_tier0": names,
                 "learn_skill_list": []}
        # fits=False = tagged for a running style / distance this trainee can't use: never activates
        listed = [c for c in self._candidates(chara, scope)
                  if c.get("fits", True) and int(c.get("skill_id") or 0) not in self.failed_this_career]
        selected, spent = [], 0
        for c in listed:
            cost = int(c.get("cost") or self._estimate_cost(c))
            if spent + cost <= points:
                selected.append(c)
                spent += cost
        self.last_candidates = [dict(c) for c in listed]
        self.last_selected = [dict(c) for c in selected]
        if not selected:
            self.last_result = {"skip": "before_goal_none_affordable", "points": points, "turn": turn}
            return state, 0
        state, bought = self._buy_batch(client, state, selected, turn, retry_205=0)
        if not bought:
            # same latch as the tier-0 buy: a refused skill isn't re-sent before every later goal
            self.failed_this_career.update(int(c.get("skill_id") or 0) for c in selected)
        return state, bought

    def buy(self, client, state, preset, force=False):
        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        self.recover_after_error = False
        self.attempt_events = []
        if not chara:
            return state, 0

        points = int(chara.get("skill_point") or 0)
        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)

        # TIER 0 = must-buy, bought DURING the run; TIER 1+ = end-of-career priority order.
        #
        # Checked EVERY turn, not on a cadence. The old need_check_interval gate (default 24) only
        # looked at turns 24/48/72, which meant a tier-0 skill that became affordable at turn 30 sat
        # unbought until 48, and one that was short of SP at all three checkpoints fell through to the
        # finish dump -- where it does nothing, because the career's races are already run. Measured on
        # 25 careers: 69% of all skills (517/751) were bought at turn 78. A tier-0 pick is bought for
        # the races it is supposed to WIN, so it is taken the moment SP covers it.
        if not force:
            return self._buy_tier0_now(client, state, chara, preset, points, turn)

        # Career-end dump: buy the user's listed/tier skills first (TIER 0 -> 1 -> 2 ...), then spend
        # leftover SP on any OTHER buyable skill (default) so a finished career never wastes SP or ends
        # with 0 skills bought -- the important/listed skills keep their place at the front, so the
        # relaxed extras are reached only once nothing better is left. Set skill_dump_leftover=false to
        # buy ONLY the user's tiers (then it buys nothing when the tiers are empty/already owned).
        candidates = self._candidates(chara, {**preset, "learn_skill_only_user_provided": True})
        if preset.get("skill_dump_leftover", True):
            seen = {c["skill_id"] for c in candidates}
            unlisted, blacklisted = [], []
            for bucket, relaxed in (
                (unlisted, {**preset, "learn_skill_only_user_provided": False, "skill_fit_gate": False}),
                (blacklisted, {**preset, "learn_skill_only_user_provided": False, "learn_skill_blacklist": [], "skill_fit_gate": False}),
            ):
                for extra in self._candidates(chara, relaxed):
                    if extra["skill_id"] not in seen:
                        seen.add(extra["skill_id"])
                        bucket.append(extra)
            # The user's order: their own tiers, then GOLD skills, then the rest. The leftover sort put
            # every unlisted ○ (priority 500) and cheap white (best grade per SP) ahead of golds: on
            # 2026-10-20 a front runner was offered Top Runner in 7 of 10 careers and never bought it.
            # Only golds this uma can use jump the queue; wrong-style ones stay with the rest.
            golds = [c for c in unlisted
                     if c.get("fits", True) and self.skill_rarities.get(int(c["skill_id"])) == 2]
            candidates += golds + [c for c in unlisted if c not in golds] + blacklisted

        self.last_candidates = [dict(item) for item in candidates]
        if not candidates:
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "no_candidates", "points": points}
            return state, 0

        # End-of-career dump: no SP reservation -- spend greedily in priority order so listed
        # (lowest-priority-number) skills are bought first, then leftover SP fills in the rest.
        selected = []
        spent = 0
        in_batch = set()
        for candidate in candidates:
            if candidate["skill_id"] in in_batch:
                continue                     # already in this batch as a gold's white prerequisite
            cost = int(candidate.get("cost") or self._estimate_cost(candidate))
            # A gold's price includes its unowned white. If that white is already in this batch (Top
            # Runner after a listed Leader's Pride), drop it from the bundle and its price from the
            # cost -- it was counted twice, making the gold look 180 SP dearer than it is.
            bundled = candidate.get("bundled_skill_ids") or []
            cost -= sum(self._estimate_cost({"skill_id": b, "hint_level": 0}) for b in bundled if b in in_batch)
            if spent + cost <= points:
                kept = [b for b in bundled if b not in in_batch]
                selected.append({**candidate, "cost": cost, "bundled_skill_ids": kept})
                spent += cost
                in_batch.update([candidate["skill_id"], *kept])

        if not selected:
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "not_enough_points", "points": points}
            return state, 0

        self.last_selected = [dict(item) for item in selected]
        
        current_state, total_bought = self._buy_batch(client, state, selected, turn)
            
        return current_state, total_bought

    def preview(self, state, preset, force=False):
        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        if not chara:
            self.last_candidates = []
            self.last_selected = []
            return
        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)
        points = int(chara.get("skill_point") or 0)
        # Mirror buy(): the per-turn preview shows the TIER 0 skills affordable NOW (the only ones
        # bought during the run). Tier 1+ is previewed under force=True with the end-of-career dump.
        if not force:
            listed = ([] if not self._tier0(preset) else
                      self._candidates(chara, {**preset, "learn_skill_only_user_provided": True,
                                               "learn_skill_list": []}))
            selected, spent = [], 0
            for c in listed:
                cost = int(c.get("cost") or self._estimate_cost(c))
                if spent + cost <= points:
                    selected.append(c)
                    spent += cost
            self.last_candidates = [dict(c) for c in listed]
            self.last_selected = [dict(c) for c in selected]
            return
        candidates = self._candidates(chara, preset)
        # End-of-career dump only: no reservation needed.
        must_buy_ids = set()
        selected = []
        spent = 0
        reserved_priority = None
        for candidate in candidates:
            priority = int(candidate.get("priority") or 999)
            if reserved_priority is not None and priority > reserved_priority:
                break
            cost = int(candidate.get("cost") or self._estimate_cost(candidate))
            if spent + cost <= points:
                selected.append(candidate)
                spent += cost
            elif candidate["skill_id"] in must_buy_ids and reserved_priority is None:
                reserved_priority = priority
        self.last_candidates = [dict(item) for item in candidates]
        self.last_selected = [dict(item) for item in selected]

    def _priority(self, rows):
        result = {}
        for index, row in enumerate(rows):
            for name in row:
                key = norm(name)
                result[key] = min(index, result.get(key, index))
        return result

    def _priority_value(self, skill_id, name, base_name, priority):
        values = [priority.get(str(skill_id)), priority.get(norm(name)), priority.get(norm(base_name))]
        values = [v for v in values if v is not None]
        return min(values) if values else 999

    @staticmethod
    def _tier0(preset):
        """TIER 0 skill names -- the user's MUST-BUY picks: bought during the run (checked every
        turn, taken as soon as SP allows) and ranked ABOVE every normal tier in the end dump."""
        return [s for s in ((preset or {}).get("learn_skill_tier0") or []) if s]

    def _priority_rows(self, preset):
        """learn_skill_list rows with TIER 0 prepended as the top (highest-priority) row, so a tier-0
        skill outranks every listed tier in the candidate ordering."""
        rows = list(preset.get("learn_skill_list") or [])
        tier0 = self._tier0(preset)
        return ([tier0] + rows) if tier0 else rows

    def _priority_context(self, preset):
        rows = self._priority_rows(preset)
        if not rows and not preset.get("learn_skill_only_user_provided"):
            rows = SKILL_LEARN_PRIORITY_LIST
        return self._priority(rows)

    def _user_listed_candidates(self, candidates, preset):
        """Candidates the user EXPLICITLY put in the preset's learn_skill_list (NOT the
        built-in default SKILL_LEARN_PRIORITY_LIST that fills in when the list is empty).
        These are the "must buy" skills -- they sort to the front of the end-of-career dump so
        they're bought first, before leftover SP is spent on anything else."""
        user_priority = self._priority(self._priority_rows(preset))
        if not user_priority:
            return []
        listed = []
        for candidate in candidates:
            name = candidate.get("name") or ""
            if self._priority_value(candidate["skill_id"], name, strip_mark(name), user_priority) < 999:
                listed.append(candidate)
        return listed

    def _blacklist(self, preset):
        return {norm(item) for item in preset.get("learn_skill_blacklist") or []}

    def _uma_fit_profile(self, chara, preset):
        """(style_tag, set-of-apt-distance-tags) describing what this uma can actually race,
        for skill-fit checks. style_tag is None if the style is unknown; an empty distance set
        means 'no aptitude data' and disables the distance check. Distance aptitude grades are
        1(G)..8(S); default threshold 6 = B (tunable via preset skill_fit_distance_min_grade)."""
        style_tag = STYLE_TAG.get(resolve_running_style(preset, chara))
        try:
            min_grade = int((preset or {}).get("skill_fit_distance_min_grade") or 6)
        except (TypeError, ValueError):
            min_grade = 6
        dist_tags = {tag for key, tag in DISTANCE_TAG_KEYS.items()
                     if int((chara or {}).get(key) or 0) >= min_grade}
        return style_tag, dist_tags

    def _skill_fits(self, skill_id, style_tag, dist_tags):
        """False only when a skill is tagged for a running style this uma does not run, or for
        distances it isn't apt at -- i.e. it physically can't/won't activate. Effect-only skills
        (no style/distance tag) always fit. Unknown style/empty distance set disables that half.
        Used for the SOFT candidate-sort demotion (D), which checks both style and distance."""
        tags = self.skill_tags.get(int(skill_id) or 0) or []
        style_in = [t for t in tags if t in STYLE_TAGS_ALL]
        if style_in and style_tag and style_tag not in style_in:
            return False
        dist_in = [t for t in tags if t in DISTANCE_TAGS_ALL]
        if dist_in and dist_tags and not (set(dist_in) & dist_tags):
            return False
        return True

    def _skill_style_conflicts(self, skill_id, style_tag):
        """True only when a skill is tagged for a DIFFERENT running style than the uma runs --
        a HIGH-confidence 'will never activate' signal, since an uma runs exactly one style.
        This (not the broader _skill_fits) is what the gold-skip GATE uses: distance mismatch is
        deliberately NOT a skip reason, because the career's race schedule can include distances
        the uma is only mid/low-apt at, and many distance-tagged golds are debuffs/recovery worth
        buying anyway. Distance mismatch stays a soft demotion in the candidate sort instead."""
        if not style_tag:
            return False
        style_in = [t for t in (self.skill_tags.get(int(skill_id) or 0) or []) if t in STYLE_TAGS_ALL]
        return bool(style_in) and style_tag not in style_in

    def _candidates(self, chara, preset):
        owned = {int(item.get("skill_id") or 0) for item in chara.get("skill_array") or []}
        owned_groups = {self.skill_to_group_id.get(skill_id, skill_id // 10) for skill_id in owned}
        priority = self._priority_context(preset)
        blacklist = self._blacklist(preset)
        style_tag, dist_tags = self._uma_fit_profile(chara, preset)
        result = []
        for tip in chara.get("skill_tips_array") or []:
            resolved = self.resolve_skill_tip(tip, owned, owned_groups, priority, blacklist, preset,
                                              style_tag=style_tag, dist_tags=dist_tags)
            if not resolved or resolved.get("skip_reason"):
                continue
            sid = resolved["resolved_skill_id"]
            grade_value = int(self.skill_grade_values.get(sid, 0))
            cost = int(resolved["cost"] or 0)
            result.append({
                "skill_id": sid,
                "group_id": resolved["group_id"],
                "tip_rarity": resolved["tip_rarity"],
                "hint_level": resolved["hint_level"],
                "name": resolved["resolved_name"],
                "priority": resolved["priority"],
                "cost": resolved["cost"],
                "grade_value": grade_value,
                "fits": self._skill_fits(sid, style_tag, dist_tags),
                "value_per_sp": grade_value / max(cost, 1),
                "bundled_skill_ids": resolved.get("bundled_skill_ids") or [],
                "resolution_reason": resolved["resolution_reason"],
                "failed_scope": resolved["failed_scope"],
                "candidate_skill_ids": resolved["candidate_skill_ids"],
            })
        # Order: user-priority first (unchanged), then skills that actually fit this uma's
        # style/distance, then best value-per-SP (grade_value/cost) instead of merely cheapest,
        # then richer hints, then id. So leftover/default SP buys the strongest ACTIVATING skills.
        result.sort(key=lambda item: (
            item["priority"],
            0 if item.get("fits", True) else 1,
            -item.get("value_per_sp", 0.0),
            -item["hint_level"],
            item["skill_id"],
        ))
        
        deduped = []
        seen = set()
        for item in result:
            if item["skill_id"] not in seen:
                seen.add(item["skill_id"])
                deduped.append(item)
        result = deduped
        
        if preset.get("learn_skill_only_user_provided"):
            if not any(row for row in (preset.get("learn_skill_list") or [])) and not self._tier0(preset):
                return []
            # Only skills that matched the user's own rows. resolve_skill_tip gives every UNLISTED
            # circle hint priority 500 ("circle_variant"), so 'priority < 999' let them all through:
            # the mid-run tier-0 buy spent 631-1,090 SP a career on unlisted ○ skills (Cloudy Days,
            # Right-Handed, Pace Chaser Savvy on a front runner). The end dump still reaches them via
            # its relaxed leftover pass, where circle hints keep their 500 head start.
            return [item for item in result if item["resolution_reason"] == "priority_match"]
        return result

    def resolve_skill_tip(self, tip, owned_skill_ids, owned_groups, priority, blacklist, preset,
                          style_tag=None, dist_tags=None):
        group_id = int(tip.get("group_id") or 0)
        tip_rarity = int(tip.get("rarity") or 0)
        hint_level = int(tip.get("level") or 0)
        failed = self._failed_for_turn()
        if tip_rarity:
            buyable_tier = self._resolve_buyable_tier(group_id, tip_rarity, owned_skill_ids)
            candidate_skill_ids = [buyable_tier] if buyable_tier else []
        else:
            candidate_skill_ids = [
                sid for sid in self.group_to_skill_ids.get(group_id, [])
                if sid not in owned_skill_ids
            ]
        
        row = {
            "group_id": group_id,
            "tip_rarity": tip_rarity,
            "hint_level": hint_level,
            "candidate_skill_ids": list(candidate_skill_ids),
            "resolved_skill_id": 0,
            "resolved_name": "",
            "cost": 0,
            "priority": 999,
            "resolution_reason": "",
            "master_exists": False,
            "skip_reason": None,
            "failed_scope": None,
        }
        if not candidate_skill_ids:
            row["skip_reason"] = "unknown_master"
            return row

        usable = [sid for sid in candidate_skill_ids if sid not in failed]
        if not usable:
            row["skip_reason"] = "failed_this_turn"
            row["failed_scope"] = "this_turn"
            return row

        normal = [sid for sid in usable if not (self.skill_names.get(sid, "").endswith(MARK_X) or self.skill_names.get(sid, "").endswith(MOJI_X))]
        if not normal:
            row["skip_reason"] = "no_normal_skills"
            return row

        normal.sort(key=self._tier_sort_key)
        resolved = normal[0]
        name = self.skill_names.get(resolved, "")
        
        best_priority = 999
        reason = "first_valid_variant"
        
        for sid in normal:
            s_name = self.skill_names.get(sid, "")
            base_name = strip_mark(s_name)
            if norm(s_name) in blacklist or norm(base_name) in blacklist:
                row["skip_reason"] = "blacklist"
                return row
            p_val = self._priority_value(sid, s_name, base_name, priority)
            if p_val < best_priority:
                best_priority = p_val
                reason = "priority_match"
                
        if best_priority == 999:
            for sid in normal:
                s_name = self.skill_names.get(sid, "")
                if any(s_name.endswith(m) for m in [MARK_WHITE_CIRCLE, MARK_LARGE_CIRCLE, MOJI_WHITE_CIRCLE, MOJI_LARGE_CIRCLE]):
                    best_priority = 500
                    reason = "circle_variant"
                    break

        # A skill tagged for a running style this uma doesn't run never activates, even when the
        # preset lists it (a Front Runner preset on a Pace Chaser). Treat it as unlisted so the
        # fitting skills are bought first; the end dump can still spend leftover SP on it.
        if self._skill_style_conflicts(resolved, style_tag):
            best_priority = 999
            reason = "style_conflict"

        if not name:
            row["skip_reason"] = "unknown_master"
            return row
            
        is_double = name.endswith(MARK_DOUBLE_CIRCLE) or name.endswith(MOJI_DOUBLE_CIRCLE)
        if preset.get("skip_double_circle_unless_high_hint", False) and is_double and hint_level < 4:
            row["skip_reason"] = "rule_rejected"
            return row

        row["resolved_skill_id"] = resolved
        row["resolved_name"] = name
        # E: don't pay the gold premium + white bundle for a GOLD skill tagged for a running
        # style this uma does NOT run (it can never activate). Only when not user-listed and the
        # gate is on; the end-of-career SP dump passes skill_fit_gate=False so leftover SP can
        # still grab any grade_value. Uses STYLE conflict only (high-confidence) -- a distance
        # mismatch is left to the soft sort demotion so off-aptitude debuff/recovery golds and
        # races at non-apt distances aren't wrongly skipped. Cheap mismatched whites aren't
        # gated either; the _candidates sort already sinks non-fitting skills below fitting ones.
        if (preset.get("skill_fit_gate", True) and best_priority >= 999
                and self.skill_rarities.get(resolved, 0) == 2
                and self._skill_style_conflicts(resolved, style_tag)):
            row["skip_reason"] = "skill_fit"
            return row
        bundled_skill_ids = []
        cost = self._estimate_cost({"skill_id": resolved, "hint_level": hint_level, "name": name})
        if self.skill_rarities.get(resolved, 0) == 2:
            bundled_skill_ids = self._unowned_white_tiers(group_id, owned_skill_ids)
            for bundled_id in bundled_skill_ids:
                cost += self._estimate_cost({
                    "skill_id": bundled_id,
                    "hint_level": 0,
                    "name": self.skill_names.get(bundled_id, ""),
                })

        row["priority"] = best_priority
        row["cost"] = cost
        row["bundled_skill_ids"] = bundled_skill_ids
        row["resolution_reason"] = reason
        row["master_exists"] = resolved in self.skill_id_exists
        if resolved in failed:
            row["failed_scope"] = "this_turn"

        return row

    # Recursion bound for the 205 bisection in the error path below. 4 levels resolves a 16-skill
    # batch down to single skills; total calls stay ~2N, each still paced by server_sleep.
    MAX_BISECT_DEPTH = 4

    def _buy_batch(self, client, state, candidates, turn, retry_205=3, _depth=0):
        if not candidates:
            return state, 0

        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        current_turn = int(chara.get("turn") or 0)
        
        if current_turn != turn:
            self.last_result = {"skip": "stale_turn_detected", "request_current_turn": turn, "source_state_turn": current_turn}
            return state, 0

        valid_tips = set()
        for tip in chara.get("skill_tips_array") or []:
            group_id = int(tip.get("group_id") or 0)
            valid_tips.update(self.group_to_skill_ids.get(group_id, []))

        owned_ids = {int(s.get("skill_id") or 0) for s in chara.get("skill_array") or []}
        points = int(chara.get("skill_point") or 0)
        selected_total_cost = 0
        valid_candidates = []

        for item in candidates:
            skill_id = item["skill_id"]
            cost = int(item.get("cost") or 0)
            if skill_id <= 0 or item.get("skip_reason"):
                item["preflight_error"] = "invalid_skill"
                continue
            if skill_id not in valid_tips:
                item["preflight_error"] = "not_in_tips"
                continue
            # Never re-buy a skill already owned at an equal-or-better tier: the game accepts
            # the call and still deducts SP, draining the budget on a no-op (see Front Runner
            # Savvy ○ being re-bought every turn while ◎ was already owned).
            if self._owns_equal_or_better(skill_id, owned_ids):
                item["preflight_error"] = "already_owned_tier"
                continue
            # Bought earlier in THIS career. The owned_ids check above can't catch it (gain_skills
            # returns no refreshed skill_array), so without this the leftover-SP pass re-sends a batch
            # that already landed and eats a guaranteed 205 plus its retries.
            if skill_id in self.bought_this_career:
                item["preflight_error"] = "already_bought_this_career"
                continue
            if selected_total_cost + cost > points:
                item["preflight_error"] = "unaffordable"
                continue
            item["preflight_passed"] = True
            selected_total_cost += cost
            valid_candidates.append(item)

        if not valid_candidates:
            self.last_result = {"skip": "preflight_failed", "turn": turn, "points": points}
            return state, 0

        payload = []
        payload_ids = set()
        for item in valid_candidates:
            for skill_id in [item["skill_id"], *(item.get("bundled_skill_ids") or [])]:
                skill_id = int(skill_id or 0)
                if skill_id > 0 and skill_id not in payload_ids:
                    payload.append({"skill_id": skill_id, "level": 1})
                    payload_ids.add(skill_id)
        self.last_attempt = [dict(item) for item in valid_candidates]
        event = {
            "turn": turn,
            "selected": [dict(item) for item in candidates],
            "attempt": [dict(item) for item in valid_candidates],
            "payload": payload,
            "result": {},
        }
        self.attempt_events.append(event)

        try:
            # Brief breather before the end-of-career buy so the finals-day server isn't hammered at
            # this one critical step (kill-switch-immune, so it applies even under "NO CD"; a 208 here
            # otherwise costs the trainee its skills). One call per career -> negligible overhead.
            server_sleep(0.6, 1.2)
            result = client.gain_skills(payload, turn, retry_205=retry_205)
            # Landed -> never send these again this career (see bought_this_career in __init__).
            self.bought_this_career.update(int(p.get("skill_id") or 0) for p in payload)
            self.last_result = {"result": "ok", "turn": turn, "count": len(valid_candidates), "payload": payload}
            event["result"] = self.last_result
            self._failed_for_turn(turn).clear()
            return self._merge_state(state, result), len(valid_candidates)
        except Exception as exc:
            print(f"Skill Purchase Error at turn {turn}: {exc}")
            if any(code in str(exc) for code in ("201", "205", "208")):
                self.recover_after_error = True
            # BISECT ON 205. A 205 here means the SERVER refused this exact batch -- and because the
            # end-of-career dump is ONE atomic call, a single unsellable skill used to take the whole
            # ~1,300 SP bank down with it (measured: 25% of careers ended with the entire bank
            # unspent, ~1,900 rank score each). Split the batch and retry the halves, recursing to
            # single skills: the good skills land and only the genuinely refused one is lost.
            # Sub-batches use retry_205=0 -- a 205 is a deterministic refusal here, not a transient
            # fault (same reasoning as the mid-run buy), so re-sending an identical payload just
            # burns calls; the split IS the retry. Depth-bounded, and each level still pays the
            # server_sleep above, so this cannot stampede the circuit breaker.
            if "205" in str(exc) and len(valid_candidates) > 1 and _depth < self.MAX_BISECT_DEPTH:
                mid = len(valid_candidates) // 2
                print(f"  205 on a {len(valid_candidates)}-skill batch -> bisecting "
                      f"({mid} + {len(valid_candidates) - mid}) at depth {_depth + 1}")
                cur, bought_total = state, 0
                for half in (valid_candidates[:mid], valid_candidates[mid:]):
                    cur, got = self._buy_batch(client, cur, half, turn, retry_205=0, _depth=_depth + 1)
                    bought_total += got
                self.last_result = {"result": "bisected", "turn": turn, "error": str(exc),
                                    "split": [mid, len(valid_candidates) - mid], "bought": bought_total}
                event["result"] = self.last_result
                return cur, bought_total
            self._failed_for_turn(turn).update(int(item["skill_id"]) for item in valid_candidates)
            self.last_result = {"result": "failed", "turn": turn, "error": str(exc), "payload": payload}
            event["result"] = self.last_result
            return state, 0

    def _merge_state(self, state, res):
        if res and isinstance(res, dict) and "data" in res:
            if not state: state = {}
            if "data" not in state: state["data"] = {}
            for k, v in res["data"].items():
                if isinstance(v, dict) and isinstance(state["data"].get(k), dict):
                    state["data"][k].update(v)
                else:
                    state["data"][k] = v
        return state


    def _select_skill_id(self, group_id, priority, owned, rarity=0):
        owned_groups = {self.skill_to_group_id.get(sid, sid // 10) for sid in owned}
        resolved = self.resolve_skill_tip({"group_id": group_id, "rarity": rarity, "level": 0}, set(owned), owned_groups, priority, set(), {})
        return int((resolved or {}).get("resolved_skill_id") or 0)

    def _estimate_cost(self, candidate):
        skill_id = candidate.get("skill_id") or 0
        level = candidate.get("hint_level") or 0
        
        # NOTE: circle-marked (o / @) skills used to be priced at a hardcoded base 130. Removed: the
        # real per-skill price is master.mdb's need_skill_point, loaded into self.skill_costs, and the
        # flat 130 was wrong for ~84% of them. Under-estimating a price makes the greedy fill pack a
        # batch it cannot afford, which is one way the end-of-career gain_skills call 205s and the
        # whole SP bank is lost. Always prefer the real cost; the rarity guess is the last resort.
        if skill_id >= 900000:
            base = 200
        else:
            base = self.skill_costs.get(skill_id)
            if not base:
                base = 200 if self.skill_rarities.get(skill_id, 0) >= 2 else 160
        # Hint discount per level 0-5 is 0/10/20/30/35/40% (matches the user's captured gain_skills
        # buys), NOT a flat 10% per level -- that priced Lv4/Lv5 hints at 60%/50% of base and 205'd.
        disc = (0, 10, 20, 30, 35, 40)[max(0, min(int(level), 5))]
        return max(1, int(base * (100 - disc) / 100))

