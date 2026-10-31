import os
import json
import re
import subprocess
import sys
import asyncio
import contextlib
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
if sys.version_info < (3, 10):
    sys.exit(f"MQA needs Python 3.10 or newer (this is {sys.version.split()[0]}).")

# Only (re)install dependencies when one is actually MISSING. Running
# "pip install -r requirements.txt" on every startup spammed the console with a wall of
# "Requirement already satisfied ..." for no reason. This stays silent when the deps are
# present and installs quietly (only) if an import is missing.
def _ensure_deps():
    import importlib
    for mod in ("fastapi", "frida", "msgpack", "Crypto", "pydantic", "uvicorn",
                "curl_cffi", "keyring", "python_multipart"):
        if mod == "frida" and os.name != "nt":
            continue   # capture is Windows-only; a carried-identity host never needs frida
        try:
            importlib.import_module(mod)
        except Exception:
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                                       "--disable-pip-version-check", "-r", "requirements.txt"])
            except Exception:
                pass
            return

_ensure_deps()
# Off Windows everything MQA creates from here on (Discord webhook config, logs, uma_runtime/) is
# owner-only: the usual umask 022 leaves it world-readable. Windows is unchanged.
if os.name != "nt":
    os.umask(0o077)

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
from typing import Optional
import random
import signal
import time
import threading
try:
    import frida   # only the Windows auth capture uses it
except ImportError:
    frida = None
from career_bot.core import master_data
from career_bot.core.presets import PresetStore
from career_bot.runner import CareerRunner
from career_bot.core.data_store import DataStore
from uma_api.client import (UmaClient, StateRecoveryError, is_api_error, carrying_identity,
                            load_auth_config, missing_carried_fields, runtime_output_root)
from career_bot.core.delay import GateKeeper, dna_sleep, dna_uniform, backoff_sleep, server_sleep
from api import static_routes, ai_routes

PROCESS_NAME = "UmamusumePrettyDerby.exe"
APP_ID = "3224770"

with open(os.path.join(APP_ROOT, 'frida_hook.js'), encoding='utf-8') as _hook:
    JS_CODE = _hook.read()


DIR = APP_ROOT

app = FastAPI()
# Self-contained route groups split out of main.py (see api/). The stateful auth/session/career
# endpoints stay below, where their module-level state lives.
app.include_router(static_routes.router)
app.include_router(ai_routes.router)

chara_map = {}
support_map = {}
active_client = None
active_account = None
active_dashboard_data = None
active_start_state = {}
active_parent_cards = {}
active_parent_rank_points = {}
# Roster id of a borrowed guest's temporary copy -> (owner viewer_id, owner trained_chara_id). The game
# adds the copy (use_type 1) when a career borrows a guest and removes it when that career finishes.
guest_copies = {}
# (parent_id_1, parent_id_2) -> the current_succession_rank_point value the server accepted, learned
# once by the start-102 sweep so every subsequent loop start with the same parents skips the sweep.
# Also saved per account in uma_runtime/succession_points.json (_remember_succession_point): kept only
# in memory, every MQA restart re-swept the same parents (~50 start calls, many answered 208 busy).
_succession_rank_point_cache = {}
_exiting = False            # set once uvicorn returns, so a running start sweep stops sending starts
_succession_saved = None    # {"<viewer_id>:<parent_1>:<parent_2>": value}, loaded on first use
pending_game_auth_config = {}
raw_load_index_response = None
active_selection = {
    "deck": None,
    "friend": None,
    "trainee": None,
    "veterans": []
}
preset_store = PresetStore(DIR)
career_runner = CareerRunner(DIR)

# --- Hard scenario lock -------------------------------------------------------
# The scenario (MANT / UNITY / URA) is CHOSEN once at terminal startup (interactive prompt, or the
# optional --scenario flag) and FROZEN for the whole process, forced into every career start so a
# running instance can never drift or silently fall back to MANT. To switch scenario, restart the
# terminal and choose again. The web UI just SHOWS the locked scenario (GET /api/scenario) -- it is
# not a toggle.
SCENARIO_ALIASES = {
    "mant": 4,
    "unity": 2,
    "ura": 1,
    "grand": 3,
    "grand live": 3,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
}
SCENARIO_NAMES = {1: "URA", 2: "UNITY", 3: "GRAND LIVE", 4: "MANT"}
LOCKED_SCENARIO_ID = 4  # overwritten by lock_scenario_at_startup() in __main__

def lock_scenario_at_startup(scenario):
    """Freeze LOCKED_SCENARIO_ID once, at process start, to the chosen scenario (2/4/1) or MANT (4)
    as the default. Returns the locked id."""
    global LOCKED_SCENARIO_ID
    sid = scenario or 4
    LOCKED_SCENARIO_ID = int(sid) if int(sid) in SCENARIO_NAMES else 4
    return LOCKED_SCENARIO_ID

def prompt_scenario_choice():
    """Ask, at terminal startup, which scenario to run THIS session. Returns 4 (MANT) / 2 (Unity) /
    1 (URA) / 3 (Grand Live), or None if there is no interactive terminal (caller falls back to the
    default). Restart the app to choose again."""
    try:
        print("\n=== Choose scenario for this session (restart to change) ===", flush=True)
        print("  [1] MANT  (Trackblazer)")
        print("  [2] UNITY (Aoharu / Unity Cup)")
        print("  [3] URA   (URA Finale)")
        print("  [4] GRAND LIVE (Our Grand Concert)")
        ans = input("Enter 1, 2, 3 or 4 (default 1 = MANT): ").strip().lower()
        # NOTE: the menu numbers are NOT the scenario ids -- menu 3 = URA (id 1), menu 4 = Grand Live (id 3).
        return {"2": 2, "unity": 2, "3": 1, "ura": 1, "4": 3, "grand": 3, "grand live": 3,
                "live": 3, "1": 4, "mant": 4, "": 4}.get(ans, 4)
    except (EOFError, KeyboardInterrupt):
        return None

base_dir = Path(DIR).absolute()
master_data_startup_status = master_data.status(base_dir)
if master_data_startup_status.get("exists"):
    master_data_startup_result = master_data.generate(base_dir)
    if master_data_startup_result.get("success"):
        print(f"master.mdb data generated: {master_data_startup_status.get('master_mdb_path')}")
    else:
        print(f"master.mdb data generation failed: {master_data_startup_result.get('detail')}")
elif master_data_startup_status.get("requires_user_action"):
    print(f"master.mdb requires user action: {master_data_startup_status.get('master_mdb_path')}")
# All data/*.json reference reads go through one validated DataStore (loaded AFTER the
# master.mdb regeneration above so it sees fresh files).
reference_data = DataStore(base_dir)
images_dir = base_dir / 'data' / 'images'

chara_map = reference_data.chara_list()
support_map = reference_data.support_list()

def display_support_type(value):
    return {
        "Friends": "Pal",
        "Wisdom": "Wit"
    }.get(value, value)


def normalize_turn_delay(min_value, max_value, disabled=False):
    left = max(0.0, float(min_value or 0.0))
    right = max(0.0, float(max_value or 0.0))
    if left > right:
        right = left
    if disabled:
        left = 0.0
        right = 0.0
    return left, right, bool(disabled)

def set_turn_delay(min_value, max_value, disabled=False):
    """Career length in MINUTES (min/max: each career draws its target in this range; MQA spreads
    the waiting over the turns). The endpoint keeps its old turn-delay name."""
    import career_bot.core.delay as delay_module
    next_min, next_max, next_disabled = normalize_turn_delay(min_value, max_value, disabled)
    if not next_disabled:
        delay_module.CAREER_MINUTES_RESTORE_MIN = next_min
        delay_module.CAREER_MINUTES_RESTORE_MAX = next_max
    delay_module.CAREER_MINUTES_MIN = next_min
    delay_module.CAREER_MINUTES_MAX = next_max
    delay_module.GLOBAL_DELAYS_DISABLED = next_disabled
    return get_turn_delay()

def get_turn_delay():
    import career_bot.core.delay as delay_module
    return {
        "success": True,
        "unit": "career_minutes",
        "min": delay_module.CAREER_MINUTES_MIN,
        "max": delay_module.CAREER_MINUTES_MAX,
        "restore_min": delay_module.CAREER_MINUTES_RESTORE_MIN,
        "restore_max": delay_module.CAREER_MINUTES_RESTORE_MAX,
        "disabled": getattr(delay_module, "GLOBAL_DELAYS_DISABLED", False)
    }

def update_start_state(data):
    global active_start_state
    if not data:
        return
    if data.get('tp_info'):
        tp_info = dict(data.get('tp_info'))
        active_start_state['tp_info'] = tp_info
    item_list = data.get('item_list')
    if item_list is None:
        item_list = data.get('user_item_array')
    if isinstance(item_list, list):
        active_start_state['current_money'] = get_item_count(item_list, 59)
        active_start_state['succession_rank_point'] = get_item_count(item_list, 75)
    for c in data.get('trained_chara') or []:
        owner_vid, owner_tcid = int(c.get('owner_viewer_id') or 0), int(c.get('owner_trained_chara_id') or 0)
        if int(c.get('use_type') or 0) == 1 and owner_vid and owner_tcid:
            guest_copies[int(c.get('trained_chara_id') or 0)] = (owner_vid, owner_tcid)


def guest_copy_to_rental(req):
    """A career started in-game with a guest parent resumes with the guest's temporary roster copy as
    an owned parent id. The copy is gone once that career finishes, so the next start would send a
    dead id (live 2026-10-27: 102, then ~50 succession sweeps). Borrow the original guest instead."""
    if int(getattr(req, 'rental_trained_chara_id', 0) or 0):
        return None
    p1, p2 = int(req.parent_id_1 or 0), int(req.parent_id_2 or 0)
    copy_id = p2 if p2 in guest_copies else p1 if p1 in guest_copies else 0
    if not copy_id:
        return None
    req.rental_viewer_id, req.rental_trained_chara_id = guest_copies[copy_id]
    if copy_id == p1:
        req.parent_id_1 = p2
    req.parent_id_2 = 0
    return (f"parent {copy_id} is a borrowed guest's temporary copy -> borrowing guest "
            f"{req.rental_trained_chara_id} again")


def normalize_friend_cards(data):
    source = 'refresh'
    friend_data = data.get('friend_support_card_data')
    if friend_data:
        source = 'initial'
        summaries = friend_data.get('summary_user_info_array', [])
        support_cards = friend_data.get('support_card_data_array', [])
    else:
        summaries = data.get('summary_user_info_array', [])
        support_cards = data.get('support_card_data_array', [])

    support_by_key = {}
    for sc in support_cards or []:
        key = (sc.get('viewer_id'), sc.get('support_card_id'))
        support_by_key[key] = sc

    friends = []
    exclude_viewer_ids = []
    seen = set()
    for info in summaries or []:
        viewer_id = info.get('viewer_id')
        support_card_id = info.get('support_card_id')
        if not viewer_id or not support_card_id:
            continue
        key = (viewer_id, support_card_id)
        if key in seen:
            continue
        seen.add(key)
        exclude_viewer_ids.append(viewer_id)
        card_data = support_by_key.get(key) or info.get('user_support_card') or {}
        support_info = support_map.get(str(support_card_id), {})
        friends.append({
            'viewer_id': viewer_id,
            'name': info.get('name', ''),
            'support_card_id': support_card_id,
            'support_name': support_info.get('name', f"Unknown ({support_card_id})"),
            'rarity': support_info.get('rarity', '?'),
            'type': display_support_type(support_info.get('type', 'Unknown')),
            'exp': card_data.get('exp', info.get('user_support_card', {}).get('exp')),
            'limit_break_count': card_data.get('limit_break_count', info.get('user_support_card', {}).get('limit_break_count')),
            'favorite_flag': card_data.get('favorite_flag', 0),
            'friend_state': info.get('friend_state', 0)
        })
    # Surface the strongest cards first in the UI: highest limit break, then exp (card level) as the
    # tiebreak. Both can be None on older payloads, so coerce to 0.
    friends.sort(key=lambda f: (f.get('limit_break_count') or 0, f.get('exp') or 0), reverse=True)
    return friends, exclude_viewer_ids, source


def normalize_guest_parents(data):
    """GUEST (rental) parent candidates from pre_single_mode's succession_trained_chara_data -- OTHER
    players' trained chara you can borrow for one inheritance slot. Also caches each candidate's
    affinity data (card_id, grandparents, wins) into active_parent_rank_points so the succession-rank
    estimate is EXACT when a guest is chosen (else the start 102s -> sweep). Returns a UI list."""
    arr = ((data.get('succession_trained_chara_data') or {}).get('succession_trained_chara_array')) or []
    guests, seen = [], set()
    for e in arr:
        tcid = e.get('trained_chara_id')
        vid = e.get('viewer_id')
        if not tcid or not vid or (vid, tcid) in seen:
            continue
        seen.add((vid, tcid))
        cid = int(e.get('card_id') or 0)
        guests.append({
            'trained_chara_id': int(tcid),
            'viewer_id': int(vid),
            'card_id': cid,
            'name': chara_map.get(str(cid), f"Unknown ({cid})"),
            'rank': int(e.get('rank') or 0),
            # same lineage/factor/wins tree owned parents carry, so the guest card gets the identical
            # hover sparks preview (renderParentSparks reads g.tree in the frontend).
            'tree': build_lineage_tree(e, cid),
        })
        # cache the guest's affinity data (same shape as owned parents) so _succession_affinity_point
        # computes the exact current_succession_rank_point when this guest is picked.
        active_parent_rank_points[int(tcid)] = {
            'rank': e.get('rank', 0),
            'rank_score': e.get('rank_score', 0),
            'card_id': cid,
            'succession_chara_array': e.get('succession_chara_array') or [],
            'win_saddle_id_array': e.get('win_saddle_id_array') or [],
        }
        active_parent_cards[int(tcid)] = [cid] + [
            int(sc.get('card_id') or 0) for sc in (e.get('succession_chara_array') or []) if sc.get('card_id')]
    guests.sort(key=lambda g: g.get('rank') or 0, reverse=True)   # strongest first
    return guests


def resolve_guest_parent(want_vid, want_tcid, offered, parent_id_1=0):
    """Re-resolve a requested GUEST parent against the CURRENTLY-offered rental list. The list rotates
    per career, so a continuous run's 2nd+ start would otherwise blindly send the stale first-run guest
    -> a deterministic 102 that kills the whole loop. Mirrors the friend-card fallback chain above:
    exact guest -> same character (card_id, best rank) -> best affinity with parent 1 (rank tiebreak).
    Returns (viewer_id, trained_chara_id, note); note is None when the exact guest is still offered,
    else the log line describing the swap. An empty offered list keeps the request unchanged (the
    start path's 102 recovery is the backstop when pre_single_mode gave us nothing)."""
    want_vid, want_tcid = int(want_vid or 0), int(want_tcid or 0)
    if not offered:
        return want_vid, want_tcid, None
    for g in offered:
        if int(g.get('viewer_id') or 0) == want_vid and int(g.get('trained_chara_id') or 0) == want_tcid:
            return want_vid, want_tcid, None
    # same character, if we still know the stale guest's card (cached when it was first surfaced)
    want_card = int((active_parent_rank_points.get(want_tcid) or {}).get('card_id') or 0)
    same_card = [g for g in offered if want_card and int(g.get('card_id') or 0) == want_card]
    if same_card:
        g = max(same_card, key=lambda x: int(x.get('rank') or 0))
        return (int(g['viewer_id']), int(g['trained_chara_id']),
                f"guest {want_tcid} no longer offered -> borrowing the same character "
                f"({g.get('name')}) from guest {g['trained_chara_id']}")
    # best inheritance affinity with parent 1 (exact succession points; rank breaks ties/missing data)
    def _aff(g):
        a = _succession_affinity_point(int(parent_id_1 or 0), int(g.get('trained_chara_id') or 0))
        return (a if a is not None else -1, int(g.get('rank') or 0))
    g = max(offered, key=_aff)
    return (int(g['viewer_id']), int(g['trained_chara_id']),
            f"guest {want_tcid} no longer offered (no same-character guest either) -> borrowing the "
            f"best-affinity offered guest {g.get('name')} ({g['trained_chara_id']})")


def normalize_card_name(name):
    return re.sub(r'[^a-z0-9]+', '', re.sub(r'\([^)]*\)', '', str(name or '').lower()))


def validate_start_selection(req):
    support_ids = [int(card_id) for card_id in req.support_card_ids]
    friend_card_id = int(req.friend_card_id)
    if friend_card_id in support_ids:
        return "Friend support card is already in selected deck"

    friend_info = support_map.get(str(friend_card_id), {})
    friend_name = normalize_card_name(friend_info.get('name'))
    if not friend_name:
        return None

    for support_id in support_ids:
        support_name = normalize_card_name(support_map.get(str(support_id), {}).get('name'))
        if support_name and support_name == friend_name:
            return "Friend support card has same character as selected deck"

    trainee_name = normalize_card_name(chara_map.get(str(req.card_id), ''))
    if trainee_name and trainee_name == friend_name:
        return "Friend support card has same character as trainee"

    parent1_cards = active_parent_cards.get(int(req.parent_id_1), [])
    parent2_cards = active_parent_cards.get(int(req.parent_id_2), [])
    if parent1_cards and parent2_cards and int(req.card_id) in (parent1_cards[0], parent2_cards[0]):
        return "Selected direct parent is same character as trainee"

    return None


