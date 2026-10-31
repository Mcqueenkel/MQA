import json
import re
import threading
from pathlib import Path

from career_bot.core.data_store import DataStore


# Circle/cross grade marks that decorate skill names (e.g. "Front Runner Corners ◎"); stripped
# so a build's wanted-skill name matches the master skill name regardless of its grade suffix.
_SKILL_MARKS = "◎○×◯❍⭕✕✖"


def _norm_skill(name):
    s = str(name or "")
    for m in _SKILL_MARKS:
        s = s.replace(m, "")
    return re.sub(r"\s+", " ", s).strip().lower()


class EventManager:
    # Stat keys recorded when observing what an event choice actually did.
    OUTCOME_KEYS = ("speed", "stamina", "power", "guts", "wiz", "skill_point", "vital", "motivation")

    # Relative value of one observed unit of each outcome, used to rank event choices by
    # their LEARNED average effect (event_choice_outcomes.json). Skill points and energy
    # (vital) are worth a touch more than a raw stat point; motivation moves on a small 1-5
    # scale so each point is weighted heavily. Guts is the least useful stat for most builds.
    OUTCOME_VALUE_WEIGHTS = {
        "speed": 1.0, "stamina": 1.0, "power": 1.0, "guts": 0.6, "wiz": 1.0,
        "skill_point": 1.3, "vital": 1.6, "motivation": 12.0,
    }
    # Minimum sightings of a choice before we trust its running average enough to pick on it.
    MIN_OUTCOME_SAMPLES = 2

    # Aoharu / Unity Cup intro team-name events (single_mode_team check_event): the "Let's name our
    # team..." pick plus its sibling flavor choice. Cosmetic 3-choice events with NO effects (no
    # single_mode_event_choice_reward rows); the live payload carries no choice text, and the two
    # deck-suggested names shuffle, but "Team Carrot" is always the FIXED bottom option -- so choose()
    # forces the last position for these. See choose() (1b).
    UNITY_TEAM_NAME_STORIES = {"501041101", "501041102"}

    # Need-awareness: when the trainee is actually short on energy or mood, a recovery option
    # should outscore a stat option. These boost the value of the matching outcome so the
    # scorer picks the recovery choice exactly when the turn calls for it.
    LOW_ENERGY_ABS = 40       # vital at/below this (out of max_vital) counts as low energy
    LOW_ENERGY_RATIO = 0.45   # ...or at/below this fraction of max_vital
    LOW_ENERGY_BOOST = 3.0    # multiply the 'vital' weight when energy is low
    LOW_MOOD_LEVEL = 2        # motivation at/below this (1=Awful..5=Great) counts as low mood
    LOW_MOOD_BOOST = 3.0      # multiply the 'motivation' weight when mood is low

    # Build-relevant hint reward: when energy/mood are fine, an option that has been observed
    # to HINT a skill the build wants (in learn_skill_list) gets this much value per such skill,
    # so the chooser leans toward "Front Runner hint" options for a Front Runner build, etc.
    # Capped at HINT_BUILD_MAX_SKILLS so accumulated hints can tip a close pick but never
    # overpower a genuine low-energy/low-mood recovery (need stays first).
    HINT_BUILD_BONUS = 8.0
    HINT_BUILD_MAX_SKILLS = 2

    # Ground-truth outcomes DB (data/support_event_outcomes.json -- GameTora, fetched by
    # scripts/fetch_event_outcomes.py, joined by the API's own story_id): effect-code -> which
    # OUTCOME_VALUE_WEIGHTS key it is valued as, so DB picks and learned picks share one value system.
    DB_EFFECT_KEYS = {"sp": "speed", "st": "stamina", "po": "power", "gu": "guts", "in": "wiz",
                      "pt": "skill_point", "en": "vital", "mo": "motivation"}
    DB_BOND_VALUE = 0.4     # per bond point (+5 bond -> 2.0): bond builds toward rainbow training
    DB_HINT_VALUE = 4.0     # per hint level for a non-build skill (build skills get HINT_BUILD_BONUS)
    # Skill hints carry no weight from the Senior year on (same turn as training_brain.SENIOR_START_TURN,
    # kept separate to avoid a circular import): no must-pick, no hint value in the scorers.
    SENIOR_START_TURN = 49
    DB_TIE_EPSILON = 0.5    # option scores closer than this = no real information -> defer

    def __init__(self, base_dir, data_store=None):
        self.base_dir = Path(base_dir)
        self.data_store = data_store or DataStore(base_dir)
        self.outcomes = {}
        self._lock = threading.Lock()
        # Built-in "good/bad" DB (read-only, lives under data/). The user's manual
        # overrides, the seen-event log and the observed per-choice outcomes live under
        # uma_runtime/ so we never touch the regenerated data/ files.
        self._overrides_path = self.base_dir / "uma_runtime" / "event_overrides.json"
        self._seen_path = self.base_dir / "uma_runtime" / "events_seen.json"
        self._choice_outcomes_path = self.base_dir / "uma_runtime" / "event_choice_outcomes.json"
        self._name_to_groups = {}   # normalized skill name -> {group_id} (for build-hint matching)
        self._skill_id_to_group = {}  # skill_id -> group_id (for outcomes-DB hint matching)
        self._outcome_db = None     # data/support_event_outcomes.json, lazy-loaded on first pick
        self._load()
        self._load_skill_index()

    def _load(self):
        self.outcomes = self.data_store.event_outcomes()

    def _load_skill_index(self):
        """Build {normalized skill name -> {group_id}} from data/skill_data.json so a recorded
        event hint (stored as a skill_tips_array group_id) can be matched against the build's
        wanted skills (learn_skill_list, by name). group_id is derived exactly as the skill
        buyer does (master group_id, else skill_id//10 for the 6-digit unique range) so a
        recorded tip group_id resolves to the same skills the game/buyer would resolve it to."""
        data = self.data_store.skill_data()
        for raw_id, info in (data or {}).items():
            try:
                sid = int(raw_id)
            except (TypeError, ValueError):
                continue
            name = info.get("name") if isinstance(info, dict) else info
            nm = _norm_skill(name)
            if not nm:
                continue
            gid = 0
            if isinstance(info, dict):
                try:
                    gid = int(info.get("group_id") or 0)
                except (TypeError, ValueError):
                    gid = 0
            if not gid:
                gid = sid if sid < 100000 else sid // 10
            self._name_to_groups.setdefault(nm, set()).add(gid)
            self._skill_id_to_group[sid] = gid

    def _wanted_skill_groups(self, preset):
        """The group_ids of the skills this build wants (from the learn_skill_list priority
        names), matched by normalized name -- the set a recorded event hint is checked against."""
        if not isinstance(preset, dict) or not self._name_to_groups:
            return frozenset()
        groups = set()
        for row in (preset.get("learn_skill_list") or []):
            names = row if isinstance(row, list) else [row]
            for nm in names:
                groups |= self._name_to_groups.get(_norm_skill(nm), set())
        return frozenset(groups)

    @staticmethod
    def _tip_levels(chara):
        """{group_id: highest hint level} from a chara's skill_tips_array. Tolerates ANY
        malformed shape (non-dict chara, non-list array, non-dict elements) without raising,
        so a corrupt payload can never discard the stat observation in record_choice_outcome."""
        out = {}
        arr = chara.get("skill_tips_array") if isinstance(chara, dict) else None
        if not isinstance(arr, list):
            return out
        for tip in arr:
            if not isinstance(tip, dict):
                continue
            try:
                gid = int(tip.get("group_id") or 0)
                lvl = int(tip.get("level") or tip.get("hint_level") or 0)
            except (TypeError, ValueError):
                continue
            if gid:
                out[gid] = max(out.get(gid, 0), lvl)
        return out

    def _hinted_groups(self, before_chara, after_chara):
        """Skill group_ids whose hint level ROSE across the event -- i.e. the skills this
        choice just hinted. Diffs skill_tips_array the same way stat outcomes diff stats."""
        before = self._tip_levels(before_chara)
        after = self._tip_levels(after_chara)
        return [gid for gid, lvl in after.items() if lvl > before.get(gid, 0)]

    def _read_overrides(self):
        """User's manual per-event choice overrides: {story_id: choice_index}."""
        try:
            if self._overrides_path.exists():
                return json.loads(self._overrides_path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
        return {}

    def _record_seen(self, story_id, event, num_choices, picked, source):
        """Log every multi-choice event the bot meets so the UI can list them and let
        the user set an override. Keyed by story_id; safe to fail silently."""
        try:
            choices = ((event.get("event_contents_info") or {}).get("choice_array") or [])
            with self._lock:
                seen = {}
                if self._seen_path.exists():
                    try:
                        seen = json.loads(self._seen_path.read_text(encoding="utf-8")) or {}
                    except Exception:
                        seen = {}
                entry = seen.get(story_id) or {}
                known = self.outcomes.get(story_id) or {}
                entry.update({
                    "story_id": story_id,
                    "event_name": known.get("event_name") or entry.get("event_name") or "",
                    # Some events vary their option count between sightings; keep the max so
                    # the UI never hides an option (and observed data for it) it once showed.
                    "num_choices": max(int(num_choices), int(entry.get("num_choices") or 0)),
                    "picked": int(picked),
                    "source": source,
                    "count": int(entry.get("count") or 0) + 1,
                    "choice_items": [int(c.get("receive_item_id") or 0) for c in choices],
                    # The game's select_index per position THIS sighting. NOT stable across
                    # sightings (e.g. "Victory!" shows subsets of 1..4), so outcomes/labels
                    # are keyed by select_index and mapped to positions via this list.
                    "choice_selects": [int(c.get("select_index") or 0) for c in choices],
                })
                seen[story_id] = entry
                self._seen_path.parent.mkdir(parents=True, exist_ok=True)
                self._seen_path.write_text(
                    json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8"
                )
        except Exception:
            pass

    # Cap fields per stat: a delta recorded while the BEFORE value already sits at its cap
    # is truncated by the game (e.g. +30 heal at 95/100 vital records as +5), which would
    # bias the running average one-directionally -- those keys are skipped instead.
    OUTCOME_CAP_KEYS = {"speed": "max_speed", "stamina": "max_stamina", "power": "max_power",
                        "guts": "max_guts", "wiz": "max_wiz", "vital": "max_vital"}
    MOTIVATION_CAP = 5

    def record_choice_outcome(self, story_id, select_index, before_chara, after_chara):
        """Learn what an event choice actually DID: diff the chara stats around the
        check_event call and fold the delta into a running average per (event, choice).
        These observations become the choice descriptions in the EVENT CHOICES panel --
        neither master.mdb nor the live payload carries choice text/effects, so what the
        bot has seen happen is the one exact, self-maintaining source. Random outcomes
        (success/fail events) wash out in the average; `n` tells the user the sample size.

        Keyed by the game's SELECT_INDEX, not the position in choice_array: the same
        event presents varying/sparse select sets across sightings (verified in real
        logs), so position would blend genuinely different choices. Safe to fail
        silently; never raises into the career loop."""
        try:
            story_id = str(story_id or "")
            select_index = int(select_index or 0)
            if not story_id or select_index <= 0:
                return
            if not isinstance(before_chara, dict) or not isinstance(after_chara, dict):
                return
            if not after_chara.get("turn"):
                return  # response without real chara state -> nothing observable
            delta = {}
            for key in self.OUTCOME_KEYS:
                try:
                    before = int(before_chara.get(key) or 0)
                    d = int(after_chara.get(key) or 0) - before
                except (TypeError, ValueError):
                    continue
                # Skip cap-truncated observations (one-directional bias, see OUTCOME_CAP_KEYS).
                cap_key = self.OUTCOME_CAP_KEYS.get(key)
                if cap_key:
                    try:
                        cap = int(before_chara.get(cap_key) or 0)
                    except (TypeError, ValueError):
                        cap = 0
                    if cap and before >= cap:
                        continue
                elif key == "motivation" and before >= self.MOTIVATION_CAP:
                    continue
                if d:
                    delta[key] = d
            with self._lock:
                db = {}
                if self._choice_outcomes_path.exists():
                    try:
                        db = json.loads(self._choice_outcomes_path.read_text(encoding="utf-8")) or {}
                    except Exception:
                        db = {}
                entry = db.setdefault(story_id, {})
                slot = entry.get(str(select_index)) or {"n": 0, "avg": {}}
                n = int(slot.get("n") or 0)
                avg = dict(slot.get("avg") or {})
                keys = set(avg) | set(delta)
                slot["avg"] = {k: round((float(avg.get(k, 0.0)) * n + delta.get(k, 0)) / (n + 1), 2) for k in keys}
                slot["n"] = n + 1
                slot["last"] = delta
                # Also remember which skill GROUPS this choice has been seen to hint (skills
                # whose hint level rose). Accumulated as a set so the build-hint matcher can
                # later prefer options that hint skills the build wants. Wrapped on its own so
                # a hint failure can NEVER discard the stat observation computed just above.
                try:
                    hinted = self._hinted_groups(before_chara, after_chara)
                    if hinted or slot.get("hints"):
                        slot["hints"] = sorted(set(slot.get("hints") or []) | set(hinted))
                except Exception:
                    pass
                entry[str(select_index)] = slot
                self._choice_outcomes_path.parent.mkdir(parents=True, exist_ok=True)
                # Atomic write: the API reads this file per request; a mid-write read
                # must never see a torn/empty JSON.
                tmp = self._choice_outcomes_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
                import os
                os.replace(tmp, self._choice_outcomes_path)
        except Exception:
            pass

    def choice_outcomes(self):
        """Read-only view of the observed per-choice outcomes ({story_id: {idx: {n, avg, last}}})."""
        try:
            if self._choice_outcomes_path.exists():
                return json.loads(self._choice_outcomes_path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
        return {}

    def _need_weights(self, chara):
        """A per-turn copy of OUTCOME_VALUE_WEIGHTS, boosted toward what the trainee NEEDS
        right now: energy (vital) when it is low, mood (motivation) when it is low. So a
        recovery option outscores a stat option exactly when recovery is what the turn calls
        for, and otherwise the normal stat/skill weighting decides."""
        weights = dict(self.OUTCOME_VALUE_WEIGHTS)
        if not isinstance(chara, dict):
            return weights
        try:
            vital = int(chara.get("vital") or 0)
            max_vital = int(chara.get("max_vital") or 0) or 100
            motivation = int(chara.get("motivation") or 3)
        except (TypeError, ValueError):
            return weights
        if vital <= self.LOW_ENERGY_ABS or (max_vital and vital / max_vital <= self.LOW_ENERGY_RATIO):
            weights["vital"] *= self.LOW_ENERGY_BOOST
        if motivation <= self.LOW_MOOD_LEVEL:
            weights["motivation"] *= self.LOW_MOOD_BOOST
        return weights

    def _score_choices_by_outcome(self, story_id, choices, chara=None, preset=None):
        """Rank the live choices by their LEARNED average effect and return the index of the
        best one (or None to defer to the curated DB / fallback).

        This wires the bot's own observations (record_choice_outcome -> the running averages
        in event_choice_outcomes.json) back into the live pick: each choice's avg stat /
        skill-point / energy / motivation deltas are valued by need-aware weights (see
        _need_weights -- energy/mood matter more when the trainee is low) and the highest
        net-positive option wins. Choices are matched to learned data by the game's
        select_index -- the same stable key record_choice_outcome stores under (position is
        NOT stable across sightings). Returns None when no sampled option is net-positive, so
        a curated DB entry or the safe fallback still decides. Sharpens every career."""
        try:
            learned = self.choice_outcomes().get(str(story_id or "")) or {}
        except Exception:
            return None
        if not learned:
            return None
        weights = self._need_weights(chara)
        wanted_groups = self._wanted_skill_groups(preset)
        best_idx, best_score = None, 0.0
        for i, choice in enumerate(choices):
            # Per-choice fail-silent: a single malformed learned entry (corrupt or hand-edited
            # JSON -- null/list/string where a number/dict is expected) must SKIP that option,
            # never raise into the career loop. Matches the fail-silent pattern used by every
            # other path in this module (so a bad file degrades to the blind fallback, not a crash).
            try:
                sel = str(int(choice.get("select_index") or 0))
                slot = learned.get(sel) or {}
                if int(slot.get("n") or 0) < self.MIN_OUTCOME_SAMPLES:
                    continue
                avg = slot.get("avg") or {}
                score = sum(float(avg.get(k, 0.0)) * w for k, w in weights.items())
                # Build-hint reward: prefer options observed to hint skills the build wants.
                # Need-boosted energy/mood still dominates when the trainee is actually low, so
                # this only tips otherwise-close picks toward the build -- the "else" in the ask.
                if wanted_groups and slot.get("hints"):
                    relevant = sum(1 for g in slot["hints"] if g in wanted_groups)
                    score += (min(relevant, self.HINT_BUILD_MAX_SKILLS) * self.HINT_BUILD_BONUS
                              * getattr(self, "_hint_weight", 1.0))
            except Exception:
                continue
            if best_idx is None or score > best_score:
                best_idx, best_score = i, score
        # Only act on a confidently net-positive learned option; otherwise defer so we never
        # pick a known-bad option over an as-yet-unobserved one.
        if best_idx is None or best_score <= 0.0:
            return None
        return best_idx

    def _build_hint_pick(self, story_id, choices, preset):
        """Index of the option OBSERVED to hint the most skills the build wants (names in the
        preset's learn_skill_list) -- a HARD must-pick: a hint for a planned skill discounts
        that skill's SP cost, so the user wants it taken over the generic value scorer. Returns
        None when no option has a build-wanted hint on record. The game never previews an
        option's hint, so this needs the option to have been SEEN at least once (the bot learns
        each event's hints by watching skill_tips_array change) -- self-improving. Fail-silent."""
        try:
            wanted = self._wanted_skill_groups(preset)
            if not wanted:
                return None
            learned = self.choice_outcomes().get(str(story_id or "")) or {}
            if not learned:
                return None
            best_idx, best_n = None, 0
            for i, choice in enumerate(choices):
                sel = str(int(choice.get("select_index") or 0))
                hints = (learned.get(sel) or {}).get("hints") or []
                n = sum(1 for g in hints if g in wanted)
                if n > best_n:
                    best_idx, best_n = i, n
            return best_idx
        except Exception:
            return None

    def _outcome_db_map(self):
        """Lazy-load the ground-truth per-choice outcomes DB (data/support_event_outcomes.json,
        GameTora via scripts/fetch_event_outcomes.py). {} when the file is absent/corrupt, so
        every caller silently degrades to the curated/learned layers."""
        if self._outcome_db is None:
            try:
                with open(self.base_dir / "data" / "support_event_outcomes.json", encoding="utf-8") as f:
                    self._outcome_db = json.load(f) or {}
            except Exception:
                self._outcome_db = {}
        return self._outcome_db

    def _score_effects(self, effects, weights, wanted_groups):
        """Value one choice's KNOWN effects with the same need-aware weights the learned scorer
        uses (stats/SP/energy/mood via DB_EFFECT_KEYS; bond flat; skill hints by build relevance).
        Special codes (random-branch markers, chain flags, statuses) score 0 by design.
        Limitation: random-branch alternatives are flat-listed so both branches' effects count --
        symmetric across the event's choices, which keeps their ORDERING sound."""
        score = 0.0
        for e in (effects or []):
            if not (isinstance(e, list) and e):
                continue
            code = e[0]
            try:
                val = float(str(e[1]).replace("+", "")) if len(e) > 1 else 0.0
            except (TypeError, ValueError):
                val = 0.0
            key = self.DB_EFFECT_KEYS.get(code)
            if key:
                score += val * weights.get(key, 0.0)
            elif code == "5s":   # "all five stats" effect
                score += val * sum(weights.get(k, 0.0) for k in ("speed", "stamina", "power", "guts", "wiz"))
            elif code == "bo":
                score += val * self.DB_BOND_VALUE
            elif code == "sk":
                gid = None
                if len(e) > 2:
                    try:
                        gid = self._skill_id_to_group.get(int(e[2]))
                    except (TypeError, ValueError):
                        gid = None
                score += (val * (self.HINT_BUILD_BONUS if gid and gid in wanted_groups else self.DB_HINT_VALUE)
                          * getattr(self, "_hint_weight", 1.0))
        return score

    def _db_hint_pick(self, story_id, choices, preset):
        """MUST-PICK a choice KNOWN (ground-truth outcomes DB) to hint a skill the build wants.
        The preset's learn_skill_list names skills; each maps to its skill GROUP (so a hint for
        any variant of the wanted skill counts -- hint discounts apply group-wide, exactly like
        the skill buyer resolves them). If one option out-hints the others on wanted skills, take
        it OVER the value scorer -- a planned-skill hint (cheaper buy at career end) outweighs
        this turn's stat delta (e.g. it rightly eats an Energy -20 option that hints 3 wanted
        skills). Returns the live choice index, or None when no option hints a wanted skill."""
        wanted = self._wanted_skill_groups(preset)
        if not wanted:
            return None
        entry = self._outcome_db_map().get(str(story_id or ""))
        db_choices = (entry or {}).get("choices") or []
        if len(db_choices) < 2 or len(db_choices) != len(choices):
            return None
        best_n, best_levels = None, 0
        for ch in db_choices:
            try:
                n = int(ch.get("n") or 0)
            except (TypeError, ValueError):
                continue
            levels = 0
            for e in (ch.get("effects") or []):
                if not (isinstance(e, list) and len(e) > 2 and e[0] == "sk"):
                    continue
                try:
                    gid = self._skill_id_to_group.get(int(e[2]))
                    lv = int(float(str(e[1]).replace("+", ""))) if len(e) > 1 else 1
                except (TypeError, ValueError):
                    continue
                if gid in wanted:
                    levels += max(1, lv)
            if n > 0 and levels > best_levels:
                best_n, best_levels = n, levels
        if best_n is None:
            return None
        for i, choice in enumerate(choices):
            if int(choice.get("select_index") or (i + 1)) == best_n:
                return i
        return None

    def energy_choice_index(self, event):
        """0-based index of the choice whose KNOWN outcomes grant the most ENERGY (vital), or None when
        the event's per-choice outcomes aren't in the DB or don't line up with the offered choices.
        Uses the same ground-truth DB (data/support_event_outcomes.json) as _outcomes_db_pick; energy is
        the 'en' effect code (DB_EFFECT_KEYS['en'] == 'vital'). Returns a 0-BASED index, matching the
        rest of choose()."""
        choices = ((event or {}).get("event_contents_info") or {}).get("choice_array") or []
        if len(choices) < 2:
            return 0 if choices else None
        entry = self._outcome_db_map().get(str((event or {}).get("story_id") or ""))
        db_choices = (entry or {}).get("choices") or []
        if len(db_choices) != len(choices):
            return None

        def energy_of(ch):
            total = 0.0
            for e in (ch.get("effects") or []):
                if isinstance(e, list) and len(e) >= 2 and e[0] == "en":
                    try:
                        total += float(str(e[1]).replace("+", ""))
                    except (TypeError, ValueError):
                        pass
            return total

        best = max(db_choices, key=energy_of, default=None)
        if best is None or energy_of(best) <= 0:
            return None                       # no energy on any option -> let the caller fall back
        best_n = int(best.get("n") or 0)      # DB `n` is the game select_index (1-based)
        for i, choice in enumerate(choices):
            if int(choice.get("select_index") or (i + 1)) == best_n:
                return i
        return None

    def _outcomes_db_pick(self, story_id, choices, chara=None, preset=None):
        """Pick by GROUND TRUTH: when this event's per-choice outcomes are in the DB, score every
        option's known effects and return the live index of the best one. Unlike the learned
        scorer this knows ALL options, so it may pick the least-bad of two bad choices (that IS
        the right move); it only defers (None) when the DB doesn't know the event, the choice
        counts don't line up, or the options score too close to carry real information."""
        entry = self._outcome_db_map().get(str(story_id or ""))
        db_choices = (entry or {}).get("choices") or []
        if len(db_choices) < 2 or len(choices) < 2 or len(db_choices) != len(choices):
            return None
        weights = self._need_weights(chara)
        wanted = self._wanted_skill_groups(preset)
        scored = {}
        for ch in db_choices:
            try:
                n = int(ch.get("n") or 0)
                if n > 0:
                    scored[n] = self._score_effects(ch.get("effects"), weights, wanted)
            except Exception:
                continue   # one malformed DB row skips that option, never crashes the career loop
        if len(scored) < 2:
            return None
        vals = sorted(scored.values(), reverse=True)
        if vals[0] - vals[1] < self.DB_TIE_EPSILON:
            return None   # effectively tied -> no information; let curated/learned/fallback decide
        best_n = max(scored, key=scored.get)
        for i, choice in enumerate(choices):
            sel = int(choice.get("select_index") or (i + 1))
            if sel == best_n:
                return i
        return None

    def _critically_low(self, chara):
        """True when the trainee is critically low on energy or mood -- then recovery comes
        first (the need-aware value scorer), even ahead of a forced build-skill hint."""
        if not isinstance(chara, dict):
            return False
        try:
            vital = int(chara.get("vital") or 0)
            max_vital = int(chara.get("max_vital") or 0) or 100
            motivation = int(chara.get("motivation") or 3)
        except (TypeError, ValueError):
            return False
        return (vital <= self.LOW_ENERGY_ABS
                or (max_vital and vital / max_vital <= self.LOW_ENERGY_RATIO)
                or motivation <= self.LOW_MOOD_LEVEL)

    def _is_victory(self, story_id):
        """True for the post-race 'Victory!' event. The curated DB names it, and its story ids
        share the char/scenario-agnostic 3-digit suffix (708) the good/bad fallback already
        matches on -- so an exact-then-suffix name lookup covers every trainee/scenario variant."""
        sid = str(story_id or "")
        if not sid:
            return False
        entry = self.outcomes.get(sid)
        if not entry and len(sid) >= 3:
            suf = sid[-3:]
            entry = next((v for k, v in self.outcomes.items() if k.endswith(suf)), None)
        return bool(entry) and entry.get("event_name") == "Victory!"

    def choose(self, event, chara=None, preset=None):
        story_id = str(event.get("story_id", ""))

        if story_id == "400004002":
            return 2

        choices = ((event.get("event_contents_info") or {}).get("choice_array") or [])
        if not choices:
            return 0
        num = len(choices)
        # 1.0 before the Senior year, 0.0 from it: read by the hint must-pick and both hint scorers.
        self._hint_weight = 0.0 if int((chara or {}).get("turn") or 0) >= self.SENIOR_START_TURN else 1.0

        # 1) User override wins (manual per-event pick from the EVENT CHOICES tab).
        ov = self._read_overrides().get(story_id)
        if ov is not None:
            try:
                idx = int(ov)
                if 0 <= idx < num:
                    self._record_seen(story_id, event, num, idx, "override")
                    return idx
            except (TypeError, ValueError):
                pass

        # 1a) Post-race "Victory!" event: always take the BOTTOM option (user rule). The game
        # shows this event's choices as varying subsets of select_index 1..4, so pick by POSITION
        # (last one shown) -- stable across sightings. Beats the value scorers/hints below; only a
        # manual override (above) wins.
        if self._is_victory(story_id):
            self._record_seen(story_id, event, num, num - 1, "victory_bottom")
            return num - 1

        # 1b) Aoharu / Unity Cup team-name pick (and its sibling intro flavor choice): always take
        # "Team Carrot" -- the fixed BOTTOM option (user rule). Both are cosmetic 3-choice events with
        # no effects and the payload carries no choice text, so pick by POSITION: Team Carrot is always
        # listed LAST. Only a manual override (1) beats it.
        if story_id in self.UNITY_TEAM_NAME_STORIES:
            self._record_seen(story_id, event, num, num - 1, "team_carrot")
            return num - 1

        # 1.5) MUST-PICK a build-relevant skill hint: if an option is observed to hint a skill in
        # the preset's learn_skill_list (e.g. the Smart Falcon event's Groundwork hint for a build
        # that wants Groundwork), take it -- a hint for a planned skill is high value and the user
        # wants it forced. Above the curated DB and the value scorer; only a manual override beats
        # it. Deferred only when the trainee is critically low on energy/mood (recovery first).
        if not self._critically_low(chara) and self._hint_weight:
            hint_idx = self._build_hint_pick(story_id, choices, preset)
            if hint_idx is not None:
                self._record_seen(story_id, event, num, hint_idx, "build_hint")
                return hint_idx
            # Ground-truth version of the same rule: the outcomes DB KNOWS which choice hints a
            # skill in learn_skill_list (no observation needed) -- force it, same as above. The
            # preset picked the skill; the event choice that hints it is taken automatically.
            db_hint_idx = self._db_hint_pick(story_id, choices, preset)
            if db_hint_idx is not None:
                self._record_seen(story_id, event, num, db_hint_idx, "db_build_hint")
                return db_hint_idx

        # 1.7) Ground-truth outcomes DB (GameTora, joined by the API's own story_id): score every
        # option's KNOWN effects with the same need-aware weights as the learned scorer and take
        # the best. Sits ABOVE the curated good/bad + learned layers (complete + deterministic
        # beats sampled observations) and BELOW the user's override + the forced build-hint.
        db_idx = self._outcomes_db_pick(story_id, choices, chara, preset)
        if db_idx is not None:
            self._record_seen(story_id, event, num, db_idx, "outcomes_db")
            return db_idx

        # 2) Built-in good/bad DB.
        outcome_data = self.outcomes.get(story_id)
        if not outcome_data and len(story_id) >= 3:
            suffix = story_id[-3:]
            for k, v in self.outcomes.items():
                if k.endswith(suffix):
                    outcome_data = v
                    break
        if outcome_data:
            outcomes = outcome_data.get("outcomes", {})
            for i, choice in enumerate(choices):
                select_index = str(choice.get("select_index", ""))
                if outcomes.get(select_index) == "good":
                    self._record_seen(story_id, event, num, i, "db")
                    return i

        # 3) Learned value scorer: when the curated DB has no "good" pick for this event,
        # rank the options by what we've actually OBSERVED each one do and take the best
        # net-positive one. This replaces the old blind "pick option 1" with a self-improving
        # choice that sharpens every career (and that Icarus can't match -- its capture is off).
        learned_idx = self._score_choices_by_outcome(story_id, choices, chara, preset)
        if learned_idx is not None:
            self._record_seen(story_id, event, num, learned_idx, "learned")
            return learned_idx

        # 4) Fallback: second choice when available, else the only one.
        fallback = 1 if num > 1 else 0
        self._record_seen(story_id, event, num, fallback, "fallback")
        return fallback
