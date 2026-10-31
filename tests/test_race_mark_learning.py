"""Unit tests for the per-stat 'learn from losses' signal.

The game gives each race a per-stat rank of our uma among the field
(popularity_mark_rank_array = [speed, stamina, power], 1 = best, higher = outclassed).
On a LOST race, a stat we rank poorly in is a stat to train up next career. These assert:
  - player_stat_marks() pulls OUR marks (the only runner with a non-zero owner_viewer_id);
  - train() aggregates losing-race marks into stat_lack;
  - race_mark_emphasis() turns that into a normalized per-stat emphasis (wins ignored,
    min-losses gated);
  - MantStrategy._train_to_win_emphasis merges it with the distance signal.

Each data test runs in an ISOLATED brain dir via the UMA_RUNTIME_DIR override (which
ai_learn's runtime_output_root honors first) so tests never touch the real uma_runtime/ai
and never leak into each other.

Run:
    python tests/test_race_mark_learning.py
    python -m pytest tests/test_race_mark_learning.py
"""
import contextlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core import ai_learn  # noqa: E402


_SESSION_VID = 100000000001


def _race_start(runners, viewer_id=_SESSION_VID):
    return {"data_headers": {"viewer_id": viewer_id},
            "data": {"race_start_info": {"race_horse_data": runners}}}


def _horse(vid, marks, owner=None):
    return {"viewer_id": vid, "owner_viewer_id": (owner if owner is not None else vid),
            "popularity_mark_rank_array": marks}


@contextlib.contextmanager
def _brain():
    """Isolated, throwaway AI brain dir for one test (restores UMA_RUNTIME_DIR after)."""
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


def _log_losses(base, n, marks, rank=3):
    for _ in range(n):
        ai_learn.log_experience(base, {"type": "race", "program_id": 1001, "rank": rank,
                                       "won": False, "stat_marks": list(marks)})


# ---------------- player_stat_marks ----------------

def test_player_stat_marks_extracts_player_not_npc():
    res = _race_start([
        _horse(0, [3, 5, 7]),               # NPC (viewer_id 0)
        _horse(_SESSION_VID, [2, 1, 1]),    # player (viewer_id == session)
    ])
    assert ai_learn.player_stat_marks(res) == [2, 1, 1]


def test_player_stat_marks_ignores_leading_npc_with_nonzero_viewer_id():
    # Adversarial: a rental/rival NPC with a non-zero viewer_id (and owner) appears BEFORE the
    # player. Matching on viewer_id == session must still pick the player's marks, not the NPC's.
    res = _race_start([
        _horse(555555555, [1, 1, 1], owner=555555555),   # NPC with non-zero viewer_id + owner
        _horse(_SESSION_VID, [8, 8, 8]),                 # player
    ])
    assert ai_learn.player_stat_marks(res) == [8, 8, 8]


def test_player_stat_marks_none_when_no_session_match():
    res = _race_start([_horse(111, [1, 2, 3]), _horse(222, [4, 5, 6])])  # neither is the session
    assert ai_learn.player_stat_marks(res) is None


def test_player_stat_marks_malformed_is_safe():
    assert ai_learn.player_stat_marks(None) is None
    assert ai_learn.player_stat_marks({}) is None
    assert ai_learn.player_stat_marks({"data_headers": {"viewer_id": _SESSION_VID},
                                       "data": {"race_start_info": {"race_horse_data": "garbage"}}}) is None
    assert ai_learn.player_stat_marks(_race_start([_horse(_SESSION_VID, [1])])) is None  # short array
    assert ai_learn.player_stat_marks(_race_start([_horse(_SESSION_VID, [1, 2, 3])], viewer_id=0)) is None  # no session id


# ---------------- race_mark_emphasis (via train) ----------------

def test_emphasis_favors_the_outclassed_stat():
    with _brain() as d:
        _log_losses(d, 4, [5, 1, 1])   # speed badly outclassed; stamina/power best in field
        ai_learn.train(d)
        emph = ai_learn.race_mark_emphasis(d)
    assert emph.get("speed", 0) > 0
    assert "stamina" not in emph and "power" not in emph   # only the weak stat is emphasized


def test_emphasis_weights_by_severity():
    with _brain() as d:
        _log_losses(d, 4, [5, 1, 2])   # speed rank 5 (very) vs power rank 2 (slight)
        ai_learn.train(d)
        emph = ai_learn.race_mark_emphasis(d)
    assert emph.get("speed", 0) > emph.get("power", 0) > 0
    assert "stamina" not in emph


def test_wins_do_not_contribute():
    with _brain() as d:
        for _ in range(5):
            ai_learn.log_experience(d, {"type": "race", "program_id": 1001, "rank": 1,
                                        "won": True, "stat_marks": [7, 1, 1]})  # won despite weak speed
        ai_learn.train(d)
        emph = ai_learn.race_mark_emphasis(d)
    assert emph == {}


def test_min_losses_gate():
    with _brain() as d:
        _log_losses(d, 2, [5, 1, 1])   # below MARK_LACK_MIN_LOSSES (3)
        ai_learn.train(d)
        emph = ai_learn.race_mark_emphasis(d)
    assert emph == {}


def test_no_data_returns_empty():
    with _brain() as d:
        assert ai_learn.race_mark_emphasis(d) == {}


# ---------------- merge in the scorer ----------------

def test_train_to_win_emphasis_merges_both_signals():
    from career_bot.scenarios.mant import MantStrategy
    s = MantStrategy()

    class _FakeRP:
        base_dir = "."
    s.race_planner = _FakeRP()
    # distance signal (weight 1x) says speed; the DIRECT mark signal (weight 2x) says stamina,
    # so the merge is 1:2 -> speed 1/3, stamina 2/3 (the more-accurate mark signal dominates).
    orig_a, orig_b = ai_learn.race_train_emphasis, ai_learn.race_mark_emphasis
    ai_learn.race_train_emphasis = lambda b: {"speed": 1.0}
    ai_learn.race_mark_emphasis = lambda b: {"stamina": 1.0}
    try:
        emph = s._train_to_win_emphasis({})
    finally:
        ai_learn.race_train_emphasis, ai_learn.race_mark_emphasis = orig_a, orig_b
    assert abs(emph.get("speed", 0) - 1 / 3) < 1e-3
    assert abs(emph.get("stamina", 0) - 2 / 3) < 1e-3


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
