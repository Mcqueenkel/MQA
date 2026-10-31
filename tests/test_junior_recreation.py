"""One MANDATORY pre-debut recreation per career, all scenarios.

Turns 1..11 are before the turn-12 Make Debut race. The bot builds friendship (bond) via training,
but spends EXACTLY ONE of those turns on recreation -- because recreation raises motivation, and
motivation multiplies every later training's stat gain, so a mood boost banked early pays off across
the whole career. It picks a WEAK friendship turn (best facility has <= max_partners deck supports on
it -> little bond to gain, so mood is worth more), and forces it on the last pre-debut turn if no weak
turn came up. Covers BaseTrainingStrategy._junior_recreation (shared by mant/unity/ura).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.training_brain import BaseTrainingStrategy, DECK_PARTNERS  # noqa: E402

REC = {"command_type": 3, "command_id": 301, "is_enable": 1}   # the mood recreation command
# two real deck partner ids to place on facilities
P = sorted(DECK_PARTNERS)[:3]


def _strat():
    s = BaseTrainingStrategy(race_planner=None)
    return s


def _train(*partner_ids):
    # a training facility with the given partners sitting on it (all bond 0 -> all bondable)
    return {"command_type": 1, "command_id": 101, "is_enable": 1,
            "training_partner_array": list(partner_ids)}


def _chara(turn):
    # no evaluation_info_array -> every partner is bond 0 (< 80) -> bondable
    return {"turn": turn, "evaluation_info_array": []}


def test_fires_on_a_weak_friendship_turn():
    s = _strat()
    training = [_train(P[0]), _train()]         # best facility has 1 partner -> weak (<= 2)
    got = s._junior_recreation(REC, 4, training, _chara(4), {})
    assert got is REC
    # ... it does not auto-commit (the caller stores the TURN); simulate having fired on turn 4
    s._junior_recreated_turn = 4
    assert s._junior_recreation(REC, 5, training, _chara(5), {}) is None   # only ONCE (a LATER turn)


def test_same_turn_redecide_still_recreates():
    # REGRESSION: the runner re-decides once after handling items on a "command" turn. That same-turn
    # re-decide must return the SAME recreation, not fall through to training. The old boolean flag was
    # consumed by the first pass, so the re-decide trained instead (logged recreation, ran a speed train).
    s = _strat()
    training = [_train(P[0]), _train()]                                     # weak board -> recreate
    assert s._junior_recreation(REC, 4, training, _chara(4), {}) is REC     # first pass
    s._junior_recreated_turn = 4                                            # _best_command commits the turn
    assert s._junior_recreation(REC, 4, training, _chara(4), {}) is REC     # SAME-turn re-decide: still REC
    assert s._junior_recreation(REC, 5, training, _chara(5), {}) is None    # next turn: done for the career


def test_holds_training_on_a_strong_friendship_turn():
    s = _strat()
    training = [_train(P[0], P[1], P[2])]       # 3 partners -> strong friendship turn -> keep training
    assert s._junior_recreation(REC, 4, training, _chara(4), {}) is None


def test_forced_on_the_last_pre_debut_turn():
    s = _strat()
    strong = [_train(P[0], P[1], P[2])]         # even a strong board...
    assert s._junior_recreation(REC, 11, strong, _chara(11), {}) is REC   # ...is forced at turn 11


def test_never_after_the_window():
    s = _strat()
    weak = [_train(P[0])]
    assert s._junior_recreation(REC, 12, weak, _chara(12), {}) is None    # debut race turn / after
    assert s._junior_recreation(REC, 20, weak, _chara(20), {}) is None


def test_gated_off_and_requires_a_recreation_command():
    s = _strat()
    weak = [_train(P[0])]
    assert s._junior_recreation(REC, 4, weak, _chara(4), {"junior_recreation": False}) is None
    assert s._junior_recreation(None, 4, weak, _chara(4), {}) is None      # no recreation offered
    # tunables: raise the partner cap so a 3-partner turn also counts as weak
    strong = [_train(P[0], P[1], P[2])]
    assert s._junior_recreation(REC, 4, strong, _chara(4), {"junior_recreation_max_partners": 3}) is REC


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_junior_recreation: OK")
