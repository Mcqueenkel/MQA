"""Per-endpoint API library.

Every call the client logs (via UmaClient.api_log) is also appended here, keyed by the
endpoint's DIRECTORY: `single_mode_free/load` -> uma_runtime/api_library/single_mode_free/load.jsonl.
One .jsonl per endpoint, one line per REQ/RESP -- so you get a browsable record of every
endpoint the bot has ever hit, grouped by namespace.

Reuses the client's single api_log choke point (no second capture path). Recording must never
break a live career, so every failure is swallowed. Disable with env UMA_NO_API_LIBRARY=1.

Rolls over instead of stopping: when an endpoint file passes 8 MB it becomes <ep>.1.jsonl, older ones
shift to .2 and .3, and the oldest drops off, so the library always holds the NEWEST traffic (fresh
shapes after every game update) in at most ~32 MB per endpoint. A career writes ~12 MB in total
(check_event alone ~3.7 MB, so its 4 files hold ~8 careers), and "keep everything" would be ~1 GB/day at
3-4 careers an hour. (Until 2026-10 it simply stopped at 8 MB, which froze most career endpoints in July;
with a single .1 file the first careers of a day were already gone by the afternoon.)
"""
import json
import os
import re
import threading
from pathlib import Path

_lock = threading.Lock()
_MAX_BYTES = 8 * 1024 * 1024   # roll an endpoint file over to <ep>.1.jsonl past this
_KEEP = 3                      # older files kept per endpoint: <ep>.1 (newest) .. <ep>.3 (oldest)


def library_root():
    override = os.environ.get("UMA_API_LIBRARY_DIR")
    if override:
        return Path(override)
    from uma_api.client import runtime_output_root
    return runtime_output_root() / "api_library"


def _json_default(obj):
    if isinstance(obj, bytes):
        return obj.hex()
    return str(obj)


def endpoint_path(ep):
    """<library>/<namespace>/<endpoint>.jsonl  (e.g. tool/signup -> tool/signup.jsonl)."""
    parts = str(ep).strip("/").split("/")
    name = parts[-1] or "root"
    sub = "/".join(parts[:-1]) or "_root"
    return library_root() / sub / f"{name}.jsonl"


def record(entry):
    """Append one api_log entry ({ts, direction, endpoint, data, req_id}) to its endpoint file."""
    if os.environ.get("UMA_NO_API_LIBRARY"):
        return
    ep = (entry or {}).get("endpoint")
    if not ep:
        return
    try:
        path = endpoint_path(ep)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > _MAX_BYTES:
                # .2 -> .3, .1 -> .2 (the old .3 is replaced), then the full file -> .1. If a rename
                # fails (file held open elsewhere) the except below skips the line: still capped.
                for n in range(_KEEP, 1, -1):
                    older = path.with_suffix(f".{n - 1}.jsonl")
                    if older.exists():
                        os.replace(older, path.with_suffix(f".{n}.jsonl"))
                os.replace(path, path.with_suffix(".1.jsonl"))
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=_json_default) + "\n")
    except Exception:
        pass   # recording never breaks the bot


def catalog():
    """{endpoint: {calls, bytes}} across the whole recorded library, for a quick overview."""
    root = library_root()
    out = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*.jsonl")):
        ep = re.sub(r"\.\d+$", "", p.relative_to(root).with_suffix("").as_posix())   # fold .1/.2/.3 in
        try:
            with open(p, encoding="utf-8") as f:
                calls = sum(1 for _ in f)
        except Exception:
            calls = 0
        row = out.setdefault(ep, {"calls": 0, "bytes": 0})
        row["calls"] += calls
        row["bytes"] += p.stat().st_size
    return out


def _demo():
    import tempfile
    os.environ["UMA_API_LIBRARY_DIR"] = str(Path(tempfile.mkdtemp()) / "api_library")
    os.environ.pop("UMA_NO_API_LIBRARY", None)
    record({"ts": 1, "direction": "REQ", "endpoint": "single_mode_free/load", "data": {"adid": ""}})
    record({"ts": 2, "direction": "RESP", "endpoint": "single_mode_free/load", "data": {"ok": True}})
    record({"ts": 3, "direction": "REQ", "endpoint": "tool/signup", "data": {"blob": b"\x00\x01"}})
    record({"ts": 4, "direction": "REQ", "endpoint": "load/index", "data": {}})
    f = endpoint_path("single_mode_free/load")
    assert f.exists(), "endpoint file not created"
    assert len(f.read_text(encoding="utf-8").splitlines()) == 2, "expected 2 recorded lines"
    cat = catalog()
    assert cat.get("single_mode_free/load", {}).get("calls") == 2, cat
    assert cat.get("tool/signup", {}).get("calls") == 1, cat
    assert cat.get("load/index", {}).get("calls") == 1, cat
    print("api_library selftest OK:", {k: v["calls"] for k, v in cat.items()})


if __name__ == "__main__":
    _demo()
