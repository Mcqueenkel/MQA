# MQA — repo map

Navigation guide — where each part lives, so you can jump straight to the code you need.
(Architecture rationale is in [CLAUDE.md](CLAUDE.md); this file is just the layout.)

```
Mcqueen Uma auto/      the MQA repo root (folder keeps its original name)
├── main.py            FastAPI server + Frida auth capture + static UI host (the entry point)
├── frida_hook.js      the Frida JS injected into the game to sniff auth (was inline in main.py)
├── discord_remote.py  optional Discord slash-command remote; calls MQA's local web API
├── api/               HTTP route groups split out of main.py (see below)
├── career_bot/        the decision engine — the bot's brain (see below)
├── uma_api/client.py  the ONLY thing that touches the network (msgpack+AES game API client)
├── data/              game reference data (generated from master.mdb) + user presets + images
│   ├── *.json         chara_list, support_list, skill_data, factor_map, race_map, career_goals
│   ├── images/        character/support-card images
│   └── presets/       the user's run configs — HARD RULE: never touch without being asked
├── public/            the web UI (vanilla index.html / app.js / styles.css) + race images
├── tests/             pure unit tests (no game/network; data injected/mocked)
├── scripts/           one-off tooling (generate_master_data, backtest_score_command) + linux_setup.sh
├── deploy/            systemd user units + env example for the optional headless Linux host
├── uma_runtime/       (gitignored) runtime state: device_seed, Discord/webhook config, learned outcomes, career logs (no auth: the opt-in identity file lives in ~/.mqa)
├── requirements.txt / requirements-dev.txt / package.json   Python (run / tests) / Node deps
├── LINUX.md           optional headless Linux host (carried identity): setup, rules, troubleshooting
└── CLAUDE.md          architecture + conventions (read this first)
```

## main.py — sections
Endpoints are grouped by `# ===== NAME =====` banners so you can grep straight to a group:

- **SETTINGS / WEBHOOK / MASTER DATA** — turn-delay, Discord webhook, master-data status/generate
- **EVENTS** — event list + user overrides
- **FANS** — daily fan tally
- **PRESETS** — load/save/delete run configs
- **SKILLS** — end-of-career skill catalog
- **AUTH / SESSION** — login, session refresh, selection, logout, auth recapture
- **CAREER CONTROL** — start / run / runner (stop/pause/resume/burn_clocks) / friends / action / delete
- **DEBUG** — start_state, raw_load

The stateful endpoints stay in main.py because they read/reassign ~17 module-level globals
(`active_client`, `active_account`, `active_selection`, …) that the app mutates at runtime.

## api/ — self-contained route groups (no shared app state)
- **static_routes.py** — file/image serving: `/`, `/styles.css`, `/app.js`, `/api/images/…`, `/races/…`, assets
- **ai_routes.py** — closed-loop AI brain: `/api/ai/status|train|reset|export|import`

Both compute their own paths and import nothing from main.py; `main.py` mounts them with
`app.include_router(...)`.

## career_bot/ — the brain
Layout rule: **`core/` = reusable only** (never imports from `scenarios/`); **`scenarios/` = one file
per scenario**; `runner.py` is the composition root binding the two. (Reorg record: ROADMAP.md.)

- **runner.py** — the turn loop (`CareerRunner.start()`): read state → decide → act → repeat. The spine.
- **scenarios/** — one self-contained file per scenario, dispatched by `STRATEGIES` in runner:
  - `mant.py` (4 = MANT/Trackblazer) · `unity.py` (2 = Unity/Aoharu: `UnityStrategy` + the whole
    `UnityScenario` cup flow + formation/opponent pickers) · `grand_live.py` (3 = Grand Live) ·
    `ura.py` (1 = URA Finale)
  - `mant_items.py` and `mant_free_bonus.py` — MANT-only shop/item and fixed bonus behavior
- **core/base.py** — `ScenarioStrategy.next_decision(state, preset) -> Decision` (the interface)
- **core/training_brain.py** — `BaseTrainingStrategy`: the shared training brain every scenario
  inherits (scoring, rest/outings, energy rescue, goal/fan race invocation, the 78-turn calendar)
- **core/races.py** — `RacePlanner`: which races to enter and when (+ goal / fan-goal program)
- **core/skills.py** — `SkillBuyer`: end-of-career skill purchasing
- **core/events.py** — `EventManager`: story-event choice selection
- **core/ai_learn.py** — records outcomes, feeds them back into decisions
- **core/foresight.py** — career forecast / spark-aim targeting (default off)
- **core/goal_solver.py** — per-trainee career-goal plans (stat priority / style / risk)
- **core/delay.py** — anti-detection timing (`TimingDNA`, jittered/backoff sleeps, `GateKeeper`)
- **core/notify.py** — Discord finished-career embed · **core/report.py** — run logs
- **core/presets.py** — `PresetStore` · **core/data_store.py** — `DataStore` (validated data access)
- **core/master_data.py** — reads the game's master.mdb (SQLite) → regenerates `data/*.json`
