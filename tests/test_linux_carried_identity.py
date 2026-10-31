"""Headless (Linux) run from an identity carried from Windows: the opt-in env gate, the startup gate,
a client that sends only carried device fields off Windows, the 394-only ticket re-mint, a clean stop
on SIGTERM, and the Windows default (no env) left exactly as it was.

Synthetic identities only -- every value below is fake. No network: transports are scripted."""
import ast
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from contextlib import ExitStack, contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uma_api.client as C

ROOT = Path(__file__).resolve().parent.parent
ENV = ("UMA_CARRY_IDENTITY", "UMA_AUTH_CONFIG", "UMA_RUNTIME_DIR", "UMA_APP_VER", "UMA_RES_VER",
       "UMA_UNITY_VER", "SWEEPY_SCENARIO", "OneDrive", "OneDriveConsumer", "OneDriveCommercial")
UDID = "3f2b6c19-8a4d-4e07-9c51-0b7a2d6e5f38"
IDENTITY = {"viewer_id": 111111111111, "udid": UDID, "auth_key": "ab" * 48, "auth_key_len": 48,
            "app_ver": "9.9.9", "res_ver": "fake", "device_id": "d" * 40, "device_name": "CARRIED (PC)",
            "graphics_device_name": "CARRIED GPU", "ip_address": "192.0.2.7",
            "platform_os_version": "Windows 11  (10.0.1) 64bit", "locale": "JPN", "screen_h": 1080}
# What the Windows PC itself reports (get_hwid): a capture carries none of the device fields.
HOST = {"udid": UDID, "device_id": "h" * 40, "device_name": "HOST (PC)", "graphics_device_name": "HOST GPU",
        "ip_address": "192.0.2.9", "platform_os_version": "Windows 11  (10.0.2) 64bit"}
CAPTURE = {k: v for k, v in IDENTITY.items() if k not in C.CARRIED_FIELDS or k in ("app_ver", "res_ver")}


@contextmanager
def env(**values):
    clean = {k: v for k, v in os.environ.items() if k not in ENV}
    clean["UMA_NO_API_LIBRARY"] = "1"   # scripted calls never land in the tree's uma_runtime/api_library
    clean.update({k: str(v) for k, v in values.items()})
    with patch.dict(os.environ, clean, clear=True):
        yield


@contextmanager
def off_windows():
    """The client module on a Linux host: platform.system() -> Linux, winreg unimportable."""
    with patch.object(C.platform, "system", lambda: "Linux"), patch.dict(sys.modules, {"winreg": None}):
        yield


@contextmanager
def on_windows(screen_h=1080):
    """The client module on the Windows PC, with its device profile and screen height faked."""
    with patch.object(C.platform, "system", lambda: "Windows"), \
            patch.object(C, "get_hwid", lambda: dict(HOST)), \
            patch.object(C, "windows_screen_h", lambda: screen_h):
        yield


class _PosixOs:
    """main.py's view of os on a Linux host: os.name only, everything else is the real os."""
    name = "posix"

    def __getattr__(self, k):
        return getattr(os, k)


class _NtOs(_PosixOs):
    name = "nt"


def _drive(coro):
    """Run an endpoint coroutine that never awaits (main.login) inline."""
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    raise AssertionError("awaited")


def _identity_file(tmp, data=IDENTITY):
    p = Path(tmp) / "auth_config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _boom(*a, **k):
    raise AssertionError("touched the host (registry / kernel string / network)")


# --- opt-in gate ----------------------------------------------------------------------------------

def test_default_is_off_and_memory_only():
    with env():
        assert not C.carrying_identity()
        assert C.auth_config_path() is None
        assert C.load_auth_config() == {}
        assert C.write_auth_config(dict(IDENTITY)) is None
    for off in ("0", "false", "no", "off", "true", "yes", "on", "2"):   # only "1" turns it on
        with env(UMA_CARRY_IDENTITY=off):
            assert not C.carrying_identity() and C.auth_config_path() is None, off
    with env(UMA_CARRY_IDENTITY=" 1 "):
        assert C.carrying_identity()
    with env(), on_windows(), patch.object(C, "windows_screen_h", _boom):   # nothing written, nothing probed
        assert C.UmaClient(dict(CAPTURE), trace_enabled=False).export_identity() is None


def test_default_path_is_outside_the_repo_and_refused_inside_it_or_onedrive():
    with tempfile.TemporaryDirectory() as tmp:
        with env(UMA_CARRY_IDENTITY="1", USERPROFILE=tmp, HOME=tmp):
            assert C.auth_config_path() == (Path(tmp) / ".mqa" / "auth_config.json").resolve()
        inside = Path(C.DIR) / "uma_runtime" / "auth_config.json"
        with env(UMA_AUTH_CONFIG=str(inside)):
            assert C.auth_config_path() is None
        if os.name == "nt":   # Windows paths are case-insensitive
            with env(UMA_AUTH_CONFIG=str(inside).swapcase()):
                assert C.auth_config_path() is None
        for onedrive in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            with env(UMA_AUTH_CONFIG=str(Path(tmp) / "a" / "id.json"), **{onedrive: tmp}):
                assert C.auth_config_path() is None, onedrive
        with env(UMA_AUTH_CONFIG=str(Path(tmp) / "id.json")):
            assert C.auth_config_path() == (Path(tmp) / "id.json").resolve()