def deck_type_counts_from_ids(support_ids, friend_card_id=0):
    counts = [0] * 5
    for sid_int in list(support_ids or []) + ([friend_card_id] if friend_card_id else []):
        info = support_map.get(str(sid_int))
        if not info:
            continue
        ctype = info.get('type')
        if ctype == "Speed": counts[0] += 1
        elif ctype == "Stamina": counts[1] += 1
        elif ctype == "Power": counts[2] += 1
        elif ctype == "Guts": counts[3] += 1
        elif ctype == "Wisdom": counts[4] += 1
    return counts


def deck_type_counts_from_chara(chara_info):
    ids = []
    for card in (chara_info or {}).get('support_card_array') or []:
        sid = int(card.get('support_card_id') or 0)
        if sid:
            ids.append(sid)
    return deck_type_counts_from_ids(ids)


def apply_deck_type_counts(preset, req=None, chara_info=None):
    counts = None
    if req and (req.support_card_ids or req.friend_card_id):
        counts = deck_type_counts_from_ids(req.support_card_ids, req.friend_card_id)
    elif chara_info:
        counts = deck_type_counts_from_chara(chara_info)
    if counts is not None:
        preset["_deck_type_counts"] = counts
        scale_table = [0.0, 0.02, 0.05, 0.09, 0.14, 0.20]
        preset["_deck_multipliers"] = [1.0 + scale_table[min(5, c)] for c in counts]


# current_succession_rank_point per-parent ESTIMATE = rank_score // divisor[rank]. Reverse-engineered
# from live rc=1 captures (rank 14 -> /128 exact: 311+1261=201; rank 15 -> /117 exact: 790+1356=258).
# Other ranks default to 117 -- only an estimate; the start-102 sweep in start_career_from_request
# corrects any residual error and caches the true value per parent-pair.
_SUCCESSION_RANK_DIVISOR = {14: 128}

def parent_rank_point(parent_id):
    parent = active_parent_rank_points.get(int(parent_id))
    if not parent:
        return 0
    rank = int(parent.get('rank') or 0)
    return int(parent.get('rank_score') or 0) // _SUCCESSION_RANK_DIVISOR.get(rank, 117)


_relation_members = None   # chara_id -> set(relation_type)
_relation_points = None    # relation_type -> point value; both loaded lazily from data/

def _load_succession_affinity():
    global _relation_members, _relation_points
    if _relation_members is not None:
        return _relation_members, _relation_points
    members, points = {}, {}
    try:
        for m in json.loads((base_dir / "data" / "succession_relation_member.json").read_text(encoding="utf-8")):
            members.setdefault(int(m["chara_id"]), set()).add(m["relation_type"])
        for p in json.loads((base_dir / "data" / "succession_relation.json").read_text(encoding="utf-8")):
            points[p["relation_type"]] = p["relation_point"]
    except Exception as e:
        print(f"[succession] affinity tables unavailable ({e}) -- falling back to rank estimate", flush=True)
    _relation_members, _relation_points = members, points
    return members, points


def _succession_affinity_point(p1_id, p2_id):
    """EXACT current_succession_rank_point = the inheritance COMPATIBILITY score, computed from the 2
    parents + their 4 grandparents (Icarus's model, ported): over 5 affinity links, sum the two charas'
    shared relation-group points (succession_relation*) + a shared-race bonus. This is the real formula
    the server validates -- unlike rank_score//divisor, which only approximates it and left the sweep
    unable to reach the true value. Returns None when parent data or the tables are missing (caller
    then falls back to the old estimate, and the sweep still backstops any residual)."""
    p1 = active_parent_rank_points.get(int(p1_id))
    p2 = active_parent_rank_points.get(int(p2_id))
    if not p1 or not p2:
        return None
    members, points = _load_succession_affinity()
    if not members:
        return None

    def gp(parent_obj, pos_id):
        for sc in parent_obj.get("succession_chara_array") or []:
            if sc.get("position_id") == pos_id:
                return sc
        return None

    # the 6-member family: parents at 10/20, their grandparents at 11/12 (under p1) and 21/22 (under p2)
    family = {10: p1, 20: p2, 11: gp(p1, 10), 12: gp(p1, 20), 21: gp(p2, 10), 22: gp(p2, 20)}
    total = 0
    for pos1, pos2 in ((10, 20), (10, 11), (10, 12), (20, 21), (20, 22)):
        c1, c2 = family.get(pos1), family.get(pos2)
        if not c1 or not c2:
            continue
        chara1 = int(c1.get("card_id") or 0) // 100    # card_id -> base chara_id (relation key)
        chara2 = int(c2.get("card_id") or 0) // 100
        shared = members.get(chara1, set()) & members.get(chara2, set())
        link = sum(points.get(t, 0) for t in shared)
        link += len(set(c1.get("win_saddle_id_array") or []) & set(c2.get("win_saddle_id_array") or []))
        total += link
    return int(total)


def _succession_cache_pair(req):
    """Canonical (parent_1, parent_2) key for _succession_rank_point_cache. A GUEST (rental) parent
    fills the 2nd inheritance slot, so key on its trained_chara_id -- NOT the owned parent_id_2, which
    the start request forces to 0 whenever a guest is used. The learned-value READ and the sweep's
    WRITE must derive the key IDENTICALLY (both call this), or a guest career never re-hits its
    calibrated succession point and re-sweeps from scratch every single time."""
    p1 = int(getattr(req, 'parent_id_1', 0) or 0)
    p2 = int(getattr(req, 'rental_trained_chara_id', 0) or 0) or int(getattr(req, 'parent_id_2', 0) or 0)
    return (p1, p2)


def _succession_saved_key(pair):
    """Key for the saved value, or None without a logged-in account: trained_chara ids are per
    account, so the same pair on another account is a different family."""
    vid = int(getattr(active_client, "viewer_id", 0) or 0) if active_client else 0
    return f"{vid}:{int(pair[0])}:{int(pair[1])}" if vid else None


def _succession_saved_values():
    global _succession_saved
    if _succession_saved is None:
        try:
            loaded = json.loads((runtime_output_root() / "succession_points.json").read_text(encoding="utf-8"))
            _succession_saved = loaded if isinstance(loaded, dict) else {}
        except Exception:
            _succession_saved = {}
    return _succession_saved


def _learned_succession_point(pair):
    """The value the server accepted for these parents before: this run, or saved by an earlier one."""
    if pair in _succession_rank_point_cache:
        return _succession_rank_point_cache[pair]
    key = _succession_saved_key(pair)
    value = _succession_saved_values().get(key) if key else None
    return int(value) if value is not None else None


def _remember_succession_point(pair, value):
    _succession_rank_point_cache[pair] = int(value)
    key = _succession_saved_key(pair)
    if not key:
        return
    saved = _succession_saved_values()
    saved[key] = int(value)
    try:
        path = runtime_output_root() / "succession_points.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".json.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(saved, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as exc:
        print(f"[succession] could not save the learned value ({exc}); it is kept for this run", flush=True)


def selected_succession_rank_point(req):
    # The exact value the SERVER validates against. Priority: env override -> learned cache ->
    # inheritance-AFFINITY computation (exact) -> the old rank estimate (last resort). The start-102
    # sweep still backstops any residual, but the affinity value lands the start on the first try.
    # ESCAPE HATCH: env UMA_SUCCESSION_RP pins the value (shown on the game's career-start screen).
    override = os.environ.get("UMA_SUCCESSION_RP")
    if override not in (None, ""):
        try:
            return int(override)
        except ValueError:
            pass
    # A GUEST (rental) parent takes the 2nd inheritance slot -> the pair keys on its trained_chara_id
    # (its data is cached by normalize_guest_parents), else the owned parent_id_2.
    pair = _succession_cache_pair(req)
    p1, p2 = pair
    learned = _learned_succession_point(pair)
    if learned is not None:
        return learned
    affinity = _succession_affinity_point(p1, p2)
    if affinity is not None:
        return affinity
    return parent_rank_point(p1) + parent_rank_point(p2)


def _succession_sweep_candidates(est, held, span=40, held_span=20):
    """Ordered current_succession_rank_point values to try when start 102s on a wrong succession point.

    The estimate is now the inheritance-affinity value: exact for 104 of 145 accepted starts in the
    captures and otherwise off by -7..+24 (all within span), so walk outward from it first. The
    account's HELD succession points (item 75) and 0 date from the old rank_score estimate (seen live:
    estimate 335 while the account held 53); no accepted value was ever near either, so they go last.
    Non-negative, de-duplicated, estimate first."""
    seeds, seen = [], set()

    def add(v):
        v = int(v)
        if v >= 0 and v not in seen:
            seen.add(v)
            seeds.append(v)

    add(est)
    for n in range(1, span + 1):
        add(est + n)
        add(est - n)
    add(held)
    add(0)
    for n in range(1, held_span + 1):
        add(held + n)
        add(held - n)
    return seeds

skill_data = reference_data.skill_data()
factor_map = reference_data.factor_map()
race_map = reference_data.race_map()

def skill_entry_name(entry):
    if isinstance(entry, dict):
        return entry.get("name") or ""
    return entry

def get_win_summary(win_saddle_ids):
    summary = {
        "g1": 0,
        "g2": 0,
        "g3": 0
    }

    for saddle_id in win_saddle_ids or []:
        race = race_map.get(str(saddle_id))
        grade = race.get("grade") if race else None
        if grade == "G1":
            summary["g1"] += 1
        elif grade == "G2":
            summary["g2"] += 1
        elif grade == "G3":
            summary["g3"] += 1

    summary["total"] = summary["g1"] + summary["g2"] + summary["g3"]
    return summary

def clean_factor_name(name, base_id=None, category=None):
    if not isinstance(name, str):
        return name

    if category == "skill" and "?" in name and base_id is not None:
        skill_name = skill_entry_name(skill_data.get(f"{base_id}2"))
        if skill_name:
            return skill_name
    return name.replace(" ?", " ○")

def get_factors(fid_array, owner_card_id=None):
    results = []
    category_order = {
        "stat": 0,
        "aptitude": 1,
        "unique": 2,
        "race": 3,
        "skill": 4,
        "scenario": 5,
        "other": 6
    }
    stat_map = {
        1: 'Speed', 2: 'Stamina', 3: 'Power', 4: 'Guts', 5: 'Wit',
        11: 'Turf', 12: 'Dirt',
        21: 'Short', 22: 'Mile', 23: 'Medium', 24: 'Long',
        31: 'Front Runner', 32: 'Pace Chaser', 33: 'Late Surger', 34: 'End Closer'
    }
    
    owner_cid_str = str(owner_card_id) if owner_card_id else ""
    if len(owner_cid_str) > 4: owner_cid_str = owner_cid_str[:4]

    for fid in fid_array:
        if not fid or fid <= 0: continue

        fid_str = str(fid)
        factor_info = factor_map.get(fid_str)
        if factor_info:
            base_id = fid // 100
            category = factor_info.get("category", "other")
            name = clean_factor_name(factor_info.get("name", f"Unknown({fid})"), base_id, category)
            stars = factor_info.get("stars", fid % 100)
            results.append({"name": name, "stars": stars, "id": fid, "category": category})
            continue

        base_id = fid // 100
        stars = fid % 100
        bid_str = str(base_id)
        name = f"Unknown({base_id})"
        category = "other"
        
        if base_id <= 34:
            category = "stat" if base_id <= 5 else "aptitude"
            name = stat_map.get(base_id, name)
        
        elif bid_str in skill_data:
            category = "skill"
            name = skill_entry_name(skill_data[bid_str])
            
        results.append({"name": name, "stars": stars, "id": base_id, "category": category})

    return [
        factor for _, factor in sorted(
            enumerate(results),
            key=lambda item: (category_order.get(item[1]["category"], 99), item[0])
        )
    ]


def get_chara_factor_ids(chara):
    factor_ids = chara.get('factor_id_array')
    if isinstance(factor_ids, list) and factor_ids:
        return factor_ids
    return [f.get('factor_id', 0) for f in chara.get('factor_info_array', [])]


def build_lineage_tree(chara, cid):
    """Inheritance lineage (self + p1/p2 + gp1-4) with factors + wins for the UI spark preview.
    Shared by OWNED parents and rental GUEST parents -- both are trained_chara with the same shape
    (succession_chara_array + factors via factor_id_array OR factor_info_array, normalized by
    get_chara_factor_ids). Grandparent factors go through get_chara_factor_ids too so a guest's
    factor_info_array-only lineage members resolve (owned parents are unaffected -- factor_id_array
    still wins when present)."""
    cid = str(cid)
    tree = {k: {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([])}
            for k in ("self", "p1", "p2", "gp1", "gp2", "gp3", "gp4")}
    tree["self"]["card_id"] = cid
    tree["self"]["name"] = chara_map.get(cid, f"Unknown ({cid})")
    tree["self"]["wins"] = get_win_summary(chara.get('win_saddle_id_array', []))
    tree["self"]["factors"] = get_factors(get_chara_factor_ids(chara), cid)
    pos_key = {10: "p1", 20: "p2", 11: "gp1", 12: "gp2", 21: "gp3", 22: "gp4"}
    for sc in chara.get('succession_chara_array', []) or []:
        key = pos_key.get(sc.get('position_id'))
        if not key:
            continue
        sc_cid = sc.get('card_id', 0)
        tree[key]["card_id"] = sc_cid
        tree[key]["name"] = chara_map.get(str(sc_cid), f"Unknown ({sc_cid})")
        tree[key]["factors"] = get_factors(get_chara_factor_ids(sc), sc_cid)
        tree[key]["wins"] = get_win_summary(sc.get('win_saddle_id_array', []))
    return tree


def build_parents_from_trained_chara(trained_chara_list):
    """Build the dashboard `parents` list (the finished-trainee roster) from a load/index
    `trained_chara` array, and (re)populate the active_parent_cards / active_parent_rank_points
    globals that the start/succession path reads. Extracted so both login and the trainee-delete
    endpoint rebuild the roster identically. Returns the parents list, sorted least-used-first."""
    global active_parent_cards, active_parent_rank_points
    active_parent_cards = {}
    active_parent_rank_points = {}
    parents = []
    for chara in trained_chara_list or []:
        raw_id = str(chara.get('card_id', ''))
        if '{' in raw_id or '-' in raw_id or not raw_id.isdigit():
            found = False
            for key, val in chara.items():
                val_str = str(val)
                if val_str.isdigit() and len(val_str) >= 4:
                    raw_id = val_str
                    found = True
                    break
            if not found:
                continue
        cid = raw_id
        tree = build_lineage_tree(chara, cid)
        parents.append({
            'instance_id': chara.get('trained_chara_id'),
            'card_id': cid,
            'name': chara_map.get(cid, f"Unknown ({cid})"),
            'rank': chara.get('rank', 0),
            # succession_num = times used as an inheritance parent. Heavily-reused parents are
            # rejected by single_mode_free/start with 102 (the game's parent-select hides them);
            # surfaced + sorted least-used-first so the UI offers valid picks.
            'succession_num': chara.get('succession_num', 0),
            # Roster-management fields (trainee deletion UI): is_locked (0/1) is the game's own
            # protect flag -- the delete panel must never offer a locked trainee, and the delete
            # endpoint refuses one server-side. create_time lets the user spot old trainees.
            'is_locked': int(chara.get('is_locked', 0) or 0),
            'is_saved': int(chara.get('is_saved', 0) or 0),
            'create_time': chara.get('create_time') or chara.get('register_time') or '',
            'tree': tree
        })
        lineage_cards = [int(cid)]
        for sc in chara.get('succession_chara_array', []) or []:
            sc_cid = sc.get('card_id', 0)
            if sc_cid:
                lineage_cards.append(int(sc_cid))
        active_parent_cards[int(chara.get('trained_chara_id'))] = lineage_cards
        active_parent_rank_points[int(chara.get('trained_chara_id'))] = {
            'rank': chara.get('rank', 0),
            'rank_score': chara.get('rank_score', 0),
            # for the inheritance-affinity succession estimate (exact current_succession_rank_point):
            'card_id': chara.get('card_id', 0),
            'succession_chara_array': chara.get('succession_chara_array') or [],  # the 2 grandparents
            'win_saddle_id_array': chara.get('win_saddle_id_array') or [],        # shared-race bonus
        }
    parents.sort(key=lambda p: p.get('succession_num') or 0)  # least-used (start-eligible) first
    return parents


def get_item_count(item_list, item_id):
    for item in item_list or []:
        if item.get('item_id') == item_id:
            return item.get('number', 0)
    return 0


def get_account_status(data, career_data=None):
    tp_info = data.get('tp_info') or (active_client.tp_info if active_client else {})
    coin_info = data.get('coin_info') or (active_client.coin_info if active_client else {})
    item_list = data.get('item_list') or data.get('user_item_array')
    if item_list is None:
        gold = active_client.item_map.get(59, 0) if active_client else 0
    else:
        gold = get_item_count(item_list, 59)
    career = data.get('single_mode_chara_light') or None

    if career_data:
        career_payload = career_data.get('data') if career_data.get('data') else career_data
        if career_payload.get('chara_info'):
            career = career_payload.get('chara_info')

    status = {
        "tp": {
            "current": tp_info.get('current_tp', 0),
            "max": tp_info.get('max_tp', 0)
        },
        "carrots": {
            "free": coin_info.get('fcoin', 0) or 0,
            "paid": coin_info.get('coin', 0) or 0,
            "total": (coin_info.get('fcoin', 0) or 0) + (coin_info.get('coin', 0) or 0)
        },
        "gold": gold,
        "clocks": active_client.item_map.get(95, 0) if active_client else 0,
        "tp_bottles": active_client.item_map.get(TOUGHNESS_30_ITEM_ID, 0) if active_client else 0,
        "career": None
    }
    if career:
        card_id = str(career.get('card_id', ''))
        
        p1 = career.get('succession_trained_chara_id_1')
        p2 = career.get('succession_trained_chara_id_2')

        friend_viewer_id = None
        friend_card_id = None
        friend_support = None
        current_deck_cards = []
        current_deck_supports = []
        
        support_array = career.get('support_card_array') or []
        for sc in support_array:
            pos = sc.get('position')
            if pos == 6:
                friend_viewer_id = sc.get('owner_viewer_id')
                friend_card_id = sc.get('support_card_id')
                friend_info = support_map.get(str(friend_card_id))
                friend_support = {
                    "viewer_id": friend_viewer_id,
                    "support_card_id": friend_card_id,
                    "support_name": friend_info['name'] if friend_info else f"Unknown ({friend_card_id})",
                    "rarity": friend_info['rarity'] if friend_info else "?",
                    "type": display_support_type(friend_info['type']) if friend_info else "?",
                    "limit_break_count": sc.get('limit_break_count')
                }
            elif 1 <= pos <= 5:
                support_card_id = sc.get('support_card_id')
                current_deck_cards.append(support_card_id)
                support_info = support_map.get(str(support_card_id))
                current_deck_supports.append({
                    "id": str(support_card_id),
                    "name": support_info['name'] if support_info else f"Unknown ({support_card_id})",
                    "rarity": support_info['rarity'] if support_info else "?",
                    "type": display_support_type(support_info['type']) if support_info else "?"
                })

        matched_deck_id = None
        user_decks = data.get('support_card_deck_array') or []
        if current_deck_cards:
            current_deck_set = set(current_deck_cards)
            for deck in user_decks:
                deck_cards = deck.get('support_card_id_array') or []
                if set(deck_cards) == current_deck_set:
                    matched_deck_id = deck.get('deck_id')
                    break

        status["career"] = {
            "active": True,
            "card_id": card_id,
            "name": chara_map.get(card_id, f"Unknown ({card_id})"),
            "turn": career.get('turn', 0),
            "scenario_id": career.get('scenario_id', 0),
            "fans": career.get('fans', 0),
            "vital": career.get('vital', 0),
            "max_vital": career.get('max_vital', 0),
            "deck_id": matched_deck_id,
            "support_card_ids": current_deck_cards,
            "support_cards": current_deck_supports,
            "friend_viewer_id": friend_viewer_id,
            "friend_card_id": friend_card_id,
            "friend": friend_support,
            "parent_id_1": p1,
            "parent_id_2": p2,
        }

    return status




class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""
    code: str = ""
    steam_id: str = ""
    steam_session_ticket: str = ""

class DeleteCareerRequest(BaseModel):
    current_turn: int = 0

class DeleteTraineesRequest(BaseModel):
    # Finished trainees (trained_chara_id) the user picked to permanently release.
    trained_chara_ids: list[int] = []

# TP-recovery item used by default at career start. "Toughness 30" (master.mdb item
# id 32) restores exactly 30 TP = one career start. RP items like Carrot Jelly Mini
# (id 34) restore RP -- a DIFFERENT resource (max 5) -- and cannot start a career.
TOUGHNESS_30_ITEM_ID = 32


class StartCareerRequest(BaseModel):
    card_id: int
    support_card_ids: list[int]
    friend_viewer_id: int
    friend_card_id: int
    parent_id_1: int
    parent_id_2: int
    rental_viewer_id: int = 0          # a borrowed GUEST parent (owner's viewer_id) -> the rental slot
    rental_trained_chara_id: int = 0   # ...and its trained_chara_id (0/0 = no guest, owned-only start)
    scenario_id: int = 4
    deck_id: int = 1
    use_tp: int = 30
    tp_recovery_mode: str = "item_then_jewels"
    tp_recovery_item_id: int = TOUGHNESS_30_ITEM_ID
    difficulty_id: int = 0
    difficulty: int = 0
    is_boost: int = 0
    boost_story_event_id: int = 0
    burn_clocks: bool = False


class RunCareerRequest(BaseModel):
    card_id: int = 0
    support_card_ids: list[int] = []
    friend_viewer_id: int = 0
    friend_card_id: int = 0
    parent_id_1: int = 0
    parent_id_2: int = 0
    rental_viewer_id: int = 0          # borrowed GUEST parent -> rental slot (0/0 = owned-only)
    rental_trained_chara_id: int = 0
    scenario_id: int = 0
    deck_id: int = 1
    use_tp: int = 30
    # TP-recovery at career start. "item_then_jewels" (default, the user's choice) = TP bottles
    # (Toughness 30 = id 32, restores 30 TP = exactly one career) while they last, then carats;
    # "item" = bottles only; "jewels" = always carats; "off" = never auto-recover.
    # NOTE: RP items like Carrot Jelly Mini
    # (id 34) restore RP, a DIFFERENT resource (max 5) -- they do NOT recover career TP.
    tp_recovery_mode: str = "item_then_jewels"
    tp_recovery_item_id: int = TOUGHNESS_30_ITEM_ID
    difficulty_id: int = 0
    difficulty: int = 0
    is_boost: int = 0
    boost_story_event_id: int = 0
    preset_name: str = ""
    max_steps: int = 2500
    burn_clocks: bool = False
    dev_mode: bool = False
    run_count: int = 1
    # Non-MANT opt-in: honor the preset's extra_race_list ON TOP of career goals (URA/Unity). Off ->
    # career goals only. Ignored for MANT (which always uses the schedule).
    use_race_schedule: bool = False
    # UI "FINISH" toggle: True = play a single career through to the natural turn-78
    # finish; False (default) = hard-stop at turn 77 and leave it unfinished. Loops
    # (run_count != 1) always finish regardless, so this only affects single runs.
    finish_career: bool = False

class SaveRacesRequest(BaseModel):
    preset_name: str
    races: list[int]

class SavePresetRequest(BaseModel):
    preset: dict

class DeletePresetByNameRequest(BaseModel):
    name: str

class CareerActionRequest(BaseModel):
    command_type: int
    command_id: int
    current_turn: int
    current_vital: int
    command_group_id: int = 0
    select_id: int = 0

class FriendListRequest(BaseModel):
    exclude_viewer_ids: list[int] = []

class ApiDelayRequest(BaseModel):
    min: float = 15.0          # career length, minutes
    max: float = 16.0
    disabled: bool = False

class MasterDataPathRequest(BaseModel):
    master_mdb_path: str


# ====================== SETTINGS / WEBHOOK / MASTER DATA ======================
@app.get("/api/settings/turn-delay")
async def get_turn_delay_settings():
    return get_turn_delay()

@app.post("/api/settings/turn-delay")
async def set_turn_delay_settings(req: ApiDelayRequest):
    return set_turn_delay(req.min, req.max, req.disabled)

# --- Scenario shower (read-only) ------------------------------------------------
# The scenario is CHOSEN at terminal startup and FROZEN (see lock_scenario_at_startup). The web UI
# only DISPLAYS it -- there is no toggle; restart the terminal to choose again.
@app.get("/api/scenario")
async def get_scenario():
    return {
        "locked_scenario_id": LOCKED_SCENARIO_ID,
        "locked_name": SCENARIO_NAMES.get(LOCKED_SCENARIO_ID, str(LOCKED_SCENARIO_ID)),
    }

# --- Event choices (EVENT CHOICES tab) ------------------------------------------
# Manual per-event overrides live in uma_runtime/ (never data/). The bot logs every
# multi-choice event it meets to events_seen.json so the UI can list them.
class EventOverrideRequest(BaseModel):
    story_id: str
    choice: int = -1   # -1 = clear the override (back to auto)

def _event_paths():
    rt = base_dir / "uma_runtime"
    return rt / "events_seen.json", rt / "event_overrides.json", base_dir / "data" / "event_outcomes.json"

def _read_json_file(p):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}

