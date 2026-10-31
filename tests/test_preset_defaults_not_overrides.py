"""hydrate_preset must supply DEFAULTS, never overrides.

These 20 fields -- the scoring table, the rest threshold, the motivation thresholds, the pal
weights -- were unreachable from a preset. Two independent blocks:
  1. serialize_preset dropped the key, because it was not in TUNABLE_KEYS.
  2. hydrate_preset then force-assigned the built-in value on top.
So setting one in a preset file did nothing, silently, and the code-only defaults were the only
behaviour the bot could ever have.

Both are fixed: the keys are allow-listed, and hydrate uses setdefault. A preset that says nothing
still gets exactly the shipped numbers.

Run:
    python tests/test_preset_defaults_not_overrides.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.presets import TUNABLE_KEYS, hydrate_preset, serialize_preset  # noqa: E402

BASE = {"name": "t", "learn_skill_tier0": [], "stat_caps": {}}

# every field hydrate_preset supplies, with a value that differs from the shipped default
OVERRIDES = {
    "rest_threshold": 35,
    "prioritize_recreation": True,
    "summer_score_threshold": 0.5,
    "motivation_threshold_year1": 5,
    "motivation_threshold_year2": 5,
    "motivation_threshold_year3": 5,
    "compensate_failure": False,
    "pal_card_multiplier": 0.42,
    "pal_thresholds": [1, 2],
    "pal_friendship_score": [0.5, 0.4, 0.3],
    "base_score": [1, 1, 1, 1, 1],
    "stat_value_multiplier": [0.9] * 6,
    "wit_special_multiplier": [2.0, 2.0],
    "special_training": [0.5, 0.5, 0.5, 0.5, 0.5],
    "cure_asap_conditions": ["Migraine"],
    "mant_config": {"x": 1},
}

SHIPPED = {"rest_threshold": 48, "prioritize_recreation": False,
           "summer_score_threshold": 0.34, "pal_card_multiplier": 0.1,
           "motivation_threshold_year1": 3, "compensate_failure": True}


def test_a_silent_preset_still_gets_the_shipped_defaults():
    d = hydrate_preset(dict(BASE))
    for key, want in SHIPPED.items():
        assert d.get(key) == want, (key, d.get(key), want)


def test_every_preset_value_survives_hydrate():
    d = hydrate_preset({**BASE, **OVERRIDES})
    for key, want in OVERRIDES.items():
        assert d.get(key) == want, f"{key} was clobbered: {d.get(key)!r} != {want!r}"


def test_every_hydrated_field_is_allow_listed():
    """A field hydrate supplies but serialize drops can never round-trip -- it would work until the
    preset is first saved, then silently revert."""
    missing = [k for k in OVERRIDES if k not in TUNABLE_KEYS]
    assert not missing, f"settable in hydrate but dropped on save: {missing}"


def test_the_override_survives_a_save_load_cycle():
    saved = serialize_preset({**BASE, **OVERRIDES})
    d = hydrate_preset(saved)
    for key, want in OVERRIDES.items():
        assert d.get(key) == want, f"{key} lost on save/load: {d.get(key)!r}"


def test_runtime_safety_knobs_survive_a_save_load_cycle():
    knobs = {
        "wit_rest_skip_ratio": 2.25,
        "rescue_good_training": False,
        "rescue_min_vital": 31,
        "rescue_score_threshold": 0.72,
        "rescue_vital_margin": 18,
        "never_skip_scheduled": False,
        "summer_race_fallback": False,
    }
    saved = serialize_preset({**BASE, **knobs})
    for key, want in knobs.items():
        assert key in TUNABLE_KEYS, f"runtime knob silently dropped: {key}"
        assert saved.get(key) == want, (key, saved.get(key), want)


def test_scenario_id_stays_resolved_not_user_settable():
    """scenario_id is DERIVED from the preset, so it must keep being force-assigned."""
    d = hydrate_preset({**BASE, "scenario_id": 999})
    assert d["scenario_id"] != 999
    assert d["scenario_id"] == d["scenario"]


def test_real_presets_are_behaviourally_unchanged():
    import glob
    import json
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in glob.glob(os.path.join(root, "data", "presets", "*.json")):
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        d = hydrate_preset(dict(raw))
        # none of the shipped presets set these, so all must still read the built-in values
        for key, want in SHIPPED.items():
            if key in raw:
                continue
            assert d.get(key) == want, (os.path.basename(path), key, d.get(key))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("preset defaults OK")