def test_refusal_sees_through_links_unc_and_relative_forms():
    with tempfile.TemporaryDirectory() as tmp:
        od = Path(tmp) / "OneDrive"
        od.mkdir()
        link = Path(tmp) / "link"
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(od), str(link))
        else:
            link.symlink_to(od, target_is_directory=True)
        forms = [link / "id.json", link / "new" / "id.json"]
        if os.name == "nt":
            bs = "\\"
            forms += [str(od) + " " + bs + "id.json",                           # trailing-space folder
                      bs * 2 + "?" + bs + str(od / "id.json"),                   # \\?\C:\...
                      bs * 2 + "localhost" + bs + str(od)[0] + "$" + str(od)[2:] + bs + "id.json",   # admin share
                      "//localhost/" + str(od)[0] + "$" + str(od)[2:].replace(bs, "/") + "/id.json"]
        for p in forms:
            with env(UMA_AUTH_CONFIG=str(p), OneDrive=str(od)):
                assert C.auth_config_path() is None, p
        with env(UMA_AUTH_CONFIG="\\\\nas\\share\\id.json"):   # any UNC path, OneDrive or not
            assert C.auth_config_path() is None
        with env(UMA_AUTH_CONFIG=str(Path(tmp) / "elsewhere" / "id.json"), OneDrive=str(od)):
            assert C.auth_config_path() == (Path(tmp) / "elsewhere" / "id.json").resolve()
        cwd = os.getcwd()
        try:
            os.chdir(ROOT)   # a bare relative name lands in the repo
            with env(UMA_AUTH_CONFIG="x.json"):
                assert C.auth_config_path() is None
            os.chdir(tmp)    # anywhere else it is pinned to an absolute path: a later chdir can't move it
            with env(UMA_AUTH_CONFIG="x.json"):
                assert C.auth_config_path() == (Path(tmp) / "x.json").resolve()
        finally:
            os.chdir(cwd)


def test_inside_check_compares_identity_not_names():
    # What resolve() can miss (a bind mount, a SUBST drive): an unresolved link still compares by identity,
    # through every existing parent of a file that does not exist yet.
    with tempfile.TemporaryDirectory() as tmp:
        od = Path(tmp) / "OneDrive"
        od.mkdir()
        link = Path(tmp) / "link"
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(od), str(link))
        else:
            link.symlink_to(od, target_is_directory=True)
        assert C._same_or_under(link, od) and C._same_or_under(link / "new" / "id.json", od)
        assert not C._same_or_under(Path(tmp) / "elsewhere" / "id.json", od)


def test_export_load_round_trip_0600_without_steam_secrets():
    import main
    modes, real_open = [], os.open

    def spy(path, flags, mode=0o777, *a, **k):
        modes.append(mode)
        return real_open(path, flags, mode, *a, **k)

    with tempfile.TemporaryDirectory() as tmp, env(UMA_AUTH_CONFIG=str(Path(tmp) / "sub" / "id.json")), \
            off_windows(), patch.object(C, "windows_screen_h", _boom):   # the carried screen_h, not a probe
        c = C.UmaClient(dict(IDENTITY, steam_id="7656", steam_session_ticket="cd" * 8,
                             steam_password_seed="pw", steam_username="u"), trace_enabled=False)
        with patch.object(C.os, "open", spy):
            path = c.export_identity()
        raw = json.loads(path.read_text(encoding="utf-8"))
        if os.name != "nt":
            assert path.stat().st_mode & 0o777 == 0o600
        back = C.load_auth_config()
    assert modes == [0o600]
    assert not any(k.startswith("steam_") for k in raw) and "pw" not in raw.values()
    assert main.has_fresh_auth_config(back) and C.missing_carried_fields(back) == []
    assert back == IDENTITY   # every field the client sends, locale included


def test_identity_write_never_shares_a_temp_name_and_cleans_up():
    def disk_full(*a, **k):
        raise OSError("disk full")

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "id.json"
        planted = Path(tmp) / "id.json.tmp"   # a fixed temp name: another writer's file, or a planted link
        planted.write_text("keep", encoding="utf-8")
        with env(UMA_AUTH_CONFIG=str(target)):
            assert C.write_auth_config({"viewer_id": 1}) == target.resolve()
            with patch.object(C.os, "fsync", disk_full):
                try:
                    C.write_auth_config({"viewer_id": 2})
                    raise AssertionError("a failed write was swallowed")
                except OSError:
                    pass
        assert planted.read_text(encoding="utf-8") == "keep"
        assert json.loads(target.read_text(encoding="utf-8")) == {"viewer_id": 1}
        assert sorted(os.listdir(tmp)) == ["id.json", "id.json.tmp"]   # no temp file left behind