def _active_deck_card_ids():
    """Support-card ids of the deck the bot is running with: the current (or most recently
    loaded) career's 5 deck cards + the friend slot, read from active_account. Deliberately
    NOT gated on career['active'] so the deck stays browsable between runs. Empty when no
    login/career data is loaded."""
    try:
        career = (active_account or {}).get("career") or {}
        ids = [int(c) for c in (career.get("support_card_ids") or []) if c]
        friend_id = int(career.get("friend_card_id") or 0)
        if friend_id and friend_id not in ids:
            ids.append(friend_id)
        return ids
    except Exception:
        return []



# ====================== EVENTS ======================
@app.get("/api/events")
async def get_events(cards: str = ""):
    # `cards` = comma-separated support_card_ids. When omitted, the deck is resolved
    # server-side from the ACTIVE career (the cards you actually brought), so the UI
    # needs no deck picker. The event list is pre-populated from master.mdb for those
    # cards, merged with anything already seen / in the outcome DB.
    seen_path, ov_path, _ = _event_paths()
    seen = _read_json_file(seen_path)
    overrides = _read_json_file(ov_path)
    db = reference_data.event_outcomes()
    # Observed per-choice outcomes the bot has recorded while playing (stat deltas).
    choice_obs = _read_json_file(base_dir / "uma_runtime" / "event_choice_outcomes.json")
    merged = {}
    for sid in set(seen.keys()) | set(db.keys()):
        s = seen.get(sid) or {}
        d = db.get(sid) or {}
        merged[sid] = {
            "story_id": sid,
            "event_name": s.get("event_name") or d.get("event_name") or "",
            "support_card_id": int(s.get("support_card_id") or 0),
            "num_choices": int(s.get("num_choices") or len(d.get("outcomes") or {}) or 0),
            "auto_pick": s.get("picked"),
            "auto_source": s.get("source") or ("db" if d else ""),
            "count": int(s.get("count") or 0),
        }
    # Numeric-only + stripped: a malformed ?cards= entry must degrade, not 500 (int() below).
    ids = ([s for s in (c.strip() for c in cards.split(",")) if s.isdigit()]
           if cards.strip() else [str(c) for c in _active_deck_card_ids()])
    if ids:
        try:
            from career_bot.core import master_data
            for ev in master_data.event_list_for_cards(base_dir, ids):
                sid = ev["story_id"]
                e = merged.get(sid)
                if e is None:
                    e = {"story_id": sid, "event_name": "", "support_card_id": 0,
                         "num_choices": 0, "auto_pick": None, "auto_source": "", "count": 0}
                    merged[sid] = e
                if not e.get("event_name"):
                    e["event_name"] = ev["event_name"]
                e["support_card_id"] = ev["support_card_id"]
        except Exception:
            pass
    events = []
    for sid, e in merged.items():
        ov = overrides.get(sid)
        e["override"] = (int(ov) if ov is not None else None)
        # Per-choice descriptions: the known good/bad label (curated DB) + what the bot has
        # actually OBSERVED each choice do (stat/energy/mood delta averaged over sightings).
        # Both are keyed by the game's SELECT_INDEX; positions map to select indexes via the
        # latest sighting's choice_selects (select sets vary/sparse across sightings). A
        # malformed source file degrades this block to choices=[] -- never a 500.
        try:
            d = db.get(sid)
            if not d and len(sid) >= 3:
                # Same suffix fallback EventManager.choose() uses for the curated DB.
                suffix = sid[-3:]
                for k, v in db.items():
                    if str(k).endswith(suffix):
                        d = v
                        break
            labels = (d or {}).get("outcomes") or {}
            observed = choice_obs.get(sid)
            observed = observed if isinstance(observed, dict) else {}
            raw_selects = (seen.get(sid) or {}).get("choice_selects") or []
            selects = []
            for x in raw_selects:
                try:
                    selects.append(int(x))
                except (TypeError, ValueError):
                    selects.append(0)
            n_choices = int(e.get("num_choices") or 0) or len(selects)
            n_choices = min(max(n_choices, 0), 8)
            e["num_choices"] = n_choices
            choices = []
            for i in range(n_choices):
                sel = selects[i] if i < len(selects) and selects[i] > 0 else (i + 1)
                slot = observed.get(str(sel))
                slot = slot if isinstance(slot, dict) else {}
                avg = slot.get("avg")
                avg = avg if isinstance(avg, dict) and avg else None
                try:
                    n_seen = int(slot.get("n") or 0)
                except (TypeError, ValueError):
                    n_seen = 0
                choices.append({
                    "index": i,
                    "select_index": sel,
                    "label": labels.get(str(sel)),
                    "observed": avg,
                    "seen": n_seen,
                })
            e["choices"] = choices
        except Exception:
            e["choices"] = []
        events.append(e)
    # Deck-card groups first (story_id-ordered), the card-0 "Other / scenario events" bucket last.
    events.sort(key=lambda x: (x.get("support_card_id") or 10**9, -x["count"], x["event_name"] or "~", x["story_id"]))
    # Card metadata so the UI can label each group (name + type) without its own deck picker.
    cards_meta = []
    for cid in ids:
        info = support_map.get(str(cid)) or {}
        cards_meta.append({
            "id": int(cid),
            "name": info.get("name") or f"Support {cid}",
            "type": display_support_type(info.get("type") or "?"),
            "rarity": info.get("rarity") or "?",
        })
    return {"success": True, "events": events, "cards": cards_meta,
            "deck_source": "request" if cards.strip() else ("active_career" if ids else "none")}

@app.post("/api/events/override")
async def set_event_override(req: EventOverrideRequest):
    _, ov_path, _ = _event_paths()
    overrides = _read_json_file(ov_path)
    sid = str(req.story_id)
    if int(req.choice) < 0:
        overrides.pop(sid, None)
    else:
        overrides[sid] = int(req.choice)
    ov_path.parent.mkdir(parents=True, exist_ok=True)
    ov_path.write_text(json.dumps(overrides, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"success": True, "story_id": sid, "override": overrides.get(sid)}

class DiscordWebhookRequest(BaseModel):
    webhook_url: Optional[str] = None
    notify_forecast: Optional[bool] = None

_TEST_FORECAST = {
    "active": True,
    "archetype": "Long / End Closer",
    "key_style": "End Closer",
    "apt_distances": [["long", 7], ["middle", 6], ["mile", 4]],
    "stat_targets": {"Speed": 1120, "Stamina": 1130, "Power": 990, "Guts": 750, "Wit": 650},
    "summary": "Direction: Long / End Closer (apt: long, middle).",
    "turn": 1,
}

@app.get("/api/settings/discord-webhook")
async def get_discord_webhook():
    from career_bot.core import notify
    url = notify.get_webhook_url(base_dir)
    return {"success": True, "configured": bool(url), "webhook_url": url,
            "notify_forecast": notify.get_notify_forecast(base_dir)}

@app.post("/api/settings/discord-webhook")
async def set_discord_webhook(req: DiscordWebhookRequest):
    from career_bot.core import notify
    # Patch-style: only update fields that were actually sent, so a partial POST (e.g. just the
    # forecast toggle) never wipes the saved webhook URL.
    if req.webhook_url is not None:
        notify.set_webhook_url(base_dir, req.webhook_url)
    if req.notify_forecast is not None:
        notify.set_notify_forecast(base_dir, req.notify_forecast)
    return {"success": True, "configured": bool(notify.get_webhook_url(base_dir)),
            "notify_forecast": notify.get_notify_forecast(base_dir)}

@app.post("/api/settings/discord-webhook/test")
async def test_discord_webhook():
    from career_bot.core import notify
    if not notify.get_webhook_url(base_dir):
        return {"success": False, "detail": "No webhook URL configured"}
    meta = {"account": os.environ.get("SWEEPY_ACCOUNT") or "", "uma_name": "Webhook Test", "preset": "test"}
    # Fire the start-of-career forecast panel too, so the test shows both new pieces.
    notify.send_forecast(base_dir, _TEST_FORECAST, meta)
    ok = notify.send_career_summary(base_dir, {
        "status": "finished",
        "scenario_id": LOCKED_SCENARIO_ID,   # preview shows this session's scenario in the title
        "account": os.environ.get("SWEEPY_ACCOUNT") or "",
        "uma_name": "Webhook Test",
        "preset": "test",
        "final_turn": 78,
        "duration": "11:00",
        "stats": {"speed": 1200, "stamina": 800, "power": 1000, "guts": 600, "wit": 900, "skill_point": 350, "fans": 123456},
        "skills_bought": 0,
        "races": 0,
        "fans": 123456,
        "factor_ids": [201, 3302, 1000702, 1001201, 1001902, 2002001, 2015302, 10060201],
        "loop_index": 2,
        "loop_target": 5,
        "forecast": _TEST_FORECAST,
        "rank": 14,
        "rank_score": 14250,
        "ranking": {"place": 2, "total": 7, "top": [
            {"pos": 1, "uma_name": "Gold Ship", "rank": 15, "rank_score": 15890, "current": False},
            {"pos": 2, "uma_name": "Webhook Test", "rank": 14, "rank_score": 14250, "current": True},
            {"pos": 3, "uma_name": "Haru Urara", "rank": 11, "rank_score": 9120, "current": False},
        ]},
        "fan_summary": {"day": "today", "total": 130000, "accounts": [
            {"account": "A", "fans": 80000}, {"account": "B", "fans": 50000}]},
    })
    return {"success": ok}


# ====================== FANS ======================
@app.get("/api/fans/daily")
async def get_daily_fans():
    # Per-account fans earned this game-day; resets with the in-game daily reset
    # (15:00 UTC), driven by the game's server clock when a session is live.
    from career_bot.core import notify
    server_ts = getattr(active_client, "last_servertime", 0) if active_client else 0
    return {"success": True, "reset": "in-game daily reset (15:00 UTC)",
            **notify.daily_fan_summary(base_dir, server_ts)}

@app.get("/api/master-data/status")
async def master_data_status():
    return master_data.status(base_dir)

def _refresh_reference_data():
    """Re-read data/*.json after a master-data regeneration so the running server serves fresh
    reference data without a restart: DataStore caches, and the module globals below were
    snapshotted at import. A career already mid-run keeps its own materialized indexes (a running
    career intentionally sees consistent reference data); the next career start() rebuilds off the
    reloaded shared store."""
    global chara_map, support_map, skill_data, factor_map, race_map
    reference_data.reload()
    career_runner.data_store.reload()
    chara_map = reference_data.chara_list()
    support_map = reference_data.support_list()
    skill_data = reference_data.skill_data()
    factor_map = reference_data.factor_map()
    race_map = reference_data.race_map()

@app.post("/api/master-data/path")
async def set_master_data_path(req: MasterDataPathRequest):
    status = master_data.set_master_mdb_path(base_dir, req.master_mdb_path)
    if status.get("exists"):
        result = master_data.generate(base_dir)
        if result.get("success"):
            _refresh_reference_data()
            status["generated"] = result.get("generated", [])
        else:
            status["generation_error"] = result.get("detail") or "master_data generation failed"
    return status

@app.post("/api/master-data/generate")
async def generate_master_data():
    result = master_data.generate(base_dir)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("detail") or "master_data generation failed")
    _refresh_reference_data()
    return result


