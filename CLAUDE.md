# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This project is called **MQA**. (The folder is still named `Mcqueen Uma auto/`.)

## What this is

MQA is an automation bot for **Umamusume: Pretty Derby** that plays the game's career/single-mode unattended. It is **not** a standalone simulator — it talks directly to the live Cygames game API and captures auth from the running game process via Frida. End-to-end runs therefore require the real game installed and running on a Windows machine, which is MQA's normal home. The one exception is the opt-in headless Linux mode (below), and even that starts from an identity exported by a Windows login.

## Commands

```bash
# Run the bot (FastAPI server + web UI on http://127.0.0.1:1616)
python main.py
python main.py 8080              # different port
python main.py --account NAME    # label the account for logs/notifications
python main.py --scenario grand  # lock this process to a scenario (mant/unity/ura/grand)
python main.py --reauth          # backward-compatible no-op; every startup captures fresh auth (unless UMA_CARRY_IDENTITY=1 starts from the identity file)
python discord_remote.py         # optional Discord slash-command remote for a running MQA (config: uma_runtime/discord_remote.json)
python mqa_cli.py status         # command-line driver for a running MQA (account, start, stop, pause, resume, log, history, watch, login; --json)

# Install deps (main.py also auto-installs missing Python deps on first launch). Python 3.10-3.14.
pip install -r requirements.txt  # Python
npm install                      # Node (steam-user, only for Steam login ticket)

# Optional headless Linux host (carried identity): read LINUX.md first
bash scripts/linux_setup.sh      # venv + steam-user on Ubuntu 24.04 / Debian 12; systemd units in deploy/

# Tests — pure unit tests, no game/network needed (data is injected/mocked)
pip install -r requirements-dev.txt      # pytest + httpx (FastAPI TestClient); not needed to run MQA
python tests/test_event_scorer.py        # run a single test file directly
python -m pytest tests/test_event_scorer.py
python -m pytest tests/                   # all tests

# Regenerate data/*.json from the game's master.mdb (done automatically on run; rarely manual)
python scripts/generate_master_data.py
```

Multi-account = **one process per port** (separate processes isolate the module-level globals); there is no in-process session manager.

## Architecture

Three layers: a FastAPI server/UI (`main.py`), a game-API client (`uma_api/client.py`), and a decision engine (`career_bot/`).

**`main.py`** — single-file FastAPI app (~50 `/api/*` endpoints) + Frida auth capture + static UI host. On startup it launches the game via Steam and uses the Frida JS hook in `frida_hook.js` (loaded as `JS_CODE`) to sniff `viewer_id`/`auth_key`/`app_ver`/`res_ver` off the live process when the user reaches the home menu (~180s). Career runs are kicked off here and executed on a background thread (`CareerRunner`).

**`uma_api/client.py` — `UmaClient`** — the only thing that touches the network. Encodes/decodes the game's msgpack+AES (`pycryptodome`) payloads, uses `curl_cffi` for a real-client TLS fingerprint, signs/encrypts each request. Has an **auto-backoff circuit breaker** (`_note_api_error` / `circuit_tripped`, tunable via `SWEEPY_CIRCUIT_*` env) plus 5xx retry-with-backoff. A trip also sets the **sticky `circuit_trip_seen`** flag, which is what the runner polls to stop cleanly when the server is throttling: the lazy cooldown inside the next `call()` clears `circuit_tripped` but never `circuit_trip_seen`, so a cooldown can't swallow the stop signal. Only `reset_circuit()` clears it (main.py calls it on deliberate run/career starts). `client.should_abort` (optional zero-arg callable) lets a Stop end a cooldown without sending the request.

**`career_bot/` — decision engine.** The turn loop lives in `runner.py::CareerRunner.start()`: it reads game state, asks the scenario strategy for the next move, executes it through the client, and repeats. Key pieces:

