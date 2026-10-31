"""Export the game's master.mdb (the UNENCRYPTED data layer) to a browsable folder tree,
with id->name lookups resolved from text_data.

master.mdb is plain SQLite that the bot already reads. It holds the DATA -- characters, skills,
races, support cards, the whole text_data string table, the single_mode/* scenario mechanics --
but NONE of the encrypted art/audio/model bundles.

Names live in text_data keyed by (category, index=id). Which category names which entity is
DISCOVERED dynamically (the category that covers >=90% of the entity's ids, shortest text = the
display name), so it survives game updates instead of hardcoding version-fragile category numbers.

Layout:
  <out>/tables/<group>/<table>.json                     every table, grouped by name prefix
  <out>/tables/text/text_data_by_category/cat_<n>.json  text_data split by its categories
  <out>/by_scenario/<scenario>/<table>.json             the scenario_id tables, per scenario
  <out>/_lookups/<entity>_names.json                     {id: name} for chara/skill/card/race/...
  <out>/index.json + README.txt
Each row also gets a `name` (for entity tables) and `<col>_name` (for chara_id/skill_id/... FKs).

Run:  python scripts/export_master_data.py            (auto-finds master.mdb)
      python scripts/export_master_data.py --out D:/UmaData --db path/to/master.mdb
      python scripts/export_master_data.py --selftest  (no game needed)

ponytail: JSON per table, plain dicts, one dynamic discovery pass. Want SQL/Parquet? swap the
writer, keep the grouping + name maps.
"""
import argparse
import json
import os
import sqlite3
from pathlib import Path

# scenario_id domain in master.mdb == the bot's scenarios. 0 = common/none.
SCENARIOS = {0: "0_common", 1: "1_ura_finale", 2: "2_aoharu_unity", 4: "4_mant_trackblazer"}

# longest-prefix-wins grouping so single_mode_* / race_jikkyo_* don't collapse to "single"/"race"
_GROUP_PREFIXES = (
    "single_mode", "race_jikkyo", "support_card", "character_system", "story_event",
    "chara", "skill", "race", "succession", "story", "gacha", "mission", "item",
    "live", "honor", "home", "text",
)

# entity -> the table whose primary key a name category must cover (name category is discovered)
NAME_ENTITIES = {
    "chara": "chara_data", "skill": "skill_data", "support_card": "support_card_data",
    "race": "race_instance", "item": "item_data",
    "succession_factor": "succession_factor", "mission": "mission_data",
}
# FK column suffix -> entity, most-specific first (so support_card_id beats card_id / chara_id)
FK_COLS = [
    ("support_card_id", "support_card"), ("race_instance_id", "race"),
    ("succession_factor_id", "succession_factor"), ("mission_id", "mission"),
    ("chara_id", "chara"), ("skill_id", "skill"), ("item_id", "item"),
]
ENTITY_TABLE = {v: k for k, v in NAME_ENTITIES.items()}  # table -> entity (for its own `name`)


def default_db():
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / \
        "AppData/LocalLow/Cygames/Umamusume/master/master.mdb"


def group_of(table):
    for p in _GROUP_PREFIXES:
        if table == p or table.startswith(p + "_"):
            return p
    return table.split("_")[0] or "misc"


def _json_default(o):
    return o.hex() if isinstance(o, (bytes, bytearray)) else str(o)


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, default=_json_default, indent=1),
                    encoding="utf-8")


def _idcol(cur, table):
    cols = [c[1] for c in cur.execute(f"PRAGMA table_info('{table}')")]
    return "id" if "id" in cols else cols[0]