def test_wrong_typed_identity_file_is_refused_cleanly():
    import main
    with tempfile.TemporaryDirectory() as tmp:
        for bad in (dict(IDENTITY, auth_key_len="forty-eight"), dict(IDENTITY, screen_h="tall"),
                    dict(IDENTITY, device_name=["x"]), dict(IDENTITY, auth_key_len=None), [IDENTITY]):
            p = _identity_file(tmp, bad)
            for host_os in (_NtOs(), _PosixOs()):
                out = StringIO()
                with env(UMA_CARRY_IDENTITY="1", UMA_AUTH_CONFIG=str(p)), patch.object(main, "os", host_os), \
                        patch.object(main, "refresh_auth_before_serving", lambda: False), \
                        patch.object(main, "pending_game_auth_config", {}), redirect_stdout(out):
                    assert C.load_auth_config() == {}, bad
                    assert main.startup_auth_ready() is False
                assert "missing or incomplete" in out.getvalue(), out.getvalue()


def test_loose_secret_file_modes_are_tightened_off_windows():
    import discord_remote
    chmods = []

    class Os(_PosixOs):
        def chmod(self, path, mode):
            chmods.append(mode)
            os.chmod(path, mode)

    class NtOs(Os):
        name = "nt"

    with tempfile.TemporaryDirectory() as tmp:
        ident = _identity_file(tmp)
        remote = Path(tmp) / "discord_remote.json"
        remote.write_text(json.dumps({"token": "t", "owner_ids": [1]}), encoding="utf-8")
        for f in (ident, remote):
            os.chmod(f, 0o644)   # what scp / a USB copy leaves (on Windows st_mode reads 0o666 anyway)
        out = StringIO()
        with env(UMA_CARRY_IDENTITY="1", UMA_AUTH_CONFIG=str(ident)), on_windows(), \
                patch.object(C, "os", NtOs()), patch.object(discord_remote, "os", NtOs()), redirect_stdout(out):
            assert C.load_auth_config()["viewer_id"] == IDENTITY["viewer_id"]
            assert discord_remote.load_config(remote)["token"] == "t"
        assert chmods == [] and "0600" not in out.getvalue(), out.getvalue()   # Windows: untouched, no warning
        with env(UMA_CARRY_IDENTITY="1", UMA_AUTH_CONFIG=str(ident)), off_windows(), \
                patch.object(C, "os", Os()), patch.object(discord_remote, "os", Os()), redirect_stdout(out):
            assert C.load_auth_config()["viewer_id"] == IDENTITY["viewer_id"]
            assert discord_remote.load_config(remote)["token"] == "t"
        assert chmods == [0o600, 0o600] and out.getvalue().count("set it to 0600") == 2, out.getvalue()
        if os.name != "nt":
            assert all(f.stat().st_mode & 0o777 == 0o600 for f in (ident, remote))


def test_load_strips_any_steam_ticket_or_password():
    with tempfile.TemporaryDirectory() as tmp:
        p = _identity_file(tmp, dict(IDENTITY, steam_id="7656", steam_session_ticket="cd",
                                     steam_password_seed="pw"))
        with env(UMA_CARRY_IDENTITY="1", UMA_AUTH_CONFIG=str(p)):
            cfg = C.load_auth_config()
    assert cfg == IDENTITY


# --- fix 1: off Windows, only carried device fields; never the host's own -------------------------

def test_off_windows_sends_the_carried_fields_and_never_probes_the_host():
    with off_windows(), patch.object(C.platform, "version", _boom), patch.object(C.socket, "socket", _boom):
        assert C.get_hwid().keys() == {"udid"}   # no model / GPU / kernel string / IP from this host
        c = C.UmaClient(dict(IDENTITY), trace_enabled=False)
    common = c.common()
    for key in ("device_id", "device_name", "graphics_device_name", "ip_address", "platform_os_version"):
        assert common[key] == IDENTITY[key], key


def test_windows_capture_without_device_fields_still_builds_a_client():
    with on_windows():
        c = C.UmaClient(dict(CAPTURE), trace_enabled=False)
    assert (c.device_id, c.device_name, c.screen_h) == (HOST["device_id"], HOST["device_name"], 0)


def _race_out_click(c):
    sent = {}

    def log(direction, ep, data, req_id=None):
        if direction == "REQ":
            sent.update(json.loads(data["payload"]["button_info"]))

    def offline(*a, **k):
        raise OSError("offline")   # the payload is built before the post

    c.api_log, c.session.post = log, offline
    try:
        c.call("single_mode_free/race_out", {"program_id": 1}, retry_net=1)
    except Exception:
        pass
    return sent["ClickPosX"], sent["ClickPosY"]


def test_race_out_click_on_the_carried_host_is_the_windows_pcs():
    with patch.object(C, "dna_gauss", lambda mu, *a, **k: mu):
        with on_windows(screen_h=1080):
            pc = _race_out_click(C.UmaClient(dict(CAPTURE), trace_enabled=False))
        with on_windows(screen_h=1440):
            other_pc = _race_out_click(C.UmaClient(dict(CAPTURE), trace_enabled=False))
        with off_windows(), patch.object(C, "windows_screen_h", _boom):
            carried = _race_out_click(C.UmaClient(dict(IDENTITY, screen_h=1080), trace_enabled=False))
    assert carried == pc != other_pc


