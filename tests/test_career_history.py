"""Career history: a finished career records name + card_id (portrait) + rank/rank_letter + resolved
sparks, and read_career_history returns them newest-first for the History UI. Only actually-finished
careers (rank_score > 0) are recorded."""
import os, sys, tempfile, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from career_bot.core import notify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # real data/factor_map.json lives here


def _base():
    # base_dir must hold BOTH data/factor_map.json (for resolve_sparks) and a writable uma_runtime/.
    import shutil
    d = tempfile.mkdtemp(prefix="hist-")
    os.makedirs(os.path.join(d, "data"))
    shutil.copy(os.path.join(ROOT, "data", "factor_map.json"), os.path.join(d, "data", "factor_map.json"))
    return d


def test_career_history():
    base = _base()
    # a finished career with 2 real Speed sparks (factor ids 101,102 from factor_map.json) at rank 17 (SS)
    r1 = notify.record_career_history(base, {
        "status": "finished", "rank": 17, "rank_score": 12345,
        "card_id": "100101", "uma_name": "Special Week", "fans": 42000,
        "factor_ids": [101, 102], "preset": "MyPreset",
    })
    # a stopped/errored run must NOT be recorded
    r2 = notify.record_career_history(base, {"status": "stopped", "rank": 0, "rank_score": 0, "card_id": "1"})
    # a later finished career -> should come FIRST (newest-first)
    r3 = notify.record_career_history(base, {
        "status": "finished", "rank": 13, "rank_score": 9000,
        "card_id": "100201", "uma_name": "Silence Suzuka", "factor_ids": [101],
    })

    # record_career_history returns the all-time TOTAL RANKING that feeds the Discord embed. Regression
    # guard: it silently returned None when the return block was stranded as dead code, so the ranking
    # field vanished from the webhook.
    assert r1 is not None and r1["place"] == 1 and r1["total"] == 1, r1
    assert len(r1["top"]) == 1 and r1["top"][0]["current"] is True, r1
    assert r2 is None, "a stopped run is neither recorded nor ranked"
    assert r3["place"] == 2 and r3["total"] == 2, r3            # 9000 < 12345 -> 2nd all-time
    assert [t["uma_name"] for t in r3["top"]] == ["Special Week", "Silence Suzuka"], r3["top"]  # top by score
    assert r3["top"][0]["current"] is False and r3["top"][1]["current"] is True, r3["top"]

    hist = notify.read_career_history(base)
    assert len(hist) == 2, hist                                  # the stopped run was skipped
    assert hist[0]["uma_name"] == "Silence Suzuka", "newest first"
    e = hist[1]
    assert e["card_id"] == "100101" and e["rank_letter"] == "SS", e
    assert [s["name"] for s in e["sparks"]] == ["Speed", "Speed"], e["sparks"]
    assert e["sparks"][1]["stars"] == 2 and e["sparks"][0]["category"] == "stat", e["sparks"]
    print("career history OK (finished-only, newest-first, name/card/rank_letter/sparks recorded)")


if __name__ == "__main__":
    test_career_history()