def build_name_maps(cur):
    """Discover the name category per entity and return ({entity: {id: name}}, {entity: category})."""
    if not cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='text_data'").fetchone():
        return {}, {}
    cats = {}
    for cat, idx, txt in cur.execute("SELECT category,[index],text FROM text_data"):
        d = cats.setdefault(cat, {"idx": {}, "len": 0, "n": 0})
        d["idx"][idx] = txt
        d["len"] += len(txt or "")
        d["n"] += 1
    name_maps, picked = {}, {}
    for ent, table in NAME_ENTITIES.items():
        try:
            if not cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                continue
            idc = _idcol(cur, table)
            ids = {r[0] for r in cur.execute(f"SELECT DISTINCT {idc} FROM '{table}'")}
        except Exception:
            continue
        if not ids:
            continue
        scored = [(c, len(ids & set(d["idx"])) / len(ids), d["len"] / max(1, d["n"]))
                  for c, d in cats.items()]
        scored = [s for s in scored if s[1] >= 0.9]
        if not scored:
            continue
        best = max(scored, key=lambda h: (round(h[1], 3), -h[2]))[0]  # max coverage, then shortest text
        picked[ent] = best
        name_maps[ent] = {i: cats[best]["idx"][i] for i in ids
                          if cats[best]["idx"].get(i) not in (None, "")}
    return name_maps, picked


def enrich_rows(rows, cols, table, name_maps):
    """Add `name` (entity's own id) and `<col>_name` (FK columns) to each row, in place."""
    ent_self = ENTITY_TABLE.get(table)
    self_idc = ("id" if "id" in cols else (cols[0] if cols else None)) if ent_self else None
    fks = []
    for col in cols:
        for suffix, ent in FK_COLS:
            if (col == suffix or col.endswith("_" + suffix)) and col != self_idc:
                fks.append((col, ent))
                break
    if not ent_self and not fks:
        return
    for r in rows:
        if ent_self and self_idc in r:
            nm = name_maps.get(ent_self, {}).get(r.get(self_idc))
            if nm is not None:
                r["name"] = nm
        for col, ent in fks:
            nm = name_maps.get(ent, {}).get(r.get(col))
            if nm is not None:
                r[col + "_name"] = nm


def export(db_path, out_dir):
    db_path, out = Path(db_path), Path(out_dir)
    if not db_path.exists():
        raise FileNotFoundError(f"master.mdb not found: {db_path}")
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro&immutable=1", uri=True)
    cur = con.cursor()
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

    name_maps, picked = build_name_maps(cur)
    for ent, m in name_maps.items():
        _write_json(out / "_lookups" / f"{ent}_names.json", {str(k): v for k, v in m.items()})

    index, total_rows, scen_count, text_split, enriched = {}, 0, 0, 0, 0
    for i, t in enumerate(tables, 1):
        try:
            cols = [c[1] for c in cur.execute(f"PRAGMA table_info('{t}')")]
            rows = [dict(zip(cols, r)) for r in cur.execute(f"SELECT * FROM '{t}'")]
        except Exception as e:
            index[t] = {"error": str(e)}
            print(f"  [{i}/{len(tables)}] {t}: SKIP ({e})")
            continue
        before = sum(len(r) for r in rows)
        enrich_rows(rows, cols, t, name_maps)
        if sum(len(r) for r in rows) > before:
            enriched += 1
        grp = group_of(t)
        _write_json(out / "tables" / grp / f"{t}.json", rows)
        total_rows += len(rows)
        entry = {"rows": len(rows), "group": grp, "columns": cols}

        if "scenario_id" in cols:
            buckets = {}
            for r in rows:
                buckets.setdefault(r.get("scenario_id"), []).append(r)
            wrote = []
            for sid, brows in buckets.items():
                name = SCENARIOS.get(sid, f"{sid}_other")
                _write_json(out / "by_scenario" / name / f"{t}.json", brows)
                wrote.append(name)
                scen_count += 1
            entry["scenarios"] = sorted(wrote)

        if t == "text_data" and "category" in cols:
            byc = {}
            for r in rows:
                byc.setdefault(r.get("category"), []).append(r)
            for cat, crows in byc.items():
                _write_json(out / "tables" / "text" / "text_data_by_category" / f"cat_{cat}.json", crows)
                text_split += 1
            entry["text_categories"] = len(byc)

        index[t] = entry
        if i % 50 == 0 or i == len(tables):
            print(f"  [{i}/{len(tables)}] tables done, {total_rows:,} rows so far")
    con.close()

    _write_json(out / "index.json", {"tables": index, "name_categories": picked,
                                     "lookups": {e: len(m) for e, m in name_maps.items()}})
    lk = "  ".join(f"{e}={len(m)}" for e, m in name_maps.items())
    (out / "README.txt").write_text(
        "Umamusume master.mdb export (DATA layer only -- no encrypted art/audio/models).\n\n"
        f"source : {db_path}\n"
        f"tables : {len(tables)}\n"
        f"rows   : {total_rows:,}\n\n"
        "layout:\n"
        "  tables/<group>/<table>.json                    every table, grouped by name\n"
        "  tables/text/text_data_by_category/cat_<n>.json text_data split by category\n"
        "  by_scenario/<name>/<table>.json                scenario_id tables per scenario\n"
        "  _lookups/<entity>_names.json                   {id: name} maps\n"
        "  index.json                                     tables + name_categories + lookup sizes\n\n"
        f"id->name: rows carry `name` (entity tables) and `<col>_name` (chara_id/skill_id/... FKs).\n"
        f"lookup sizes: {lk}\n"
        f"name categories (text_data): {picked}\n\n"
        "scenarios: 0=common  1=URA Finale  2=Aoharu/Unity  4=MANT/Trackblazer\n",
        encoding="utf-8")
    print(f"\nDONE: {len(tables)} tables, {total_rows:,} rows -> {out}")
    print(f"  scenario-split: {scen_count} | text categories: {text_split} | "
          f"tables name-enriched: {enriched} | lookups: {lk}")
    return {"tables": len(tables), "rows": total_rows, "out": str(out),
            "name_categories": picked, "enriched": enriched}


