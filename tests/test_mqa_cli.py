"""mqa_cli.py against a fake MQA on 127.0.0.1: commands hit the right endpoints, `start` sends the same
run body as the web UI, `login` never carries a password, and errors map to exit codes 1/2."""
import io
import json
import os
import sys
import threading
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mqa_cli  # noqa: E402

SELECTION = {
    "trainee": {"id": 103802},
    "deck": {"id": 3, "cards": [{"id": 30001}, {"id": 30002}]},
    "friend": {"viewer_id": 111, "support_card_id": 30099},
    "veterans": [{"instance_id": 7}, {"instance_id": 8}],
}
ACCOUNT = {"tp": {"current": 12, "max": 100}, "carrots": {"total": 4500}, "clocks": 3, "tp_bottles": 2,
           "career": None}


class Fake:
    def __init__(self):
        self.posts = []
        self.session = {"success": True, "account": ACCOUNT, "selection": SELECTION}
        self.runners = []          # successive /api/career/runner snapshots (last one repeats)
        self.refuse_run = False


def serve(fake):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/career/runner":
                r = fake.runners.pop(0) if len(fake.runners) > 1 else (fake.runners or [{}])[0]
                return self._send({"success": True, "runner": r})
            if self.path == "/api/session":
                return self._send(fake.session)
            if self.path == "/api/presets":
                return self._send({"success": True, "presets": [{"name": "fan"}, {"name": "xguri parent"}]})
            if self.path == "/api/career/history":
                return self._send({"success": True, "history": [{"when": "2026-10-16T01:02", "uma_name": "Mejiro",
                                                                 "rank_letter": "A", "rank_score": 12000, "fans": 300000},
                                                                {"when": "2026-10-16T02:02", "uma_name": "Bourbon",
                                                                 "rank_letter": "B+", "rank_score": 9674, "fans": 1,
                                                                 "outcome": "goal_failed@turn72"}]})
            self._send({"success": False, "detail": "no such endpoint"})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
            fake.posts.append((self.path, body))
            if self.path == "/api/login" and getattr(fake, "needs_2fa", False) and not (body or {}).get("code"):
                return self._send({"success": False, "needs_2fa": True})
            if self.path == "/api/career/run" and fake.refuse_run:
                return self._send({"success": False, "detail": "Career runner loop already active"})
            self._send({"success": True, "runner": {"running": True}})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def run(url, *args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = mqa_cli.main(["--url", url, *args])
    return code, out.getvalue(), err.getvalue()


def test_status_account_presets_history():
    fake = Fake()
    fake.runners = [{"running": True, "preset": "fan", "scenario_id": 4, "turn": 40, "last_action": "train",
                     "log": [{"turn": 40, "action": "train", "detail": "speed"}]}]
    srv, url = serve(fake)
    try:
        code, out, _ = run(url, "status")
        assert code == 0 and "MQA: running" in out and "turn 40/78" in out and "MANT" in out, out
        code, out, _ = run(url, "--json", "status")
        assert code == 0 and json.loads(out)["turn"] == 40
        code, out, _ = run(url, "account")
        assert "TP 12/100" in out and "TP bottles 2" in out and "carats 4500" in out, out
        fake.session = {"success": False}
        code, out, _ = run(url, "account")
        assert code == 0 and "Not logged in" in out
        assert run(url, "presets")[1].split() == ["fan", "xguri", "parent"]
        hist = run(url, "history")[1]
        assert "Mejiro" in hist and "[goal_failed@turn72]" in hist and "completed" not in hist, hist
    finally:
        srv.shutdown()


def test_start_sends_the_ui_run_body_and_reports_refusals():
    fake = Fake()
    srv, url = serve(fake)
    try:
        code, out, _ = run(url, "start", "--preset", "fan", "--runs", "3", "--finish")
        assert code == 0, out
        path, body = fake.posts[-1]
        assert path == "/api/career/run"
        assert (body["preset_name"], body["run_count"], body["finish_career"]) == ("fan", 3, True)
        assert body["card_id"] == 103802 and body["parent_id_2"] == 8   # from the web UI's selection
        fake.refuse_run = True
        code, _, err = run(url, "start", "--preset", "fan")
        assert code == 1 and "already active" in err
        fake.session = {"success": False}
        code, _, err = run(url, "start", "--preset", "fan")
        assert code == 1 and "not logged in" in err
    finally:
        srv.shutdown()


def test_login_never_sends_a_password():
    fake = Fake()
    srv, url = serve(fake)
    try:
        assert run(url, "login")[0] == 0
        assert fake.posts[-1] == ("/api/login", {})              # = use MQA's saved Steam login
        assert run(url, "login", "--code", "AB12C")[0] == 0
        assert fake.posts[-1] == ("/api/login", {"code": "AB12C"})
        fake.needs_2fa = True
        code, _, err = run(url, "login")
        assert code == 1 and "Steam Guard code" in err and "--code" in err, err
    finally:
        srv.shutdown()


def test_stop_and_watch():
    fake = Fake()
    fake.runners = [{"running": True, "turn": 5, "last_action": "train"},
                    {"running": False, "loop_active": False, "turn": 6, "finished": True},
                    {"running": False, "loop_active": False, "turn": 6, "finished": True}]
    srv, url = serve(fake)
    try:
        code, out, _ = run(url, "stop")
        assert code == 0 and fake.posts[-1][0] == "/api/career/runner/stop"
        code, out, _ = run(url, "watch", "--every", "0")
        assert code == 0 and "Run ended." in out, out
        fake.runners = [{"running": False, "last_error": "API error 208 on start"}]
        code, _, err = run(url, "watch", "--every", "0")
        assert code == 1 and "208" in err
    finally:
        srv.shutdown()


def test_unreachable_mqa_is_exit_code_2():
    code, _, err = run("http://127.0.0.1:9", "status")
    assert code == 2 and "isn't reachable" in err


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