def test_off_windows_client_refuses_an_identity_missing_any_carried_field():
    for key in ("device_id", "device_name", "graphics_device_name", "ip_address",
                "platform_os_version", "app_ver", "res_ver", "screen_h"):
        for cfg in ({k: v for k, v in IDENTITY.items() if k != key}, dict(IDENTITY, **{key: " "})):
            with off_windows(), patch.object(C.platform, "version", _boom), \
                    patch.object(C.socket, "socket", _boom), env():
                try:
                    C.UmaClient(cfg, trace_enabled=False)
                    raise AssertionError(f"constructed without {key}")
                except RuntimeError as e:
                    assert key in str(e) and "Windows PC" in str(e), e


def test_no_hardcoded_machine_defaults_remain():
    src = Path(C.__file__).read_text(encoding="utf-8")
    assert "DEFAULT_DEVICE_NAME" not in src and "DEFAULT_LAN_IP" not in src and "UMA_LAN_IP" not in src


def test_startup_gate_carried_identity_skips_the_capture():
    import main
    with tempfile.TemporaryDirectory() as tmp, \
            env(UMA_CARRY_IDENTITY="1", UMA_AUTH_CONFIG=str(_identity_file(tmp))), \
            patch.object(main, "refresh_auth_before_serving", _boom), \
            patch.object(main, "pending_game_auth_config", {}):
        assert main.startup_auth_ready() is True
        assert main.pending_game_auth_config == IDENTITY
        with patch.object(main, "os", _PosixOs()):
            assert main.startup_auth_ready() is True


def test_startup_gate_off_windows_refuses_without_device_fields_and_never_launches():
    import main
    partial = {k: v for k, v in IDENTITY.items() if k not in ("device_name", "ip_address")}
    with tempfile.TemporaryDirectory() as tmp:
        for envs in ({"UMA_CARRY_IDENTITY": "1", "UMA_AUTH_CONFIG": str(_identity_file(tmp, partial))}, {}):
            out = StringIO()
            with env(**envs), patch.object(main, "os", _PosixOs()), patch.object(main, "launch_game", _boom), \
                    patch.object(main, "pending_game_auth_config", {}), redirect_stdout(out):
                assert main.startup_auth_ready() is False
                assert main.pending_game_auth_config == {}
            assert main.CAPTURE_WINDOWS_ONLY in out.getvalue()
            if envs:
                assert "lacks device_name, ip_address" in out.getvalue(), out.getvalue()


def test_relogin_after_logout_uses_the_carried_file_only_when_carrying():
    import main
    built = []

    class FakeClient:
        def __init__(self, cfg, trace_enabled=True):
            built.append(dict(cfg))

        def login(self):
            raise Exception("stop here")

    def relogin():
        coro = main.login(main.LoginRequest(username="u", password="p"))
        try:
            coro.send(None)
        except StopIteration as stop:
            return stop.value
        raise AssertionError("login awaited")

    with tempfile.TemporaryDirectory() as tmp, patch.object(C, "UmaClient", FakeClient), \
            patch.object(C, "get_ticket", lambda *a: ("7656", "ef")), \
            patch.object(main, "pending_game_auth_config", {}):
        path = _identity_file(tmp)
        with env(UMA_CARRY_IDENTITY="1", UMA_AUTH_CONFIG=str(path)):
            assert relogin()["detail"] == "stop here"
        assert built and built[0]["viewer_id"] == IDENTITY["viewer_id"]
        with env(UMA_AUTH_CONFIG=str(path)):   # Windows export-only: re-login still needs a capture
            assert "capture required" in relogin()["detail"]
    assert len(built) == 1


def test_api_login_writes_the_identity_only_when_opted_in():
    import main
    ok = {"data_headers": {"result_code": 1, "sid": "00" * 16}, "data": {}}
    state = ("active_client", "active_account", "active_dashboard_data", "active_start_state",
             "active_parent_cards", "active_parent_rank_points", "raw_load_index_response", "active_selection")
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
        for name in state:
            stack.enter_context(patch.object(main, name, getattr(main, name)))
        stack.enter_context(on_windows(screen_h=1234))
        stack.enter_context(patch.object(C, "unpack", lambda text, udid: json.loads(json.dumps(ok))))
        stack.enter_context(patch.object(C.requests.Session, "post",
                                         lambda *a, **k: SimpleNamespace(status_code=200, text="x")))
        home = str(Path(tmp) / "home")
        for envs in ({"UMA_AUTH_CONFIG": str(Path(tmp) / "id.json")}, {"HOME": home, "USERPROFILE": home}):
            with env(**envs), patch.object(main, "pending_game_auth_config",
                                           dict(CAPTURE, steam_id="7656", steam_session_ticket="cd" * 8)):
                res = _drive(main.login(main.LoginRequest(username="u", password="p")))
            assert res.get("success"), res
        with env(UMA_AUTH_CONFIG=str(Path(tmp) / "id.json")), patch.object(C.UmaClient, "export_identity", _boom), \
                patch.object(main, "pending_game_auth_config", dict(CAPTURE, steam_id="7656", steam_session_ticket="cd" * 8)):
            res = _drive(main.login(main.LoginRequest(username="u", password="p")))
            assert res.get("success"), res   # a failed export never fails the login
        saved = json.loads((Path(tmp) / "id.json").read_text(encoding="utf-8"))
        assert os.listdir(tmp) == ["id.json"]   # the env-unset login wrote nothing (no ~/.mqa either)
    assert saved["screen_h"] == 1234 and saved["device_name"] == HOST["device_name"]
    assert C.missing_carried_fields(saved) == [] and not any(k.startswith("steam_") for k in saved)


