"""Collect everything the master.mdb DATA layer knows about the Unity Cup (Aoharu) scenario
-- scenario_id = 2 -- into one folder, with an asset-reference manifest.

This gathers the scenario's tables (the team_* stadium/mechanic tables, the single_mode_aoharu_*
tables, and every scenario_id=2 tagged row) and scans them for ASSET REFERENCES -- audio cue
names, background/motion/dress ids -- so you get the list of assets the scenario uses. The
referenced bundles themselves stay in the encrypted store; this is the manifest, not the media.

Reuses the id->name discovery from export_master_data so rows read in plain language.

Run:  python scripts/collect_unity_cup.py            (-> %USERPROFILE%/UmaMasterExport/unity_cup)
      python scripts/collect_unity_cup.py --selftest
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_master_data import build_name_maps, enrich_rows, _write_json, default_db  # noqa: E402

SCENARIO_ID = 2
# tables that ARE the Unity Cup mechanic by name (not scenario_id-tagged, but inherently Aoharu)
NAME_PREFIXES = ("team_", "single_mode_aoharu", "race_single_mode_team", "support_card_team")
# columns that reference an asset (audio cue, background, motion, dress, icon, movie, live)
ASSET_COL = re.compile(r"(cue|bgm|_bg$|bg_id|bg_sub_id|background|motion|dress|prefab|icon|banner|movie|live_id|se_|atmos|env_)")


def _tables(cur):
    return [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]


def collect(db_path, out_dir):
    db_path, out = Path(db_path), Path(out_dir)
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro&immutable=1", uri=True)
    cur = con.cursor()
    name_maps, _ = build_name_maps(cur)

    picked = {}   # table -> (rows, is_scenario_filtered)
    for t in _tables(cur):
        cols = [c[1] for c in cur.execute(f"PRAGMA table_info('{t}')")]
        by_name = any(t.startswith(p) for p in NAME_PREFIXES)
        by_scen = "scenario_id" in cols
        if not (by_name or by_scen):
            continue
        q = f"SELECT * FROM '{t}'" + ("" if by_name else f" WHERE scenario_id={SCENARIO_ID}")
        rows = [dict(zip(cols, r)) for r in cur.execute(q)]
        if not rows:
            continue
        enrich_rows(rows, cols, t, name_maps)
        _write_json(out / "tables" / f"{t}.json", rows)
        picked[t] = (len(rows), not by_name)

    # asset-reference manifest: distinct non-empty/non-zero values of every asset column
    assets = {}
    for t, (_n, scen_filtered) in picked.items():
        cols = [c[1] for c in cur.execute(f"PRAGMA table_info('{t}')")]
        acols = [c for c in cols if ASSET_COL.search(c.lower())]
        if not acols:
            continue
        where = f" WHERE scenario_id={SCENARIO_ID}" if scen_filtered else ""
        seen = {}
        for r in cur.execute(f"SELECT {','.join(chr(96)+c+chr(96) for c in acols)} FROM '{t}'{where}"):
            for c, v in zip(acols, r):
                if v in (None, "", 0):
                    continue
                seen.setdefault(c, set()).add(v)
        if seen:
            assets[t] = {c: sorted(vs, key=str) for c, vs in seen.items()}
    _write_json(out / "asset_references.json", assets)
    con.close()

    audio = sorted({v for tb in assets.values() for c, vs in tb.items()
                    if "cue" in c.lower() or "bgm" in c.lower() or "atmos" in c.lower()
                    for v in vs if isinstance(v, str)})
    _write_json(out / "index.json",
                {"scenario_id": SCENARIO_ID, "scenario": "Aoharu / Unity Cup (team race)",
                 "tables": {t: {"rows": n, "scenario_filtered": sf} for t, (n, sf) in sorted(picked.items())},
                 "audio_cues": audio})
    (out / "README.txt").write_text(
        "Unity Cup (Aoharu, scenario_id=2) -- DATA + asset-reference manifest.\n\n"
        f"tables/           {len(picked)} tables (team_* + aoharu_* full; scenario_id=2 tables filtered)\n"
        "asset_references.json  distinct asset ids/cues referenced, per table+column\n"
        "index.json        table list + the full audio-cue set\n\n"
        f"distinct audio cues referenced: {len(audio)}\n"
        "NOTE: the referenced art/audio/model BUNDLES live in the encrypted dat/ store and are\n"
        "NOT extracted here. This is the manifest of WHAT the scenario uses, by name/id.\n",
        encoding="utf-8")
    print(f"DONE: {len(picked)} tables, {sum(a and 1 for a in assets)} with asset refs, "
          f"{len(audio)} audio cues -> {out}")
    return {"tables": len(picked), "audio_cues": len(audio), "asset_tables": len(assets)}


def _selftest():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    dbp = tmp / "master.mdb"
    con = sqlite3.connect(dbp)
    con.execute("CREATE TABLE team_stadium_bgm (id INT, cue_name TEXT, cuesheet_name TEXT)")
    con.execute("INSERT INTO team_stadium_bgm VALUES (1,'snd_bgm_CS007_team','snd_bgm_CS007')")
    con.execute("CREATE TABLE single_mode_top_bg (id INT, scenario_id INT, bg_id INT, bgm_cue_name TEXT)")
    con.execute("INSERT INTO single_mode_top_bg VALUES (1,2,124,'snd_bgm_GM123_single'),(2,1,5,'other')")
    con.execute("CREATE TABLE unrelated (id INT, x INT)")
    con.execute("INSERT INTO unrelated VALUES (1,1)")
    con.execute("CREATE TABLE text_data (id INT, category INT, [index] INT, text TEXT)")  # for build_name_maps
    con.commit(); con.close()
    out = tmp / "unity_cup"
    r = collect(dbp, out)
    assert (out / "tables" / "team_stadium_bgm.json").exists()
    # scenario_id table only keeps scenario 2 rows
    tb = json.loads((out / "tables" / "single_mode_top_bg.json").read_text(encoding="utf-8"))
    assert len(tb) == 1 and tb[0]["scenario_id"] == 2, tb
    assert not (out / "tables" / "unrelated.json").exists(), "unrelated table leaked in"
    idx = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert "snd_bgm_CS007_team" in idx["audio_cues"] and "snd_bgm_GM123_single" in idx["audio_cues"], idx
    assert "other" not in idx["audio_cues"], "scenario-1 cue leaked in"
    print("collect_unity_cup selftest OK")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(default_db()))
    ap.add_argument("--out", default=str(Path(os.environ.get("USERPROFILE", str(Path.home()))) / "UmaMasterExport" / "unity_cup"))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    _selftest() if a.selftest else collect(a.db, a.out)
