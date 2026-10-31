"""The capture library rolls a full endpoint file over to <ep>.1.jsonl instead of silently stopping
(it used to stop at 8 MB, which froze most career endpoints in July and missed every game update)."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uma_api import api_library as L  # noqa: E402


def test_full_file_rolls_over_and_keeps_recording():
    root = Path(tempfile.mkdtemp()) / "api_library"
    env = {"UMA_API_LIBRARY_DIR": str(root)}
    with patch.dict(os.environ, env), patch.object(L, "_MAX_BYTES", 200):
        os.environ.pop("UMA_NO_API_LIBRARY", None)
        for i in range(40):
            L.record({"ts": i, "direction": "REQ", "endpoint": "single_mode/load", "data": {"pad": "x" * 40}})
        folder = root / "single_mode"
        cur = folder / "load.jsonl"
        assert json.loads(cur.read_text(encoding="utf-8").splitlines()[-1])["ts"] == 39   # newest kept
        # three older generations, newest first; nothing beyond .3
        assert sorted(p.name for p in folder.iterdir()) == ["load.1.jsonl", "load.2.jsonl", "load.3.jsonl", "load.jsonl"]
        first = lambda name: json.loads((folder / name).read_text(encoding="utf-8").splitlines()[0])["ts"]
        assert first("load.3.jsonl") < first("load.2.jsonl") < first("load.1.jsonl") < first("load.jsonl")
        assert all(p.stat().st_size <= 200 + 100 for p in folder.iterdir())               # each bounded
        assert first("load.3.jsonl") > 0                                                   # oldest dropped
        assert list(L.catalog()) == ["single_mode/load"]                                   # generations folded
        assert L.catalog()["single_mode/load"]["calls"] < 40
