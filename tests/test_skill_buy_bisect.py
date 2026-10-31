"""End-of-career skill buy: bisect on 205 instead of losing the whole SP bank.

The finale skill dump is ONE atomic gain_skills call. Measured across real careers, ~25% ended
with the ENTIRE ~1,300 SP bank unspent because a single unsellable skill 205'd the batch and the
whole purchase was abandoned (~1,900 rank score each time). _buy_batch now splits a refused batch
in half and recurses to single skills, so the sellable skills land and only the refused one is lost.

Sub-batches use retry_205=0: a 205 here is a deterministic refusal, not a transient fault, so the
SPLIT is the retry -- re-sending an identical payload only burns API calls.

Run:
    python tests/test_skill_buy_bisect.py
    python -m pytest tests/test_skill_buy_bisect.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.skills import SkillBuyer


SP_START = 2000
SP_COST = 100


class _Client:
    """gain_skills that refuses any payload containing a poisoned skill id, like the live 205.

    It also DEDUCTS the spend and returns the remaining skill_point, exactly as the real endpoint
    does -- that matters: after a partial buy, _buy_batch re-runs preflight for the next half against
    the merged state, so an unrealistic mock (e.g. always returning 0 SP) would make the second half
    look unaffordable and silently skip it.
    """

    def __init__(self, poison=(), points=SP_START, cost=SP_COST):
        self.poison = set(poison)
        self.calls = []                      # payload id-lists, in order
        self.points = points
        self.cost = cost

    def gain_skills(self, payload, turn, retry_205=3):
        ids = [int(p["skill_id"]) for p in payload]
        self.calls.append(ids)
        bad = self.poison & set(ids)
        if bad:
            raise Exception(f"API error 205 on single_mode_free/gain_skills: unsellable {sorted(bad)}")
        self.points = max(0, self.points - self.cost * len(ids))
        return {"data": {"chara_info": {"turn": turn, "skill_point": self.points}}}


def _buyer():
    b = SkillBuyer.__new__(SkillBuyer)        # method-only; skip __init__ (no data files needed)
    b.bought_this_career = set()
    b.attempt_events = []
    b.recover_after_error = False
    b.last_result = {}
    b.last_attempt = []
    b._turn_failed = {}
    b.group_to_skill_ids = {}
    b.skill_to_group_id = {}
    return b


def _state(points=SP_START, tips=(), turn=78):
    return {"data": {"chara_info": {
        "turn": turn, "skill_point": points,
        "skill_tips_array": [{"group_id": g} for g in tips],
        "skill_array": [],
    }}}


def _cands(ids, cost=SP_COST):
    return [{"skill_id": i, "cost": cost} for i in ids]


def _prep(buyer, ids):
    # every candidate must resolve as a valid tip, and nothing is owned
    buyer.group_to_skill_ids = {i: [i] for i in ids}
    buyer._owns_equal_or_better = lambda sid, owned: False
    buyer._failed_for_turn = lambda turn=None: buyer._turn_failed.setdefault(turn, set())


def test_clean_batch_buys_in_one_call():
    b = _buyer(); ids = [1, 2, 3, 4]; _prep(b, ids)
    c = _Client()
    _, bought = b._buy_batch(c, _state(tips=ids), _cands(ids), 78)
    assert bought == 4
    assert len(c.calls) == 1, c.calls


def test_one_poisoned_skill_no_longer_kills_the_whole_batch():
    # THE FIX: 1 bad skill out of 8 -> the other 7 still land (before: 0 bought, bank lost)
    b = _buyer(); ids = [1, 2, 3, 4, 5, 6, 7, 8]; _prep(b, ids)
    c = _Client(poison={5})
    _, bought = b._buy_batch(c, _state(tips=ids), _cands(ids), 78)
    assert bought == 7, (bought, c.calls)
    assert 5 not in b.bought_this_career
    assert b.bought_this_career == {1, 2, 3, 4, 6, 7, 8}


def test_bisection_is_call_bounded():
    b = _buyer(); ids = list(range(1, 9)); _prep(b, ids)
    c = _Client(poison={5})
    b._buy_batch(c, _state(tips=ids), _cands(ids), 78)
    # ~2N worst case; assert we are nowhere near a stampede that would trip the circuit breaker
    assert len(c.calls) <= 2 * len(ids), len(c.calls)


def test_depth_is_bounded():
    # every skill poisoned: recursion must stop at MAX_BISECT_DEPTH, not spin
    b = _buyer(); ids = list(range(1, 17)); _prep(b, ids)
    c = _Client(poison=set(ids))
    _, bought = b._buy_batch(c, _state(tips=ids), _cands(ids), 78)
    assert bought == 0
    assert len(c.calls) <= 2 ** (SkillBuyer.MAX_BISECT_DEPTH + 1), len(c.calls)


def test_single_skill_refusal_still_reports_failure():
    b = _buyer(); _prep(b, [9])
    c = _Client(poison={9})
    _, bought = b._buy_batch(c, _state(tips=[9]), _cands([9]), 78)
    assert bought == 0
    assert len(c.calls) == 1                      # nothing to split
    assert b.last_result.get("result") == "failed"


def test_non_205_errors_do_not_bisect():
    # a transient/network fault must NOT be split into N more calls
    class Boom(_Client):
        def gain_skills(self, payload, turn, retry_205=3):
            self.calls.append([int(p["skill_id"]) for p in payload])
            raise Exception("Network error: connection reset")

    b = _buyer(); ids = [1, 2, 3, 4]; _prep(b, ids)
    c = Boom()
    _, bought = b._buy_batch(c, _state(tips=ids), _cands(ids), 78)
    assert bought == 0
    assert len(c.calls) == 1, c.calls


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
