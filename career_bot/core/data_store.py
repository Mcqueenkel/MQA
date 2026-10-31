"""Single validated access point for the generated/curated reference data under `data/`.

Before this, every module opened its own `data/*.json` with a bare `json.load` and no
validation, so a shape change silently broke one consumer with no error (that is exactly how
the career_goals `#0` fan-goal bug hid). `DataStore` centralises loading so shapes live in ONE
place, loads each file once (lazily) and caches it, and validates the top-level shape on load --
emitting a loud, deduped warning but still returning a safe default rather than crashing a live
career run.

Consumers keep their own derived indexes (e.g. `SkillBuyer` builds name/cost maps): the store
returns the raw on-disk shapes verbatim, so migrating a consumer is a one-line swap of its
`open()+json.load` for the matching accessor -- public attributes and behaviour are unchanged.

ponytail: validators are intentionally shallow (top-level type + one sampled value). A deep
per-field schema would false-alarm on the game's own additions; upgrade only if a real shape
regression slips through.
"""
import json
from pathlib import Path


def _sample_value(mapping):
    for value in mapping.values():
        return value
    return None


def _is_str_map(raw):
    """dict of str -> str (chara_list.json)."""
    if not isinstance(raw, dict):
        return f"expected a dict, got {type(raw).__name__}"
    sample = _sample_value(raw)
    if sample is not None and not isinstance(sample, str):
        return f"expected str values, got {type(sample).__name__}"
    return None


def _is_obj_map(raw):
    """dict of str -> dict (support_list, skill_data, factor_map, event_outcomes, career_goals)."""
    if not isinstance(raw, dict):
        return f"expected a dict, got {type(raw).__name__}"
    sample = _sample_value(raw)
    if sample is not None and not isinstance(sample, dict):
        return f"expected object values, got {type(sample).__name__}"
    return None


def _is_race_map(raw):
    """dict with meta/program/instance sections (race_map.json)."""
    if not isinstance(raw, dict):
        return f"expected a dict, got {type(raw).__name__}"
    for section in ("meta", "program", "instance"):
        if section not in raw:
            return f"missing '{section}' section"
        if not isinstance(raw[section], dict):
            return f"'{section}' should be a dict, got {type(raw[section]).__name__}"
    return None


# filename -> (accessor default, validator)
_FILES = {
    "chara_list.json": ({}, _is_str_map),
    "support_list.json": ({}, _is_obj_map),
    "skill_data.json": ({}, _is_obj_map),
    "race_map.json": ({"meta": {}, "program": {}, "instance": {}}, _is_race_map),
    "factor_map.json": ({}, _is_obj_map),
    "event_outcomes.json": ({}, _is_obj_map),
    "career_goals.json": ({}, _is_obj_map),
}


class DataStore:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.data_dir = self.base_dir / "data"
        self._cache = {}
        self._warned = set()

    def reload(self):
        """Drop the cache so the next access re-reads from disk (call after regeneration)."""
        self._cache.clear()

    def _warn(self, filename, problem):
        key = (filename, problem)
        if key not in self._warned:
            self._warned.add(key)
            print(f"[data_store] WARNING {filename}: {problem}")

    def _get(self, filename):
        if filename in self._cache:
            return self._cache[filename]
        default, validate = _FILES[filename]
        value = default
        path = self.data_dir / filename
        if not path.exists():
            self._warn(filename, f"missing file {path}")
        else:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # malformed JSON -> loud, but keep the run alive on defaults
                self._warn(filename, f"invalid JSON: {exc}")
                raw = None
            if raw is not None:
                problem = validate(raw)
                if problem:
                    self._warn(filename, problem)
                value = raw  # surface the problem, but still hand back what's on disk
        self._cache[filename] = value
        return value

    # --- accessors (return the raw on-disk shapes; consumers build their own indexes) ---
    def chara_list(self):
        return self._get("chara_list.json")

    def chara_name(self, card_id):
        return self.chara_list().get(str(card_id))

    def support_list(self):
        return self._get("support_list.json")

    def skill_data(self):
        return self._get("skill_data.json")

    def race_map(self):
        return self._get("race_map.json")

    def factor_map(self):
        return self._get("factor_map.json")

    def event_outcomes(self):
        return self._get("event_outcomes.json")

    def career_goals(self):
        return self._get("career_goals.json")

    def career_goals_for(self, chara_id):
        """The goal list for a base chara_id (int or str), or [] if none/unknown.

        career_goals.json is keyed by base chara_id -> {name, goals:[...]}; a career's
        chara_info exposes card_id, so callers pass card_id // 100.
        """
        entry = self.career_goals().get(str(chara_id)) or {}
        return entry.get("goals") or []
