"""career_bot/core/master_data.py -- locating the GLOBAL client's master.mdb.

The client MOVED this file: it used to live in AppData/LocalLow/Cygames/Umamusume/master and now
ships inside the Steam install under <library>/steamapps/common/UmamusumePrettyDerby/
UmamusumePrettyDerby_Data/Persistent/master. The resolver has to find either, because a wrong answer
is silent: main.py just reports "master.mdb requires user action" and every data/*.json goes stale.

The JP-exclusion test is the important one. JP ships a much bigger database (169 charas / 543 support
cards / 14 scenarios vs Global's 95 / 238 / 4) with ids Global's server has never heard of, so
regenerating from it would produce a bot that picks content that does not exist on the account.

Run:
    python tests/test_master_mdb_path.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core import master_data as M  # noqa: E402

GLOBAL_REL = ("steamapps", "common", "UmamusumePrettyDerby",
              "UmamusumePrettyDerby_Data", "Persistent", "master", "master.mdb")
JP_REL = ("steamapps", "common", "UmamusumePrettyDerby_Jpn",
          "UmamusumePrettyDerby_Jpn_Data", "Persistent", "master", "master.mdb")


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"SQLite format 3\x00")
    return path


class _Fake:
    """Swap the Steam-library probe and the legacy path for temp dirs."""

    def __init__(self, tmp, roots):
        self.tmp = Path(tmp)
        self.roots = [self.tmp / r for r in roots]
        self.legacy = self.tmp / "AppData" / "LocalLow" / "Cygames" / "Umamusume" / "master" / "master.mdb"

    def __enter__(self):
        self._roots, self._legacy = M._steam_library_roots, M._legacy_master_mdb_path
        M._steam_library_roots = lambda: list(self.roots)
        M._legacy_master_mdb_path = lambda: self.legacy
        return self

    def __exit__(self, *exc):
        M._steam_library_roots, M._legacy_master_mdb_path = self._roots, self._legacy


def test_finds_the_new_install_location():
    with tempfile.TemporaryDirectory() as tmp, _Fake(tmp, ["SteamA"]) as f:
        want = _touch(f.roots[0].joinpath(*GLOBAL_REL))
        assert M.default_master_mdb_path() == want


def test_falls_back_to_the_legacy_localllow_path():
    with tempfile.TemporaryDirectory() as tmp, _Fake(tmp, ["SteamA"]) as f:
        _touch(f.legacy)                       # only the OLD layout exists
        assert M.default_master_mdb_path() == f.legacy


def test_install_wins_over_legacy_when_both_exist():
    with tempfile.TemporaryDirectory() as tmp, _Fake(tmp, ["SteamA"]) as f:
        install = _touch(f.roots[0].joinpath(*GLOBAL_REL))
        _touch(f.legacy)
        assert M.default_master_mdb_path() == install, "the live client writes the install copy"


def test_searches_every_steam_library():
    # Games commonly sit on a second drive; libraryfolders.vdf is why extra roots are probed.
    with tempfile.TemporaryDirectory() as tmp, _Fake(tmp, ["SteamA", "D_Library", "F_Library"]) as f:
        want = _touch(f.roots[2].joinpath(*GLOBAL_REL))
        assert M.default_master_mdb_path() == want


def test_never_selects_the_JP_install():
    """JP ids are a different game -- silently regenerating from it is worse than finding nothing."""
    with tempfile.TemporaryDirectory() as tmp, _Fake(tmp, ["SteamA"]) as f:
        _touch(f.roots[0].joinpath(*JP_REL))   # ONLY the JP database is present
        got = M.default_master_mdb_path()
        assert "Jpn" not in str(got), got
        assert got == f.legacy                 # falls back to the missing legacy path instead


def test_missing_everywhere_returns_the_legacy_path():
    # Keeps main.py's "master.mdb requires user action" message pointing somewhere recognisable.
    with tempfile.TemporaryDirectory() as tmp, _Fake(tmp, ["SteamA"]) as f:
        got = M.default_master_mdb_path()
        assert got == f.legacy and not got.exists()


def test_library_probe_never_raises():
    roots = M._steam_library_roots()           # real registry / filesystem
    assert isinstance(roots, list) and roots
    assert len(roots) == len({str(r).lower() for r in roots}), "roots must be de-duplicated"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("master.mdb path OK")
