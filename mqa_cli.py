"""MQA command-line driver: run a running MQA from a terminal, no browser needed.

It talks to MQA's own local web API (the same endpoints the web UI and discord_remote.py use), so
start MQA first (python main.py: it captures the game login at startup) and log in once -- in the
web UI, or with `login` below if MQA has your Steam login saved.

    python mqa_cli.py status              what MQA is doing now (+ recent log)
    python mqa_cli.py account             logged in? TP, TP bottles, carats, clocks, career
    python mqa_cli.py presets             your presets
    python mqa_cli.py start --preset fan --runs 3 [--finish] [--burn-clocks]
    python mqa_cli.py stop | pause | resume
    python mqa_cli.py log [-n 30]         recent log lines
    python mqa_cli.py history [-n 10]     finished careers
    python mqa_cli.py watch [--every 30]  follow the run until it ends (exit 1 if it ends on an error)
    python mqa_cli.py login [--code XXXXX]  log in with the Steam login MQA has saved

Add --json to any command for machine-readable output. --url (or MQA_URL) points at another port.
Exit codes: 0 ok, 1 MQA refused or reported an error, 2 MQA not reachable.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

SCENARIOS = {1: "URA", 2: "Unity", 3: "Grand Live", 4: "MANT"}


class MQAError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def call(url, method, path, body=None, timeout=30):
    """One request to MQA's local API; raises MQAError on refusal (1) or when unreachable (2)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url.rstrip("/") + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:   # FastAPI HTTPException: {"detail": ...}
        try:
            payload = json.loads(e.read() or b"{}")
        except ValueError:
            payload = {}
        raise MQAError(str(payload.get("detail") or f"MQA refused {path} (HTTP {e.code})"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise MQAError(f"MQA isn't reachable at {url} ({e}). Is `python main.py` running?", code=2)
    if isinstance(payload, dict) and payload.get("success") is False:
        if payload.get("needs_2fa"):
            raise MQAError("Steam asks for a Steam Guard code: run `python mqa_cli.py login --code <code>` "
                           "with the code from your Steam app/email (or type it in the web UI).")
        raise MQAError(str(payload.get("detail") or f"MQA refused {path}"))
    return payload


def runner(url):
    return call(url, "GET", "/api/career/runner").get("runner") or {}


def state_of(r):
    if r.get("paused"):
        return "paused"
    if r.get("running"):
        return "running"
    return "between careers" if r.get("loop_active") else "idle"


def log_lines(r, n):
    return [f"T{int(x.get('turn') or 0):>2} {x.get('time', '')} {x.get('action', '')}: {x.get('detail', '')}"
            for x in (r.get("log") or [])[-n:]]


def show_status(r, n=8):
    lines = [f"MQA: {state_of(r)}",
             f"  preset {r.get('preset') or '-'} | scenario {SCENARIOS.get(int(r.get('scenario_id') or 0), '-')}"
             f" | turn {int(r.get('turn') or 0)}/78{' (finished)' if r.get('finished') else ''}",
             f"  last action: {r.get('last_action') or '-'}",
             f"  skills {r.get('skills_bought', 0)} | items used {r.get('items_used', 0)} | clocks {r.get('clocks_used', 0)}"]
    if r.get("circuit_tripped"):
        lines.append("  AUTO-BACKOFF: the server was throttling, MQA stopped itself")
    if r.get("last_error"):
        lines.append(f"  ERROR: {r['last_error']}")
    tail = log_lines(r, n)
    if tail:
        lines += ["  recent:"] + [f"    {t}" for t in tail]
    return "\n".join(lines)


def cmd_status(a):
    r = runner(a.url)
    return r if a.json else show_status(r)


def cmd_log(a):
    r = runner(a.url)
    return (r.get("log") or [])[-a.n:] if a.json else "\n".join(log_lines(r, a.n)) or "(no log yet)"


def cmd_account(a):
    try:
        s = call(a.url, "GET", "/api/session")
    except MQAError as e:
        if e.code == 2:
            raise
        return {"logged_in": False} if a.json else "Not logged in: log in at the web UI or run `python mqa_cli.py login`."
    acc = s.get("account") or {}
    if a.json:
        return dict(acc, logged_in=True)
    tp, coins, career = acc.get("tp") or {}, acc.get("carrots") or {}, acc.get("career") or {}
    lines = ["Logged in",
             f"  TP {tp.get('current', '?')}/{tp.get('max', '?')} | TP bottles {acc.get('tp_bottles', '?')}"
             f" | carats {coins.get('total', '?')} | clocks {acc.get('clocks', '?')}"]
    if career.get("active"):
        lines.append(f"  career in progress: turn {career.get('turn', '?')}")
    return "\n".join(lines)


def cmd_presets(a):
    names = [p.get("name", "") for p in call(a.url, "GET", "/api/presets").get("presets") or []]
    return names if a.json else "\n".join(names) or "(no presets)"


def cmd_history(a):
    rows = (call(a.url, "GET", "/api/career/history").get("history") or [])[:a.n]
    if a.json:
        return rows
    return "\n".join(f"{h.get('when', '')[:16]}  {h.get('uma_name')}  {h.get('rank_letter') or ''} "
                     f"({h.get('rank_score', 0)})  {h.get('fans', 0):,} fans"
                     + (f"  [{h['outcome']}]" if h.get("outcome") not in (None, "", "completed") else "")
                     for h in rows) or "(no finished careers)"


def cmd_start(a):
    from discord_remote import build_run_body, MQAError as RemoteError   # one source for the run body
    try:
        session = call(a.url, "GET", "/api/session")
    except MQAError as e:
        if e.code == 2:
            raise
        raise MQAError("MQA is running but not logged in yet: log in first.")
    try:
        body = build_run_body(session, a.preset, a.runs, a.burn_clocks, a.finish)
    except RemoteError as e:
        raise MQAError(str(e))
    call(a.url, "POST", "/api/career/run", body, timeout=600)
    r = runner(a.url)
    return r if a.json else f"Started {a.preset}, {'until stopped' if a.runs == 0 else f'{a.runs} career(s)'}.\n" + show_status(r, 3)


def _simple(path, msg):
    def run(a):
        r = call(a.url, "POST", path).get("runner") or {}
        return r if a.json else msg
    return run


def cmd_login(a):
    # Empty password = "use the Steam login MQA has saved" (main.py /api/login). No password is ever
    # passed through this tool; the Steam Guard code, if Steam asks for one, is typed by the user.
    body = {"code": a.code} if a.code else {}
    res = call(a.url, "POST", "/api/login", body, timeout=180)
    return res if a.json else "Logged in."


def cmd_watch(a):
    last, idle = None, 0
    while True:
        r = runner(a.url)
        key = (state_of(r), r.get("turn"), r.get("last_action"), r.get("last_error"))
        if key != last:
            last = key
            line = f"[{time.strftime('%H:%M:%S')}] {state_of(r)} | turn {int(r.get('turn') or 0)} | {r.get('last_action') or '-'}"
            print(json.dumps(r) if a.json else line + (f" | ERROR: {r['last_error']}" if r.get("last_error") else ""), flush=True)
        idle = 0 if (r.get("running") or r.get("loop_active")) else idle + 1
        if idle >= 2:
            if r.get("last_error"):
                raise MQAError(f"run ended with an error: {r['last_error']}")
            return None if a.json else "Run ended."
        time.sleep(a.every)


def build_parser():
    p = argparse.ArgumentParser(prog="mqa_cli.py", description="Drive a running MQA from the terminal.")
    p.add_argument("--url", default=os.environ.get("MQA_URL", "http://127.0.0.1:1616"))
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("account").set_defaults(fn=cmd_account)
    sub.add_parser("presets").set_defaults(fn=cmd_presets)
    s = sub.add_parser("log"); s.add_argument("-n", type=int, default=30); s.set_defaults(fn=cmd_log)
    s = sub.add_parser("history"); s.add_argument("-n", type=int, default=10); s.set_defaults(fn=cmd_history)
    s = sub.add_parser("start")
    s.add_argument("--preset", required=True)
    s.add_argument("--runs", type=int, default=1, help="careers to run; 0 = until stopped")
    s.add_argument("--finish", action="store_true", help="finish the career at the end (UI FINISH)")
    s.add_argument("--burn-clocks", action="store_true", help="spend clocks on lost races")
    s.set_defaults(fn=cmd_start)
    sub.add_parser("stop").set_defaults(fn=_simple("/api/career/runner/stop", "Stop sent: MQA stops between API calls."))
    sub.add_parser("pause").set_defaults(fn=_simple("/api/career/runner/pause", "Paused."))
    sub.add_parser("resume").set_defaults(fn=_simple("/api/career/runner/resume", "Resumed."))
    s = sub.add_parser("watch"); s.add_argument("--every", type=float, default=30.0); s.set_defaults(fn=cmd_watch)
    s = sub.add_parser("login"); s.add_argument("--code", default="", help="Steam Guard code, if Steam asks"); s.set_defaults(fn=cmd_login)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        out = a.fn(a)
    except MQAError as e:
        print(json.dumps({"error": str(e)}) if a.json else f"error: {e}", file=sys.stderr)
        return e.code
    if out is not None:
        print(json.dumps(out, indent=2, default=str) if a.json else out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
