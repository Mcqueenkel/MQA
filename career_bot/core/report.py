import json
import re
import traceback
from datetime import datetime
from pathlib import Path


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def new_report(preset=None, scenario_id=0):
    preset = preset or {}
    return {
        "started_at": now_iso(),
        "ended_at": None,
        "preset_name": preset.get("name", ""),
        "scenario_id": scenario_id,
        "status": "running",
        "outcome": None,   # clear 'why it ended': completed / goal_failed@turnN / error / auto_backoff / stopped
        "error": None,
        "final_turn": 0,
        "turns": [],
    }


def safe_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


# The trainee's aptitude grades (game scale: 1=G .. 8=S). Enough to tell "lost a dirt race" from
# "should never have entered a dirt race".
_APTITUDE_KEYS = (
    "proper_distance_short", "proper_distance_mile", "proper_distance_middle", "proper_distance_long",
    "proper_ground_turf", "proper_ground_dirt",
    "proper_running_style_nige", "proper_running_style_senko",
    "proper_running_style_sashi", "proper_running_style_oikomi",
)


def capture_career_identity(report, state):
    """Record the career's STARTING HAND once, at career start.

    The rest of this log says what the bot DID; without this there is no record of what it was DEALT,
    so two careers on the same preset that score 2972 vs 4171 are indistinguishable -- you cannot tell
    a worse decision from a worse draw, and the ai_learn loop cannot be scored at all.

    Ids only, deliberately: names live in data/chara_list.json + data/support_list.json and are a join
    away, and resolving them here would couple the logger to regenerated game data. Idempotent (first
    call with a real card_id wins) and never raises -- logging must not break a career.
    """
    try:
        if report is None or report.get("identity"):
            return
        chara = ((state or {}).get("data") or {}).get("chara_info") or {}
        card_id = safe_int(chara.get("card_id"))
        if not card_id:
            return                      # pre-start / torn-down state: try again next turn
        report["identity"] = {
            "card_id": card_id,
            "chara_id": card_id // 100,               # card_id = chara_id * 100 + outfit
            "single_mode_chara_id": safe_int(chara.get("single_mode_chara_id")),
            "rarity": safe_int(chara.get("rarity")),
            "talent_level": safe_int(chara.get("talent_level")),
            "chara_grade": safe_int(chara.get("chara_grade")),
            "race_running_style": safe_int(chara.get("race_running_style")),
            "aptitudes": {k: safe_int(chara.get(k)) for k in _APTITUDE_KEYS if chara.get(k) is not None},
            # position/limit_break matter: the same card at LB0 vs LB4 is a different card in practice.
            "support_deck": [
                {"position": safe_int(c.get("position")),
                 "support_card_id": safe_int(c.get("support_card_id")),
                 "limit_break_count": safe_int(c.get("limit_break_count"))}
                for c in (chara.get("support_card_array") or []) if isinstance(c, dict)
            ],
            "inherit_parent_ids": [safe_int(chara.get("succession_trained_chara_id_1")),
                                   safe_int(chara.get("succession_trained_chara_id_2"))],
        }
    except Exception:
        pass


def turn_from_event(event):
    data = event.get("data") or {}
    for key in ("payload", "request_payload"):
        payload = data.get(key) or {}
        if payload.get("current_turn") is not None:
            return safe_int(payload.get("current_turn"))
    if event.get("turn") is not None:
        return safe_int(event.get("turn"))
    return 0


def get_turn(report, turn_number):
    turn_number = safe_int(turn_number)
    for turn in report.setdefault("turns", []):
        if safe_int(turn.get("turn")) == turn_number:
            return turn
    turn = {
        "turn": turn_number,
        "api_calls": [],
        "skill_buy_attempts": [],
        "item_buy_attempts": [],
        "item_usage_attempts": [],
    }
    report.setdefault("turns", []).append(turn)
    report["turns"].sort(key=lambda row: safe_int(row.get("turn")))
    return turn


def merge_turn(report, row):
    turn_number = safe_int(row.get("turn"))
    turn = get_turn(report, turn_number)
    preserved = {
        "api_calls": turn.get("api_calls") or [],
        "skill_buy_attempts": turn.get("skill_buy_attempts") or [],
        "item_buy_attempts": turn.get("item_buy_attempts") or [],
        "item_usage_attempts": turn.get("item_usage_attempts") or [],
    }
    turn.update(row)
    for key, value in preserved.items():
        turn[key] = value
    report["final_turn"] = max(safe_int(report.get("final_turn")), turn_number)
    return turn


def add_event(report, row):
    event = row.get("event")
    turn = get_turn(report, row.get("turn"))
    if event == "turn":
        return merge_turn(report, row)
    if event == "skills_attempt":
        turn.setdefault("skill_buy_attempts", []).append(row)
    elif event == "items_buy_attempt":
        turn.setdefault("item_buy_attempts", []).append(row)
    elif event == "items_use_attempt":
        turn.setdefault("item_usage_attempts", []).append(row)
    else:
        turn.setdefault("events", []).append(row)
    report["final_turn"] = max(safe_int(report.get("final_turn")), safe_int(row.get("turn")))
    return turn