- **`scenarios/`** — scenario implementations dispatched by `STRATEGIES`: **1 = URA (`ura.py`), 2 = Unity/Aoharu (`unity.py`), 3 = Grand Live (`grand_live.py`), 4 = MANT/Trackblazer (`mant.py`)**. MANT-only item and free-bonus behavior lives in `mant_items.py` and `mant_free_bonus.py`.
- **`core/base.py`** — defines `ScenarioStrategy.next_decision(state, preset) -> Decision`.
- **`core/training_brain.py`** — shared training scoring, race scheduling hooks, energy rescue, and rest/recreation decisions.
- **`core/races.py` (`RacePlanner`)** — which races to enter and when.
- **`core/skills.py` (`SkillBuyer`)** — end-of-career skill purchasing.
- **`core/events.py` (`EventManager`)** — story-event choice selection, ranked by learned stat-delta outcomes + a curated good/bad DB + user overrides.
- **`core/ai_learn.py`** — learning layer that records outcomes and feeds them back into decisions.
- **`core/foresight.py`** — career forecast / spark-aim targeting (default off).
- **`core/delay.py`** — anti-detection timing. Per-account thread-safe `TimingDNA` seeded from the per-install `career_bot/.timing_dna` mixed with `viewer_id` (`sha256(f"{seed}:{viewer_id}")`), jittered/backoff sleeps, `GateKeeper`. `backoff_sleep`/`server_sleep` are **kill-switch-immune** so retry waits never zero-hammer the server even when UI delays are disabled.
- **`core/notify.py`** — Discord webhook posting a rich finished-career embed (stats, skills, races, inheritance sparks via `factor_map.json`).
- **`core/presets.py` (`PresetStore`)** — load/save run configs.
- **`core/master_data.py`** — reads the game's `master.mdb` (SQLite) and regenerates `data/*.json`.

### Data & runtime layout

- **`data/*.json`** — game reference data **generated from `master.mdb`**; running the bot rewrites these. Treat incidental diffs as noise and **do not stage them**.
- **`data/presets/`** — the user's personal preset configs. **HARD RULE: never touch, edit, delete, or `git add` anything under `data/presets/` unless the user explicitly asks.**
- **`uma_runtime/`** (gitignored) — local runtime state: Discord config, fan totals, learned outcomes, API diagnostics, and **career decision logs** at `uma_runtime/bot_logs/career_log_*.json` (+ `latest_career_log.json`). Startup auth is captured fresh into memory rather than reused from disk, except with the opt-in `UMA_CARRY_IDENTITY=1`, which reads the identity file (default `~/.mqa/auth_config.json`, never under `uma_runtime/`). `uma_runtime/device_seed` is the random per-install seed of the Windows `device_id` (SHA-1 of model + MachineGuid + seed, never the Steam password), created when missing or blank: deleting it makes MQA a new device to the server. It is created on the first Windows start after the update that added it, so every existing Windows install sends a new `device_id` once (before, it was SHA-1 of model + MachineGuid + Steam password) and the same one after that. These logs are the best way to verify per-turn behavior after a run: each carries `races` (one row per race run: every finishing position incl. clock retries, the goal requirement and whether it was met) and per-turn `decisions` (every non-event decision in order; `selected_action` is only the last one).
- **`public/`** — the web UI (vanilla `index.html`/`app.js`/`styles.css`). All API calls go through `apiJson()`, which returns `res.json()` **without checking `res.ok`**: a 4xx `HTTPException` resolves to `{detail: ...}`, so a caller must check the body (`success` / `detail`) itself — only network errors and non-JSON (500) bodies throw. Every caller wraps in try/catch, so a missing/failing endpoint degrades to an empty panel rather than a white screen.

### Career turn structure

Junior 1–24, Classic 25–48, Senior 49–72, climax/finale 73–78. `play_full_career` (default on) plays each career to its natural finish (final skill buy + `finish_career`). Run count is set in the UI (1 = single, N = N careers, 0 = infinite).

## Linux (optional, headless)

Windows stays the normal home. When the laptop can't stay on, MQA can run under systemd on an always-on Linux box on the same home network (never a VPS), one account at a time, never alongside Windows MQA or the game. **[LINUX.md](LINUX.md)** is the guide; `deploy/` holds the user units and `mqa.env.example`, `scripts/linux_setup.sh` the setup. It is opt-in by env only, and with these unset none of it runs on Windows: `UMA_AUTH_CONFIG=<file>` on Windows writes the identity that just logged in (atomic, no ticket/password; refused inside the repo, OneDrive or a UNC path); `UMA_CARRY_IDENTITY=1` (exactly `1`) starts from that file (default `~/.mqa/auth_config.json`) with no game and no Frida, refuses to start off Windows unless it holds every `CARRIED_FIELDS` entry (incl. `screen_h`), and allows one mid-run Steam-ticket re-mint on 394 (never on 391; login's own 394 re-mint is not gated); `SWEEPY_SCENARIO` locks the scenario for a service with no TTY (`--scenario` wins). On every OS, Windows included, the Steam login reaches `node` only through its environment, never argv. The identity file holds `auth_key` + `udid` + `viewer_id`, which sign game API requests as the account, so treat it as a password; nothing in it is derived from the Steam password.

