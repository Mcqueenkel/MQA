"""URA get_choice_reward wiring + reward-choice validation.

get_choice_reward fires BEFORE check_event (URA only), and check_event's choice_number is snapped to
a VALID offered select_index -- a default like 1 that the reward event didn't offer is 205-looped by
the server (verified live: event 102001 offered [4,5,6], the bot sent 1 -> endless 205)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from career_bot.runner import CareerRunner


class FakeClient:
    def __init__(self, scenario, offered=None, boom=False):
        self.current_scenario_id = scenario
        self.calls = []                 # ordered (kind, event_id, choice)
        self.offered = offered or []    # [(select_index, gain), ...]
        self.boom = boom

    def get_choice_reward(self, event_id, current_turn=None, chara_id=0, choice_number=None):
        self.calls.append(("gcr", event_id, choice_number))
        if self.boom:
            raise RuntimeError("server 500")
        arr = [{"select_index": si, "gain_param_array": [{"effect_value_0": g}]} for si, g in self.offered]
        return {"data": {"choice_reward_array": arr}}

    def check_event(self, event_id, current_turn=None, chara_id=0, choice_number=0):
        self.calls.append(("check", event_id, choice_number))


def _runner():
    r = CareerRunner.__new__(CareerRunner)   # bypass heavy __init__; only exercise _event
    r._log = lambda *a, **k: None
    return r


def _drive(scenario, choice, offered=None, boom=False):
    r, c = _runner(), FakeClient(scenario, offered, boom)
    r._event(c, None, {"event_id": 102001, "chara_id": 0, "choice_number": choice, "current_turn": 13})
    return c.calls


def _rc(scenario, choice, offered, force):
    r, c = _runner(), FakeClient(scenario, offered)
    return r._reward_choice(c, 102001, 0, choice, 16, force=force)


def test_reward_choice():
    OFFERED = [(4, 10), (5, 30), (6, 5)]   # valid select_index values 4/5/6; best gain = 5

    # force=True (the multi-choice _event path): a chooser default of 0/None must STILL snap to a valid
    # offered index -- this is the resume crash (event 102001 offered [4,5,6], chooser sent 0 -> 205).
    assert _rc(1, 0, OFFERED, True) == 5, _rc(1, 0, OFFERED, True)
    assert _rc(1, None, OFFERED, True) == 5
    assert _rc(1, 5, OFFERED, True) == 5          # already-offered pick is honoured
    assert _rc(1, 2, [], True) == 2               # not a reward event (no offered) -> keep the pick
    # force=False: a 0/None choice is a no-choice event -> untouched, no get_choice_reward
    assert _rc(1, 0, OFFERED, False) == 0
    assert _rc(4, 0, OFFERED, True) == 0          # MANT gate holds even under force
    # URA + a choice the event offered -> gcr first, then check with that same valid choice
    assert _drive(1, 5, OFFERED) == [("gcr", 102001, 5), ("check", 102001, 5)], _drive(1, 5, OFFERED)
    # URA + a choice NOT offered (1, the old bug) -> snap to the best-gain offered index (5)
    assert _drive(1, 1, OFFERED) == [("gcr", 102001, 1), ("check", 102001, 5)], _drive(1, 1, OFFERED)
    # URA + no reward list returned -> keep the strategy's pick
    assert _drive(1, 2, []) == [("gcr", 102001, 2), ("check", 102001, 2)], _drive(1, 2, [])
    # URA + choice 0 (no-choice event) -> no gcr at all, check with 0
    assert _drive(1, 0, OFFERED) == [("check", 102001, 0)], _drive(1, 0, OFFERED)
    # MANT (scenario 4) -> never gcr, choice untouched (gate holds)
    assert _drive(4, 1, OFFERED) == [("check", 102001, 1)], _drive(4, 1, OFFERED)
    # gcr failure -> keep the pick, check still runs (a failed claim must never block the event)
    assert _drive(1, 3, OFFERED, boom=True) == [("gcr", 102001, 3), ("check", 102001, 3)], _drive(1, 3, OFFERED, True)
    print("ura reward-choice OK (gcr-first + valid-choice snap + gain-best + scenario/choice gates + failure-safe)")


if __name__ == "__main__":
    test_reward_choice()
