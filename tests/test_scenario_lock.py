"""Scenario is CHOSEN at terminal startup (interactive prompt, or the optional --scenario flag) and
FROZEN for the session -- forced into every career start (no mid-session drift, no silent MANT
fallback). To switch, restart the terminal. The web UI only DISPLAYS it (GET /api/scenario) -- no
toggle. Covers the pure lock logic + the read-only shower endpoint."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main


def test_cli_scenario_parsing():
    assert main.parse_cli_args(["--scenario", "unity"])[3] == 2
    assert main.parse_cli_args(["--scenario", "mant"])[3] == 4
    assert main.parse_cli_args(["-s", "ura"])[3] == 1
    assert main.parse_cli_args(["--scenario", "2"])[3] == 2
    assert main.parse_cli_args(["1616"])[3] is None            # no flag -> unset (prompt handles it)
    assert main.parse_cli_args(["--scenario", "bogus"])[3] is None
    # scenario flag does not eat the port / account
    port, acct, reauth, sc = main.parse_cli_args(["8080", "--scenario", "unity", "--account", "A"])
    assert (port, acct, sc) == (8080, "A", 2)


def test_lock_precedence():
    # the chosen scenario (from flag or prompt) freezes the lock; None -> MANT default
    assert main.lock_scenario_at_startup(None) == 4
    assert main.lock_scenario_at_startup(2) == 2
    assert main.lock_scenario_at_startup(4) == 4
    assert main.lock_scenario_at_startup(1) == 1
    assert main.lock_scenario_at_startup(99) == 4              # unknown -> MANT default


def test_scenario_shower_is_read_only():
    from fastapi.testclient import TestClient
    main.lock_scenario_at_startup(2)   # session launched as UNITY
    c = TestClient(main.app)

    r = c.get("/api/scenario").json()
    assert r["locked_scenario_id"] == 2 and r["locked_name"] == "UNITY"

    # it is a SHOWER, not a toggle: there is no POST route to change it
    assert c.post("/api/scenario", json={"scenario_id": 4}).status_code == 405   # method not allowed

    main.lock_scenario_at_startup(4)   # a "restart" re-choosing MANT
    assert c.get("/api/scenario").json()["locked_scenario_id"] == 4


def test_startup_prompt_offers_all_three_scenarios():
    # the interactive prompt maps: 1/mant -> 4, 2/unity -> 2, 3/ura -> 1, empty/garbage -> MANT
    import io
    for typed, want in (("1", 4), ("mant", 4), ("2", 2), ("unity", 2),
                        ("3", 1), ("ura", 1), ("", 4), ("banana", 4)):
        real = sys.stdin
        sys.stdin = io.StringIO(typed + "\n")
        try:
            assert main.prompt_scenario_choice() == want, (typed, want)
        finally:
            sys.stdin = real


def test_scenario_completion_nicknames():
    # close-out change_nickname ids: Team=154 + MANT=180 live-verified; URA has NO scenario-1 rows
    # in master.mdb's nickname table, so it uses the generic 92 (verified on a real URA-trained uma).
    from uma_api.client import UmaClient
    m = UmaClient.SCENARIO_COMPLETION_NICKNAME
    assert m[2] == 154 and m[4] == 180 and m[1] == 92
    assert m.get(99) is None   # unknown scenario -> caller's default (180)


if __name__ == "__main__":
    test_cli_scenario_parsing()
    test_lock_precedence()
    test_scenario_shower_is_read_only()
    test_startup_prompt_offers_all_three_scenarios()
    test_scenario_completion_nicknames()
    print("test_scenario_lock: OK")
