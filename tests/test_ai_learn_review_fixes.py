"""Unit tests for the learned training signal in ai_learn.

  - log_training_outcome reads partners / failure rate from the BOARD (the exec_command payload has
    neither), counts rainbows like training_brain (deck slots at bond >= 80), and takes success from
    command_result.result_state (1 = failed, 2 = succeeded), not from the turn advancing;
  - train() still accepts legacy rows and re-derives their success from the stat gain;
  - validation picks the best action on one set of careers and checks it on the others, so a
    ranking that flips between careers is no longer "validated";
  - the learned adjustment stays tie-breaker sized next to _score_command_base (~0.35 a training).

Each test runs in an isolated brain dir via UMA_RUNTIME_DIR.

Run:
    python tests/test_ai_learn_review_fixes.py
    python -m pytest tests/test_ai_learn_review_fixes.py
"""
import contextlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core import ai_learn  # noqa: E402


@contextlib.contextmanager
def _brain():
    prev = os.environ.get("UMA_RUNTIME_DIR")
    d = tempfile.mkdtemp()
    os.environ["UMA_RUNTIME_DIR"] = d
    try:
        yield d
    finally:
        if prev is None:
            os.environ.pop("UMA_RUNTIME_DIR", None)
        else:
            os.environ["UMA_RUNTIME_DIR"] = prev


def _rows():
    with open(os.path.join(os.environ["UMA_RUNTIME_DIR"], "ai", "experience.jsonl"), encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _chara(turn=30, speed=300, vital=70):
    return {"turn": turn, "vital": vital, "speed": speed, "stamina": 300, "power": 300,
            "guts": 300, "wiz": 300, "skill_point": 100,
            # slot 1 maxed (rainbow), slot 2 still bonding, NPC 105 maxed but never a rainbow
            "evaluation_info_array": [{"target_id": 1, "evaluation": 90},
                                      {"target_id": 2, "evaluation": 50},
                                      {"target_id": 105, "evaluation": 100}]}


def _before():
    board = [
        {"command_type": 1, "command_id": 106, "failure_rate": 0, "training_partner_array": [2]},
        {"command_type": 1, "command_id": 101, "failure_rate": 12, "training_partner_array": [1, 2, 105]},
    ]
    return {"data": {"chara_info": _chara(), "home_info": {"command_info_array": board}}}


def _after(speed=320, turn=30, result_state=2):
    data = {"chara_info": _chara(turn=turn, speed=speed, vital=50)}
    if result_state is not None:
        data["command_result"] = {"command_id": 101, "sub_id": 1, "result_state": result_state}
    return {"data": data}


# Exactly what runner passes: the exec_command arguments.
_PAYLOAD = {"command_type": 1, "command_id": 101, "command_group_id": 0, "select_id": 0,
            "current_turn": 30, "current_vital": 70}


def test_training_row_reads_chosen_command_from_board():
    with _brain() as base:
        ai_learn.log_training_outcome(base, _before(), _after(), _PAYLOAD, 4)
        row = _rows()[-1]
    assert row["partner_count"] == 3
    assert row["rainbow_count"] == 1          # slot 1 only: slot 2 < 80, NPC 105 is no deck partner
    assert row["failure_rate"] == 12.0
    assert row["success"] is True             # result_state 2, although the turn did not advance


def test_failed_training_is_logged_as_failure_even_when_turn_advances():
    with _brain() as base:
        ai_learn.log_training_outcome(base, _before(), _after(speed=300, turn=31, result_state=1),
                                      _PAYLOAD, 4)
        failed = _rows()[-1]
        # No command_result at all: the stat gain decides.
        ai_learn.log_training_outcome(base, _before(), _after(result_state=None), _PAYLOAD, 4)
        no_flag = _rows()[-1]
    assert failed["success"] is False
    assert no_flag["success"] is True


def test_train_rederives_success_for_legacy_rows():
    legacy = {"type": "training", "scenario_id": 4, "phase": "mid", "turn": 30, "command_id": 101,
              "stat_gain": 20, "turn_advanced": False, "success": False, "vitality_before": 70,
              "vitality_bucket": "high", "failure_rate": 0.0, "partner_count": 0, "rainbow_count": 0}
    with _brain() as base:
        for _ in range(6):
            ai_learn.log_experience(base, dict(legacy))
        summary = ai_learn.train(base)
        training = ai_learn._load_models(base)["training"]
    assert summary["trained"] is True
    assert training["by_action"]["4:mid:101"]["success_rate"] == 1.0
    # Legacy rows logged rainbow_count=0 for every board: no per-condition credit from them.
    assert training["by_condition"] == {}


def _career(base, gains, phases=("early", "mid", "late"), reps=13):
    turns = {"early": 10, "mid": 30, "late": 60}
    for phase in phases:
        for command_id, gain in gains.items():
            for _ in range(reps):
                ai_learn.log_experience(base, {
                    "type": "training", "scenario_id": 4, "phase": phase, "turn": turns[phase],
                    "command_id": command_id, "stat_gain": gain, "success": True, "result_state": 2,
                    "vitality_before": 70, "vitality_bucket": "high", "failure_rate": 0.0,
                    "partner_count": 0, "rainbow_count": 0,
                })
    ai_learn.log_experience(base, {"type": "career", "status": "finished", "rank": 1})


def test_ranking_that_flips_between_careers_is_not_validated():
    with _brain() as base:
        _career(base, {101: 50, 106: 10})   # fit career: Speed looks best
        _career(base, {101: 20, 106: 30})   # held-out career: it was noise, Wit wins
        ai_learn.train(base)
        validation = ai_learn._load_models(base)["training"]["validation"]
        adj = ai_learn.training_policy_adjustment(base, 101, 4, 30, vitality=70)
    assert validation["evaluated_contexts"] == 3
    assert validation["positive_contexts"] == 0
    assert validation["validated"] is False
    assert adj["adjustment"] == 0.0           # the gate blocks an unvalidated policy


def test_learned_adjustment_is_tie_breaker_sized():
    with _brain() as base:
        _career(base, {101: 40, 106: 10}, phases=("mid",))
        _career(base, {101: 40, 106: 10}, phases=("mid",))
        ai_learn.train(base)
        assert ai_learn._load_models(base)["training"]["validation"]["validated"] is True
        speed = ai_learn.training_policy_adjustment(base, 101, 4, 30, vitality=70)["adjustment"]
        wit = ai_learn.training_policy_adjustment(base, 106, 4, 30, vitality=70)["adjustment"]
    # +15 stat points over the context is worth ~0.15 to the base scorer; the learned term stays
    # below one rainbow (~0.12) instead of the old +/-1.5 that outvoted the whole scorer.
    assert 0 < speed <= 0.05
    assert -0.05 <= wit < 0


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {fn.__name__}: {exc}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