# ====================== PRESETS ======================
@app.post("/api/presets/save_races")
async def save_races(req: SaveRacesRequest):
    preset = preset_store.read_one(req.preset_name)
    if not preset:
        return {"success": False, "detail": f"{req.preset_name} preset missing"}
    preset["extra_race_list"] = req.races
    preset_store.write(preset)
    return {"success": True}

@app.get("/api/career_goals/{card_id}")
def api_career_goals(card_id: int):
    """The trainee's career-goal RACES (program_id + turn), so the UI can show the auto-scheduled
    URA/Unity goal route in the race-schedule grid. Keyed by base chara (card_id // 100)."""
    try:
        cg = json.loads((base_dir / "data" / "career_goals.json").read_text(encoding="utf-8"))
    except Exception:
        return {"goals": []}
    entry = cg.get(str(int(card_id) // 100)) or {}
    goals = [{"program_id": g.get("program_id"), "turn": g.get("turn"),
              "race": g.get("race"), "require": g.get("require")}
             for g in (entry.get("goals") or [])
             if g.get("kind") == "race" and g.get("program_id")]
    return {"name": entry.get("name"), "goals": goals}

@app.get("/api/presets")
async def get_presets():
    return {"success": True, "presets": preset_store.read_all()}

@app.post("/api/presets")
async def save_preset(req: SavePresetRequest):
    return {"success": True, "preset": preset_store.write(req.preset)}

@app.post("/api/presets/delete")
async def delete_preset(req: DeletePresetByNameRequest):
    return {"success": preset_store.delete(req.name)}


# ====================== SKILLS ======================
@app.get("/api/skills")
async def get_skills():
    current_skill_data = {}
    path = base_dir / 'data' / 'skill_data.json'
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            current_skill_data = json.load(f)
    return {"success": True, "skills": current_skill_data}

def _finished_trained_chara_id(data):
    """trained_chara_id of a finished career, wherever it rides (single_mode_finish_common /
    trained_chara_info / chara_info -- verified in capture 20260706_053931). Passed to close_career so
    change_nickname (the slot-RELEASE step) can run even when the team finish 102s and returns nothing."""
    d = data if isinstance(data, dict) else {}
    for blk in (d.get("single_mode_finish_common"), d.get("trained_chara_info"), d.get("chara_info")):
        if isinstance(blk, dict) and blk.get("trained_chara_id"):
            return int(blk["trained_chara_id"])
    return None


def _resumable_career(data):
    """Return True only for an occupied, nonterminal career state.

    ``load/index`` and ``load_career`` use slightly different wrappers, so accept either the
    response itself or its ``data`` block.  A server-confirmed nonterminal slot is always resumed;
    it must never be closed merely because a fresh start returned 102.

    Terminal = server ``state`` 2 (goal failed, only factor_select/finish left) or 3 (finished), or
    a finish block. NOT playing_state 5 or turn >= 78 on their own: the api_library captures show
    state 0 / playing_state 5 on thousands of live mid-career responses (an event is pending), and
    state 0 at turn 78 is a live career (every scenario) whose final race has not run yet.
    """
    d = data if isinstance(data, dict) else {}
    if isinstance(d.get("data"), dict):
        d = d["data"]
    src = d.get("chara_info") or d.get("single_mode_chara_light") or {}
    if not (isinstance(src, dict) and src.get("card_id")):
        return False
    terminal = int(src.get("state") or 0) in (2, 3) or "single_mode_finish_common" in d
    return not terminal


def _load_index_has_career(data):
    """True when a load/index response shows an IN-PROGRESS career slot to resume. Post-1.32.8 the
    game surfaces the career directly as chara_info (with a real card_id); the old
    single_mode_chara_light home-summary is now absent (verified capture 20260706_082046, where
    load/index carried chara_info turn=1/state=0). A card_id means a slot is occupied -- but a
    JUST-FINISHED career LINGERS here right after the loop's previous career ended, so exclude
    terminal ones (see _resumable_career); resuming a finished phantom made the next loop career
    start with a terminal state and stop at turn 0."""
    return _resumable_career(data)


def _close_terminal_slot(career_result):
    """Close out a positively identified FINISHED career (card_id, but not resumable) so a fresh
    start can land. Shared by the pre-check and the 205/217 start recoveries, which used to leave
    such a slot occupied and end on 'Delete Career Data'. True when a close was attempted."""
    cdata = (career_result or {}).get("data") or {}
    chara = cdata.get("chara_info") or {}
    if not chara.get("card_id") or _resumable_career(cdata):
        return False
    print("start_career_from_request: stale/finished career slot -> closing it out to free the slot", flush=True)
    try:
        active_client.close_career(current_turn=int(chara.get("turn") or 78),
                                   trained_chara_id=_finished_trained_chara_id(cdata))
    except Exception as e:
        print(f"  close finished career: {e}", flush=True)
    return True


def start_career_from_request(req):
    global active_account, active_dashboard_data, active_start_state
    if not active_client:
        return {"success": False, "detail": "Not logged in"}

    raw_tp_mode = getattr(req, "tp_recovery_mode", "item")
    tp_mode = str(raw_tp_mode).strip().lower() if raw_tp_mode is not None else ""
    if tp_mode not in {"off", "item", "item_then_jewels", "jewels"}:
        return {"success": False,
                "detail": "Invalid tp_recovery_mode; expected one of: off, item, item_then_jewels, jewels"}

    # Hard scenario lock: any fresh career this process starts IS the locked scenario, whatever the
    # request carried. (A resume detected below reloads the live career, which self-corrects routing
    # from its own chara_info.scenario_id.)
    req.scenario_id = LOCKED_SCENARIO_ID

    # NOTE: this used to hard-fail with "Cannot start a new career while another is active" whenever
    # the in-memory career flag was set. That flag is only CLEARED on a clean finish, so any runner
    # crash mid-career (e.g. a 217 desync on race_out) left it stuck True and every retry bounced off
    # this line -- the loop burned its 5 attempts and gave up while a perfectly resumable career sat
    # at turn N. The resume pre-check further down already reasons about exactly this case from LIVE
    # state (resume a live career, close out a finished/terminal slot, else fresh-start),
    # so the flag must not short-circuit it. Left as a no-op on purpose: the live state decides.

    if not req.friend_viewer_id or not req.friend_card_id:
        return {"success": False, "detail": "Friend support card is required"}
    
    selection_error = validate_start_selection(req)
    if selection_error:
        return {"success": False, "detail": selection_error}

    # Never let a failed live refresh reuse TP/item values cached by a previous start attempt. A
    # stale low value can trigger an unnecessary spend; a stale high value can make start 102 and
    # send the recovery logic down the wrong path.
    active_start_state = {}
    data = {}
    try:
        # read_info/index is deprecated after 1.32.8 (returns 102); load/index carries the same
        # tp/coin/item + start-state data into update_start_state / refresh_cached_account_state.
        try:
            res = active_client.call("load/index", {"adid": ""})
        except Exception as exc:
            # 217 = session out of sync (e.g. after an HTTP 504 that still landed server-side); a hard
            # 217 carries no fresh sid to rotate to, so re-handshake once and retry. Live 2026-10-20:
            # the loop re-sent a 217'd load/index on every retry without resyncing and never recovered.
            if not is_api_error(exc, 217) or not hasattr(active_client, "resync_session"):
                raise
            print(f"start_career: 217 refreshing account state -> resync + retry ({exc})", flush=True)
            active_client.resync_session()
            res = active_client.call("load/index", {"adid": ""})
        data = res.get('data', {})
        active_client.refresh_cached_account_state(data)
        update_start_state(data)
        if active_account:
            active_account = get_account_status(data)
            if active_dashboard_data:
                active_dashboard_data["account"] = active_account
    except Exception as exc:
        return {"success": False,
                "detail": f"Could not refresh live account state before starting: {exc}"}

    # Cheap pre-check: if the just-refreshed live state already shows a career in progress,
    # resume it instead of attempting a start that is guaranteed to 205 (the start path's 205
    # recovery is the backstop when read_info doesn't carry the career flag).
    # The account-flag path relies on single_mode_chara_light, which post-1.32.8 load/index no
    # longer returns; _load_index_has_career reads the chara_info the new shape carries instead, so
    # a re-launch onto an in-progress career resumes rather than dead-ending on a rejected start.
    if (active_account and (active_account.get("career") or {}).get("active")) or _load_index_has_career(data):
        try:
            career_result = active_client.load_career()
            cdata = (career_result or {}).get("data") or {}
            if _resumable_career(cdata):
                print("start_career_from_request: in-progress career -> resuming it", flush=True)
                return {"success": True, "result": career_result, "resumed": True}
            if _close_terminal_slot(career_result):
                try:
                    d = active_client.call("load/index", {"adid": ""}).get("data", {})
                    active_client.refresh_cached_account_state(d)
                    update_start_state(d)
                    active_account = get_account_status(d)
                    if active_dashboard_data:
                        active_dashboard_data["account"] = active_account
                except Exception:
                    pass
        except Exception:
            pass

    if not active_start_state.get('tp_info'):
        return {"success": False, "detail": "Missing live TP state; login again before starting career"}
    if 'current_money' not in active_start_state:
        return {"success": False, "detail": "Missing live item state; login again before starting career"}

    tp_info = active_start_state['tp_info']
    current_tp = int(tp_info.get('current_tp') or 0)
    tp_item_id = int(getattr(req, "tp_recovery_item_id", 0) or 0) or TOUGHNESS_30_ITEM_ID
    if req.use_tp and current_tp < req.use_tp and tp_mode == "off":
        return {"success": False, "detail": f"TP {current_tp} is below the required {req.use_tp} and tp_recovery_mode is 'off' -- recover TP manually (with your items) then start, or switch the mode to 'jewels'/'item'."}
    if req.use_tp and current_tp < req.use_tp:
        needed = ((req.use_tp - current_tp) + 29) // 30
        use_items = tp_mode == "item"
        if tp_mode in ("item", "item_then_jewels"):
            potions = active_client.tp_potion_count(tp_item_id)
            use_items = potions >= needed
            if not use_items and tp_mode == "item":
                return {"success": False,
                        "detail": (f"Not enough TP recovery items: need {needed} of item {tp_item_id}, "
                                   f"have {potions}. Item mode will not spend jewels.")}
            if not use_items:
                print(f"[TP] {potions} TP bottle(s) left, {needed} needed -> refilling with carats", flush=True)
        try:
            # Resource recovery is intentionally attempted once, through ONE endpoint chosen up front.
            # Retrying an ambiguous mutation can double-spend, so a failed item call never falls
            # through to the jewels endpoint (carats are only chosen when the bottles already ran out).
            if use_items:
                active_client.use_recovery_item(item_num=needed, item_id=tp_item_id)
            else:  # explicit "jewels", or "item_then_jewels" with too few bottles
                active_client.recovery_tp(needed)
            tp_info = active_client.tp_info
            active_start_state['tp_info'] = tp_info
            current_tp = int(tp_info.get('current_tp') or 0)
        except Exception as e:
            return {"success": False,
                    "detail": f"TP recovery failed in {tp_mode} mode; no fallback was attempted ({e})"}

    if req.use_tp and current_tp < req.use_tp:
        return {"success": False, "detail": f"Not enough TP: {current_tp}/{req.use_tp}"}
    current_money = active_start_state['current_money']

    pre_decks = []
    offered_friends = {}
    pre_guests = []
    try:
        # Do NOT exclude the chosen friend here -- exclude_viewer_id_array means "don't offer
        # me these again" (the old code excluded the very friend we want to borrow from!).
        pre_res = active_client.pre_single_mode([])
        pdata = (pre_res or {}).get('data') or {}
        pre_decks = pdata.get('support_card_deck_array') or []
        # Fresh GUEST (rental) parent offers -- also re-caches each guest's affinity data, so the
        # succession-rank estimate below is exact even on the loop's 2nd+ career.
        pre_guests = normalize_guest_parents(pdata)
        # Initial offers are nested under friend_support_card_data on pre_single_mode/index;
        # reload responses carry them at top level (same as normalize_friend_cards).
        fsc = pdata.get('friend_support_card_data') or pdata
        for row in fsc.get('support_card_data_array') or []:
            offered_friends[int(row.get('viewer_id') or 0)] = row
        dna_sleep(0.5, 1.5)
    except Exception:
        pass

    # The friend card sent in start_chara must be in the server's currently-OFFERED set
    # (batches of 10; the live client rerolls with an accumulating exclude list until the
    # wanted friend appears -- capture 20260702_101347 shows a 70-friend exclude). Reroll
    # to find the chosen friend; fall back to any offered copy of the same support card.
    if req.friend_viewer_id and offered_friends and int(req.friend_viewer_id) not in offered_friends:
        seen = set(offered_friends)
        for _ in range(8):
            try:
                rl = active_client.friend_support_card_reload(sorted(seen))
                rows = (((rl or {}).get('data') or {}).get('support_card_data_array')) or []
            except Exception as reroll_exc:
                print(f"friend reroll failed (non-fatal): {reroll_exc}", flush=True)
                break
            if not rows:
                break
            for row in rows:
                vid = int(row.get('viewer_id') or 0)
                offered_friends[vid] = row
                seen.add(vid)
            if int(req.friend_viewer_id) in offered_friends:
                break
            dna_sleep(0.4, 0.9)
        if int(req.friend_viewer_id) not in offered_friends:
            fallback = next((vid for vid, row in offered_friends.items()
                             if int(row.get('support_card_id') or 0) == int(req.friend_card_id or 0)), 0)
            if fallback:
                print(f"friend {req.friend_viewer_id} not offered after rerolls -> borrowing the same "
                      f"card ({req.friend_card_id}) from offered friend {fallback}", flush=True)
                req.friend_viewer_id = fallback
            else:
                print(f"friend {req.friend_viewer_id} (card {req.friend_card_id}) not in the offered set "
                      f"after 8 rerolls -- start may 102; re-pick a friend in the UI if it does", flush=True)

    # GUEST parent: like the friend card above, the requested rental must be in the CURRENTLY-offered
    # set (it rotates per career -- a continuous run's 2nd+ start was blindly re-sending the first
    # run's guest, a deterministic 102 that killed the loop). Re-resolve against the fresh offer.
    copy_note = guest_copy_to_rental(req)
    if copy_note:
        print(f"[guest] {copy_note}", flush=True)
    if int(getattr(req, 'rental_trained_chara_id', 0) or 0):
        rv, rt, note = resolve_guest_parent(req.rental_viewer_id, req.rental_trained_chara_id,
                                            pre_guests, req.parent_id_1)
        if note:
            print(f"[guest] {note}", flush=True)
        req.rental_viewer_id, req.rental_trained_chara_id = rv, rt

    # AFTER guest resolution: the affinity pair (and its freshly re-cached data) is now the one
    # actually sent, so the estimate matches what the server validates.
    succession_rank_point = selected_succession_rank_point(req)

    def _sync_decks_after_start():
        # Live-client step right after a successful start (capture 20260702_005444 msg 0011):
        # support_card_deck/change_party saves the deck lineups, with the deck just used updated
        # to the cards actually started with. Best-effort -- must never fail the start.
        if not pre_decks:
            return
        try:
            decks = [dict(d) for d in pre_decks]
            for d in decks:
                if int(d.get('deck_id') or 0) == int(req.deck_id or 0):
                    d['support_card_id_array'] = list(req.support_card_ids or d.get('support_card_id_array') or [])
            active_client.change_party(decks)
        except Exception as sync_exc:
            print(f"change_party after start failed (non-fatal): {sync_exc}", flush=True)

    # A GUEST (rental) parent occupies the 2nd inheritance slot: it goes to the rental_* slot and the
    # OWNED parent_id_2 must be 0 (the game rejects a non-owned id in the owned slot).
    _rental_vid = int(getattr(req, 'rental_viewer_id', 0) or 0)
    _rental_tcid = int(getattr(req, 'rental_trained_chara_id', 0) or 0)
    _owned_p2 = 0 if (_rental_vid and _rental_tcid) else req.parent_id_2
    # An owned parent missing from the roster 102s every start; no succession value can fix that.
    roster_ids = {int(c.get('trained_chara_id') or 0) for c in (data.get('trained_chara') or [])}
    missing = [int(p) for p in (req.parent_id_1, _owned_p2) if int(p or 0) and roster_ids
               and int(p) not in roster_ids]
    if missing:
        return {"success": False, "fatal_start": True,
                "detail": (f"Parent {missing} is not in your roster any more (a borrowed guest's copy is "
                           f"removed when its career ends). Pick the parents again in SETUP.")}
    start_kwargs = dict(
        card_id=req.card_id,
        support_card_ids=req.support_card_ids,
        friend_viewer_id=req.friend_viewer_id,
        friend_card_id=req.friend_card_id,
        parent_id_1=req.parent_id_1,
        parent_id_2=_owned_p2,
        rental_viewer_id=_rental_vid,
        rental_trained_chara_id=_rental_tcid,
        scenario_id=req.scenario_id,
        deck_id=req.deck_id,
        use_tp=req.use_tp,
        tp_info=tp_info,
        current_money=current_money,
        succession_rank_point=succession_rank_point,
        difficulty_id=req.difficulty_id,
        difficulty=req.difficulty,
        is_boost=req.is_boost,
        boost_story_event_id=req.boost_story_event_id,
    )
    # Seed the client's scenario BEFORE the first career call so its namespace router
    # (single_mode_free/* -> single_mode_team/* for scenario 2) is correct even on a
    # resume/load that fires before any response sets current_scenario_id from chara_info.
    if req.scenario_id:
        active_client.current_scenario_id = int(req.scenario_id)
    try:
        result = active_client.start_career(**start_kwargs)
    except Exception as e:
        # 102 on start = a career already occupies the slot -- usually a FINISHED career the game
        # client hasn't reconciled (common after a resource-version patch desync). Try one proper
        # close-out (factor_select + finish) and retry; if it still won't release, stop with a clear,
        # actionable message instead of re-raising and letting the loop hammer start into the breaker.
        if is_api_error(e, 102):
            # 102 on start has TWO distinct causes; single_mode_free/load tells them apart:
            #   (a) load returns a career  -> the slot is occupied (stale FINISHED career) -> close-out.
            #   (b) load ALSO 102s ("no active career") -> the slot is FREE and a START PRECONDITION
            #       failed instead. The server validates the client-echoed tp_info/current_money (set
            #       at LOGIN time from active_start_state -- stale by start time if TP regenerated or
            #       money changed) plus the parent trainee ids and friend card. Refresh + retry once.
            cr = None
            cdata = {}
            chara = {}
            try:
                # probe: a 102 here just means "no active career" -- expected, must not feed the breaker
                with active_client.probing_102():
                    cr = active_client.load_career()
                cdata = (cr or {}).get("data") or {}
                chara = cdata.get("chara_info") or {}
            except Exception as load_exc:
                # 102 and 201 both mean "no career here" (load_career treats them alike, and re-raises
                # whichever the last namespace probe answered) -> the free-slot recovery below.
                if not is_api_error(load_exc, 102, 201):
                    print(f"start_career: 102 diag load failed ({load_exc})", flush=True)
                    return {"success": False, "fatal_start": True,
                            "detail": ("Start returned 102, but the active-career check could not be "
                                       f"completed safely ({load_exc}). No career was closed or deleted.")}

            if _resumable_career(cdata):
                print("start_career: 102 but a nonterminal career is active -> resuming it", flush=True)
                return {"success": True, "result": cr, "resumed": True}

            def _diag_102():
                # One-shot precondition dump so a persistent 102 names its cause instead of guessing.
                lines = []
                try:
                    li = active_client.call("load/index", {"adid": ""})
                    dh = li.get("data_headers") or {}
                    d = li.get("data") or {}
                    lines.append(f"identity sent={active_client.viewer_id} server_ack={dh.get('viewer_id')}")
                    tp = d.get("tp_info") or {}
                    lines.append(f"tp server={tp.get('current_tp')}/{tp.get('max_tp')} use_tp={req.use_tp}")
                    items = d.get("item_list") or d.get("user_item_array") or []
                    lines.append(f"money server={get_item_count(items, 59)} sent={start_kwargs.get('current_money')}")
                    lines.append(f"succession_pts server_item75={get_item_count(items, 75)} "
                                 f"sent={start_kwargs.get('succession_rank_point')}")
                    lines.append(f"start_chara sent: card={req.card_id} scenario={req.scenario_id} "
                                 f"deck={req.deck_id} supports={req.support_card_ids}")
                    roster = d.get("trained_chara") or []
                    ids = {int(c.get("trained_chara_id") or 0) for c in roster}
                    lines.append(f"roster {len(roster)}/240")
                    lines.append(f"parent1={req.parent_id_1} in_roster={int(req.parent_id_1 or 0) in ids} "
                                 f"parent2={req.parent_id_2} in_roster={int(req.parent_id_2 or 0) in ids}")
                    lines.append(f"friend viewer={req.friend_viewer_id} card={req.friend_card_id}")
                except Exception as dexc:
                    lines.append(f"diag fetch failed: {dexc}")
                msg = " | ".join(lines)
                print(f"[102-diag] {msg}", flush=True)
                return msg

            if chara.get("card_id"):
                # The loaded career was positively identified as terminal by _resumable_career.
                # Never close a live turn merely because the fresh start found the slot occupied.
                print(f"start_career: 102 (terminal slot occupied) -> close-out + retry once ({e})", flush=True)
                try:
                    active_client.close_career(current_turn=int(chara.get("turn") or 78),
                                               trained_chara_id=_finished_trained_chara_id(cdata))
                    result = active_client.start_career(**start_kwargs)
                    _sync_decks_after_start()
                    # The server just ACCEPTED a career start -- it isn't throttling; any breaker
                    # entries were the close-out's expected/tolerated 102s. Clear them so the new
                    # career's runner doesn't stop on a phantom trip (it re-trips fast if real).
                    active_client.reset_circuit()
                    return {"success": True, "result": result}
                except Exception as close_exc:
                    return {"success": False, "fatal_start": True,
                            "detail": (f"Career slot stuck: start 102s and a graceful close-out didn't "
                                       f"release it ({close_exc}). Likely an orphaned / pre-maintenance "
                                       f"career (game error 2512). FIX: with THIS account active in-game, "
                                       f"use 'Delete Career Data', then re-run. [{_diag_102()}]")}

            # Post-finish reconciliation lag: right after the PREVIOUS career's finish + change_nickname,
            # the server can briefly still 102 the next start even though the slot is already free
            # (load_career above returned "no active career") -- the common cause of a 2nd-career start
            # 102 in a loop. Before assuming a wrong succession point and force-deleting + sweeping ~130
            # values (which just hammers a busy server -> the 208 storm), WAIT a moment and retry the
            # ORIGINAL start ONCE. If the slot only needed to settle, this succeeds with zero sweep.
            server_sleep(2.5, 4.0)
            try:
                with active_client.probing_102():   # a still-102 here is expected -> don't feed the breaker
                    result = active_client.start_career(**start_kwargs)
                _sync_decks_after_start()
                active_client.reset_circuit()
                print("start_career: 102 cleared after a brief wait (slot reconciled) -> no sweep needed", flush=True)
                return {"success": True, "result": result}
            except Exception as wait_exc:
                print(f"start_career: post-finish wait-retry still 102/failed ({str(wait_exc)[:80]}) "
                      f"-> succession sweep", flush=True)

            # No active career (load also 102s), so current_succession_rank_point is wrong: the game
            # computes it from the parents and grandparents, and our affinity estimate misses some
            # families. The server rejects a wrong value with a harmless 102 (no career starts), so SWEEP
            # values around the estimate until one is accepted, then remember it per parent pair.
            # (This used to force-delete "any stuck slot" first -- finish{is_force_delete, target = the
            # newest trained uma} -- but all 10 captured attempts were refused with 102: it never freed
            # anything, and a delete aimed at a real trained uma has no place on a clean slot.)
            print("start_career: 102 + no active career -> calibrate succession-rank-point", flush=True)
            try:
                d = (active_client.call("load/index", {"adid": ""}) or {}).get("data") or {}
                update_start_state(d)
                active_client.refresh_cached_account_state(d)
            except Exception:
                pass
            fresh_kwargs = dict(start_kwargs)
            if active_start_state.get("tp_info"):
                fresh_kwargs["tp_info"] = active_start_state["tp_info"]
            if "current_money" in active_start_state:
                fresh_kwargs["current_money"] = active_start_state["current_money"]

            pair = _succession_cache_pair(req)   # SAME key the reader uses (rental id, not the owned 0)
            est = int(fresh_kwargs.get("succession_rank_point") or 0)
            held = int(active_start_state.get("succession_rank_point") or 0)  # item 75: pts the account holds
            tried = set()
            queue = list(_succession_sweep_candidates(est, held))
            busy = {}
            while queue:
                val = queue.pop(0)
                if val in tried:
                    continue
                if _exiting:
                    print("start_career: MQA is shutting down -> succession sweep stopped", flush=True)
                    break
                tried.add(val)
                try:
                    k = dict(fresh_kwargs)
                    k["succession_rank_point"] = val
                    # probe: each wrong value 102s BY DESIGN -- the sweep's own calibration probes
                    # must never feed the breaker (they tripped it and killed the freshly-started
                    # career in live log 20260706_171909). 205/208 still count + back off normally.
                    with active_client.probing_102():
                        # The outer succession sweep owns the retry cadence. Do not let each candidate
                        # start independently replay 208 several times, or one sweep becomes a request
                        # storm while the server is already telling us to slow down.
                        active_client._sweep_start_no_retry_208 = True
                        try:
                            result = active_client.start_career(**k)
                        finally:
                            active_client._sweep_start_no_retry_208 = False
                    _remember_succession_point(pair, val)
                    if val != est:
                        print(f"start_career: OK with current_succession_rank_point={val} "
                              f"(estimate {est}, held {held}) -> cached for parents {pair}", flush=True)
                    _sync_decks_after_start()
                    # Start ACCEPTED -> server is fine; clear any breaker entries accumulated by the
                    # recovery path so the new career's runner doesn't stop on a phantom trip.
                    active_client.reset_circuit()
                    return {"success": True, "result": result}
                except Exception as se:
                    if is_api_error(se, 205, 208):
                        # Server BUSY (208) / stale (205) is NOT a wrong-value signal -- the value went
                        # untested. Aborting here is what CREATES the storm: the run-loop just re-enters
                        # and re-hammers the whole sweep. Back off harder and move to the next candidate
                        # instead, and re-queue the value at the end: it was never tested (live
                        # 2026-10-29: five values next to the estimate only ever got 208, never a verdict).
                        tried.discard(val)
                        busy[val] = busy.get(val, 0) + 1
                        if busy[val] < 3:
                            queue.append(val)
                        server_sleep(1.5, 3.0)
                        continue
                    if not is_api_error(se, 102):
                        print(f"start_career: succession sweep stopped on non-102 ({se})", flush=True)
                        break
                    server_sleep(0.25, 0.45)  # gentle pacing so the sweep never floods the server
            return {"success": False, "fatal_start": True,
                    "detail": (f"start still 102s after a succession sweep (estimate {est}, held {held}, "
                               f"tried {len(tried)} values). Send the new [102-diag] so the exact value "
                               f"can be pinned. [{_diag_102()}]")}
        # 217 on start = session inconsistency (SID desync). Unlike a 205, a hard 217 returns an
        # EMPTY sid, so the client can't rotate its way out -- it needs a fresh handshake. Reseed the
        # session (resync_session), then reconcile: the start may have actually LANDED server-side
        # before the 217, so check for an active career and resume it; else retry start once.
        if is_api_error(e, 217):
            print(f"start_career: 217 (session desync) -> resync + reconcile ({e})", flush=True)
            try:
                active_client.resync_session()
            except Exception as resync_exc:
                print(f"start_career: 217 resync note: {resync_exc}", flush=True)
            try:
                cr = active_client.load_career()
                if _resumable_career(cr):
                    print("start_career: career already active after 217 resync -> resuming it", flush=True)
                    return {"success": True, "result": cr, "resumed": True}
                _close_terminal_slot(cr)
            except Exception:
                pass
            try:
                result = active_client.start_career(**start_kwargs)
                _sync_decks_after_start()
                return {"success": True, "result": result}
            except Exception as retry_exc:
                return {"success": False, "retryable_start": True,
                        "detail": f"Session desync (API 217) on start; session re-synced but the retry "
                                  f"failed once ({retry_exc}). It should clear on the next attempt."}
        # A persistent 205 on single_mode_free/start means the session is stale (or a
        # previous career didn't fully clean up). Retrying the same start just 205s
        # forever -- the loop-killer. Recovery, in order:
        #   (a) if a career IS active server-side, resume THAT;
        #   (b) else re-establish a FRESH session with a full login() and retry start once
        #       -- hard_reset() assumes there's a career to recover and raises on 102, so it
        #       cannot fix a start-fresh 205; login() rebuilds the session from existing auth;
        #   (c) if it STILL 205s, stop cleanly with a re-login message instead of looping.
        if not is_api_error(e, 205):
            raise
        print(f"start_career: persistent 205 -> recovering session ({e})", flush=True)
        try:
            career_result = active_client.load_career()
            if _resumable_career(career_result):
                print("start_career: a career is already active -> resuming it instead", flush=True)
                return {"success": True, "result": career_result, "resumed": True}
            _close_terminal_slot(career_result)
        except Exception:
            pass
        try:
            active_client.login()
            print("start_career: re-logged in (fresh session) -> retrying start once", flush=True)
        except Exception as login_exc:
            print(f"start_career: re-login failed ({login_exc})", flush=True)
            return {"success": False, "fatal_start": True,
                    "detail": "Session went stale and the automatic re-login failed -- log in again from the UI (or re-capture auth), then start."}
        try:
            result = active_client.start_career(**start_kwargs)
        except Exception as retry_exc:
            if is_api_error(retry_exc, 205):
                return {"success": False, "fatal_start": True,
                        "detail": "Still error 205 (stale session) after a fresh re-login -- your auth is likely stale, or the game's resource version updated. Log in again / re-capture auth (update the game first if it just patched), then start."}
            raise
    _sync_decks_after_start()
    return {"success": True, "result": result}

def apply_career_result(result):
    global active_account, active_dashboard_data
    result_data = result.get('data', {})
    update_start_state(result_data)
    account = get_account_status(result_data, result)
    chara_info = result_data.get('chara_info') or {}
    if chara_info:
        account["career"] = account.get("career") or {}
        card_id = str(chara_info.get('card_id', account["career"].get("card_id", '')))
        account["career"].update({
            "active": True,
            "card_id": card_id,
            "name": chara_map.get(card_id, f"Unknown ({card_id})"),
            "turn": chara_info.get('turn', 0),
            "scenario_id": chara_info.get('scenario_id', 0),
            "fans": chara_info.get('fans', 0),
            "vital": chara_info.get('vital', 0),
            "max_vital": chara_info.get('max_vital', 0)
        })
    active_account = account
    if active_dashboard_data:
        active_dashboard_data["account"] = account
    return account, chara_info


# ====================== AUTH / SESSION ======================
# Saved Steam login: password lives in the OS vault (keyring), only the username on disk.
# GET never returns the password -- just whether one is stored -- so it can't leak to the browser.
class SteamCredRequest(BaseModel):
    username: str = ""
    password: str = ""

@app.get("/api/steam/credential")
def api_get_steam_credential():
    from uma_api import steam_credential
    cred = steam_credential.load()
    if not cred:
        return {"saved": False}
    return {"saved": True, "username": cred["username"], "has_password": bool(cred.get("password"))}

@app.post("/api/steam/credential")
def api_save_steam_credential(req: SteamCredRequest):
    from uma_api import steam_credential
    try:
        steam_credential.save(req.username, req.password)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not save credential: {e}")
    return {"success": True, "username": req.username.strip()}

@app.delete("/api/steam/credential")
def api_delete_steam_credential():
    from uma_api import steam_credential
    steam_credential.clear()
    return {"success": True}


@app.post("/api/login")
async def login(req: LoginRequest):
    from uma_api.client import UmaClient, get_ticket
    from career_bot.core.delay import GateKeeper
    global active_client, active_account, active_dashboard_data, active_start_state, active_parent_cards, active_parent_rank_points, pending_game_auth_config, raw_load_index_response, active_selection
    try:
        chara = None
        # Auth lives only in memory for this process: the freshly captured config.
        # (Saving auth to disk was removed -- the persisted file could never hold the
        # short-lived Steam ticket anyway, so "saved" logins kept dead-ending at
        # "No Steam ticket available". Capture fresh, log in, done.)
        # Pending is consumed only on SUCCESS, so a transient login failure can be
        # retried without forcing another capture.
        cfg = dict(pending_game_auth_config or (load_auth_config() if carrying_identity() else {}))

        # Saved-credential fallback: a username with no password means "use the saved login" --
        # pull the password from the OS vault so it never has to be re-typed (a fresh ticket is
        # minted from it below). The captured-ticket path still wins when a capture is available.
        if not req.password:
            from uma_api import steam_credential
            saved = steam_credential.load()
            if saved and saved.get("password") and (not req.username or req.username == saved["username"]):
                req.username = saved["username"]
                req.password = saved["password"]

        active_client = None
        active_account = None
        active_dashboard_data = None
        active_start_state = {}
        active_parent_cards = {}
        active_parent_rank_points = {}
        raw_load_index_response = None
        active_selection = {
            "deck": None,
            "friend": None,
            "trainee": None,
            "veterans": []
        }

        has_form_creds = bool(req.username and req.password)
        has_captured_ticket = bool(cfg.get('steam_id') and cfg.get('steam_session_ticket'))
        used_captured = False
        if req.steam_id and req.steam_session_ticket:
            sid = str(req.steam_id)
            tkt = str(req.steam_session_ticket)
            print('Using provided Steam ticket', flush=True)
        elif has_captured_ticket:
            # PREFER the Steam ticket captured from the game during --reauth: it skips the
            # manual Steam login AND always matches the just-captured in-game account, so
            # there is no viewer_id mismatch / error 1055 -- exactly what a 1-Steam /
            # many-Uma-accounts setup needs. If this ticket is stale/rejected we auto-fall
            # back to manual login below (when credentials were entered), so it can never
            # make login worse than before.
            sid = str(cfg.get('steam_id'))
            tkt = str(cfg.get('steam_session_ticket'))
            used_captured = True
            print('Using captured in-game Steam ticket (no manual Steam login needed)', flush=True)
        elif has_form_creds:
            sid, tkt = get_ticket(req.username, req.password, req.code)
        else:
            raise Exception('No Steam ticket available -- re-capture with "auth" first, or enter Steam credentials')

        if not cfg.get('steam_id') or not cfg.get('steam_session_ticket'):
            cfg.update({
                'steam_id': sid,
                'steam_session_ticket': tkt,
            })
        cfg['steam_password_seed'] = req.password   # in memory, for a 394 ticket re-mint only (not device_id)
        # Stash the Steam username too (when a form login was used) so the client can
        # re-mint a fresh ticket on a mid-run 394 (stale ticket). Harmless when empty.
        if req.username:
            cfg['steam_username'] = req.username
        if not has_fresh_auth_config(cfg):
            raise Exception('Fresh in-game auth capture required; switch to the target in-game account, restart capture, then login again')

        # The interactive login + first dashboard load run on the RAW client (no
        # GateKeeper pacing). The per-endpoint "human think-time" delays exist to
        # humanise the autonomous CAREER GRIND; piling ~14s (start_session + load/index
        # + read_info + load_career) onto a one-time login the user is actively watching
        # buys no real anti-detection -- a real game client bursts these on startup, it
        # does not pause ~5s before load/index -- and just makes the UI feel hung. The
        # SAME client is wrapped in a GateKeeper AFTER login below, so the career runner
        # still gets full human pacing.
        c = UmaClient(cfg, trace_enabled=False)
        # Seed the career-namespace router with this session's LOCKED scenario so the first
        # load_career probe hits the right prefix immediately (a URA login used to 205-storm through
        # free -> team before ever trying single_mode/*). Just a HINT: a successful load pins the
        # live career's REAL scenario from chara_info, which overrides this on any mismatch.
        c.current_scenario_id = LOCKED_SCENARIO_ID
        try:
            res = c.login()
            if not res:
                raise Exception("empty login response")
        except Exception as login_err:
            # Auto-fallback: if the captured in-game ticket was used and it failed (e.g.
            # expired / already consumed by the game), retry once with a fresh manual
            # Steam login -- but only when credentials were actually provided.
            if used_captured and has_form_creds:
                print(f'Captured ticket login failed ({login_err}); falling back to manual Steam login', flush=True)
                sid, tkt = get_ticket(req.username, req.password, req.code)
                cfg['steam_id'] = sid
                cfg['steam_session_ticket'] = tkt
                c = UmaClient(cfg, trace_enabled=False)
                c.current_scenario_id = LOCKED_SCENARIO_ID   # same namespace hint as the first client
                res = c.login()
            else:
                raise
        if not res:
            raise HTTPException(status_code=401, detail="Game login failed")

        d = res.get('data', {})
        try:
            # Auto-detect the in-game trainer name so Discord notifications can use
            # it by default (no manual entry needed). Stored in SWEEPY_ACCOUNT,
            # which the webhook uses unless a manual override is set in the UI.
            ingame_name = str((d.get('user_info') or {}).get('name') or '').strip()
            if ingame_name:
                os.environ['SWEEPY_ACCOUNT'] = ingame_name
        except Exception:
            pass
        career_data = None
        if d.get('single_mode_chara_light') or d.get('single_mode_chara'):
            try:
                career_res = c.load_career()   # raw client -> no pacing -> fast
                career_data = career_res.get('data')
            except Exception:
                pass

        # Login + first dashboard load are done. NOW wrap the client in a GateKeeper
        # so the autonomous career runner keeps its human-like per-action pacing.
        # (active_client must be set before get_account_status, which reads
        # active_client.tp_info / coin_info / item_map -- GateKeeper proxies these to c.)
        gated_client = GateKeeper(c)
        active_client = gated_client

        account = get_account_status(d, career_data)
        active_account = account
        active_start_state = {}
        active_parent_cards = {}
        active_parent_rank_points = {}
        update_start_state(d)
        
        umas = []
        card_list = d.get('card_list', [])
        for card in card_list:
            cid = str(card.get('card_id', card.get('id', '')))
            umas.append({
                'id': cid, 
                'name': chara_map.get(cid, f"Unknown ({cid})")
            })
            
        supports = []
        support_card_list = d.get('support_card_list', [])
        for s in support_card_list:
            sid = str(s.get('support_card_id', s.get('id', '')))
            info = support_map.get(sid)
            if info:
                supports.append({
                    'id': sid, 
                    'name': info['name'], 
                    'type': display_support_type(info['type']),
                    'rarity': info['rarity']
                })
            else:
                supports.append({
                    'id': sid, 
                    'name': f"Unknown ({sid})", 
                    'type': 'Unknown', 
                    'rarity': '?'
                })
                
        decks = []
        deck_array = d.get('support_card_deck_array', [])
        for deck in deck_array:
            cards = []
            for cid in deck.get('support_card_id_array', []):
                sid = str(cid)
                info = support_map.get(sid)
                if info:
                    cards.append({
                        'id': sid,
                        'name': info['name'],
                        'rarity': info['rarity'],
                        'type': display_support_type(info['type'])
                    })
                else:
                    cards.append({'id': sid, 'name': f'Unknown ({sid})', 'rarity': '?', 'type': '?'})
            
            decks.append({
                'id': deck.get('deck_id'),
                'name': deck.get('name', f'Deck {deck.get("deck_id")}'),
                'cards': cards
            })

        parents = build_parents_from_trained_chara(d.get('trained_chara', []))
        active_dashboard_data = {
            "success": True,
            "account": account,
            "umas": umas,
            "supports": supports,
            "decks": decks,
            "parents": parents
        }
        # Opt-in (UMA_AUTH_CONFIG / UMA_CARRY_IDENTITY): keep the identity that just worked, for a
        # headless host to carry. Env unset: nothing is written, as before.
        try:
            saved_to = c.export_identity()
            if saved_to:
                print(f"[identity] saved to {saved_to}", flush=True)
        except Exception as e:
            print(f"[identity] NOT saved (non-fatal): {e}", flush=True)
        # Login succeeded: the captured auth has served its purpose -- consume it now
        # (failures above keep it, so a retry doesn't need a fresh capture).
        pending_game_auth_config = {}
        return active_dashboard_data
    except Exception as e:
        msg = str(e)
        if "STEAM_GUARD_REQUIRED" in msg:
             pending_game_auth_config = cfg
             return {"success": False, "needs_2fa": True}
        return {"success": False, "detail": str(e)}

@app.get("/api/session")
async def session_status():
    global active_client, active_dashboard_data, active_account, active_selection
    if not active_client or not active_dashboard_data:
        return {"success": False}
    
    data = dict(active_dashboard_data)
    if active_account:
        data["account"] = active_account
    data["selection"] = active_selection
    data["success"] = True
    return data

@app.post("/api/session/refresh")
async def refresh_session():
    # Re-pull live state from the game so changes made directly in the game
    # (e.g. a career started in-game) show up without a full logout/login.
    global active_account, active_dashboard_data
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if career_runner.snapshot().get("running") or (backend_loop_thread and backend_loop_thread.is_alive()):
        return {"success": False, "detail": "Career runner active; stop it before refreshing"}
    try:
        # Re-establish the session (start_session + load/index + read_info, with
        # built-in retries) rather than a bare load/index, which can 201 on a
        # stale session. This is an INTERACTIVE button press -- run it UNPACED so the
        # user isn't made to wait the ~14s of GateKeeper humanise delays meant for the
        # autonomous grind. Safe because the guard above guarantees no runner is using
        # the client right now. unpaced() restores pacing on exit (even on error).
        unpaced = active_client.unpaced() if hasattr(active_client, "unpaced") else contextlib.nullcontext()
        with unpaced:
            res = active_client.login()
            d = (res or {}).get('data', {})
            active_client.refresh_cached_account_state(d)
            update_start_state(d)
            career_data = None
            if d.get('single_mode_chara_light') or d.get('single_mode_chara'):
                try:
                    career_res = active_client.load_career()
                    career_data = career_res.get('data')
                except Exception:
                    pass
            account = get_account_status(d, career_data)
            active_account = account
            if active_dashboard_data:
                active_dashboard_data["account"] = account
        return {"success": True, "account": account}
    except Exception as e:
        return {"success": False, "detail": str(e)}

class UISelectionRequest(BaseModel):
    selection: dict

@app.post("/api/selection")
async def update_selection(req: UISelectionRequest):
    global active_selection
    active_selection = req.selection
    return {"success": True}

@app.post("/api/logout")
async def logout():
    global active_client, active_account, active_dashboard_data, active_start_state, active_parent_cards, active_parent_rank_points, raw_load_index_response, pending_game_auth_config, active_selection
    active_client = None
    active_account = None
    active_dashboard_data = None
    active_start_state = {}
    active_parent_cards = {}
    active_parent_rank_points = {}
    raw_load_index_response = None
    pending_game_auth_config = {}
    active_selection = {
        "deck": None,
        "friend": None,
        "trainee": None,
        "veterans": []
    }
    return {"success": True}


# ====================== CAREER CONTROL ======================
@app.post("/api/career/start")
async def start_career(req: StartCareerRequest):
    try:
        # Off the event loop: start_career_from_request does blocking network I/O + the 102/succession
        # sweep + 208 backoffs (up to ~minute on a cold estimate). Running it inline froze the whole
        # asyncio loop -> the Web UI went dead and the request appeared to fail even though the career
        # started underneath (seen live: succession sweep succeeds, then a lifespan CancelledError).
        started = await asyncio.to_thread(start_career_from_request, req)
        if not started.get("success"):
            return started
        account, chara_info = apply_career_result(started["result"])
        return {"success": True, "account": account, "chara_info": chara_info}
    except Exception as e:
        return {"success": False, "detail": str(e)}

backend_loop_thread = None
backend_loop_stop = False
_last_session_recover = 0.0


def _recover_stale_session():
    """Error 394 (stale Steam ticket) mid-loop on Windows: relaunch the game, re-capture (auto-tap),
    log in again (captured ticket, else the saved Steam login) and keep the start selection, so the
    loop carries on unattended. At most once per 10 minutes, so a 394 that keeps coming back still
    ends the loop. Never called for 391: that one means a person or another client took the session."""
    global _last_session_recover, active_selection
    if os.name != 'nt' or carrying_identity() or time.time() - _last_session_recover < 600:
        return False
    _last_session_recover = time.time()
    print("[LOOP] error 394 (stale session) -- re-capturing auth and logging in again", flush=True)
    saved = dict(active_selection or {})
    if not refresh_auth_before_serving():
        print("[LOOP] re-capture failed -- log in again by hand", flush=True)
        return False
    try:
        res = asyncio.run(login(LoginRequest()))
    except Exception as e:
        res = {"success": False, "detail": str(e)}
    ok = active_client is not None and not (isinstance(res, dict) and res.get("success") is False)
    if ok:
        active_selection = saved
    print(f"[LOOP] re-login {'ok -- carrying on' if ok else 'failed: ' + str((res or {}).get('detail'))}", flush=True)
    return ok

def manage_career_loop(req, preset, initial_result):
    global backend_loop_stop, active_account, active_client
    max_steps = max(1, min(int(req.max_steps or 2500), 3000))
    target = max(0, int(getattr(req, "run_count", 1) or 0))  # 0 = run forever
    consecutive_fails = 0
    best_turn = 0   # furthest turn any exit of the current career reached
    current_result = initial_result
    runs_done = 0

    print(f"[LOOP] starting career loop: {'INFINITE (until Stop)' if not target else f'{target} career(s)'}", flush=True)

    while not backend_loop_stop:
        career_runner.set_loop_info(runs_done + 1, target)
        career_runner.start(active_client, preset, current_result, max_steps, burn_clocks=req.burn_clocks, dev_mode=True)

        while career_runner.snapshot().get("running"):
            if backend_loop_stop:
                career_runner.stop()
                return
            # server_sleep: a real 1s poll even when humanization delays are disabled
            # (dna_sleep would return instantly and busy-spin this loop).
            server_sleep(0.9, 1.1)

        status = career_runner.snapshot()
        if status.get("circuit_tripped"):
            print("[LOOP] AUTO-BACKOFF: circuit breaker tripped (too many server "
                  "errors) — stopping the whole loop. Wait before running again.", flush=True)
            backend_loop_stop = True
            break
        # The fail limit below is for a career STUCK on one spot. An exit that got further than
        # every earlier one made progress, so a long loop survives transient crashes as before.
        exit_turn = int(status.get("turn") or 0)
        if exit_turn > best_turn:
            consecutive_fails, best_turn = 0, exit_turn
        if is_api_error(status.get("last_error") or "", 394) and _recover_stale_session():
            pass   # logged in again; the start below resumes this career
        elif status.get("last_error"):
            consecutive_fails += 1
            if consecutive_fails >= 3:
                break
        elif not status.get("finished") and int(status.get("turn") or 0) <= 0:
            # Ended instantly: no error, no finish, zero turns played (an unreadable/empty
            # start state -- the "error / ended@turn0" stub). A broken handoff, NOT a career:
            # never consume a run slot for it, or N runs silently yields ~N/2 real careers.
            consecutive_fails += 1
            print(f"[LOOP] career ended at turn 0 without playing -- NOT counted "
                  f"({consecutive_fails}/3 broken handoffs)", flush=True)
            if consecutive_fails >= 3:
                break
        elif not status.get("finished") and not backend_loop_stop:
            # Ended mid-career with no error and no finish (an idle / still-blocked / unknown-action
            # exit). Not a finished career: the next start just resumes it and it tends to stop the
            # same way, so counting it as a run made the loop cycle on one stuck career forever.
            consecutive_fails += 1
            print(f"[LOOP] career stopped at turn {status.get('turn')} without finishing "
                  f"({status.get('last_action') or '?'}) -- NOT counted ({consecutive_fails}/3)", flush=True)
            if consecutive_fails >= 3:
                break
        else:
            consecutive_fails = best_turn = 0
            runs_done += 1
            print(f"[LOOP] career {runs_done}/{target if target else '∞'} finished", flush=True)
            if active_account and "career" in active_account and active_account["career"]:
                active_account["career"]["active"] = False

        if target and runs_done >= target:
            print(f"[LOOP] target reached ({runs_done}/{target}) — stopping loop", flush=True)
            break

        # Real pause between careers, immune to the delay kill-switch.
        for _ in range(6):
            if backend_loop_stop:
                return
            server_sleep(0.9, 1.1)

        # Start retries get their own count: a successful start must NOT reset consecutive_fails, or
        # a career that keeps ending unfinished (error / idle / blocked) on every resume never
        # reaches the limit above and the loop cycles on it forever.
        start_fails = 0
        started_ok = False
        while not started_ok and not backend_loop_stop:
            try:
                started = start_career_from_request(req)
                if not started.get("success"):
                    detail = str(started.get("detail") or "")
                    # detail can embed a raw UmaClient error (servertime / viewer_id digits), so
                    # match the 'API error 102 on' prefix, not a bare "102".
                    if started.get("fatal_start") or is_api_error(detail, 102) or "stuck" in detail.lower():
                        print(f"[LOOP] STOPPING -- career slot stuck: {detail}", flush=True)
                        return
                    if is_api_error(detail, 394) and _recover_stale_session():
                        continue
                    start_fails += 1
                    if start_fails >= 5:
                        break
                    # Escalating cool-down between failed starts (15s, 30s, 45s, 60s):
                    # a 205/208 wall here means the server is throttling -- hammering
                    # it on a fixed short timer is what got accounts flagged.
                    wait_s = min(60, 15 * start_fails)
                    print(f"[LOOP] career start failed ({started.get('detail') or '?'}) -- "
                          f"cooling down {wait_s}s before retry {start_fails}/5", flush=True)
                    for _ in range(wait_s):
                        if backend_loop_stop:
                            return
                        server_sleep(0.9, 1.1)
                    continue
                current_result = started["result"]
                account, chara_info = apply_career_result(current_result)
                active_account = account
                started_ok = True
            except Exception as e:
                if is_api_error(e, 102):
                    print("[LOOP] STOPPING -- start keeps returning 102 (career slot stuck). Your account "
                          "is fine; a stuck/pre-maintenance career is occupying its slot. FIX: with THIS "
                          "account active in-game, use 'Delete Career Data' to clear it, then re-run. "
                          "(The viewer_id in the 102 error is a server placeholder, not your account.)", flush=True)
                    return
                start_fails += 1
                if start_fails >= 5:
                    break
                for _ in range(15):
                    if backend_loop_stop:
                        return
                    server_sleep(0.9, 1.1)   # kill-switch-immune: NO CD must not zero this cooldown

        if not started_ok:
            break

# One career start at a time: run_career awaits worker threads before the runner/loop flags its guard
# checks are set, so a second Run (another tab, the Discord remote) could slip past that guard and run
# two starts on one client -- interleaved requests and a double TP-recovery spend.
_run_career_lock = asyncio.Lock()


@app.post("/api/career/run")
async def run_career_endpoint(req: RunCareerRequest):
    if _run_career_lock.locked():
        return {"success": False, "detail": "A career start is already in progress"}
    async with _run_career_lock:
        return await run_career(req)


async def run_career(req: RunCareerRequest):
    # backend_loop_stop MUST be global: it's reset to False at loop start below. Without it here that
    # reset makes a dead local, leaving the module flag True after any Stop -> the next looped run's
    # `while not backend_loop_stop` is instantly false and the loop silently does nothing.
    global active_account, backend_loop_thread, backend_loop_stop
    if career_runner.snapshot().get("running") or (backend_loop_thread and backend_loop_thread.is_alive()):
        return {"success": False, "detail": "Career runner loop already active"}
    preset_name = req.preset_name or "xguri parent"
    preset = preset_store.read_one(preset_name)
    if not preset:
        return {"success": False, "detail": f"{preset_name} preset missing"}
    
    try:
        account = active_account or {}
        career = account.get("career") or {}
        # HARD SCENARIO LOCK: this process only plays LOCKED_SCENARIO_ID (frozen at startup). Force it
        # so the UI toggle can never make a running instance drift or silently fall back to MANT. The
        # resume branch below still lets a live in-game career's OWN scenario win (routing must match
        # the real career), warning on mismatch. Seeds the client's namespace router for the first load;
        # load/index self-corrects from chara_info.scenario_id if a resumed career differs.
        req.scenario_id = LOCKED_SCENARIO_ID
        active_client.current_scenario_id = int(req.scenario_id)
        # Client calls run in a worker thread: a breaker cooldown inside call() sleeps up to 300s and
        # would otherwise freeze the whole server (every UI poll) on the event loop.
        if career.get("active"):
            index_result = await asyncio.to_thread(active_client.call, 'load/index')
            load_data = index_result.get('data', {})
            update_start_state(load_data)

            account = get_account_status(load_data)
            active_account = account
            career = account.get("career") or {}

        if career.get("active"):
            career_result = await asyncio.to_thread(active_client.load_career)
            career_data = career_result.get('data', {})
            
            account = get_account_status(load_data, career_result)
            active_account = account
            
            career_status = account.get("career")
            # Guard every field: a resumed career (especially one started in-game) can
            # leave some of these empty -> int(None) crashed RESUME with the
            # "int() argument ... not 'NoneType'" error.
            req.card_id = int(career_status.get("card_id") or 0)
            req.support_card_ids = career_status.get("support_card_ids") or []
            req.friend_viewer_id = int(career_status.get("friend_viewer_id") or 0)
            req.friend_card_id = int(career_status.get("friend_card_id") or 0)
            req.parent_id_1 = int(career_status.get("parent_id_1") or 0)
            req.parent_id_2 = int(career_status.get("parent_id_2") or 0)
            req.deck_id = int(career_status.get("deck_id") or 0)
            # Resume: the LIVE in-game career's own scenario wins (you cannot re-route an existing
            # career); fall back to the lock only when the live state doesn't carry one. Warn on a
            # mismatch so a wrong-scenario resume is visible rather than silent.
            live_sid = int(career_status.get("scenario_id") or 0)
            req.scenario_id = live_sid or LOCKED_SCENARIO_ID
            if live_sid and live_sid != LOCKED_SCENARIO_ID:
                print(f"[scenario] WARNING: resuming a {SCENARIO_NAMES.get(live_sid, live_sid)} career "
                      f"while this process is locked to {SCENARIO_NAMES.get(LOCKED_SCENARIO_ID)}. Running "
                      f"the live career as-is; restart with that scenario to keep everything consistent.", flush=True)

            chara_info = career_data.get('chara_info') or {}
            if active_dashboard_data:
                active_dashboard_data["account"] = account
            result = career_result
        else:
            req.scenario_id = LOCKED_SCENARIO_ID   # a fresh career is always the locked scenario
            # Off the event loop (see /api/career/start): the fresh-start 102/succession sweep + 208
            # backoffs are the slow blocking path that froze the Web UI on a URA start.
            started = await asyncio.to_thread(start_career_from_request, req)
            if not started.get("success"):
                return started
            result = started["result"]
            account, chara_info = apply_career_result(result)

        # Keep the runner's scenario gates (coin shop / hammer / Unity Cup) consistent with the
        # scenario actually being played this run (locked for fresh, live for a resume).
        preset["scenario_id"] = preset["scenario"] = int(req.scenario_id)
        # Non-MANT schedule opt-in lives ON the preset now (per-preset toggle, persisted via
        # TUNABLE_KEYS), so the value loaded from the saved preset is authoritative -- no per-run
        # override that could silently clobber it back to off. MANT ignores it by design. The log
        # makes "is the schedule actually on for this run" visible instead of an invisible flag.
        _erl = preset.get("extra_race_list") or []
        print(f"[schedule] preset '{preset_name}': use_race_schedule={bool(preset.get('use_race_schedule'))} "
              f"| {len(_erl)} races scheduled | scenario={int(req.scenario_id)}", flush=True)
        apply_deck_type_counts(preset, req=req, chara_info=chara_info)

        # Fresh, deliberate run: clear any prior auto-backoff state so the user gets a
        # clean chance. If the server is still throttling, the breaker re-trips fast.
        try:
            if active_client is not None:
                active_client.reset_circuit()
        except Exception:
            pass

        # run_count: 1 = single career, N = N careers, 0 = run forever.
        # Anything other than exactly 1 loops via manage_career_loop.
        looping = int(req.run_count or 0) != 1
        if looping:
            backend_loop_stop = False
            backend_loop_thread = threading.Thread(target=manage_career_loop, args=(req, preset, result), daemon=True)
            backend_loop_thread.start()
            dna_sleep(0.5, 0.5)
        else:
            career_runner.set_loop_info(1, 1)
            career_runner.start(active_client, preset, result, max(1, min(int(req.max_steps or 2500), 3000)), burn_clocks=req.burn_clocks, dev_mode=False, finish_to_end=bool(req.finish_career))

        return {"success": True, "account": account, "chara_info": chara_info, "runner": career_runner.snapshot()}
    except Exception as e:
        return {"success": False, "detail": str(e)}

@app.get("/api/career/runner")
async def career_runner_status():
    snap = career_runner.snapshot()
    snap["loop_active"] = bool(backend_loop_thread and backend_loop_thread.is_alive())
    return {"success": True, "runner": snap}

@app.get("/api/career/history")
async def career_history():
    """Finished-career history (newest first) for the History UI: trainee name + card_id
    (portrait), rank/rank_letter, rank_score, fans, sparks, when."""
    from career_bot.core import notify
    return {"success": True, "history": notify.read_career_history(DIR)}

@app.post("/api/career/runner/stop")
async def stop_career_runner():
    global backend_loop_stop
    backend_loop_stop = True
    career_runner.stop()
    return {"success": True, "runner": career_runner.snapshot()}

@app.post("/api/career/runner/pause")
async def pause_career_runner():
    # Hold the bot's moves without ending the career (resumable). Does not touch the
    # loop-stop flag, so the multi-run loop simply waits while this career is paused.
    career_runner.pause()
    return {"success": True, "runner": career_runner.snapshot()}

@app.post("/api/career/runner/resume")
async def resume_career_runner():
    career_runner.resume()
    return {"success": True, "runner": career_runner.snapshot()}

class BurnClocksRequest(BaseModel):
    burn_clocks: bool

@app.post("/api/career/runner/burn_clocks")
async def set_burn_clocks(req: BurnClocksRequest):
    career_runner.set_burn_clocks(req.burn_clocks)
    return {"success": True, "runner": career_runner.snapshot()}

# --- In-app auth re-capture: switch Uma account WITHOUT restarting the server. ---
CAPTURE_WINDOWS_ONLY = ("Auth capture only runs on the Windows PC (it launches the game there). Log in on "
                        "Windows with UMA_AUTH_CONFIG=<file> set, copy that file to this host, and restart "
                        "MQA here with UMA_CARRY_IDENTITY=1.")
auth_capture_status = {"capturing": False, "ok": None, "message": "idle", "viewer_id": None}
auth_capture_lock = threading.Lock()

def _run_recapture():
    global auth_capture_status
    try:
        ok = refresh_auth_before_serving()
        vid = (pending_game_auth_config or {}).get("viewer_id") if ok else None
        with auth_capture_lock:
            auth_capture_status = {
                "capturing": False,
                "ok": bool(ok),
                "message": ("Capture complete -- now click LOGIN with the Steam fields BLANK."
                            if ok else
                            "Capture failed/timed out -- trigger a FRESH game login (title screen -> tap to enter), then try again."),
                "viewer_id": vid,
            }
    except Exception as e:
        with auth_capture_lock:
            auth_capture_status = {"capturing": False, "ok": False, "message": f"Capture error: {e}", "viewer_id": None}

@app.post("/api/auth/recapture")
async def recapture_auth():
    global auth_capture_status
    if os.name != 'nt':
        return {"success": False, "detail": CAPTURE_WINDOWS_ONLY}
    # Re-capture closes the game, so refuse while a career/loop is running -- stop first.
    if career_runner.snapshot().get("running") or bool(backend_loop_thread and backend_loop_thread.is_alive()):
        return {"success": False, "detail": "Stop the current run first -- re-capture closes the game."}
    with auth_capture_lock:
        if auth_capture_status.get("capturing"):
            return {"success": False, "detail": "Already capturing.", "capture": dict(auth_capture_status)}
        auth_capture_status = {"capturing": True, "ok": None,
                               "message": "Launching game -- switch to your target Uma account and reach the home menu (<=180s).",
                               "viewer_id": None}
    threading.Thread(target=_run_recapture, daemon=True).start()
    return {"success": True, "capture": dict(auth_capture_status)}

@app.get("/api/auth/recapture/status")
async def recapture_auth_status():
    with auth_capture_lock:
        return {"success": True, "capture": dict(auth_capture_status)}

@app.post("/api/career/friends")
async def get_friend_list(req: FriendListRequest):
    global active_client, active_dashboard_data, active_account
    if not active_client:
        return {"success": False, "detail": "Not logged in"}

    # INTERACTIVE call the user is actively waiting on (the post-login dashboard blocks on it):
    # bypass the GateKeeper's humanise pacing, exactly like the login/REFRESH exemption. Without
    # this, pre_single_mode's pacing row (1.8..26s!) made "login" feel hung for up to half a
    # minute. unpaced() swaps the SHARED client's call, so only do it when no automation could be
    # touching the client concurrently (runner idle AND no between-careers loop thread alive) --
    # which is exactly the post-login dashboard case this exists for.
    import contextlib
    automation_busy = bool(career_runner.snapshot().get("running")
                           or (backend_loop_thread and backend_loop_thread.is_alive()))
    unpaced = getattr(active_client, "unpaced", None)
    if unpaced is None or automation_busy:
        unpaced = contextlib.nullcontext

    # The cached career.active flag goes STALE after a career finishes (nothing clears it), which left
    # the friend endpoint permanently "Active career, endpoint blocked". Trust the SERVER, not the cache:
    # when the cache says active, probe load_career -- it 102s ("no active career") once the slot is
    # actually free, so we clear the stale flag and proceed to reload friends.
    if active_account and (active_account.get("career") or {}).get("active"):
        try:
            with unpaced():
                cr = active_client.load_career()
            still_active = bool(((cr or {}).get("data") or {}).get("chara_info"))
        except Exception as e:
            # 102/201/StateRecoveryError = no active career (slot free); anything else -> stay cautious.
            still_active = not (is_api_error(e, 102, 201) or isinstance(e, StateRecoveryError))
        if not still_active and active_account.get("career"):
            active_account["career"]["active"] = False
        if still_active:
            return {
                "success": True,
                "friends": [],
                "guest_parents": [],
                "exclude_viewer_ids": [],
                "source": "Active Career (Skip)"
            }

    if not req.exclude_viewer_ids and active_dashboard_data is not None and "friends" in active_dashboard_data:
        return {
            "success": True,
            "friends": active_dashboard_data["friends"],
            "guest_parents": active_dashboard_data.get("guest_parents", []),
            "exclude_viewer_ids": active_dashboard_data.get("friendExcludeIds", []),
            "source": "cache"
        }

    try:
        with unpaced():
            result = active_client.pre_single_mode(req.exclude_viewer_ids)
        data = result.get('data', {})
        update_start_state(data)
        friends, exclude_viewer_ids, source = normalize_friend_cards(data)
        guest_parents = normalize_guest_parents(data)

        if active_dashboard_data is not None:
            active_dashboard_data["friends"] = friends
            active_dashboard_data["friendExcludeIds"] = exclude_viewer_ids
            active_dashboard_data["friendsLoaded"] = True
            active_dashboard_data["guest_parents"] = guest_parents

        return {
            "success": True,
            "friends": friends,
            "guest_parents": guest_parents,
            "exclude_viewer_ids": exclude_viewer_ids,
            "source": source
        }
    except Exception as e:
        return {"success": False, "detail": str(e)}

@app.post("/api/career/action")
async def career_action(req: CareerActionRequest):
    global active_client, active_account
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    
    try:
        result = active_client.exec_command(
            command_type=req.command_type,
            command_id=req.command_id,
            current_turn=req.current_turn,
            current_vital=req.current_vital,
            command_group_id=req.command_group_id,
            select_id=req.select_id
        )
        
        data = result.get('data', {})
        return {
            "success": True,
            "chara_info": data.get('chara_info', {}),
            "command_result": data.get('command_result', {})
        }
    except Exception as e:
        return {"success": False, "detail": str(e)}

@app.post("/api/career/delete")
async def delete_career(req: DeleteCareerRequest):
    global active_client, active_account, active_dashboard_data, backend_loop_thread
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if career_runner.snapshot().get("running") or (backend_loop_thread and backend_loop_thread.is_alive()):
        return {"success": False, "detail": "Cannot delete career while runner is active"}

    try:
        # FORCE clear: the cached account.career flag can be stale (the game shows no career while
        # the server slot is still occupied), so pull the REAL server state and force-delete no
        # matter what the cached flag says.
        try:
            load_result = active_client.call('load/index', {'adid': ''})
            update_start_state(load_result.get('data', {}))
            account = get_account_status(load_result.get('data', {}))
            active_account = account
        except Exception:
            account = active_account or {}
        # True turn from the live single-mode state.
        chara = {}
        try:
            car = active_client.load_career()
            chara = ((car or {}).get('data') or {}).get('chara_info') or {}
        except Exception as e:
            if is_api_error(e, 102, 201) or isinstance(e, StateRecoveryError):
                account["career"] = None
                active_account = account
                return {"success": True, "detail": "No career on the server -- slot is already clear."}
        current_turn = req.current_turn or int(chara.get('turn') or 0) or 78
        # Force-delete (finish with is_force_delete); 102/201 = server treats it as already done.
        try:
            active_client.finish_career(current_turn=current_turn, is_force_delete=True)
        except Exception as e:
            if not (is_api_error(e, 102, 201, 1503) or isinstance(e, StateRecoveryError)):
                raise
        # Verify the slot actually freed.
        still_stuck = False
        try:
            car2 = active_client.load_career()
            still_stuck = bool(((car2 or {}).get('data') or {}).get('chara_info'))
        except Exception:
            still_stuck = False
        account["career"] = None
        active_account = account
        if active_dashboard_data:
            active_dashboard_data["account"] = account
        if still_stuck:
            return {"success": False, "detail": (
                "Force-delete didn't clear it -- the server still holds a career (result_code 102). "
                "This is a PRE-MAINTENANCE career (game error 2512): the API refuses to delete it; "
                "only the game CLIENT can, via the in-game 'Delete Career Data' prompt on this exact "
                "account. If the game shows no career, the bot is running a different account than the "
                "one you see in-game -- that account is the one holding the stuck career.")}
        return {"success": True, "detail": "Career slot force-cleared.", "account": account}
    except Exception as e:
        return {"success": False, "detail": str(e)}


@app.post("/api/trainees/delete")
async def delete_trainees(req: DeleteTraineesRequest):
    """Permanently RELEASE the finished trainees the user selected (trained_chara/remove, batch).
    Manual + user-selected only. Refuses while the runner is active, and never removes a LOCKED
    trainee or one currently configured as an inheritance parent (deleting a live parent breaks the
    next career start). Returns the removed ids, any skipped ids with reasons, and the refreshed
    roster."""
    global active_client, active_account, active_dashboard_data
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if career_runner.snapshot().get("running") or (backend_loop_thread and backend_loop_thread.is_alive()):
        return {"success": False, "detail": "Cannot delete trainees while the career runner is active. Stop it first."}

    requested = []
    seen = set()
    for x in (req.trained_chara_ids or []):
        try:
            v = int(x)
        except (TypeError, ValueError):
            continue
        if v > 0 and v not in seen:
            seen.add(v)
            requested.append(v)
    if not requested:
        return {"success": False, "detail": "No trainees selected."}

    try:
        # Pull the authoritative roster (is_locked is the game's own protect flag) so the guards below
        # act on live server state, not a stale cached dashboard.
        load_result = active_client.call('load/index', {'adid': ''})
        d = load_result.get('data', {}) or {}
        roster = {int(c.get('trained_chara_id') or 0): c
                  for c in (d.get('trained_chara') or []) if c.get('trained_chara_id')}

        # Ids we must never remove: the two inheritance parents of the active/queued career, plus any
        # veteran the user has picked in SETUP for the next start -- deleting one 102s the next start.
        protected = set()
        career = (active_account or {}).get('career') or {}
        for k in ('parent_id_1', 'parent_id_2'):
            try:
                pid = int(career.get(k) or 0)
            except (TypeError, ValueError):
                pid = 0
            if pid:
                protected.add(pid)
        for vet in (active_selection or {}).get('veterans') or []:
            try:
                vid = int((vet or {}).get('instance_id') or 0)
            except (TypeError, ValueError):
                vid = 0
            if vid:
                protected.add(vid)

        allowed, skipped = [], []
        for tid in requested:
            chara = roster.get(tid)
            if chara is None:
                skipped.append({"id": tid, "reason": "not in roster"})
            elif int(chara.get('is_locked', 0) or 0) == 1:
                skipped.append({"id": tid, "reason": "locked"})
            elif tid in protected:
                skipped.append({"id": tid, "reason": "configured inheritance parent"})
            else:
                allowed.append(tid)

        removed = []
        if allowed:
            active_client.remove_trained_chara(allowed)
            removed = allowed
            # Re-pull the roster so the returned list + succession caches reflect the deletions.
            load_result = active_client.call('load/index', {'adid': ''})
            d = load_result.get('data', {}) or {}

        parents = build_parents_from_trained_chara(d.get('trained_chara', []))
        if active_dashboard_data is not None:
            active_dashboard_data["parents"] = parents

        detail = f"Released {len(removed)} trainee(s)."
        if skipped:
            detail += f" Skipped {len(skipped)} (locked / parent / missing)."
        return {"success": True, "detail": detail, "removed": removed,
                "skipped": skipped, "parents": parents}
    except Exception as e:
        return {"success": False, "detail": str(e)}


# ====================== DEBUG ======================
@app.get("/api/debug/start_state")
async def get_start_state():
    return active_start_state

@app.get("/api/debug/raw_load")
async def get_raw_load():
    return {"error": "raw load/index response storage disabled"}

def set_console_topmost():
    if os.name != 'nt':
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return
        ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
    except Exception:
        pass

def kill_process_by_name(name):
    if os.name != 'nt':
        return
    try:
        subprocess.run(['taskkill', '/IM', name, '/F'], capture_output=True, text=True, timeout=10)
    except Exception:
        pass

def kill_listeners_on_port(port):
    if os.name != 'nt':
        return
    try:
        proc = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True,
            text=True,
            timeout=5
        )
    except Exception:
        return

    current_pid = os.getpid()
    pids = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local_addr = parts[1]
        state = parts[3].upper() if len(parts) >= 5 else ''
        pid_text = parts[-1]
        # Exact port match: a substring test for ':1616' also hit 0.0.0.0:16160-16169 and killed
        # unrelated programs. rsplit keeps IPv6 ([::]:1616) working.
        if local_addr.rsplit(':', 1)[-1] != str(port) or state != 'LISTENING':
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid and pid != current_pid:
            pids.add(pid)

    if not pids:
        return
    print(f"Port {port} already in use; killing listener PID(s): {', '.join(map(str, sorted(pids)))}", flush=True)
    for pid in sorted(pids):
        try:
            subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, text=True, timeout=5)
        except Exception:
            pass
    dna_sleep(0.5, 0.5)

