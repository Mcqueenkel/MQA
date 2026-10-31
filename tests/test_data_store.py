"""Offline unit tests for career_bot/data_store.py (DataStore).

Pure, no game/network: writes tiny JSON fixtures into a temp base_dir and asserts the store
loads/validates/caches them. Covers the three things that make the store safe to build on:
  1. accessors return the raw on-disk shape verbatim (drop-in for the old open()+json.load).
  2. a missing/malformed file degrades to the safe default with a warning, not a crash.
  3. a wrong-shape file still returns its data but records a loud warning (no silent breakage).
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.core.data_store import DataStore


def _store(files):
    tmp = tempfile.mkdtemp()
    data = os.path.join(tmp, "data")
    os.makedirs(data)
    for name, obj in files.items():
        with open(os.path.join(data, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
    return DataStore(tmp)


def test_accessors_return_raw_shape():
    s = _store({
        "chara_list.json": {"103801": "Curren Chan", "103802": "Curren Chan (Alt)"},
        "race_map.json": {"meta": {}, "program": {"624": {"name": "Asahi Hai"}}, "instance": {}},
        "skill_data.json": {"10071": {"name": "Warning Shot!", "tags": [401]}},
    })
    assert s.chara_name("103802") == "Curren Chan (Alt)"
    assert s.chara_name(103801) == "Curren Chan"          # int key coerced to str
    assert s.race_map()["program"]["624"]["name"] == "Asahi Hai"
    assert s.skill_data()["10071"]["tags"] == [401]


def test_missing_file_returns_default_and_warns():
    s = _store({})  # empty data dir
    assert s.chara_list() == {}                            # default, no crash
    assert s.race_map() == {"meta": {}, "program": {}, "instance": {}}
    assert s.career_goals_for(1038) == []
    assert any("missing" in p for (_, p) in s._warned)


def test_malformed_json_degrades():
    tmp = tempfile.mkdtemp()
    data = os.path.join(tmp, "data")
    os.makedirs(data)
    with open(os.path.join(data, "factor_map.json"), "w", encoding="utf-8") as fh:
        fh.write("{ this is not json ")
    s = DataStore(tmp)
    assert s.factor_map() == {}                            # safe default
    assert any("invalid JSON" in p for (_, p) in s._warned)


def test_wrong_shape_still_returns_but_warns():
    # race_map missing 'instance' -> validator flags it, but the data is still handed back.
    s = _store({"race_map.json": {"meta": {}, "program": {}}})
    assert s.race_map() == {"meta": {}, "program": {}}
    assert any("instance" in p for (_, p) in s._warned)


def test_career_goals_for_reads_goals():
    s = _store({"career_goals.json": {
        "1038": {"name": "Curren Chan", "goals": [
            {"turn": 23, "kind": "fan", "fans": 3000, "require": "3,000 fans"}]}}})
    goals = s.career_goals_for(1038)
    assert len(goals) == 1 and goals[0]["kind"] == "fan" and goals[0]["fans"] == 3000
    assert s.career_goals_for(9999) == []                  # unknown chara -> []


def test_cache_reused_until_reload():
    s = _store({"chara_list.json": {"1": "A"}})
    assert s.chara_name("1") == "A"
    # overwrite on disk; cached value persists until reload()
    with open(os.path.join(s.data_dir, "chara_list.json"), "w", encoding="utf-8") as fh:
        json.dump({"1": "B"}, fh)
    assert s.chara_name("1") == "A"
    s.reload()
    assert s.chara_name("1") == "B"


if __name__ == "__main__":
    test_accessors_return_raw_shape()
    test_missing_file_returns_default_and_warns()
    test_malformed_json_degrades()
    test_wrong_shape_still_returns_but_warns()
    test_career_goals_for_reads_goals()
    test_cache_reused_until_reload()
    print("test_data_store: OK")
