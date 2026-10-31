"""Saved Steam login (single account).

The PASSWORD goes to the OS vault (Windows Credential Manager, via `keyring`) -- never to
disk. Only the non-secret username is written to uma_runtime/steam_credential.json, so the
login form can pre-fill it and the backend can pull the password from the vault and re-mint a
fresh Steam ticket each login. (The short-lived ticket itself is still never persisted.)

ponytail: single login on purpose. If multi-account ever comes back, key the vault entry by
label instead of one fixed username and store a list in the json.
"""
import json

SERVICE = "umabot-steam"   # keyring service name; the username is the vault key


def _file():
    from uma_api.client import runtime_output_root
    return runtime_output_root() / "steam_credential.json"


def save(username, password):
    """Persist the username (disk) + password (OS vault). Empty password leaves the vault as-is."""
    username = (username or "").strip()
    if not username:
        raise ValueError("username required")
    import keyring
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"username": username}), encoding="utf-8")   # NEVER the password
    if password:
        keyring.set_password(SERVICE, username, password)


def load():
    """{'username', 'password'} for the saved login (password from the vault), or None."""
    try:
        username = json.loads(_file().read_text(encoding="utf-8")).get("username")
    except Exception:
        return None
    if not username:
        return None
    try:
        import keyring
        password = keyring.get_password(SERVICE, username) or ""
    except Exception:
        password = ""   # vault unreachable -> caller sees a username with no password
    return {"username": username, "password": password}


def clear():
    """Forget the saved login: drop the vault entry and delete the on-disk username file."""
    cur = load()
    if cur and cur.get("username"):
        try:
            import keyring
            keyring.delete_password(SERVICE, cur["username"])
        except Exception:
            pass
    try:
        _file().unlink()
    except Exception:
        pass


if __name__ == "__main__":
    # Self-check with a fake in-memory keyring + temp file -- touches neither the real OS
    # vault nor uma_runtime.
    import sys, types, tempfile
    from pathlib import Path
    _store = {}
    fk = types.ModuleType("keyring")
    fk.set_password = lambda s, u, p: _store.__setitem__((s, u), p)
    fk.get_password = lambda s, u: _store.get((s, u))
    fk.delete_password = lambda s, u: _store.pop((s, u), None)
    sys.modules["keyring"] = fk
    _tmp = Path(tempfile.mkdtemp()) / "steam_credential.json"
    _file = lambda: _tmp   # noqa: E731  (shadow for the test)

    assert load() is None, "should start empty"
    save("example_user", "hunter2")
    assert load() == {"username": "example_user", "password": "hunter2"}, load()
    assert "hunter2" not in _tmp.read_text(encoding="utf-8"), "password must NEVER hit disk"
    clear()
    assert load() is None, "clear() should forget it"
    print("steam_credential selftest OK")