def _selftest():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    dbp = tmp / "master.mdb"
    con = sqlite3.connect(dbp)
    con.execute("CREATE TABLE chara_data (id INT, foo TEXT)")
    con.execute("INSERT INTO chara_data VALUES (1001,'a'),(1002,'b')")
    con.execute("CREATE TABLE text_data (id INT, category INT, [index] INT, text TEXT)")
    con.executemany("INSERT INTO text_data VALUES (?,?,?,?)", [
        (1, 6, 1001, "Alpha"), (2, 6, 1002, "Beta"),                          # cat 6 = short names
        (3, 99, 1001, "a long descriptive sentence"), (4, 99, 1002, "another long one"),  # cat 99 = desc
        (5, 5, 0, "x"), (6, 9, 0, "y")])                                      # for category-split
    con.execute("CREATE TABLE some_fk (id INT, scenario_id INT, chara_id INT)")
    con.execute("INSERT INTO some_fk VALUES (1,1,1001),(2,4,1002)")
    con.commit(); con.close()
    out = tmp / "export"
    r = export(dbp, out)
    # name category picked = 6 (100% coverage, shorter than the 99 descriptions)
    assert r["name_categories"].get("chara") == 6, r["name_categories"]
    # {id: name} lookup written
    lk = json.loads((out / "_lookups" / "chara_names.json").read_text(encoding="utf-8"))
    assert lk == {"1001": "Alpha", "1002": "Beta"}, lk
    # entity table rows carry `name`
    cd = json.loads((out / "tables" / "chara" / "chara_data.json").read_text(encoding="utf-8"))
    assert {r["id"]: r.get("name") for r in cd} == {1001: "Alpha", 1002: "Beta"}, cd
    # FK column resolved to <col>_name
    fk = json.loads((out / "tables" / "some" / "some_fk.json").read_text(encoding="utf-8"))
    assert fk[0]["chara_id_name"] == "Alpha" and fk[1]["chara_id_name"] == "Beta", fk
    # unchanged behaviour: scenario split + text categories still there
    assert (out / "by_scenario" / "1_ura_finale" / "some_fk.json").exists()
    assert (out / "tables" / "text" / "text_data_by_category" / "cat_6.json").exists()
    print("export_master_data selftest OK (id->name lookups + enrichment verified)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(default_db()))
    ap.add_argument("--out", default=str(Path(os.environ.get("USERPROFILE", str(Path.home()))) / "UmaMasterExport"),
                    help="output folder (default: %USERPROFILE%\\UmaMasterExport -- outside OneDrive & the repo)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    _selftest() if a.selftest else export(a.db, a.out)