def test_windows_carry_needs_no_device_fields():
    import main   # on the Windows PC itself the device fields come from the PC, as after a capture
    with tempfile.TemporaryDirectory() as tmp, \
            env(UMA_CARRY_IDENTITY="1", UMA_AUTH_CONFIG=str(_identity_file(tmp, CAPTURE))), \
            patch.object(main, "os", _NtOs()), patch.object(main, "refresh_auth_before_serving", _boom), \
            patch.object(main, "pending_game_auth_config", {}):
        assert main.startup_auth_ready() is True and main.pending_game_auth_config == CAPTURE


def test_windows_incomplete_carried_identity_falls_back_to_the_capture():
    import main
    captures = []
    with tempfile.TemporaryDirectory() as tmp, \
            env(UMA_CARRY_IDENTITY="1", UMA_AUTH_CONFIG=str(_identity_file(tmp, {"viewer_id": 1}))), \
            patch.object(main, "refresh_auth_before_serving", lambda: captures.append(1) or False):
        assert main.startup_auth_ready() is False
    assert captures == [1]


# --- 394 re-mint: carried-identity hosts only, once, never on 391 ---------------------------------

@contextmanager
def rig(codes, creds=True):
    """A client whose server answers `codes` in order and whose Steam mint is counted."""
    state = {"posts": 0, "minted": 0}

    def fake_unpack(text, udid):
        rc, extra = codes.pop(0) if codes else 1, {}
        if isinstance(rc, tuple):   # (code, extra data_headers)
            rc, extra = rc
        return {"data_headers": {"result_code": rc, "sid": "00" * 16, **extra}, "data": {}}

    def fake_ticket(u, p, c=""):
        state["minted"] += 1
        return "7656", "ef" * 8

    def fake_post(*a, **k):
        state["posts"] += 1
        return SimpleNamespace(status_code=200, text="x")

    # Session.post on the class: login() swaps in a fresh session, which must stay scripted too.
    with patch.object(C, "unpack", fake_unpack), patch.object(C, "get_ticket", fake_ticket), \
            patch.object(C, "server_sleep", lambda *a, **k: None), patch.object(C.requests.Session, "post", fake_post):
        with off_windows():
            cfg = dict(IDENTITY, steam_id="7656", steam_session_ticket="cd" * 8,
                       **({"steam_username": "u", "steam_password_seed": "p"} if creds else {}))
            c = C.UmaClient(cfg, trace_enabled=False)
        state["c"] = c
        yield state


def _raises_394(fn):
    try:
        fn()
    except Exception as e:
        return C.is_api_error(e, 394)
    return False


def test_394_remints_once_when_carrying():
    with env(UMA_CARRY_IDENTITY="1"):
        with rig([394, 1]) as r:
            assert r["c"].call("single_mode_free/check_event", {})["data_headers"]["result_code"] == 1
        assert r["posts"] == 2 and r["minted"] == 1 and r["c"].steam_ticket == "ef" * 8
        with rig([394, 394, 394]) as r:
            assert _raises_394(lambda: r["c"].call("single_mode_free/check_event", {}))
        assert r["minted"] == 1 and r["posts"] == 2
        with rig([205, 394, 205, 394, 1]) as r:   # the budget survives the 205 retry chain
            assert _raises_394(lambda: r["c"].call("single_mode_free/exec_command", {}))
        assert r["minted"] == 1
        with rig([394], creds=False) as r:
            assert _raises_394(lambda: r["c"].call("single_mode_free/check_event", {}))
        assert r["minted"] == 0 and r["posts"] == 1
        with rig([394, 1]) as r:   # irreversible spends never replay
            assert _raises_394(lambda: r["c"].call_once("single_mode_free/multi_item_use", {}))
        assert r["minted"] == 0 and r["posts"] == 1
        with rig([394, (214, {"resource_version": "fake2"}), 394, 1]) as r:   # nor does a 214 retry refill it
            assert _raises_394(lambda: r["c"].call("single_mode_free/check_event", {}))
        assert r["minted"] == 1 and r["posts"] == 3

        def guard_needed(u, p, c=""):
            raise Exception("STEAM_GUARD_REQUIRED")

        with rig([394, 1]) as r, patch.object(C, "get_ticket", guard_needed):   # a failed mint is the 394
            assert _raises_394(lambda: r["c"].call("single_mode_free/check_event", {}))


def test_login_394_remints_once_not_per_call():
    for codes, posts in (([394] * 8, 4), ([1] + [394] * 8, 5)):   # 394 on start_session / on load/index
        with env(UMA_CARRY_IDENTITY="1"), rig(codes) as r:   # login's own 394 branch is the only re-mint
            assert _raises_394(r["c"].login)
        assert r["minted"] == 1 and r["posts"] == posts, (r["minted"], r["posts"])


