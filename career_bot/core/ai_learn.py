"""Lean closed-loop AI-learning subsystem for the MQA career bot.

This module is local-first, stdlib-only, and deterministic.  It learns from the
bot's own race/career outcomes, trains a tiny inspectable model, exposes a
confidence-gated policy signal the deterministic solver may optionally use, and
supports transferring the learned "brain" between installs.

Design contract (hard rules):
- Pure Python standard library only (json, os, time, zipfile, pathlib, tempfile).
- Every public function is robust to missing/corrupt files and NEVER raises into
  the running bot.  Errors are swallowed; callers get safe neutral defaults.
- Additive only.  Nothing here mutates existing bot state or files outside the
  AI directory (``uma_runtime/ai`` and ``uma_runtime/ai_backups``).

The closed loop:
    log_experience()  -> append raw race/career outcomes
    train()           -> aggregate experience into models.json
    race_policy_adjustment() -> feed the learned signal back into decisions
    (runner retrains after each career)
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict

from career_bot.core.data_store import DataStore

# --- tunables -----------------------------------------------------------------
MIN_SAMPLES = 6          # races needed before confidence reaches 1.0
ADJ_SCALE = 0.6          # how strongly a learned win-rate skews the race value
MAX_LINES = 50000        # experience.jsonl growth ceiling (lines)
KEEP_LINES = 40000       # lines retained when trimming kicks in
# Order of the per-stat rank marks in a race's popularity_mark_rank_array (the game's
# per-stat ranking of the player among the field: index 0=speed, 1=stamina, 2=power).
STAT_MARK_ORDER = ("speed", "stamina", "power")
MARK_LACK_MIN_LOSSES = 3   # need at least this many sampled losing races before the signal fires
# Learned training overlay, on _score_command_base's scale: stat_value_multiplier prices a stat
# point at ~0.01, so a +30 training scores ~0.35 and one rainbow adds ~0.12. The clamp keeps the
# learned term a tie-breaker (~5 stat points) that cannot outvote rainbows, caps or balance.
TRAINING_GAIN_WEIGHT = 0.01
TRAINING_ADJ_CLAMP = 0.05

# Files inside the AI directory the brain is allowed to contain.
EXPERIENCE_NAME = "experience.jsonl"
MODELS_NAME = "models.json"
_ALLOWED_BRAIN_FILES = {EXPERIENCE_NAME, MODELS_NAME}


# --- internal helpers ---------------------------------------------------------

def _ai_dir(base_dir: Any) -> Path:
    """Return ``uma_runtime/ai`` for this install (never raises).

    ``runtime_output_root`` lives in :mod:`career_bot.runner`; it is imported
    lazily here to avoid a circular import (runner -> mant -> ai_learn -> runner).
    """
    from career_bot.runner import runtime_output_root
    return runtime_output_root(base_dir) / "ai"


def _experience_path(base_dir: Any) -> Path:
    return _ai_dir(base_dir) / EXPERIENCE_NAME


def _models_path(base_dir: Any) -> Path:
    return _ai_dir(base_dir) / MODELS_NAME


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except Exception:
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return float(default)


def _read_jsonl(path: Path) -> list:
    """Read a JSONL file into a list of dicts, skipping corrupt lines."""
    rows: list = []
    try:
        if not path.exists():
            return rows
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        rows.append(row)
                except Exception:
                    continue
    except Exception:
        return rows
    return rows


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write JSON atomically (tmp file + os.replace). Best effort."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(path))
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def _trim_experience(path: Path) -> None:
    """Bound experience.jsonl growth: if over MAX_LINES, keep the newest KEEP_LINES."""
    try:
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
        if len(lines) <= MAX_LINES:
            return
        keep = lines[-KEEP_LINES:]
        fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.writelines(keep)
            os.replace(str(tmp), str(path))
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
    except Exception:
        return


def _load_models(base_dir: Any) -> Dict[str, Any]:
    """Load models.json, returning {} on any problem."""
    try:
        path = _models_path(base_dir)
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# --- public API ---------------------------------------------------------------

def log_experience(base_dir: Any, record: Dict[str, Any]) -> None:
    """Append one experience record (with a ``ts`` epoch) to experience.jsonl.

    Creates the AI directory if needed.  Bounds file growth.  Swallows all
    errors so a telemetry failure can never break a running career.
    """
    try:
        if not isinstance(record, dict):
            return
        path = _experience_path(base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        row = dict(record)
        row.setdefault("ts", time.time())
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        _trim_experience(path)
    except Exception:
        return


def _training_phase(turn: Any) -> str:
    try:
        value = int(turn or 0)
    except (TypeError, ValueError):
        value = 0
    if value <= 24:
        return "early"
    if value <= 48:
        return "mid"
    return "late"


_AUTO_REFRESH_STATE = {}
_MODEL_CACHE = {}


def _training_vitality_bucket(vitality: Any) -> str:
    try:
        value = float(vitality or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value < 20:
        return "critical"
    if value < 40:
        return "low"
    if value < 65:
        return "medium"
    return "high"


def _training_condition_key(scenario_id: Any, phase: Any, vitality_bucket: Any,
                           rainbow_count: Any, command_id: Any) -> str:
    try:
        rainbow = min(3, max(0, int(rainbow_count or 0)))
    except (TypeError, ValueError):
        rainbow = 0
    return f"{_safe_int(scenario_id)}:{phase}:{vitality_bucket}:r{rainbow}:{_safe_int(command_id)}"


def _load_models_cached(base_dir: Any) -> Dict[str, Any]:
    """Load models once per file version so scoring does not hit disk per candidate."""
    try:
        path = _models_path(base_dir)
        key = str(path.resolve())
        stat = path.stat()
        version = (getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)), stat.st_size)
        cached = _MODEL_CACHE.get(key)
        if cached and cached.get("version") == version:
            return cached.get("models") or {}
        models = _load_models(base_dir)
        _MODEL_CACHE[key] = {"version": version, "models": models}
        return models
    except Exception:
        return _load_models(base_dir)


def _training_policy_score(row: Dict[str, Any]) -> float:
    """Learned value of one aggregated training bucket (same weights as the live adjustment)."""
    return (
        _safe_float(row.get("avg_gain")) * TRAINING_GAIN_WEIGHT
        + _safe_float(row.get("success_rate")) * 0.50
        - _safe_float(row.get("avg_failure_rate")) * 0.01
        + _safe_float(row.get("avg_career_reward")) * 0.40
    )


def _validate_training_policy(training_by_context: Dict[str, Dict[str, Any]],
                              training_by_action: Dict[str, Dict[str, Any]],
                              holdout_by_context: Any = None,
                              holdout_by_action: Any = None) -> Dict[str, Any]:
    """Out-of-sample check of the learned ranking.

    Each context's best action is picked on the fit buckets, then scored on the held-out buckets
    against the REST of its context (the context minus that action). Picking and scoring on the
    same rows is vacuous: the best of several n-weighted means always beats their pool. train()
    passes alternate careers as the holdout; without one the fit buckets are reused (in-sample).
    """
    holdout_by_context = training_by_context if holdout_by_context is None else holdout_by_context
    holdout_by_action = training_by_action if holdout_by_action is None else holdout_by_action
    evaluated = 0
    positive = 0
    improvement_sum = 0.0
    for context_key, context in training_by_context.items():
        if _safe_int(context.get("n")) < 5:
            continue
        candidates = [
            key for key, row in training_by_action.items()
            if key.startswith(context_key + ":") and _safe_int(row.get("n")) >= 5
        ]
        if not candidates:
            continue
        best_key = max(candidates, key=lambda key: _training_policy_score(training_by_action[key]))
        held_context = holdout_by_context.get(context_key) or {}
        held_best = holdout_by_action.get(best_key) or {}
        best_n = _safe_int(held_best.get("n"))
        rest_n = _safe_int(held_context.get("n")) - best_n
        if best_n < 5 or rest_n <= 0:
            continue
        # The score is linear in the bucket means, so the rest's score falls out of the sums.
        rest_score = (_training_policy_score(held_context) * (best_n + rest_n)
                      - _training_policy_score(held_best) * best_n) / rest_n
        improvement = _training_policy_score(held_best) - rest_score
        evaluated += 1
        improvement_sum += improvement
        if improvement > 0:
            positive += 1
    return {
        "evaluated_contexts": evaluated,
        "positive_contexts": positive,
        "positive_rate": round(positive / evaluated, 4) if evaluated else 0.0,
        "avg_improvement": round(improvement_sum / evaluated, 4) if evaluated else 0.0,
        # A real out-of-sample pick beats the rest about half the time by chance alone.
        "validated": bool(evaluated and positive / evaluated > 0.5),
    }


def log_training_outcome(base_dir: Any, before_state: Any, after_state: Any,
                         command: Any, scenario_id: Any = 0) -> None:
    """Record one accepted training command for contextual policy learning.

    This is deliberately telemetry-only: malformed or incomplete responses are ignored, and no
    learned value is applied until ``train()`` has enough samples to build a model.
    """
    try:
        before_data = (before_state or {}).get("data") or {}
        after_data = (after_state or {}).get("data") or {}
        before = before_data.get("chara_info") or {}
        after = after_data.get("chara_info") or {}
        if not before or not after:
            return
        command = command or {}
        command_type = int(command.get("command_type") or 0)
        if command_type != 1:
            return
        command_id = int(command.get("command_id") or 0)
        # `command` is the exec_command payload (request args only). The chosen facility's partners
        # and failure rate live on the board the decision was made from, as training_brain reads it.
        board = next((
            row for row in ((before_data.get("home_info") or {}).get("command_info_array") or [])
            if isinstance(row, dict) and _safe_int(row.get("command_type")) == 1
            and _safe_int(row.get("command_id")) == command_id
        ), {})
        # Lazy import: training_brain imports this module at load time.
        from career_bot.core.training_brain import DECK_PARTNERS
        evaluation = {
            row.get("target_id"): int(row.get("evaluation") or 0)
            for row in (before.get("evaluation_info_array") or [])
            if isinstance(row, dict)
        }
        partners = board.get("training_partner_array") or []
        rainbow_count = sum(1 for partner_id in partners
                            if partner_id in DECK_PARTNERS and evaluation.get(partner_id, 0) >= 80)
        stat_keys = ("speed", "stamina", "power", "guts", "wiz", "intelligence")
        before_total = sum(int(before.get(key) or 0) for key in stat_keys)
        after_total = sum(int(after.get(key) or 0) for key in stat_keys)
        stat_gain = max(0, after_total - before_total)
        before_turn = int(before.get("turn") or 0)
        after_turn = int(after.get("turn") or 0)
        # command_result.result_state: 1 = the training failed, 2 = it succeeded (captured
        # exec_command responses). The turn usually advances only after events drain, so it is no
        # success signal. Without the flag, a failed training shows no stat gain.
        result = after_data.get("command_result")
        result_state = _safe_int(result.get("result_state")) if isinstance(result, dict) else 0
        success = result_state == 2 if result_state in (1, 2) else stat_gain > 0
        log_experience(base_dir, {
            "type": "training",
            "scenario_id": int(scenario_id or 0),
            "phase": _training_phase(before_turn),
            "turn": before_turn,
            "command_id": command_id,
            "stat_gain": stat_gain,
            "vital_delta": int(after.get("vital") or 0) - int(before.get("vital") or 0),
            "skill_point_delta": int(after.get("skill_point") or 0) - int(before.get("skill_point") or 0),
            "turn_advanced": after_turn > before_turn,
            "success": success,
            # Presence of this key marks a board-aware row; train() treats rows without it as legacy.
            "result_state": result_state,
            "vitality_before": int(before.get("vital") or 0),
            "vitality_after": int(after.get("vital") or 0),
            "vitality_bucket": _training_vitality_bucket(before.get("vital")),
            "failure_rate": _safe_float(board.get("failure_rate")),
            "partner_count": len(partners),
            "rainbow_count": rainbow_count,
        })
        _maybe_refresh_training_model(base_dir)
    except Exception:
        return


def _maybe_refresh_training_model(base_dir: Any) -> None:
    """Rebuild the learned model after a bounded number of new training samples."""
    try:
        threshold = max(5, _safe_int(os.environ.get("SWEEPY_AI_REFRESH_EVERY") or 20))
        key = str(_models_path(base_dir).resolve())
        state = _AUTO_REFRESH_STATE.setdefault(key, {"pending": 0, "refreshing": False})
        state["pending"] += 1
        if state["pending"] < threshold or state["refreshing"]:
            return
        state["pending"] = 0
        state["refreshing"] = True
        try:
            train(base_dir)
        except Exception:
            state["pending"] = threshold - 1
        finally:
            state["refreshing"] = False
    except Exception:
        return


def train(base_dir: Any) -> Dict[str, Any]:
    """Aggregate experience.jsonl into models.json. Returns a short summary.

    - ``type=="race"`` rows are aggregated by program_id into
      {n, wins, win_rate}.
    - ``type=="career"`` rows are aggregated into
      {n, finished, avg_rank, avg_fans, by_preset}.

    Never raises; on failure returns a summary with an ``error`` key.
    """
    try:
        rows = _read_jsonl(_experience_path(base_dir))

        races: Dict[str, Dict[str, Any]] = {}
        # Per-stat "lacking" signal: how outclassed the bot was, per stat, in races it LOST.
        # popularity_mark_rank_array is the player's rank among the field for [speed,stamina,
        # power] (1 = best in the field, higher = the field beats us in that stat). On a loss,
        # a stat ranked >=2 contributes (rank-1) -- the more outclassed, the more we should
        # train it up next career. Aggregated here so race_mark_emphasis() can read it back.
        stat_lack: Dict[str, float] = {"speed": 0.0, "stamina": 0.0, "power": 0.0}
        stat_lack_losses = 0
        career_n = 0
        career_finished = 0
        rank_sum = 0.0
        rank_count = 0
        fans_sum = 0.0
        fans_count = 0
        by_preset: Dict[str, Dict[str, Any]] = {}
        training_by_context: Dict[str, Dict[str, Any]] = {}
        training_by_action: Dict[str, Dict[str, Any]] = {}
        training_by_condition: Dict[str, Dict[str, Any]] = {}
        # Validation-only copies split by career: even careers fit, odd careers are held out.
        split_by_context: list = [{}, {}]
        split_by_action: list = [{}, {}]

        def training_targets(row: Dict[str, Any], split: int) -> list:
            scenario = _safe_int(row.get("scenario_id"))
            phase = str(row.get("phase") or _training_phase(row.get("turn")))
            context_key = f"{scenario}:{phase}"
            action_key = f"{context_key}:{_safe_int(row.get('command_id'))}"
            targets = [(context_key, training_by_context), (action_key, training_by_action),
                       (context_key, split_by_context[split]), (action_key, split_by_action[split])]
            # Legacy rows logged rainbow_count=0 for every board, so they say nothing per condition.
            if "result_state" in row:
                targets.append((_training_condition_key(
                    scenario,
                    phase,
                    row.get("vitality_bucket") or _training_vitality_bucket(row.get("vitality_before")),
                    row.get("rainbow_count"),
                    row.get("command_id"),
                ), training_by_condition))
            return targets

        for row in rows:
            rtype = str(row.get("type") or "")
            if rtype == "race":
                pid = str(_safe_int(row.get("program_id")))
                bucket = races.setdefault(pid, {"n": 0, "wins": 0, "win_rate": 0.0})
                bucket["n"] += 1
                won = bool(row.get("won")) or _safe_int(row.get("rank")) == 1
                if won:
                    bucket["wins"] += 1
                else:
                    marks = row.get("stat_marks")
                    if isinstance(marks, list) and len(marks) >= 3:
                        stat_lack_losses += 1
                        for i, stat in enumerate(STAT_MARK_ORDER):
                            v = _safe_int(marks[i])
                            if v >= 2:  # not rank-1 in the field for this stat -> outclassed
                                stat_lack[stat] += float(v - 1)
            elif rtype == "training":
                # Legacy rows stored "turn advanced" as success; a gain is the closest real signal.
                success = (bool(row.get("success")) if "result_state" in row
                           else _safe_float(row.get("stat_gain")) > 0)
                for key, bucket_map in training_targets(row, career_n % 2):
                    bucket = bucket_map.setdefault(key, {
                        "n": 0, "successes": 0, "_gain_sum": 0.0,
                        "_vital_delta_sum": 0.0, "_skill_point_delta_sum": 0.0,
                        "_vitality_sum": 0.0, "_failure_rate_sum": 0.0,
                        "_partner_sum": 0.0, "_rainbow_sum": 0.0,
                        "_career_reward_sum": 0.0,
                    })
                    bucket["n"] += 1
                    bucket["successes"] += int(success)
                    bucket["_gain_sum"] += _safe_float(row.get("stat_gain"))
                    bucket["_vital_delta_sum"] += _safe_float(row.get("vital_delta"))
                    bucket["_skill_point_delta_sum"] += _safe_float(row.get("skill_point_delta"))
                    bucket["_vitality_sum"] += _safe_float(row.get("vitality_before"))
                    bucket["_failure_rate_sum"] += _safe_float(row.get("failure_rate"))
                    bucket["_partner_sum"] += _safe_float(row.get("partner_count"))
                    bucket["_rainbow_sum"] += _safe_float(row.get("rainbow_count"))
            elif rtype == "career":
                career_n += 1
                status = str(row.get("status") or "")
                is_finished = status == "finished"
                if is_finished:
                    career_finished += 1
                rank = _safe_int(row.get("rank"))
                if rank > 0:
                    rank_sum += rank
                    rank_count += 1
                fans = _safe_int(row.get("fans"))
                if fans > 0:
                    fans_sum += fans
                    fans_count += 1
                preset = str(row.get("preset") or "unknown") or "unknown"
                pb = by_preset.setdefault(preset, {"n": 0, "finished": 0, "fans_sum": 0.0, "fans_count": 0})
                pb["n"] += 1
                if is_finished:
                    pb["finished"] += 1
                if fans > 0:
                    pb["fans_sum"] += fans
                    pb["fans_count"] += 1

        # Assign each completed career's bounded outcome reward to the training rows since the
        # previous career result. This works with existing logs and does not require changing the
        # network payload or exposing account identifiers.
        pending_training = []
        career_index = 0   # mirrors career_n in the first pass, so each row hits the same split
        for row in rows:
            rtype = str(row.get("type") or "")
            if rtype == "training":
                pending_training.append(row)
                continue
            if rtype != "career":
                continue
            rank = _safe_int(row.get("rank"))
            rank_reward = 1.0 / max(1, rank) if rank > 0 else 0.0
            career_reward = (0.60 if str(row.get("status") or "") == "finished" else 0.0) + 0.40 * rank_reward
            for training_row in pending_training:
                for key, bucket_map in training_targets(training_row, career_index % 2):
                    bucket = bucket_map.get(key)
                    if bucket is not None:
                        bucket["_career_reward_sum"] += career_reward
            pending_training = []
            career_index += 1

        for bucket in races.values():
            n = bucket["n"]
            bucket["win_rate"] = round(bucket["wins"] / n, 4) if n else 0.0

        preset_out: Dict[str, Any] = {}
        for preset, pb in by_preset.items():
            n = pb["n"]
            fc = pb["fans_count"]
            preset_out[preset] = {
                "n": n,
                "finished": pb["finished"],
                "finish_rate": round(pb["finished"] / n, 4) if n else 0.0,
                "avg_fans": round(pb["fans_sum"] / fc, 2) if fc else 0.0,
            }

        careers = {
            "n": career_n,
            "finished": career_finished,
            "avg_rank": round(rank_sum / rank_count, 3) if rank_count else 0.0,
            "avg_fans": round(fans_sum / fans_count, 2) if fans_count else 0.0,
            "by_preset": preset_out,
        }

        for bucket in (list(training_by_context.values()) + list(training_by_action.values())
                       + list(training_by_condition.values())
                       + [b for split in split_by_context + split_by_action for b in split.values()]):
            n = int(bucket.get("n") or 0)
            bucket["avg_gain"] = round(bucket.pop("_gain_sum", 0.0) / n, 4) if n else 0.0
            bucket["avg_vital_delta"] = round(bucket.pop("_vital_delta_sum", 0.0) / n, 4) if n else 0.0
            bucket["avg_skill_point_delta"] = round(bucket.pop("_skill_point_delta_sum", 0.0) / n, 4) if n else 0.0
            bucket["avg_vitality"] = round(bucket.pop("_vitality_sum", 0.0) / n, 4) if n else 0.0
            bucket["avg_failure_rate"] = round(bucket.pop("_failure_rate_sum", 0.0) / n, 4) if n else 0.0
            bucket["avg_partner_count"] = round(bucket.pop("_partner_sum", 0.0) / n, 4) if n else 0.0
            bucket["avg_rainbow_count"] = round(bucket.pop("_rainbow_sum", 0.0) / n, 4) if n else 0.0
            bucket["avg_career_reward"] = round(bucket.pop("_career_reward_sum", 0.0) / n, 4) if n else 0.0
            bucket["success_rate"] = round(bucket.get("successes", 0) / n, 4) if n else 0.0

        models = {
            "races": races,
            "careers": careers,
            "training": {
                "by_context": training_by_context,
                "by_action": training_by_action,
                "by_condition": training_by_condition,
                "validation": _validate_training_policy(split_by_context[0], split_by_action[0],
                                                        split_by_context[1], split_by_action[1]),
            },
            "stat_lack": {**stat_lack, "_losses": stat_lack_losses},
            "trained_at": time.time(),
        }
        _atomic_write_json(_models_path(base_dir), models)

        return {
            "trained": True,
            "records": len(rows),
            "programs_learned": len(races),
            "careers": career_n,
            "trained_at": models["trained_at"],
        }
    except Exception as exc:
        return {"trained": False, "error": str(exc)}


def training_policy_adjustment(base_dir: Any, command_id: Any, scenario_id: Any, turn: Any,
                               vitality: Any = 0, failure_rate: Any = 0,
                               rainbow_count: Any = 0) -> Dict[str, Any]:
    """Return a small confidence-gated adjustment for one training command.

    The action is compared with other training actions in the same scenario and career phase. With
    fewer than five contextual samples the result is neutral, so a new account starts entirely on
    the deterministic scorer instead of guessing from sparse data.
    """
    neutral = {"adjustment": 0.0, "confidence": 0.0, "samples": 0}
    try:
        models = _load_models_cached(base_dir)
        training = models.get("training") or {}
        by_context = training.get("by_context") or {}
        by_action = training.get("by_action") or {}
        by_condition = training.get("by_condition") or {}
        validation = training.get("validation") or {}
        context_key = f"{_safe_int(scenario_id)}:{_training_phase(turn)}"
        action_key = f"{context_key}:{_safe_int(command_id)}"
        context = by_context.get(context_key) or {}
        action = by_action.get(action_key) or {}
        condition_key = _training_condition_key(
            scenario_id,
            _training_phase(turn),
            _training_vitality_bucket(vitality),
            rainbow_count,
            command_id,
        )
        condition = by_condition.get(condition_key) or {}
        if _safe_int(condition.get("n")) >= 5:
            action = condition
        min_samples = max(5, _safe_int(os.environ.get("SWEEPY_AI_MIN_SAMPLES") or 5))
        samples = _safe_int(action.get("n"))
        if samples < min_samples or not context:
            return neutral
        if (_safe_int(validation.get("evaluated_contexts")) >= 3
                and not bool(validation.get("validated"))):
            return neutral
        confidence = min(1.0, samples / 25.0)
        gain_delta = _safe_float(action.get("avg_gain")) - _safe_float(context.get("avg_gain"))
        success_delta = _safe_float(action.get("success_rate")) - _safe_float(context.get("success_rate"))
        failure_delta = _safe_float(action.get("avg_failure_rate")) - _safe_float(context.get("avg_failure_rate"))
        career_delta = _safe_float(action.get("avg_career_reward")) - _safe_float(context.get("avg_career_reward"))
        adjustment = (
            gain_delta * TRAINING_GAIN_WEIGHT
            + success_delta * 0.50
            - max(0.0, failure_delta) * 0.01
            + career_delta * 0.40
        ) * confidence

        # Career outcomes calibrate how aggressively the learned signal is trusted. This is a
        # global quality gate until enough linked career/action records exist for per-career credit.
        careers = models.get("careers") or {}
        career_count = _safe_int(careers.get("n"))
        if career_count >= 5:
            finish_rate = max(0.0, min(1.0, _safe_float(careers.get("finished")) / career_count))
            adjustment *= 0.85 + 0.30 * finish_rate
        return {
            "adjustment": max(-TRAINING_ADJ_CLAMP, min(TRAINING_ADJ_CLAMP, adjustment)),
            "confidence": confidence,
            "samples": samples,
            "validated": bool(validation.get("validated", True)),
        }
    except Exception:
        return neutral


def race_policy_adjustment(base_dir: Any, program_id: Any) -> Dict[str, Any]:
    """Return the learned, confidence-gated signal for one race program.

    {"adjustment": max(0.0, win_rate - 0.5) * ADJ_SCALE, "confidence": min(1.0, n/MIN_SAMPLES)}
    Unknown / no-data programs return a neutral {"adjustment": 0.0, "confidence": 0.0}.
    Never raises.
    """
    neutral = {"adjustment": 0.0, "confidence": 0.0}
    try:
        models = _load_models_cached(base_dir)
        races = models.get("races") or {}
        if not isinstance(races, dict):
            return neutral
        bucket = races.get(str(_safe_int(program_id)))
        if not isinstance(bucket, dict):
            return neutral
        n = _safe_int(bucket.get("n"))
        if n <= 0:
            return neutral
        win_rate = _safe_float(bucket.get("win_rate"))
        # Clamp the adjustment to >= 0. This signal is ADDED to a scheduled race's value
        # in mant._race_value, so a negative value would lower a race's worth and could make
        # the bot SKIP a race it usually loses -- the exact opposite of what we want. With the
        # clamp the AI can still BOOST races it usually wins (positive nudge) but can never
        # penalize one, so it can never push the bot to avoid a scheduled race. "Learn to win"
        # (steering training toward the losers' stats) is handled by race_train_emphasis below.
        return {
            "adjustment": round(max(0.0, win_rate - 0.5) * ADJ_SCALE, 4),
            "confidence": round(min(1.0, n / float(MIN_SAMPLES)), 4),
        }
    except Exception:
        return neutral


def _load_race_map_program(base_dir: Any) -> Dict[str, Any]:
    """Load the ``program`` section of data/race_map.json -> {str(program_id): {...}}.

    Returns {} on any problem (missing file, corrupt JSON, wrong shape). Never raises.
    The repo root that holds ``data/`` is the same ``base_dir`` the planner is built from.
    """
    try:
        program = DataStore(base_dir).race_map().get("program")
        return {str(k): v for k, v in program.items()} if isinstance(program, dict) else {}
    except Exception:
        return {}


def player_stat_marks(race_start_response: Any) -> Any:
    """The PLAYER's [speed, stamina, power] rank marks for a race, from the race_start
    response's race_horse_data popularity_mark_rank_array (1 = best in the field for that
    stat, higher = more outclassed).

    The player's runner is the one whose viewer_id equals the SESSION viewer_id
    (res.data_headers.viewer_id) -- the exact way the runner identifies the player elsewhere
    (runner.py) -- so an NPC's marks are never taken (matching on owner_viewer_id is not safe:
    rental/inherited NPCs also carry an owner). Returns a 3-int list or None. Never raises."""
    try:
        res = race_start_response or {}
        viewer_id = _safe_int((res.get("data_headers") or {}).get("viewer_id"))
        if not viewer_id:
            return None
        info = (res.get("data") or {}).get("race_start_info") or {}
        for horse in info.get("race_horse_data") or []:
            if not isinstance(horse, dict):
                continue
            if _safe_int(horse.get("viewer_id")) == viewer_id:
                arr = horse.get("popularity_mark_rank_array")
                if isinstance(arr, list) and len(arr) >= 3:
                    return [_safe_int(arr[0]), _safe_int(arr[1]), _safe_int(arr[2])]
    except Exception:
        pass
    return None


def race_mark_emphasis(base_dir: Any) -> Dict[str, float]:
    """Per-stat training emphasis learned from the rank MARKS the game gives in races the bot
    LOST. A stat the bot ranks poorly in among the field (popularity_mark_rank_array >= 2 on a
    loss) is a stat to train up -- a far more direct signal than guessing from race distance.
    Reads the aggregate in models.json (stat_lack, built by train()). Returns a normalized
    {stat: weight} over speed/stamina/power summing to 1.0, or {} when there isn't enough data.
    Never raises."""
    try:
        models = _load_models(base_dir)
        lack = models.get("stat_lack") or {}
        if _safe_int(lack.get("_losses")) < MARK_LACK_MIN_LOSSES:
            return {}
        weights = {s: max(0.0, _safe_float(lack.get(s))) for s in STAT_MARK_ORDER}
        total = sum(weights.values())
        if total <= 0:
            return {}
        return {s: round(w / total, 4) for s, w in weights.items() if w > 0}
    except Exception:
        return {}


def race_train_emphasis(base_dir: Any) -> Dict[str, float]:
    """"Learn to win": which training stats the bot's CONFIDENT losing races reward.

    Reads models.json (learned per-program win rates) and data/race_map.json (each
    program's distance). For every confident loser -- a race with n >= MIN_SAMPLES and
    win_rate < 0.5 -- map its distance to the stat(s) that race-type rewards and add a
    weight proportional to its loss severity (how far below 0.5 it sits). The scorer can
    then nudge training toward those stats so the bot trains to WIN the races it loses,
    instead of avoiding them.

    Returns a normalized {stat: weight} dict over lowercase stat keys
    (speed/stamina/power/guts/wit) summing to 1.0, or {} when there is no data.
    Never raises.
    """
    try:
        models = _load_models(base_dir)
        races = models.get("races") or {}
        if not isinstance(races, dict) or not races:
            return {}
        program = _load_race_map_program(base_dir)

        weights: Dict[str, float] = {
            "speed": 0.0, "stamina": 0.0, "power": 0.0, "guts": 0.0, "wit": 0.0,
        }
        for pid, bucket in races.items():
            if not isinstance(bucket, dict):
                continue
            n = _safe_int(bucket.get("n"))
            if n < MIN_SAMPLES:
                continue
            win_rate = _safe_float(bucket.get("win_rate"))
            if win_rate >= 0.5:
                continue
            severity = 0.5 - win_rate  # how far below 0.5 -> how badly we lose this race
            info = program.get(str(pid)) or program.get(str(_safe_int(pid))) or {}
            distance = _safe_int(info.get("distance"), 1600) if isinstance(info, dict) else 1600
            # Distance -> the stat(s) that race rewards. EVERY band keeps a stamina share so the
            # "learn to win" signal can never train AWAY from stamina: a stamina-light build that
            # loses miles loses them partly BECAUSE it runs out, and the old mile/sprint mappings
            # had ZERO stamina -- so the bonus deepened the very deficit it was meant to fix (it
            # reinforced a speed/power build that keeps losing 1600m races). Split per-race
            # severity across the rewarded stats. The DIRECT per-stat signal (race_mark_emphasis,
            # from the game's rank marks) is the authoritative correction; this stays as a coarse
            # distance prior.
            if distance <= 1400:        # sprint
                contrib = {"speed": 0.55, "power": 0.3, "stamina": 0.15}
            elif distance <= 1800:      # mile
                contrib = {"speed": 0.4, "stamina": 0.3, "power": 0.3}
            elif distance <= 2400:      # medium
                contrib = {"speed": 0.4, "stamina": 0.5, "power": 0.1}
            else:                       # long
                contrib = {"stamina": 0.6, "power": 0.3, "speed": 0.1}
            for stat, share in contrib.items():
                weights[stat] += severity * share

        total = sum(weights.values())
        if total <= 0:
            return {}
        return {stat: round(w / total, 4) for stat, w in weights.items() if w > 0}
    except Exception:
        return {}


def status(base_dir: Any) -> Dict[str, Any]:
    """Return a compact status snapshot of the learning subsystem. Never raises."""
    try:
        exp_path = _experience_path(base_dir)
        models_path = _models_path(base_dir)
        records = 0
        try:
            if exp_path.exists():
                with exp_path.open("r", encoding="utf-8") as fh:
                    records = sum(1 for line in fh if line.strip())
        except Exception:
            records = -1
        models = _load_models(base_dir)
        races = models.get("races") or {}
        careers = models.get("careers") or {}
        return {
            "records": records,
            "programs_learned": len(races) if isinstance(races, dict) else 0,
            "careers": _safe_int(careers.get("n")) if isinstance(careers, dict) else 0,
            "last_trained": models.get("trained_at"),
            "model_exists": models_path.exists(),
        }
    except Exception as exc:
        return {
            "records": 0,
            "programs_learned": 0,
            "careers": 0,
            "last_trained": None,
            "model_exists": False,
            "error": str(exc),
        }


def reset(base_dir: Any) -> Dict[str, Any]:
    """RETRAIN-ONLY erase: delete models.json but KEEP experience.jsonl, then
    rebuild the model from the kept experience. Returns the new status."""
    try:
        models_path = _models_path(base_dir)
        try:
            if models_path.exists():
                models_path.unlink()
        except Exception:
            pass
        train(base_dir)
    except Exception:
        pass
    return status(base_dir)


# --- owner-only encrypted brain (closed source) -------------------------------
#
# The exported brain is sealed with AES-256-GCM under a key derived from the
# OWNER's password (PBKDF2-HMAC-SHA256, 200k iterations + a random salt). Without
# the password the file is opaque ciphertext that cannot be read OR imported, so a
# copied/leaked brain is useless to anyone but the owner. GCM also makes the file
# tamper-evident -- any edit fails the integrity check on import.

_BRAIN_MAGIC = b"SWEEPYAIBRAIN1\n"
_PBKDF2_ITERS = 200_000


def _derive_key(password: Any, salt: bytes) -> bytes:
    from Crypto.Protocol.KDF import PBKDF2
    from Crypto.Hash import SHA256
    return PBKDF2(str(password or "").encode("utf-8"), salt, dkLen=32,
                  count=_PBKDF2_ITERS, hmac_hash_module=SHA256)


def _encrypt_brain(plaintext: bytes, password: Any) -> bytes:
    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes
    salt = get_random_bytes(16)
    nonce = get_random_bytes(12)
    key = _derive_key(password, salt)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    return _BRAIN_MAGIC + salt + nonce + tag + ciphertext


def _decrypt_brain(blob: bytes, password: Any) -> bytes:
    """Return the decrypted zip bytes, or raise ValueError on a wrong password or a
    tampered file (the GCM integrity check fails)."""
    from Crypto.Cipher import AES
    if not blob.startswith(_BRAIN_MAGIC):
        raise ValueError("not an encrypted MQA brain file")
    body = blob[len(_BRAIN_MAGIC):]
    salt, nonce, tag, ciphertext = body[:16], body[16:28], body[28:44], body[44:]
    cipher = AES.new(_derive_key(password, salt), AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)


def export_brain(base_dir: Any, password: Any) -> str:
    """Seal the AI brain (experience.jsonl + models.json) into an OWNER-ONLY
    encrypted file ``uma_runtime/ai_backups/ai-brain-<timestamp>.aibrain``.

    Requires the owner's password; the output is AES-256-GCM ciphertext that only
    the same password can open or import. Returns the path, or "" on failure
    (including an empty password) -- never raises."""
    try:
        if not str(password or "").strip():
            return ""
        from career_bot.runner import runtime_output_root
        ai_dir = _ai_dir(base_dir)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in _ALLOWED_BRAIN_FILES:
                src = ai_dir / name
                if src.exists():
                    zf.write(str(src), arcname=name)
        sealed = _encrypt_brain(buf.getvalue(), password)
        backups = runtime_output_root(base_dir) / "ai_backups"
        backups.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        target = backups / f"ai-brain-{stamp}.aibrain"
        target.write_bytes(sealed)
        return str(target)
    except Exception:
        return ""


def import_brain(base_dir: Any, source_path: Any, password: Any = "") -> Dict[str, Any]:
    """Load a brain file into the AI directory, then retrain. Encrypted ``.aibrain``
    files require the owner's password (a wrong password or a tampered file is
    rejected); a plain zip (legacy/unencrypted) is accepted directly. Validates that
    the payload contains only the expected files. Returns the new status. Never raises."""
    try:
        src = Path(str(source_path)).expanduser()
        if not src.exists():
            return {**status(base_dir), "imported": False, "error": "missing file"}
        raw = src.read_bytes()
        if raw.startswith(_BRAIN_MAGIC):
            if not str(password or "").strip():
                return {**status(base_dir), "imported": False,
                        "error": "owner password required to open this encrypted brain"}
            try:
                zip_bytes = _decrypt_brain(raw, password)
            except Exception:
                return {**status(base_dir), "imported": False,
                        "error": "wrong owner password or corrupted/tampered brain"}
        else:
            zip_bytes = raw  # legacy unencrypted zip
        buf = io.BytesIO(zip_bytes)
        if not zipfile.is_zipfile(buf):
            return {**status(base_dir), "imported": False, "error": "invalid brain payload"}
        ai_dir = _ai_dir(base_dir)
        ai_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(buf, "r") as zf:
            members = [info for info in zf.infolist() if not info.is_dir()]
            # Validate: only expected files, no path traversal.
            for info in members:
                name = Path(info.filename).name
                if name not in _ALLOWED_BRAIN_FILES or info.filename != name:
                    return {**status(base_dir), "imported": False,
                            "error": f"unexpected entry: {info.filename}"}
            for info in members:
                name = Path(info.filename).name
                (ai_dir / name).write_bytes(zf.read(info))
        train(base_dir)
        return {**status(base_dir), "imported": True}
    except Exception as exc:
        return {**status(base_dir), "imported": False, "error": str(exc)}