## Conventions & gotchas

- **Python 3.10-3.14** (developed on 3.10.11; `main.py` exits below 3.10): `msgpack` is pinned to 1.1.2, the first release with 3.14 wheels, and the dep probe imports `python_multipart` because the old `multipart` name is deprecated and can be shadowed by an unrelated package (`audioop-lts` covers discord.py on 3.13+).
- **Git identity:** no global identity on this machine — commits use the repo-local identity (`git config --local user.name/user.email`, a GitHub noreply address). Never write a personal email into the repo.
- **Skill timing** (Skills tab): TIER 0 is bought as soon as affordable, TIER 1..n only in the end-of-career dump, and BEFORE GOAL RACES (`learn_skill_before_goal`) right before each hard career-goal race (Top 3 or better, turn 25+) via `runner._buy_before_goal` -> `SkillBuyer.buy_before_goal` (listed + fitting + affordable only; once per goal turn). The end-of-career dump (`SkillBuyer.buy(force=True)`) spends in this order: the listed tiers, then gold skills that fit the uma, then the rest (unlisted ○ first, then by grade per SP, blacklisted last); a gold's white already in the batch is not charged or sent twice. A skill tagged for a running style the uma doesn't run (a Front Runner skill on a Pace Chaser) is treated as unlisted even when the preset lists it, so it is only bought with leftover SP.
- **Skill hints are silent in the Senior year** (`training_brain.SENIOR_START_TURN` = 49): no hint bonus in training scores, Grand Live hint lessons rank last, and events drop hint must-picks/values. The panel's "Prioritise hints until turn" can only end it earlier.
- **Grand Live stamina push** (`GrandLiveStrategy._stamina_push`): in the 16 turns before a long goal race (> 2400 m) a training's Stamina gain earns score while Stamina is short of that race's need (`RacePlanner.STAMINA_NEED_BANDS`: 400 up to 3000 m, 500 above), growing toward the race; only the gain that closes the gap counts. The goal-driven Stamina cap in `_with_stat_caps` is just the ceiling.
- **Optional-race guard** (`TrainingBrain._optional_race_veto`): a race picked from the user's schedule is skipped on aptitude below B, a 3rd race in a row, a career-goal race within 2 turns, or mood <= 2, and the turn's reason says `skipped <race>: <why>`. On for Grand Live via `RACE_POLICY["optional_race_guard"]`, off for MANT/URA/Unity; the preset key `optional_race_guard` overrides. Goal, forced, fan-goal and maiden races never pass through it.
- **Many decision knobs are code-only defaults** (rainbow scoring, rescue thresholds, `ACTION_DELAY_SCALE`, etc.), not yet wired to the UI/preset; `serialize_preset` drops unknown keys.
- **Classify API result codes with `uma_api.client.is_api_error(exc, *codes)` / `api_error_code(exc)`**, never bare substring checks like `'205' in str(e)` — the message also embeds servertime/viewer_id digits, so substrings match by chance. They parse only the `API error <rc> on ` prefix `UmaClient.call` raises (outermost if chained).
- **API error 214** on `load/index` = resource-version mismatch. Fully update the game via Steam, let the title screen finish downloading, then restart the bot to capture fresh auth. **Error 1055** = viewer_id mismatch, typically after switching in-game accounts; restart with the intended account active.
- The user has **one Steam account with multiple in-game Uma accounts**; switching in-game invalidates the cached auth for the inactive one. Do **not** run two of their accounts simultaneously.
- **Guest (rental) parents:** borrowing a guest makes a temporary roster copy (`use_type` 1, `owner_viewer_id`/`owner_trained_chara_id` = the guest) that the game deletes when that career finishes. A career started in-game resumes with the copy's id as a parent, so `guest_copy_to_rental` turns it back into a guest borrow before the next start, and a start whose owned parent is missing from the roster stops with a clear message instead of 102-sweeping.
- In-game finish data is double-nested at `res['data']['data']`; `single_mode_finish_common.trained_chara` is the full roster list, not just the new uma.
- `pacing` lives in `delay.py` (`ACTION_DELAY_SCALE`; career length `CAREER_MINUTES_MIN/MAX`, default 15-16, set from the Web UI's CAREER (MIN)) and only applies when UI delays aren't disabled (NO CD). The pause before each turn is `TimingDNA.career_pause`: what is left of the career's budget after its measured play, spread over the turns left, so every career lands on its length; the runner calls `begin_career_pacing()` per career and `wait_turn_delay(turn)`.
