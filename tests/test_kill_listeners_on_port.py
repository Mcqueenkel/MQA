"""Freeing MQA's port must only kill a process LISTENING on exactly that port -- never one on a port
that merely starts with the same digits (1616 vs 16160), nor an established connection."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main

NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:16160          0.0.0.0:0              LISTENING       111
  TCP    127.0.0.1:1616         0.0.0.0:0              LISTENING       222
  TCP    [::]:1616              [::]:0                 LISTENING       333
  TCP    127.0.0.1:51000        127.0.0.1:1616         ESTABLISHED     444
  TCP    127.0.0.1:8080         0.0.0.0:0              LISTENING       555
"""


def test_only_exact_port_listeners_are_killed():
    killed = []

    def fake_run(cmd, **_kw):
        if cmd[0] == "netstat":
            return SimpleNamespace(stdout=NETSTAT, returncode=0)
        if cmd[0] == "taskkill":
            killed.append(int(cmd[cmd.index("/PID") + 1]))
        return SimpleNamespace(stdout="", returncode=0)

    with patch.object(main.os, "name", "nt"), patch.object(main.subprocess, "run", fake_run), \
            patch.object(main.os, "getpid", lambda: 999), patch.object(main, "dna_sleep", lambda *_: None):
        main.kill_listeners_on_port(1616)
    assert sorted(killed) == [222, 333], killed


if __name__ == "__main__":
    test_only_exact_port_listeners_are_killed()
    print("test_kill_listeners_on_port: OK")