def test_env_keeps_scripted_calls_out_of_the_api_library():
    from uma_api import api_library
    hits = []
    with env(UMA_CARRY_IDENTITY="1"), rig([1]) as r, \
            patch.object(api_library, "endpoint_path", lambda ep: hits.append(ep) or Path(os.devnull)):
        r["c"].call("single_mode_free/check_event", {})
    assert hits == []


def test_394_remint_is_not_repeated_while_it_keeps_failing_nor_during_a_stop():
    ep = "single_mode_free/check_event"
    with env(UMA_CARRY_IDENTITY="1"):
        with rig([394, 394, 394, 1, 394, 1]) as r:
            assert _raises_394(lambda: r["c"].call(ep, {}))   # re-minted, still 394
            assert _raises_394(lambda: r["c"].call(ep, {}))   # no second Steam login for the next call
            r["c"].call(ep, {})                               # a success re-arms it
            r["c"].call(ep, {})                               # 394 -> one re-mint -> ok
        assert r["minted"] == 2 and r["posts"] == 6
        with rig([394, 1]) as r:
            r["c"].should_abort = lambda: True                # Stop was pressed
            assert _raises_394(lambda: r["c"].call(ep, {}))
        assert r["minted"] == 0 and r["posts"] == 1


def test_391_never_remints():
    with env(UMA_CARRY_IDENTITY="1"), rig([391, 1]) as r:
        try:
            r["c"].call("single_mode_free/check_event", {})
            raise AssertionError("391 was retried")
        except Exception as e:
            assert C.is_api_error(e, 391), e
    assert r["minted"] == 0 and r["posts"] == 1


def test_394_unchanged_without_carrying():
    for envs in ({}, {"UMA_AUTH_CONFIG": "x.json"}):   # Windows default, and the Windows export-only mode
        with env(**envs), rig([394, 1]) as r:
            assert _raises_394(lambda: r["c"].call("single_mode_free/check_event", {}))
        assert r["minted"] == 0 and r["posts"] == 1


# --- fix 2: SIGTERM / systemd stop lands between API calls ----------------------------------------

def test_stop_runs_for_exit_requests_stop_and_joins_both_threads():
    import main
    runner = main.career_runner
    saved = runner.thread, runner.stop_requested, main.backend_loop_thread, main.backend_loop_stop
    done = []

    def turn_loop():   # a run that only ends between API calls, when the stop flag is seen
        while not runner.stop_requested:
            threading.Event().wait(0.01)
        threading.Event().wait(0.2)   # finishing the in-flight call
        done.append("runner")

    def career_loop():
        while not main.backend_loop_stop:
            threading.Event().wait(0.01)
        done.append("loop")

    try:
        runner.stop_requested, main.backend_loop_stop = False, False
        runner.thread = threading.Thread(target=turn_loop, daemon=True)
        main.backend_loop_thread = threading.Thread(target=career_loop, daemon=True)
        runner.thread.start()
        main.backend_loop_thread.start()
        main.stop_runs_for_exit(timeout_sec=10)
        assert sorted(done) == ["loop", "runner"]   # both joined, not abandoned
        assert runner.stop_requested and main.backend_loop_stop
    finally:
        runner.thread, runner.stop_requested, main.backend_loop_thread, main.backend_loop_stop = saved


def test_stop_runs_for_exit_rearms_ctrl_c_and_joins_a_career_the_loop_started_late():
    import main
    runner = main.career_runner
    saved = runner.thread, runner.stop_requested, main.backend_loop_thread, main.backend_loop_stop
    handler_seen, done = [], []

    def turn_loop():
        while not runner.stop_requested:
            threading.Event().wait(0.01)
        handler_seen.append(signal.getsignal(signal.SIGINT))   # what a second Ctrl+C hits during the wait
        threading.Event().wait(0.2)                             # finishing the in-flight call
        done.append("late career")

    def career_loop():   # was between its stop check and career_runner.start(): starts one more career
        threading.Event().wait(0.1)
        runner.stop_requested = False                           # as start() does
        runner.thread = threading.Thread(target=turn_loop, daemon=True)
        runner.thread.start()

    uvicorns = signal.signal(signal.SIGINT, lambda *a: None)   # uvicorn 0.18.2 leaves its handler behind
    try:
        runner.thread, runner.stop_requested, main.backend_loop_stop = None, False, False
        main.backend_loop_thread = threading.Thread(target=career_loop, daemon=True)
        main.backend_loop_thread.start()
        main.stop_runs_for_exit(timeout_sec=10)
        assert done == ["late career"] and handler_seen == [signal.default_int_handler]
    finally:
        signal.signal(signal.SIGINT, uvicorns)
        runner.stop_requested = True
        runner.thread, runner.stop_requested, main.backend_loop_thread, main.backend_loop_stop = saved