# Device/auth fields the game envelope repeats on EVERY request -- pure bloat in a decision log.
_ENV_KEYS = frozenset({
    "viewer_id", "device", "device_id", "device_name", "graphics_device_name", "ip_address",
    "platform_os_version", "carrier", "keychain", "locale", "button_info", "dmm_viewer_id",
    "dmm_onetime_token", "steam_id", "steam_session_ticket", "device_token", "attestation_type", "adid",
})
# chara-state fields worth keeping from a response (for per-turn analysis)
_CHARA_KEYS = ("turn", "vital", "motivation", "fans", "speed", "stamina", "power", "guts", "wiz")


def compact_api_data(direction, data):
    """Shrink a logged api payload to what's worth analysing: drop the device/auth envelope (repeated
    on every request) and the multi-KB full game-state RESPONSE blob. The raw call is still in
    uma_runtime/api_library/<ns>/<ep>.jsonl if ever needed -- this only trims the CAREER LOG, taking a
    full career from ~37 MB to a few hundred KB. Never raises (logging must not break a career)."""
    try:
        if not isinstance(data, dict):
            return data
        # RESPONSE -> result_code + a tiny chara summary; drop the giant data/data_headers blob
        if direction in ("RES", "RESP") or "response_code" in data or "data_headers" in data:
            rc = data.get("response_code")
            if rc is None:
                rc = (data.get("data_headers") or {}).get("result_code")
            out = {"result_code": rc}
            body = (data.get("data") or {})
            chara = body.get("chara_info") or {}
            summ = {k: chara.get(k) for k in _CHARA_KEYS if chara.get(k) is not None}
            if summ:
                out["chara"] = summ
            # playing_state decides which screen the game is parked on -- it is what separates a
            # Concert screen from a normal turn, and losing it is why a Grand Live idle-out could not
            # be explained from the log (career_log_20260731_105832).
            if chara.get("playing_state") is not None:
                out["playing_state"] = chara.get("playing_state")
            # How many events were still queued when this response came back. check_event is ~39% of
            # a URA career (139 calls of 356), and without this there is no way to tell a poll that
            # found work from one that found an empty queue -- so the drain loop cannot be judged.
            # A COUNT only, never the events themselves: the point is to stay small.
            events = body.get("unchecked_event_array")
            if isinstance(events, list):
                out["queued_events"] = len(events)
            return out
        # REQUEST -> unwrap {payload:...}, drop envelope keys, collapse long arrays to just their length
        pl = data.get("payload") if "payload" in data else data
        if not isinstance(pl, dict):
            return pl
        return {k: (len(v) if isinstance(v, list) and len(v) > 6 else v)
                for k, v in pl.items() if k not in _ENV_KEYS}
    except Exception:
        return None


def add_api_call(report, event):
    turn = get_turn(report, turn_from_event(event))   # turn_from_event needs the RAW payload -> before trim
    event["data"] = compact_api_data(event.get("direction"), event.get("data"))
    turn.setdefault("api_calls", []).append(event)
    report["final_turn"] = max(safe_int(report.get("final_turn")), safe_int(turn.get("turn")))


def add_decision(report, state, decision):
    data = (state or {}).get("data") or {}
    chara = data.get("chara_info") or {}
    payload = dict(getattr(decision, "payload", {}) or {})
    turn = get_turn(report, payload.get("current_turn") or chara.get("turn") or 0)
    turn["current_command"] = payload
    turn["selected_action"] = getattr(decision, "action", "")
    turn["decision_reason"] = getattr(decision, "reason", "")
    turn["current_action_taken"] = getattr(decision, "action", "")
    # selected_action keeps only the LAST decision, so a Grand Live concert (or the final finish)
    # hid the race/training done earlier that turn. Keep every non-event decision in order.
    action = getattr(decision, "action", "")
    if action != "event":
        row = {"action": action, "reason": getattr(decision, "reason", "")}
        for key in ("program_id", "command_type", "command_id", "command_group_id", "square_id"):
            if payload.get(key) is not None:
                row[key] = payload[key]
        turn.setdefault("decisions", []).append(row)


def add_race(report, row):
    """One record per race actually run: turn, program, every finishing position (clock retries
    included), and the career-goal requirement when it was a goal race."""
    if report is not None:
        report.setdefault("races", []).append(row)


def set_error(report, exc):
    report["status"] = "error"
    report["error"] = {
        "type": type(exc).__name__,
        "message": str(exc),
        "stack_trace": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }


def finish_report(report, status=None, outcome=None):
    if status:
        report["status"] = status
    if report.get("status") == "running":
        report["status"] = "finished"
    if outcome:
        report["outcome"] = outcome
    report["ended_at"] = now_iso()
    turns = report.get("turns") or []
    if turns:
        report["final_turn"] = max(safe_int(turn.get("turn")) for turn in turns)


def write_report(report, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"career_log_{stamp}.json"
    
    def _json_default(obj):
        if isinstance(obj, bytes):
            return obj.hex()
        return str(obj)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=_json_default)
    
    latest = output_dir / "latest_career_log.json"
    try:
        import shutil
        shutil.copyfile(path, latest)
    except Exception:
        pass
    return path
