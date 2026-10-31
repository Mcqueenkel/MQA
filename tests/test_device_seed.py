"""device_id comes from a per-install random seed (<runtime>/device_seed), not the Steam password.

Synthetic registry values only; no network (GPU / IP lookups are faked)."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uma_api.client as C

ROOT = Path(__file__).resolve().parent.parent
GUID = "00000000-0000-4000-8000-000000000000"
REG = {"SystemProductName": "FAKE BOARD", "MachineGuid": GUID}
CAPTURE = {"viewer_id": 111111111111, "udid": "3f2b6c19-8a4d-4e07-9c51-0b7a2d6e5f38", "auth_key": "ab" * 48,
           "auth_key_len": 48, "app_ver": "9.9.9", "res_ver": "fake"}


def _query(key, name):
    if name not in REG:
        raise OSError(name)
    return REG[name], 1


@contextmanager
def env(**values):
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("UMA_", "OneDrive"))}
    clean.update(values)
    with patch.dict(os.environ, clean, clear=True):
        yield


@contextmanager
def windows_pc(runtime):
    """The Windows PC: a fake registry/GPU/IP, and the runtime dir at `runtime`."""
    winreg = SimpleNamespace(HKEY_LOCAL_MACHINE=0, OpenKey=lambda root, sub: nullcontext(sub), QueryValueEx=_query)
    with env(UMA_RUNTIME_DIR=str(runtime)), patch.object(C.platform, "system", lambda: "Windows"), \
            patch.dict(sys.modules, {"winreg": winreg}), patch.object(C, "get_gpu", lambda: "FAKE GPU"), \
            patch.object(C, "get_ip", lambda: "192.0.2.1"), patch.object(C, "windows_screen_h", lambda: 1080), \
            patch.object(C, "get_os", lambda: "Windows 11  (fake) 64bit"):   # platform.version() reads the real registry
        yield Path(runtime) / "device_seed"


def _device_id(seed):
    return hashlib.sha1(f"FAKE BOARD_{GUID}_{seed}".encode()).hexdigest()


def test_missing_seed_is_created_once_then_reused():
    with tempfile.TemporaryDirectory() as tmp, windows_pc(tmp) as seed_file:
        first = C.get_hwid()["device_id"]
        seed = seed_file.read_text(encoding="utf-8")
        assert re.fullmatch(r"[0-9a-f]{64}", seed), seed
        assert C.get_hwid()["device_id"] == first == _device_id(seed)   # a restart keeps the device_id
        assert seed_file.read_text(encoding="utf-8") == seed
        assert os.listdir(tmp) == ["device_seed"]   # no temp file left behind
        if os.name != "nt":
            assert seed_file.stat().st_mode & 0o777 == 0o600


def test_blank_seed_is_regenerated_and_an_existing_one_kept():
    with tempfile.TemporaryDirectory() as tmp, windows_pc(tmp) as seed_file:
        seen = set()
        for blank in ("", "  \n\t"):
            seed_file.write_text(blank, encoding="utf-8")
            seed = C.device_seed()
            assert re.fullmatch(r"[0-9a-f]{64}", seed) and seed_file.read_text(encoding="utf-8") == seed
            seen.add(seed)
        assert len(seen) == 2
        seed_file.write_text("  kept-seed \n", encoding="utf-8")
        assert C.device_seed() == "kept-seed"
        assert C.get_hwid()["device_id"] == _device_id("kept-seed")
        assert seed_file.read_text(encoding="utf-8") == "  kept-seed \n"


def test_device_id_no_longer_depends_on_the_steam_password():
    with tempfile.TemporaryDirectory() as tmp, windows_pc(tmp) as seed_file:
        ids = {C.UmaClient(dict(CAPTURE, steam_password_seed=pw), trace_enabled=False).device_id
               for pw in ("pw-one", "pw-two", "")}
        ids.add(C.UmaClient(dict(CAPTURE), trace_enabled=False).device_id)
        seed = seed_file.read_text(encoding="utf-8")
    assert ids == {_device_id(seed)} and _device_id("pw-one") not in ids


def test_export_identity_writes_the_seeded_device_id():
    with tempfile.TemporaryDirectory() as tmp, windows_pc(Path(tmp) / "rt") as seed_file:
        with patch.dict(os.environ, {"UMA_AUTH_CONFIG": str(Path(tmp) / "id.json")}):
            path = C.UmaClient(dict(CAPTURE, steam_password_seed="pw"), trace_enabled=False).export_identity()
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["device_id"] == _device_id(seed_file.read_text(encoding="utf-8")) != _device_id("pw")
    assert "pw" not in saved.values()


def test_off_windows_never_makes_a_seed():
    with tempfile.TemporaryDirectory() as tmp, env(UMA_RUNTIME_DIR=tmp), \
            patch.object(C.platform, "system", lambda: "Linux"), patch.dict(sys.modules, {"winreg": None}):
        assert C.get_hwid().keys() == {"udid"}
        assert os.listdir(tmp) == []


def test_the_seed_file_is_gitignored():
    git = shutil.which("git")
    if not git or not (ROOT / ".git").exists():
        return   # not a git checkout (a ZIP download): nothing to commit it to
    with env():
        rel = (C.runtime_output_root() / "device_seed").relative_to(ROOT)
    try:
        r = subprocess.run([git, "check-ignore", "-q", "--no-index", rel.as_posix()], cwd=ROOT, timeout=60)
    except OSError:
        return   # a sandbox that refuses to start git
    assert r.returncode == 0, f"{rel} is not gitignored"



def test_a_seed_written_by_another_process_at_the_same_instant_is_used():
    with tempfile.TemporaryDirectory() as tmp, windows_pc(tmp) as seed_file:
        def lost_the_race(path, text):   # the other MQA wrote first; our os.replace is refused
            Path(path).write_text("theirs" * 8, encoding="utf-8")
            raise PermissionError(5, "Access is denied")

        with patch.object(C, "_write_private", lost_the_race):
            assert C.device_seed() == "theirs" * 8


def test_a_seed_that_cannot_be_read_is_not_regenerated():
    with tempfile.TemporaryDirectory() as tmp, windows_pc(tmp) as seed_file:
        seed_file.mkdir()   # unreadable as a file: must raise, never silently become a new device
        try:
            C.device_seed()
            raise AssertionError("an unreadable seed was replaced")
        except OSError:
            pass
        assert seed_file.is_dir() and os.listdir(seed_file) == []

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