def test_a_second_ctrl_c_ends_the_shutdown_wait_at_once():
    import _thread
    import time
    import main
    runner = main.career_runner
    saved = runner.thread, runner.stop_requested, main.backend_loop_thread, main.backend_loop_stop
    release = threading.Event()
    uvicorns = signal.signal(signal.SIGINT, lambda *a: None)   # uvicorn 0.18.2 leaves its handler behind
    try:
        runner.thread = threading.Thread(target=release.wait, daemon=True)   # an API call that hangs
        runner.thread.start()
        main.backend_loop_thread = None
        # The second Ctrl+C, tripped from another thread as Windows' console handler does: a single long
        # join() only sees it when the join times out.
        threading.Timer(0.3, _thread.interrupt_main).start()
        t0 = time.monotonic()
        try:
            main.stop_runs_for_exit(timeout_sec=6)
            raise AssertionError("the second Ctrl+C was swallowed")
        except KeyboardInterrupt:
            assert time.monotonic() - t0 < 3, time.monotonic() - t0
    finally:
        release.set()
        signal.signal(signal.SIGINT, uvicorns)
        runner.thread, runner.stop_requested, main.backend_loop_thread, main.backend_loop_stop = saved


def _main_block(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return next(n for n in tree.body if isinstance(n, ast.If) and "__main__" in ast.dump(n.test))


def test_main_stops_the_run_after_uvicorn_returns():
    calls = [ast.unparse(n.value) for n in _main_block(ROOT / "main.py").body if isinstance(n, ast.Expr)]
    i = next(i for i, s in enumerate(calls) if s.startswith("uvicorn.run("))
    assert calls[i + 1] == "stop_runs_for_exit()", calls[i:]


# --- fix 3: the Steam password never rides on argv ------------------------------------------------

def test_get_ticket_passes_the_password_in_the_env_not_argv():
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, env=kw.get("env") or {})
        return SimpleNamespace(returncode=0, stderr="", stdout='{"steam_id": "1", "session_ticket": "AB"}\n')

    with patch.object(C, "check_deps", lambda: None), patch.object(C.subprocess, "run", fake_run):
        assert C.get_ticket("user", "s3cret-pw", "G7UARD") == ("1", "AB")
    assert seen["cmd"] == ["node", "-e", C.TICKET_GEN_JS]   # no login, no --flags on argv
    assert {k: seen["env"].get(k) for k in ("MQA_STEAM_USERNAME", "MQA_STEAM_PASSWORD", "MQA_STEAM_CODE")} \
        == {"MQA_STEAM_USERNAME": "user", "MQA_STEAM_PASSWORD": "s3cret-pw", "MQA_STEAM_CODE": "G7UARD"}


def test_ticket_js_reads_the_login_from_the_env():
    for var in ("MQA_STEAM_USERNAME", "MQA_STEAM_PASSWORD", "MQA_STEAM_CODE"):
        assert f"process.env.{var}" in C.TICKET_GEN_JS, var
    node = shutil.which("node")
    if not node:
        return   # no Node here: the text check above is all this host can do
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp) / "node_modules" / "steam-user"
        stub.mkdir(parents=True)
        # A stub SteamUser that prints the login it was handed instead of contacting Steam.
        (stub / "index.js").write_text(
            "module.exports = class { logOn(o) { process.stdout.write(JSON.stringify(o), () => process.exit(0)); }"
            " on() {} };", encoding="utf-8")
        login = {"MQA_STEAM_USERNAME": "user", "MQA_STEAM_PASSWORD": "s3cret-pw", "MQA_STEAM_CODE": "G7UARD"}
        try:
            r = subprocess.run([node, "-e", C.TICKET_GEN_JS], cwd=tmp, env=dict(os.environ, **login),
                               capture_output=True, text=True, timeout=60)
        except OSError:
            return   # a sandbox that refuses to start node
    assert json.loads(r.stdout or "{}") == {"accountName": "user", "password": "s3cret-pw",
                                            "twoFactorCode": "G7UARD"}, (r.stdout, r.stderr)


def test_get_ticket_timeout_error_never_contains_the_password():
    def slow_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    with patch.object(C, "check_deps", lambda: None), patch.object(C.subprocess, "run", slow_run):
        try:
            C.get_ticket("user", "s3cret-pw", "")
            raise AssertionError("no timeout")
        except Exception as e:
            chain = [e, e.__cause__, e.__context__]
            assert not any("s3cret-pw" in str(x) for x in chain if x is not None), chain
            # a short message, without the node command line chained under it
            assert str(e) == "Steam login timed out after 60s" and e.__suppress_context__, repr(e)


# --- fix 4: owner-only files off Windows ----------------------------------------------------------

def test_main_and_discord_remote_set_a_private_umask_off_windows():
    for name in ("main.py", "discord_remote.py"):
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        hits = [n for n in tree.body if isinstance(n, ast.If)
                and ast.unparse(n.test) == "os.name != 'nt'"
                and any(ast.unparse(b) == "os.umask(63)" for b in n.body)]   # 63 == 0o077
        assert hits, f"{name}: no module-level `if os.name != 'nt': os.umask(0o077)`"


# --- fix 5: runtime dir fallback without .git is the app root, as runner.py does ------------------

def test_client_runtime_root_without_git_matches_the_runner():
    from career_bot.runner import runtime_output_root as runner_root
    with tempfile.TemporaryDirectory() as tmp, env():
        app = Path(tmp) / "app"
        with patch.object(C, "__file__", str(app / "uma_api" / "client.py")):
            got = C.runtime_output_root()
        assert got == app.resolve() / "uma_runtime" == runner_root(app)


