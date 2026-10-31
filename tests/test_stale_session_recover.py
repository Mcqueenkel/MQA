"""Error 394 mid-loop: _recover_stale_session re-captures, logs in again and keeps the start selection,
at most once per 10 minutes, and gives up when the capture fails."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main


def test_stale_session_recover(monkeypatch=None):
    calls = {"capture": 0, "login": 0}
    capture_ok = {"v": True}

    def fake_capture():
        calls["capture"] += 1
        return capture_ok["v"]

    async def fake_login(req):
        calls["login"] += 1
        main.active_selection = {"deck": None, "friend": None, "trainee": None, "veterans": []}  # login clears it
        main.active_client = object()
        return {"account": {}}

    old = (main.refresh_auth_before_serving, main.login, main.os.name, main.carrying_identity)
    main.refresh_auth_before_serving, main.login = fake_capture, fake_login
    main.os.name, main.carrying_identity = 'nt', lambda: False
    try:
        pick = {"trainee": {"id": "106802"}, "deck": {"id": 8}, "friend": {"viewer_id": 1}, "veterans": [{}, {}]}
        main.active_selection = dict(pick)
        main._last_session_recover = 0.0
        assert main._recover_stale_session() is True
        assert main.active_selection == pick                     # selection survives the re-login
        assert main._recover_stale_session() is False            # second 394 within 10 min: let the loop stop
        assert calls == {"capture": 1, "login": 1}

        main._last_session_recover = 0.0
        capture_ok["v"] = False
        assert main._recover_stale_session() is False            # no capture -> no login attempt
        assert calls == {"capture": 2, "login": 1}

        # The loop only recovers on 394, never on 391 (another client took the session).
        assert main.is_api_error("Could not refresh: API error 394 on load/index: {}", 394)
        assert not main.is_api_error("API error 391 on load/index: {}", 394)
    finally:
        main.refresh_auth_before_serving, main.login, main.os.name, main.carrying_identity = old


if __name__ == "__main__":
    test_stale_session_recover()
    print("ok")