def has_fresh_auth_config(cfg):
    app_ver = str(cfg.get('app_ver') or '').strip()
    res_ver = str(cfg.get('res_ver') or '').strip()
    if not app_ver or not res_ver:
        return False
    if int(cfg.get('auth_key_len') or 0) != 48:
        return False
    viewer_id = cfg.get('viewer_id')
    udid = str(cfg.get('udid') or '').strip()
    auth_key = str(cfg.get('auth_key') or '').strip().lower()
    if not viewer_id or not udid or not auth_key:
        return False
    if not re.fullmatch(r'[0-9a-f]+', auth_key):
        return False
    if len(auth_key) < 32 or len(auth_key) % 2:
        return False
    if len(udid) != 36 or udid.count('-') != 4:
        return False
    return True

def launch_game():
    if os.name != 'nt':
        print('Auth refresh needs Windows Steam launch.')
        return False
    try:
        os.startfile(f'steam://rungameid/{APP_ID}')
        return True
    except Exception as e:
        print(f'Failed to launch Umamusume through Steam: {e}')
        return False

def _auto_tap_game(stop):
    """While a capture waits, click the middle of the game window every few seconds: the title
    screen's "tap to start", so a capture (startup or a 394 recovery) needs nobody at the PC.
    A click is only sent when the game window is in front AND under that point, so it never lands
    in another program. Off with SWEEPY_AUTO_TAP=0."""
    # ponytail: blind centre taps; a pop-up whose button sits off-centre still needs a person.
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.WindowFromPoint.argtypes = [wintypes.POINT]
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def pid_of(h):
        p = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        return p.value

    while not stop.wait(4.0):
        try:
            pid = frida.get_local_device().get_process(PROCESS_NAME).pid
        except Exception:
            continue                      # game not up yet
        wins = []

        def collect(h, _):
            if pid_of(h) == pid and u.IsWindowVisible(h):
                r = wintypes.RECT()
                u.GetClientRect(h, ctypes.byref(r))
                if r.right > 200 and r.bottom > 200:
                    wins.append((r.right * r.bottom, h, r))
            return True
        u.EnumWindows(enum_proc(collect), 0)
        if not wins:
            continue
        _, h, r = max(wins, key=lambda w: w[0])
        pt = wintypes.POINT(r.right // 2, r.bottom // 2)
        u.ClientToScreen(h, ctypes.byref(pt))
        u.SetForegroundWindow(h)
        under = u.WindowFromPoint(pt)
        if u.GetForegroundWindow() != h or not under or pid_of(under) != pid:
            continue                      # something else is on top: don't click into it
        old = wintypes.POINT()
        u.GetCursorPos(ctypes.byref(old))
        u.SetCursorPos(pt.x, pt.y)
        u.mouse_event(0x0002, 0, 0, 0, 0)   # left down
        time.sleep(0.08)
        u.mouse_event(0x0004, 0, 0, 0, 0)   # left up
        u.SetCursorPos(old.x, old.y)


def refresh_auth_before_serving(timeout_sec=None):
    global pending_game_auth_config
    timeout_sec = timeout_sec or int(os.environ.get('SWEEPY_AUTH_CAPTURE_TIMEOUT_SEC', '180'))
    started_at = time.time()
    deadline = started_at + timeout_sec

    print('[NEED TO CAPTURE AUTH]', flush=True)
    if os.name != 'nt':
        print(f'[capture] {CAPTURE_WINDOWS_ONLY}', flush=True)
        return False
    if frida is None:
        print('[capture] frida is not installed: pip install -r requirements.txt', flush=True)
        return False
    if not launch_game():
        return False
    
    print(f'Waiting up to {timeout_sec}s for user to enter game menu', flush=True)

    tap_stop = threading.Event()
    if os.environ.get('SWEEPY_AUTO_TAP', '1') != '0':
        print('[capture] auto-tapping the game title screen (SWEEPY_AUTO_TAP=0 turns this off)', flush=True)
        threading.Thread(target=_auto_tap_game, args=(tap_stop,), daemon=True).start()
    try:
        return _capture_until(deadline)
    finally:
        tap_stop.set()


def _capture_until(deadline):
    global pending_game_auth_config
    session = None
    captured_data = {}
    done = {'ok': False}

    def on_message(message, data):
        if message.get('type') == 'error':
            print(f"Frida Error: {message.get('description')}", flush=True)
            return
        payload = message.get('payload') or {}
        if payload.get('type') == 'creds':
            if payload.get('app_ver') and payload.get('res_ver'):
                try:
                    from uma_api.client import unpack
                    wire = unpack(payload.get('body') or '', payload.get('udid') or '')
                    for key in (
                        'viewer_id',
                        'device_id',
                        'device_name',
                        'graphics_device_name',
                        'ip_address',
                        'platform_os_version',
                        'locale',
                        'steam_id',
                        'steam_session_ticket',
                    ):
                        if wire.get(key) is not None:
                            payload[key] = wire.get(key)
                except Exception:
                    pass
                captured_data.update(payload)
                done['ok'] = True

    while time.time() < deadline:
        try:
            session = frida.attach(PROCESS_NAME)
            break
        except Exception:
            dna_sleep(1.0, 1.0)
    
    if not session:
        print(f'Error: {PROCESS_NAME} not found within timeout.', flush=True)
        return False

    try:
        script = session.create_script(JS_CODE)
        script.on('message', on_message)
        script.load()

        while time.time() < deadline:
            if done['ok'] and has_fresh_auth_config(captured_data):
                pending_game_auth_config = dict(captured_data)
                # Echo the version pair so a stale capture (game updated past this
                # res_ver -> API error 214 on load/index) is visible before serving,
                # not a mystery later. Secrets (auth_key, steam ticket) stay unprinted.
                print(f"[AUTH CAPTURED] app_ver={captured_data.get('app_ver')} "
                      f"res_ver={captured_data.get('res_ver')} "
                      f"viewer_id={captured_data.get('viewer_id')}", flush=True)
                dna_sleep(2.0, 4.0)
                kill_process_by_name(PROCESS_NAME)
                return True
            dna_sleep(0.5, 0.5)
    except Exception as e:
        print(f'Frida injection failed: {e}', flush=True)
    finally:
        if session:
            try:
                session.detach()
            except Exception:
                pass

    print('Auth refresh failed: no fresh credentials captured before timeout.', flush=True)
    return False


def startup_auth_ready():
    """The startup gate. UMA_CARRY_IDENTITY=1 adopts the identity file instead of capturing (no game,
    no Frida) -- off Windows the only way in, and only with every device field carried. Env unset:
    capture fresh exactly as before."""
    global pending_game_auth_config
    if carrying_identity():
        cfg = load_auth_config()
        missing = missing_carried_fields(cfg) if os.name != 'nt' else []
        if has_fresh_auth_config(cfg) and not missing:
            pending_game_auth_config = cfg
            print(f"[auth] using the carried identity (viewer_id {cfg.get('viewer_id')}, app_ver "
                  f"{cfg.get('app_ver')}, res_ver {cfg.get('res_ver')}) -- no capture, no game launch", flush=True)
            return True
        print("[auth] UMA_CARRY_IDENTITY is set but the identity file is missing or incomplete"
              + (f" (lacks {', '.join(missing)})" if missing else ""), flush=True)
    return refresh_auth_before_serving()


def stop_runs_for_exit(timeout_sec=30):
    """uvicorn returned (Ctrl+C, or SIGTERM from a systemd stop): stop the loop and the runner and wait
    for them, so the process exits between API calls instead of killing a daemon thread mid-request.
    The career stays resumable either way; the timeout keeps a stuck call from blocking exit."""
    global backend_loop_stop, _exiting
    _exiting = True
    # uvicorn 0.18.2 leaves its own SIGINT handler installed, which swallows a second Ctrl+C: put the
    # default back so a second Ctrl+C ends the wait at once.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    deadline = time.monotonic() + timeout_sec

    def wait(t):
        if t and t.is_alive():
            print(f"[shutdown] waiting up to {timeout_sec}s for the run to stop between API calls", flush=True)
            while t.is_alive() and time.monotonic() < deadline:
                t.join(0.25)   # short slices: on Windows a Ctrl+C only lands between joins, never inside one

    backend_loop_stop = True
    career_runner.stop()
    wait(backend_loop_thread)   # the loop first: it can start another career after the stop above,
    career_runner.stop()        # so stop the runner again and join the thread it runs NOW
    wait(career_runner.thread)


def parse_cli_args(argv):
    # Usage: python main.py [PORT] [--account NAME]
    # Each account runs as its own process on its own port. --account NAME is a
    # display label (Discord notifications / multi-instance bookkeeping) -- auth is
    # always captured fresh at startup and never saved to disk. --reauth is
    # accepted for backward compatibility but is a no-op now (every start reauths).
    port = None
    account = os.environ.get("SWEEPY_ACCOUNT") or None
    reauth = False
    # --scenario mant|unity|ura|4|2|1 -> hard-locks the scenario for this process. SWEEPY_SCENARIO does
    # the same for a service with no terminal to prompt on; the flag wins.
    scenario = SCENARIO_ALIASES.get(str(os.environ.get("SWEEPY_SCENARIO") or "").strip().lower())
    args = list(argv)
    i = 0
    while i < len(args):
        a = str(args[i]).strip()
        if a in ("--account", "-a") and i + 1 < len(args):
            account = str(args[i + 1]).strip() or account
            i += 2
            continue
        if a in ("--scenario", "-s") and i + 1 < len(args):
            scenario = SCENARIO_ALIASES.get(str(args[i + 1]).strip().lower())
            i += 2
            continue
        if a == "--reauth":
            reauth = True
        elif a.isdigit() and port is None and 1 <= int(a) <= 65535:
            port = int(a)
        i += 1
    if port is None:
        env = str(os.environ.get("SWEEPY_PORT") or "").strip()
        port = int(env) if env.isdigit() and 1 <= int(env) <= 65535 else 1616
    return port, account, reauth, scenario


if __name__ == "__main__":
    import uvicorn

    port, account, reauth, cli_scenario = parse_cli_args(sys.argv[1:])
    if account:
        os.environ["SWEEPY_ACCOUNT"] = account

    # Choose the scenario for this session: --scenario flag if given, else an interactive prompt
    # (only when a real terminal is attached, so headless/cron runs fall back to the MANT default).
    chosen = cli_scenario
    _src = "--scenario flag / SWEEPY_SCENARIO"
    if chosen is None and sys.stdin is not None and sys.stdin.isatty():
        chosen = prompt_scenario_choice()
        _src = "startup prompt"
    if chosen is None:
        _src = "default"
    locked = lock_scenario_at_startup(chosen)
    print(f"[scenario] LOCKED to {SCENARIO_NAMES.get(locked, locked)} ({locked}) for this session "
          f"[from {_src}] -- restart the terminal to choose again.", flush=True)

    # Auto git-pull intentionally disabled: this build is detached from any
    # remote, so the upstream repo can never overwrite local work on startup.

    set_console_topmost()
    kill_listeners_on_port(port)

    # Auth is captured fresh every start (saved-auth was removed: the persisted file
    # could never hold the short-lived Steam ticket, so it only produced confusing
    # "No Steam ticket available" dead-ends). The game launches, Frida captures the
    # login, the game closes, and the auth lives in memory for this process only --
    # unless UMA_CARRY_IDENTITY=1 carries it in from a file (see startup_auth_ready).
    if not startup_auth_ready():
        raise SystemExit(1)

    print(f"Access the Web UI at: http://127.0.0.1:{port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", interface="asgi3")
    stop_runs_for_exit()