# --- fix 6: recapture off Windows says so instead of trying to launch -----------------------------

def test_recapture_off_windows_returns_the_windows_only_message():
    import main
    before = dict(main.auth_capture_status)
    with patch.object(main, "os", _PosixOs()), patch.object(main, "launch_game", _boom), \
            patch.object(main, "_run_recapture", lambda: None), \
            patch.object(main, "auth_capture_status", dict(before)):
        res = asyncio.run(main.recapture_auth())
        assert main.auth_capture_status == before   # no capture was started
        assert main.refresh_auth_before_serving(timeout_sec=1) is False
    assert res == {"success": False, "detail": main.CAPTURE_WINDOWS_ONLY}
    assert "Windows PC" in main.CAPTURE_WINDOWS_ONLY and "UMA_CARRY_IDENTITY" in main.CAPTURE_WINDOWS_ONLY


def test_recapture_on_windows_starts_a_capture():
    import main
    started = threading.Event()
    with patch.object(main, "os", _NtOs()), patch.object(main, "_run_recapture", started.set), \
            patch.object(main, "auth_capture_status", {"capturing": False}), \
            patch.object(main, "backend_loop_thread", None):
        res = asyncio.run(main.recapture_auth())
        assert res["success"] is True and main.auth_capture_status["capturing"] is True, res
        assert started.wait(5)


# --- frida is Windows-only: main imports without it ------------------------------------------------

def test_capture_without_frida_says_so_and_never_launches_the_game():
    import main
    out = StringIO()
    with patch.object(main, "os", _NtOs()), patch.object(main, "frida", None), \
            patch.object(main, "launch_game", _boom), redirect_stdout(out):
        assert main.refresh_auth_before_serving(timeout_sec=1) is False
    assert "frida is not installed" in out.getvalue()


def test_frida_is_windows_only_in_deps_and_requirements():
    import importlib
    import main
    seen = []
    with patch.object(main, "os", _PosixOs()), patch.object(importlib, "import_module", seen.append), \
            patch.object(main.subprocess, "check_call", _boom):
        main._ensure_deps()
    assert "frida" not in seen and "fastapi" in seen, seen
    frida = [l for l in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
             if l.strip().lower().startswith("frida")]
    assert frida and all('sys_platform == "win32"' in l for l in frida), frida


def test_main_imports_without_frida():
    code = ("import subprocess, sys; sys.modules['frida'] = None; "
            "subprocess.check_call = lambda *a, **k: 1 / 0; "   # _ensure_deps' pip install never really runs
            "import main; assert main.frida is None; print('imported')")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and r.stdout.strip().endswith("imported"), r.stderr[-3000:]


# --- optional: SWEEPY_SCENARIO for a service with no terminal --------------------------------------

def test_sweepy_scenario_env_locks_the_scenario_and_the_flag_wins():
    import main
    with env(SWEEPY_SCENARIO=" Grand "):   # as typed into a unit file
        assert main.parse_cli_args([])[3] == 3
        assert main.parse_cli_args(["--scenario", "ura"])[3] == 1
    with env():
        assert main.parse_cli_args([])[3] is None



def test_a_failed_remint_is_not_retried_by_later_394s_or_relogins():
    attempts = []

    def wrong_password(u, p, c=""):
        attempts.append(1)
        raise Exception("ERROR:InvalidPassword")

    ep = "single_mode_free/check_event"
    # the breaker would trip after 6 errors, and with the rig's no-op sleep its cooldown is a busy loop
    with env(UMA_CARRY_IDENTITY="1"), rig([394] * 20) as r, patch.object(C, "get_ticket", wrong_password), \
            patch.object(C, "CIRCUIT_ERROR_THRESHOLD", 1000):
        for _ in range(5):
            assert _raises_394(lambda: r["c"].call(ep, {}))
        assert _raises_394(r["c"].login)   # the runner's re-login after the error
    assert len(attempts) == 1, f"{len(attempts)} Steam logins for one stale ticket"


def test_shutdown_wait_shares_one_deadline():
    import main, time
    runner = main.career_runner
    saved = runner.thread, runner.stop_requested, main.backend_loop_thread, main.backend_loop_stop
    release = threading.Event()
    try:
        runner.thread = threading.Thread(target=release.wait, daemon=True)          # both stuck mid-call
        main.backend_loop_thread = threading.Thread(target=release.wait, daemon=True)
        runner.thread.start()
        main.backend_loop_thread.start()
        t0 = time.monotonic()
        with redirect_stdout(StringIO()):
            main.stop_runs_for_exit(timeout_sec=1)
        assert time.monotonic() - t0 < 1.6, "each thread got its own timeout instead of one shared one"
    finally:
        release.set()
        runner.thread, runner.stop_requested, main.backend_loop_thread, main.backend_loop_stop = saved


def test_a_unc_identity_path_is_refused_before_any_resolve():
    def no_resolve(self, *a, **k):
        raise AssertionError("resolve() would contact the UNC host")

    with env(UMA_AUTH_CONFIG=r"\\host\share\x.json"), patch.object(C.Path, "resolve", no_resolve), \
            redirect_stdout(StringIO()):
        assert C.auth_config_path() is None

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
