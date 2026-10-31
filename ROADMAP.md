# Reorganization Roadmap — one place for reusable code, one file per scenario

Goal (user-defined, in order):
1. **First**: a single place holding ONLY reusable functions (the shared engine every scenario uses).
2. **Second**: each scenario's own logic in its own file, isolated so changing one cannot break another —
   `mant.py` for MANT, `unity.py` for Unity.

Ground rule for every phase: **behavior-preserving** (pure moves/renames, no logic edits), full offline
suite green + `import main` clean before the phase is checked off. The live game run remains the final
ground truth — offline tests prove wiring, not gameplay.

## Target layout

```
career_bot/
  runner.py                  # engine / composition root: the turn loop (binds core + scenarios)
  core/                      # REUSABLE ONLY — nothing scenario-branded lives anywhere else
    base.py                  # Decision, ScenarioStrategy (the strategy interface)
    training_brain.py        # BaseTrainingStrategy — the shared training brain (ex-MantStrategy body)
    races.py  skills.py  items.py  events.py  delay.py  data_store.py
    ai_learn.py  foresight.py  notify.py  presets.py  master_data.py
    goal_solver.py  free_bonus.py  report.py
  scenarios/                 # ONE FILE PER SCENARIO — the only place scenario logic may live
    mant.py                  # MantStrategy (scenario 4): MANT-only overrides + Trackblazer schedule
    unity.py                 # UnityStrategy (scenario 2) + UnityScenario cup flow (merged from
                             #   team.py + unity_cup_team_race.py)
    ura.py                   # UraStrategy (scenario 1)
uma_api/client.py            # network layer (unchanged; scenario branches stay in the right layer)
main.py + api/               # server (unchanged)
```

## Phases

- [x] **Phase 0 — Baseline**: suite 24/24, `import main` OK, snapshot recorded. No changes.
- [x] **Phase 1 — core/ package**: `git mv` the 14 reusable modules (races, skills, items, events,
      delay, data_store, ai_learn, foresight, notify, presets, master_data, goal_solver, free_bonus,
      report) into `career_bot/core/`; move `scenarios/base.py` → `core/base.py`; sweep every import
      (`career_bot.X` → `career_bot.core.X`) across main.py, api/, career_bot/, uma_api/, tests/,
      scripts/. Suite green. *(Two `__file__`-relative paths fixed for the new depth: goal_solver's
      repo root and delay's persisted `.timing_dna` anchor. Found + flagged: `uma_api/career_bot/` is
      a stale untracked DUPLICATE of the whole bot — inert, nothing imports it; recommend deleting.)*
- [x] **Phase 2 — shared brain extraction**: `git mv scenarios/mant.py` → `core/training_brain.py`,
      class `MantStrategy` → `BaseTrainingStrategy` (this is the code Unity/URA already inherit — it
      was never MANT-only, it just lived under MANT's name). New thin `scenarios/mant.py`:
      `MantStrategy(BaseTrainingStrategy)`, `scenario_id = 4`. Team/URA now inherit the brain
      directly. All importers updated (runner + 6 test files split constants←brain from
      MantStrategy←mant). *(The Sirius/Throne outing schedule stayed in the brain: it is DECK-driven,
      not scenario-driven — a Unity career with that deck runs the same outings.)* Suite green.
- [x] **Phase 3 — unity.py**: merged `scenarios/team.py` + `scenarios/unity_cup_team_race.py` into one
      `scenarios/unity.py` (`TeamStrategy` → `UnityStrategy`, plus the formation/opponent helpers and
      `UnityScenario`); deleted the two old files; runner STRATEGIES + imports + tests updated
      (test_team_scenario.py → test_unity_scenario.py). Suite green.
- [x] **Phase 4 — docs + final sweep**: no stale import paths remain (only docstring mentions of the
      old filenames, kept as history); CLAUDE.md architecture section + STRUCTURE.md updated to the
      new layout; suite 24/24 + `import main` clean; STRATEGIES dispatch verified
      `{1: UraStrategy, 2: UnityStrategy, 4: MantStrategy}`.

## Status: COMPLETE (offline-verified)

All four phases done, behavior-preserving (pure moves/renames — no logic edits). The offline suite
proves the wiring; the next LIVE career run is the real confirmation. Future work this roadmap
deliberately did not do: splitting the brain's MANT-flavored climax/cleat logic out of
`core/training_brain.py` into `scenarios/mant.py` (changes inheritance behavior — needs live
validation), and deleting the stale untracked duplicate at `uma_api/career_bot/` (user's call).

## Known honest caveats (stated up front, not discovered later)

- `items.py` (MantItemManager) is MANT-*flavored* but is imported by the shared brain
  (MASTER_CLEAT_CLIMAX_RESERVE) and the runner, so it goes to `core/` to keep layering clean
  (core never imports from scenarios). Splitting the brain's climax/cleat logic out into mant.py is
  **future work** that changes inheritance behavior — not part of this behavior-preserving pass.
- The shared brain keeps its few `scenario_id == 4` gates (e.g. career-goal emphasis off for MANT).
  Those are cross-scenario rules keyed by an attribute; they behave identically from either file.
- `runner.py` stays at `career_bot/runner.py`: it is the composition root that binds core + scenarios,
  so it may import both; core modules must never import from scenarios/.
