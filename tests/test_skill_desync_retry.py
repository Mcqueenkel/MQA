"""Career-end skill buy must survive a SID desync. At the Unity finish the buy runs on the post-race
state whose SID is stale, so every gain_skills returns 205 and the skill_buyer sets recover_after_error.
The old _buy_skills reloaded the state (fresh SID) but never RETRIED -> the career ended with all SP
unspent / 0 skills. _buy_skills now reloads AND retries a force (career-end) buy so the purchase lands.

Run:
    python tests/test_skill_desync_retry.py
    python -m pytest tests/test_skill_desync_retry.py
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.runner import CareerRunner  # noqa: E402


class _Buyer:
    """Fake SkillBuyer: 205s (recover_after_error) for the first `fail_n` buys, then buys `n_bought`."""
    def __init__(self, fail_n, n_bought=5):
        self.fail_n = fail_n
        self.n_bought = n_bought
        self.calls = 0
        self.recover_after_error = False
        self.attempt_events = []

    def buy(self, client, state, preset, force):
        self.calls += 1
        if self.calls <= self.fail_n:
            self.recover_after_error = True          # desync: gain_skills 205'd
            return state, 0
        self.recover_after_error = False
        return state, self.n_bought


def _runner(buyer):
    r = CareerRunner.__new__(CareerRunner)           # bypass __init__; stub only what _buy_skills uses
    r.skill_buyer = buyer
    r.lock = threading.Lock()
    r.status = {"skills_bought": 0}
    r._debug = lambda *a, **k: None
    r._debug_turn = lambda *a, **k: None
    r._log = lambda *a, **k: None
    r._log_locked = lambda *a, **k: None
    r._sum_cost = lambda x: 0
    r._api_result = lambda x: x
    r._fresh_career_state = lambda client: {"data": {"chara_info": {"turn": 78}}}
    return r


_STATE = {"data": {"chara_info": {"turn": 78}}}


def test_force_buy_reloads_and_retries_after_desync():
    # first buy 205s, retry (on the reloaded fresh SID) succeeds -> skills actually bought
    b = _Buyer(fail_n=1, n_bought=5)
    r = _runner(b)
    r._buy_skills(None, _STATE, {}, force=True)
    assert b.calls == 2                    # retried once
    assert r.status["skills_bought"] == 5  # the retry's purchase counted


def test_force_buy_gives_up_after_bounded_retries():
    # a genuinely stuck desync must not loop forever: force caps at 3 attempts
    b = _Buyer(fail_n=99)
    r = _runner(b)
    r._buy_skills(None, _STATE, {}, force=True)
    assert b.calls == 3
    assert r.status["skills_bought"] == 0


def test_per_turn_buy_does_not_retry():
    # non-force (per-turn) buy attempts once and defers a 205 to the end-of-career dump
    b = _Buyer(fail_n=99)
    r = _runner(b)
    r._buy_skills(None, _STATE, {}, force=False)
    assert b.calls == 1


def test_clean_buy_does_not_reload():
    # no desync -> single attempt, skills counted
    b = _Buyer(fail_n=0, n_bought=7)
    r = _runner(b)
    r._buy_skills(None, _STATE, {}, force=True)
    assert b.calls == 1
    assert r.status["skills_bought"] == 7


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
    print("skill desync retry OK")
