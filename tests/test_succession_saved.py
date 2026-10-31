"""Career start: the current_succession_rank_point the server accepted is saved per account + parent
pair (uma_runtime/succession_points.json), so a restart no longer re-sweeps ~50 start calls for parents
it already knows (live, 2026-10-20: estimate 151, accepted 174 after ~50 starts, two of them 208 busy).
The never-effective force-delete before the sweep is gone (10 of 10 captured attempts were refused).

Run:
    python tests/test_succession_saved.py
    python -m pytest tests/test_succession_saved.py
"""
import json
import os
import sys
import tempfile
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


@contextmanager
def _fresh(client=None, **extra):
    """Temp runtime dir, empty caches, the given client logged in."""
    names = dict(dict(active_client=client, _succession_rank_point_cache={}, _succession_saved=None,
                      _exiting=False), **extra)
    originals = {n: getattr(main, n) for n in names}
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"UMA_RUNTIME_DIR": tmp}):
        try:
            for n, v in names.items():
                setattr(main, n, v)
            yield tmp
        finally:
            for n, v in originals.items():
                setattr(main, n, v)


def test_learned_value_survives_a_restart_and_stays_per_account():
    with _fresh(SimpleNamespace(viewer_id=123)) as tmp:
        main._remember_succession_point((1845, 2188), 174)
        saved = json.load(open(os.path.join(tmp, "succession_points.json"), encoding="utf-8"))
        assert saved == {"123:1845:2188": 174}
        main._succession_rank_point_cache, main._succession_saved = {}, None      # "restart"
        assert main._learned_succession_point((1845, 2188)) == 174
        main.active_client = SimpleNamespace(viewer_id=456)                      # other account
        assert main._learned_succession_point((1845, 2188)) is None
        main.active_client = None                                                # not logged in
        main._remember_succession_point((1, 2), 99)
        assert json.load(open(os.path.join(tmp, "succession_points.json"), encoding="utf-8")) == saved


def test_the_saved_value_beats_the_estimate():
    with _fresh(SimpleNamespace(viewer_id=123), active_parent_rank_points={}):
        req = SimpleNamespace(parent_id_1=1845, parent_id_2=2188, rental_trained_chara_id=0)
        assert main.selected_succession_rank_point(req) == 0                     # no data: estimate 0
        main._remember_succession_point((1845, 2188), 174)
        main._succession_rank_point_cache = {}
        assert main.selected_succession_rank_point(req) == 174


def test_sweep_walks_out_from_the_estimate_before_the_old_fallbacks():
    order = main._succession_sweep_candidates(151, 1008)
    assert order[:3] == [151, 152, 150]
    assert order.index(174) == 2 * 23 - 1                                       # +23: 45 tries after it
    assert order.index(1008) > order.index(191) and order.index(0) > order.index(111)   # after est +/- 40
    assert len(order) == len(set(order)) and min(order) >= 0


class _Client:
    """Accepts exactly one succession value; records every finish/close call."""
    def __init__(self, accept):
        self.viewer_id = 123
        self.tp_info = {"current_tp": 100, "max_tp": 100}
        self.current_scenario_id = 0
        self.accept, self.sent, self.deletes = accept, [], []

    def call(self, endpoint, payload=None):
        return {"data": {"tp_info": dict(self.tp_info), "item_list": [{"item_id": 59, "number": 1000}]}}

    def refresh_cached_account_state(self, data):
        pass

    def pre_single_mode(self, _excluded):
        return {"data": {}}

    def start_career(self, **kw):
        self.sent.append(kw["succession_rank_point"])
        if kw["succession_rank_point"] != self.accept:
            raise RuntimeError("API error 102 on single_mode_free/start: {}")
        return {"data": {"chara_info": {"card_id": 100101, "turn": 1}}}

    def probing_102(self):
        return nullcontext()

    def load_career(self):
        raise RuntimeError("API error 102 on single_mode_free/load: {}")    # no active career

    def finish_career(self, **kw):
        self.deletes.append(kw)

    def close_career(self, **kw):
        self.deletes.append(kw)

    def reset_circuit(self):
        pass


def _request():
    return main.RunCareerRequest(
        card_id=100101, support_card_ids=[1, 2, 3, 4, 5, 6], friend_viewer_id=99, friend_card_id=77,
        parent_id_1=1845, parent_id_2=2188, scenario_id=4, use_tp=30, tp_recovery_mode="off", run_count=0)


def test_start_sweeps_without_deleting_anything_then_starts_first_try_next_time():
    client = _Client(accept=174)
    env = dict(active_account=None, active_dashboard_data=None, active_start_state={},
               validate_start_selection=lambda _r: None, dna_sleep=lambda *a, **k: None,
               server_sleep=lambda *a, **k: None, active_parent_rank_points={})
    with _fresh(client, **env):
        with patch.object(main, "_succession_affinity_point", lambda a, b: 151):
            first = main.start_career_from_request(_request())
            assert first["success"] is True, first
            assert client.deletes == [], client.deletes          # no force-delete on a clean slot
            assert client.sent[-1] == 174 and len(client.sent) == 2 + 46
            main._succession_rank_point_cache, main._succession_saved = {}, None   # MQA restarted
            client.sent.clear()
            again = main.start_career_from_request(_request())
            assert again["success"] is True and client.sent == [174]           # first try


class _BusyClient(_Client):
    """Answers 208 (busy) the first time the accepted value is sent, like the live 2026-10-29 sweep."""
    def __init__(self, accept):
        super().__init__(accept)
        self.busy_once = {accept}

    def start_career(self, **kw):
        v = kw["succession_rank_point"]
        if v in self.busy_once:
            self.busy_once.discard(v)
            self.sent.append(v)
            raise RuntimeError("API error 208 on single_mode_free/start: {}")
        return super().start_career(**kw)


def test_a_value_answered_busy_is_tried_again_later():
    client = _BusyClient(accept=174)
    env = dict(active_account=None, active_dashboard_data=None, active_start_state={},
               validate_start_selection=lambda _r: None, dna_sleep=lambda *a, **k: None,
               server_sleep=lambda *a, **k: None, active_parent_rank_points={})
    with _fresh(client, **env):
        with patch.object(main, "_succession_affinity_point", lambda a, b: 151):
            started = main.start_career_from_request(_request())
    assert started["success"] is True, started
    assert client.sent.count(174) == 2 and client.sent[-1] == 174


def test_the_sweep_stops_when_mqa_is_shutting_down():
    client = _Client(accept=174)
    env = dict(active_account=None, active_dashboard_data=None, active_start_state={},
               validate_start_selection=lambda _r: None, dna_sleep=lambda *a, **k: None,
               server_sleep=lambda *a, **k: None, active_parent_rank_points={}, _exiting=True)
    with _fresh(client, **env):
        with patch.object(main, "_succession_affinity_point", lambda a, b: 151):
            started = main.start_career_from_request(_request())
    assert started["success"] is False and 174 not in client.sent and len(client.sent) == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
