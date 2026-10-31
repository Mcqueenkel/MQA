import json
import os
import contextlib
import sqlite3
from pathlib import Path


DIRECT_TABLES = [
    "skill_data",
    "single_mode_skill_need_point",
    "race",
    "race_course_set",
    "race_instance",
    "single_mode_program",
    "single_mode_fan_count",     # fan_set_id -> fans gained by finishing place (order 1 = win reward)
    "single_mode_scout_chara",
    "card_rarity_data",
    "available_skill_set",
    "support_card_data",
    "single_mode_route",        # chara_id -> race_set_id (career goal route)
    "single_mode_route_race",   # race_set_id -> per-turn goals (races + fan goals + finale)
    "single_mode_race_group",   # race_group_id -> race_program_id (a goal can target a GROUP of races)
    "single_mode_story_data",   # story_id -> owning support_card_id / card_id (event catalog)
    "succession_relation",         # relation_type -> relation_point (inheritance-affinity points)
    "succession_relation_member",  # chara_id -> relation_type (which charas share each affinity group)
    "single_mode_live_square",        # Grand Live Master Square: perf_type/perf_value = the COST
    "single_mode_live_master_bonus",  # square_id -> the reward it pays (gain_type + values)
    "single_mode_live_song_list",     # the 40xxx SONG squares + their live_bonus_type/value
]

TEXT_DATA_CATEGORIES = {
    "cat_4_text": 4,
    "cat_28_text": 28,
    "cat_47_text": 47,
    "cat_75_text": 75,
    "cat_147_text": 147,
    "cat_181_text": 181,
    "cat_209_text": 209,   # Grand Live Master Square titles
}


def _legacy_master_mdb_path():
    """Where master.mdb lived until the client moved it (AppData/LocalLow/Cygames/Umamusume)."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data).parent if local_app_data else Path.home() / "AppData"
    return base / "LocalLow" / "Cygames" / "Umamusume" / "master" / "master.mdb"


def _steam_library_roots():
    """Steam library roots to search: the install from the registry, the default location, and every
    extra library in libraryfolders.vdf (games are commonly installed to a second drive). Best-effort
    -- any lookup that fails is skipped, never raised."""
    roots = []
    try:
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    for name in ("SteamPath", "InstallPath"):
                        try:
                            roots.append(Path(winreg.QueryValueEx(handle, name)[0]))
                        except OSError:
                            pass
            except OSError:
                pass
    except Exception:
        pass                                            # non-Windows / no registry: fall through
    roots.append(Path(r"C:\Program Files (x86)\Steam"))

    out = []
    for root in roots:
        out.append(root)
        try:
            text = (root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line in text.splitlines():
            # entries look like:   "path"    "D:\\SteamLibrary"
            parts = line.split('"')
            if len(parts) >= 5 and parts[1] == "path":
                out.append(Path(parts[3].replace("\\\\", "\\")))
    seen, unique = set(), []
    for path in out:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def default_master_mdb_path():
    """Locate the GLOBAL client's master.mdb.

    The client MOVED this file. It used to live in AppData/LocalLow/Cygames/Umamusume/master; it now
    ships inside the Steam install at
        <library>/steamapps/common/UmamusumePrettyDerby/UmamusumePrettyDerby_Data/Persistent/master/
    Both are probed -- install first -- and the first that EXISTS wins, so either layout works and a
    future move only needs another candidate here.

    Deliberately does NOT fall back to the JP install (UmamusumePrettyDerby_Jpn). JP is a different
    game data-wise -- 169 charas / 543 support cards / 14 scenarios against Global's 95 / 238 / 4 --
    so regenerating data/*.json from it would have the bot choosing skills, races and cards that this
    account's server has never heard of. Silently wrong is worse than missing.
    """
    legacy = _legacy_master_mdb_path()
    candidates = [root / "steamapps" / "common" / "UmamusumePrettyDerby" /
                  "UmamusumePrettyDerby_Data" / "Persistent" / "master" / "master.mdb"
                  for root in _steam_library_roots()]
    candidates.append(legacy)
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return legacy      # nothing found: keep the historical path so the startup message stays familiar


def settings_path(base_dir):
    return Path(base_dir) / "settings.json"


def read_settings(base_dir):
    path = settings_path(base_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_settings(base_dir, settings):
    path = settings_path(base_dir)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def configured_master_mdb_path(base_dir):
    settings = read_settings(base_dir)
    configured = (settings.get("master_data") or {}).get("master_mdb_path")
    return Path(configured).expanduser() if configured else default_master_mdb_path()


def set_master_mdb_path(base_dir, master_mdb_path):
    settings = read_settings(base_dir)
    master_settings = settings.setdefault("master_data", {})
    master_settings["master_mdb_path"] = str(Path(master_mdb_path).expanduser())
    write_settings(base_dir, settings)
    return status(base_dir)


def path_access(path):
    try:
        return path.exists(), None
    except OSError as exc:
        return False, str(exc)


def status(base_dir):
    db_path = configured_master_mdb_path(base_dir)
    exists, access_error = path_access(db_path)
    return {
        "success": True,
        "master_mdb_path": str(db_path),
        "exists": exists,
        "access_error": access_error,
        "requires_user_action": not exists,
    }


def dump_table(cursor, table):
    cursor.execute(f'SELECT * FROM "{table}";')
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def dump_text_data_category(cursor, category):
    cursor.execute(
        'SELECT id, category, "index", text FROM text_data WHERE category = ?;',
        (category,),
    )
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def event_list_for_cards(base_dir, support_card_ids):
    """Story-event ids tied to the given support cards + their names (text_data
    category 181), read read-only from master.mdb. Used to pre-populate the EVENT
    CHOICES panel so the user can configure a deck's events up front."""
    ids = []
    for x in (support_card_ids or []):
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []
    db_path = configured_master_mdb_path(base_dir)
    if not Path(db_path).exists():
        return []
    out, seen = [], set()
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        placeholders = ",".join("?" for _ in ids)
        rows = con.execute(
            'SELECT s.story_id, s.support_card_id, t.text '
            'FROM single_mode_story_data s '
            'LEFT JOIN text_data t ON t.category = 181 AND t."index" = s.story_id '
            f'WHERE s.support_card_id IN ({placeholders}) '
            'ORDER BY s.support_card_id, s.story_id',
            ids,
        ).fetchall()
        con.close()
    except Exception:
        return out
    for story_id, card_id, name in rows:
        sid = str(story_id)
        if sid in seen:
            continue
        seen.add(sid)
        out.append({"story_id": sid, "support_card_id": int(card_id or 0), "event_name": name or ""})
    return out


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def text_map(rows):
    return {int(row["index"]): row.get("text", "") for row in rows if row.get("index") is not None}


def display_name(name):
    name = str(name or "").strip()
    if name.startswith("[") and "] " in name:
        return name.split("] ", 1)[1].strip()
    return name


def master_rows(master_data, name):
    return master_data.get("tables", {}).get(name) or master_data.get("text", {}).get(name) or []


def synthesize_skill_data(base_dir, master_data):
    data_dir = Path(base_dir) / "data"
    skill_names = text_map(master_rows(master_data, "cat_47_text"))
    skill_costs = {
        int(row["id"]): int(row.get("need_skill_point") or 0)
        for row in master_rows(master_data, "single_mode_skill_need_point")
        if row.get("id") is not None
    }
    skills = {}
    for row in master_rows(master_data, "skill_data"):
        skill_id = int(row.get("id") or 0)
        if not skill_id:
            continue
            
        tags = []
        raw_tags = str(row.get("tag_id") or "")
        if raw_tags:
            tags = [int(t) for t in raw_tags.split("/") if t.isdigit()]

        skills[str(skill_id)] = {
            "name": skill_names.get(skill_id, str(skill_id)),
            "rarity": int(row.get("rarity") or 0),
            "group_id": int(row.get("group_id") or 0),
            "grade_value": int(row.get("grade_value") or 0),
            "need_skill_point": skill_costs.get(skill_id, 0),
            "disable_singlemode": int(row.get("disable_singlemode") or 0),
            "tags": tags,
            "icon_id": int(row.get("icon_id") or 0),
            "skill_category": int(row.get("skill_category") or 0),
        }

    write_json(data_dir / "skill_data.json", skills)
    return {"file": "skill_data.json", "skills": len(skills)}


def synthesize_chara_list(base_dir, master_data):
    data_dir = Path(base_dir) / "data"
    names = text_map(master_rows(master_data, "cat_4_text"))
    rows_by_card_id = {}
    for row in master_rows(master_data, "card_rarity_data"):
        card_id = int(row.get("card_id") or 0)
        name = display_name(names.get(card_id, ""))
        if card_id and name:
            rows_by_card_id[card_id] = name

    chara = {}
    name_counts = {}
    for card_id, name in sorted(rows_by_card_id.items()):
        name_counts[name] = name_counts.get(name, 0) + 1
        count = name_counts[name]
        if count == 1:
            display = name
        elif count == 2:
            display = f"{name} (Alt)"
        else:
            display = f"{name} (Alt {count - 1})"
        chara[str(card_id)] = display

    if chara:
        write_json(data_dir / "chara_list.json", chara)
    return {"file": "chara_list.json", "rows": len(chara)}


def synthesize_support_list(base_dir, master_data):
    data_dir = Path(base_dir) / "data"
    names = text_map(master_rows(master_data, "cat_75_text"))
    rarity_map = {
        1: "R",
        2: "SR",
        3: "SSR",
    }
    command_type_map = {
        101: "Speed",
        102: "Power",
        103: "Guts",
        105: "Stamina",
        106: "Wisdom",
    }
    support_card_type_map = {
        2: "Friends",
        3: "Group",
    }
    supports = {}
    for row in master_rows(master_data, "support_card_data"):
        support_id = int(row.get("id") or 0)
        if not support_id:
            continue
        key = str(support_id)
        support_type = support_card_type_map.get(int(row.get("support_card_type") or 0))
        if not support_type:
            support_type = command_type_map.get(int(row.get("command_id") or 0), "")
        supports[key] = {
            "name": display_name(names.get(support_id, str(support_id))),
            "rarity": rarity_map.get(int(row.get("rarity") or 0), ""),
            "type": support_type,
        }
    if supports:
        write_json(data_dir / "support_list.json", supports)
    return {"file": "support_list.json", "rows": len(supports)}


GRADE_LABELS = {
    100: "G1",
    200: "G2",
    300: "G3",
    400: "OP",
    700: "PRE-OP",
}

TRACK_LABELS = {
    10001: "Sapporo",
    10002: "Hakodate",
    10003: "Niigata",
    10004: "Fukushima",
    10005: "Nakayama",
    10006: "Tokyo",
    10007: "Chukyo",
    10008: "Kyoto",
    10009: "Hanshin",
    10010: "Kokura",
    10101: "Ooi",
}

MONTH_LABELS = [
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

YEAR_LABELS = {
    0: "Junior Year",
    24: "Classic Year",
    48: "Senior Year",
}


def distance_label(distance):
    distance = int(distance or 0)
    if distance <= 1400:
        return "Sprint"
    if distance <= 1800:
        return "Mile"
    if distance <= 2400:
        return "Medium"
    return "Long"


def year_offsets_for_permission(race_permission):
    return {
        1: [0],
        2: [24],
        3: [24, 48],
        4: [48],
    }.get(int(race_permission or 0), [])


def race_date_label(month, half, year_offset):
    period = "Early" if int(half or 0) == 1 else "Late"
    return f"{YEAR_LABELS[year_offset]} {period} {MONTH_LABELS[int(month or 0)]}"


def race_turn(month, half, year_offset):
    return int(year_offset or 0) + (int(month or 0) - 1) * 2 + int(half or 0)


def race_occurrence_id(program_id, year_offset):
    year_key = {
        0: 1,
        24: 2,
        48: 3,
    }.get(int(year_offset or 0), 9)
    return year_key * 100000 + int(program_id or 0)


_ASCII_PUNCT = {
    0x2018: "'", 0x2019: "'",    # ' '  smart single quotes / apostrophe
    0x201C: '"', 0x201D: '"',    # " "  smart double quotes
    0x2013: "-", 0x2014: "-",    # - -  en / em dash
    0x2026: "...",               # ...  ellipsis
    0x00A0: " ",                 # nbsp -> normal space
}


def _ascii_punct(text):
    """Fold smart punctuation to ASCII so generated race names are console-safe: a raw U+2019 in a
    name (e.g. "JBC Ladies' Classic") mojibakes -- or raises UnicodeEncodeError -- when printed to a
    Windows cp1252 console, and can trip name-based matching. Valid UTF-8 either way; this just
    normalizes it to a portable ASCII form."""
    return (text or "").translate(_ASCII_PUNCT)


def build_race_context(master_data):
    race_names = text_map(master_rows(master_data, "cat_28_text"))
    races = {int(row.get("id") or 0): row for row in master_rows(master_data, "race")}
    course_sets = {int(row.get("id") or 0): row for row in master_rows(master_data, "race_course_set")}
    instances = {int(row.get("id") or 0): row for row in master_rows(master_data, "race_instance")}
    # Fans gained for finishing 1st (order == 1), keyed by the program's fan_set_id -- the "gain"
    # shown in the race picker. (need_fan_count is the ENTRY requirement, not a reward.)
    win_fans_by_set = {}
    for row in master_rows(master_data, "single_mode_fan_count"):
        if int(row.get("order") or 0) == 1:
            win_fans_by_set[int(row.get("fan_set_id") or 0)] = int(row.get("fan_count") or 0)
    programs = {}

    for row in master_rows(master_data, "single_mode_program"):
        program_id = int(row.get("id") or 0)
        race_instance_id = int(row.get("race_instance_id") or 0)
        if not program_id or not race_instance_id:
            continue
        instance = instances.get(race_instance_id, {})
        race = races.get(int(instance.get("race_id") or 0), {})
        course = course_sets.get(int(race.get("course_set") or 0), {})
        name = _ascii_punct(race_names.get(race_instance_id, str(race_instance_id)))
        programs[program_id] = {
            "program": row,
            "race_instance_id": race_instance_id,
            "race": race,
            "course": course,
            "name": name,
            "win_fans": win_fans_by_set.get(int(row.get("fan_set_id") or 0), 0),
            "entry_fans": int(row.get("need_fan_count") or 0),
        }
    return programs


def is_ui_selectable_race(info):
    program = info["program"]
    race = info["race"]
    name = info["name"]
    if int(program.get("base_program_id") or 0) != 0:
        return False
    if not year_offsets_for_permission(program.get("race_permission")):
        return False
    if int(race.get("grade") or 0) not in GRADE_LABELS:
        return False
    if "Make Debut" in name or "Maiden Race" in name:
        return False
    return True


def legacy_race_ids_by_occurrence(existing_meta):
    legacy = {}
    for key, value in (existing_meta or {}).items():
        try:
            race_id = int(key)
            program_id = int((value or {}).get("program_id") or 0)
            turn = int((value or {}).get("turn") or 0)
        except (TypeError, ValueError):
            continue
        if not race_id or not program_id or not turn:
            continue
        if race_id == program_id or race_id >= 100000:
            continue
        legacy.setdefault((program_id, turn), []).append(race_id)
    return {key: sorted(set(value)) for key, value in legacy.items()}


def synthesize_public_race_data(base_dir, race_context, existing_meta=None):
    races = []
    legacy_ids = legacy_race_ids_by_occurrence(existing_meta)
    for program_id, info in sorted(race_context.items()):
        if not is_ui_selectable_race(info):
            continue
        program = info["program"]
        race = info["race"]
        course = info["course"]
        month = int(program.get("month") or 0)
        half = int(program.get("half") or 0)
        for year_offset in year_offsets_for_permission(program.get("race_permission")):
            turn = race_turn(month, half, year_offset)
            row = {
                "id": race_occurrence_id(program_id, year_offset),
                "program_id": program_id,
                "turn": turn,
                "name": info["name"],
                "date": race_date_label(month, half, year_offset),
                "type": GRADE_LABELS.get(int(race.get("grade") or 0), ""),
                "terrain": "Dirt" if int(course.get("ground") or 0) == 2 else "Turf",
                "distance": distance_label(course.get("distance")),
                "venue": TRACK_LABELS.get(int(course.get("race_track_id") or 0), ""),
                "win_fans": info.get("win_fans", 0),      # fans for finishing 1st (the "gain")
                "entry_fans": info.get("entry_fans", 0),  # fans needed to enter (requirement)
            }
            row_legacy_ids = legacy_ids.get((program_id, turn), [])
            if row_legacy_ids:
                row["legacy_ids"] = row_legacy_ids
            races.append(row)

    def sort_key(item):
        year_offset = next(offset for offset, label in YEAR_LABELS.items() if item["date"].startswith(label))
        month = MONTH_LABELS.index(item["date"].split()[-1])
        half = 1 if " Early " in item["date"] else 2
        return (year_offset + (month - 1) * 2 + half, item["type"], item["name"], item["id"])

    races.sort(key=sort_key)
    path = Path(base_dir) / "public" / "assets" / "data" / "uma_race_data.json"
    write_json(path, {"races": races})
    return {"file": "public/assets/data/uma_race_data.json", "rows": len(races)}


def synthesize_race_map(base_dir, master_data):
    data_dir = Path(base_dir) / "data"
    existing = read_json(data_dir / "race_map.json", {})
    existing_public = read_json(Path(base_dir) / "public" / "assets" / "data" / "uma_race_data.json", {})
    race_context = build_race_context(master_data)
    programs = {}
    instances = {}
    meta = {}

    for program_id, info in sorted(race_context.items()):
        row = info["program"]
        race_instance_id = info["race_instance_id"]
        course = info["course"]
        month = int(row.get("month") or 0)
        half = int(row.get("half") or 0)
        programs[str(program_id)] = {
            "race_instance_id": race_instance_id,
            "month": month,
            "half": half,
            "name": info["name"],
            "ground": int(course.get("ground") or 0),
            "distance": int(course.get("distance") or 0),
            "entry_fans": int(info.get("entry_fans") or 0),   # fans required to ENTER (goal-eligibility)
            "win_fans": int(info.get("win_fans") or 0),        # fans awarded for a 1st-place finish
        }
        instances.setdefault(str(race_instance_id), []).append(program_id)
        for year_offset in year_offsets_for_permission(row.get("race_permission")):
            occurrence_id = race_occurrence_id(program_id, year_offset)
            meta[str(occurrence_id)] = {
                "program_id": program_id,
                "race_instance_id": race_instance_id,
                "turn": race_turn(month, half, year_offset),
                "name": info["name"],
            }

    if programs:
        public_result = synthesize_public_race_data(base_dir, race_context, existing.get("meta") or {})
        current_public = read_json(Path(base_dir) / "public" / "assets" / "data" / "uma_race_data.json", {})
        generated_by_key = {
            (row["name"], row["date"]): row
            for row in current_public.get("races", [])
        }
        for row in existing_public.get("races", []):
            generated = generated_by_key.get((row.get("name"), row.get("date")))
            if not generated:
                continue
            legacy_id = int(row.get("id") or 0)
            program_id = int(generated.get("program_id") or generated.get("id") or 0)
            if not legacy_id or not program_id or legacy_id == program_id:
                continue
            info = race_context.get(program_id)
            if not info:
                continue
            program = info["program"]
            year_offset = next(offset for offset, label in YEAR_LABELS.items() if row["date"].startswith(label))
            turn = race_turn(program.get("month"), program.get("half"), year_offset)
            meta[str(legacy_id)] = {
                "program_id": program_id,
                "race_instance_id": info["race_instance_id"],
                "turn": turn,
                "name": info["name"],
            }

        for key, value in (existing.get("meta") or {}).items():
            if str(key) in meta:
                continue
            program_id = int((value or {}).get("program_id") or 0)
            if program_id in race_context:
                meta[str(key)] = value

        output = {
            "meta": meta,
            "program": programs,
            "instance": {key: sorted(value) for key, value in instances.items()},
        }
        write_json(data_dir / "race_map.json", output)
        return {
            "file": "race_map.json",
            "programs": len(programs),
            "instances": len(instances),
            "meta": len(meta),
            "public_races": public_result["rows"],
        }

    write_json(data_dir / "race_map.json", existing)
    return {"file": "race_map.json", "programs": 0, "instances": 0, "preserved_existing": bool(existing)}


def factor_category(factor_id):
    text = str(factor_id)
    if len(text) == 3:
        return "stat"
    if len(text) == 4:
        return "aptitude"
    if len(text) == 7:
        if text.startswith("1"):
            return "race"
        if text.startswith("2"):
            return "skill"
        if text.startswith("3"):
            return "scenario"
    if len(text) == 8:
        return "unique"
    return "other"


def synthesize_factor_map(base_dir, master_data):
    data_dir = Path(base_dir) / "data"
    factors = {}
    for row in master_rows(master_data, "cat_147_text"):
        factor_id = int(row.get("index") or 0)
        if not factor_id:
            continue
        factors[str(factor_id)] = {
            "name": row.get("text", ""),
            "stars": factor_id % 10,
            "category": factor_category(factor_id),
        }

    if factors:
        write_json(data_dir / "factor_map.json", factors)
    return {"file": "factor_map.json", "rows": len(factors)}


_GOAL_REQUIRE = {0: "Complete", 1: "WIN (1st)", 2: "Top 2", 3: "Top 3", 4: "Top 4", 5: "Top 5"}


def goal_require(rank):
    rank = int(rank or 0)
    return _GOAL_REQUIRE.get(rank, f"Top {rank}")


def synthesize_career_goals(base_dir, master_data):
    """Per-character career goal route -> data/career_goals.json, keyed by base chara_id.

    Each goal row (single_mode_route_race) is one of three kinds, distinguished so a fan goal
    is NEVER mis-rendered as a placement race (the historical `#0`/`Top 3000` bug):
      - condition_type == 3 -> fan-count goal   -> {kind:"fan", fans:N}
      - target_type == 3    -> scenario finale  -> {kind:"finale", race:"URA Finals"}
      - otherwise           -> placement race   -> {kind:"race", program_id, race name, Top N}
    """
    data_dir = Path(base_dir) / "data"
    programs = build_race_context(master_data)            # program_id -> {name, race, course, ...}
    names = text_map(master_rows(master_data, "cat_4_text"))

    # base chara_id -> display name (from that chara's lowest card_id, i.e. the base card)
    chara_names, chara_min_card = {}, {}
    for row in master_rows(master_data, "card_rarity_data"):
        card_id = int(row.get("card_id") or 0)
        if not card_id:
            continue
        base = card_id // 100
        if base not in chara_min_card or card_id < chara_min_card[base]:
            chara_min_card[base] = card_id
            chara_names[base] = display_name(names.get(card_id, ""))

    # chara_id -> race_set_id, preferring the universal (scenario_id 0) base route
    chara_route = {}
    for row in master_rows(master_data, "single_mode_route"):
        chara_id = int(row.get("chara_id") or 0)
        race_set_id = int(row.get("race_set_id") or 0)
        if not chara_id or not race_set_id:
            continue
        prio = 0 if int(row.get("scenario_id") or 0) == 0 else 1
        if chara_id not in chara_route or prio < chara_route[chara_id][0]:
            chara_route[chara_id] = (prio, race_set_id)

    rows_by_set = {}
    for row in master_rows(master_data, "single_mode_route_race"):
        race_set_id = int(row.get("race_set_id") or 0)
        if race_set_id:
            rows_by_set.setdefault(race_set_id, []).append(row)

    # race_group_id -> [race_program_id]: a goal row with race_type 4 targets a GROUP of races
    # ("place in any of these"), so its condition_id must be expanded, not used as a program_id.
    race_groups = {}
    for row in master_rows(master_data, "single_mode_race_group"):
        gid = int(row.get("race_group_id") or 0)
        pid = int(row.get("race_program_id") or 0)
        if gid and pid:
            race_groups.setdefault(gid, []).append(pid)

    goals_out = {}
    for chara_id, (_, race_set_id) in chara_route.items():
        rows = rows_by_set.get(race_set_id) or []
        if not rows:
            continue
        goals = []
        for row in sorted(rows, key=lambda r: (int(r.get("turn") or 0), int(r.get("sort_id") or 0))):
            turn = int(row.get("turn") or 0)
            condition_type = int(row.get("condition_type") or 0)
            target_type = int(row.get("target_type") or 0)
            value = int(row.get("condition_value_1") or 0)
            if condition_type == 3:
                goals.append({"turn": turn, "kind": "fan", "fans": value, "require": f"{value:,} fans"})
            elif target_type == 3:
                goals.append({"turn": turn, "kind": "finale", "race": "URA Finals", "require": "WIN (1st)"})
            else:
                cond_id = int(row.get("condition_id") or 0)
                member_ids = race_groups.get(cond_id) or []
                if int(row.get("race_type") or 0) == 4 and member_ids:
                    # race_type 4 => condition_id is a RACE GROUP, not a program. The goal is "place in
                    # ANY of these". Writing the group id as a program_id produced a phantom race the
                    # bot could never enter, so the goal silently failed the career (live: Copano
                    # Rickey turn 69, group 20003 = the four JBC Classic variants -> failed at 69).
                    first = programs.get(member_ids[0]) or {}
                    goals.append({
                        "turn": turn,
                        "kind": "race",
                        "race": first.get("name") or f"race group {cond_id}",
                        "program_id": member_ids[0],      # back-compat: a single usable id
                        "program_ids": member_ids,        # ...and every race that satisfies the goal
                        "require": goal_require(value),
                    })
                elif cond_id in programs:
                    goals.append({
                        "turn": turn,
                        "kind": "race",
                        "race": programs[cond_id].get("name") or f"program {cond_id}",
                        "program_id": cond_id,
                        "require": goal_require(value),
                    })
                else:
                    # condition_id resolves to NEITHER a program nor a race group (e.g. condition_type
                    # 2, the character-unique "win N of a category" goals). Emitting it as a race gave
                    # a phantom the bot chased and never found -- record it as UNKNOWN instead so the
                    # goal picker ignores it rather than burning the turn on a wrong race.
                    goals.append({
                        "turn": turn,
                        "kind": "unknown",
                        "race": f"unresolved goal (condition_type {condition_type}, id {cond_id})",
                        "condition_type": condition_type,
                        "condition_id": cond_id,
                        "require": goal_require(value),
                    })
        goals_out[str(chara_id)] = {"name": chara_names.get(chara_id) or str(chara_id), "goals": goals}

    if goals_out:
        write_json(data_dir / "career_goals.json", goals_out)
    return {"file": "career_goals.json", "charas": len(goals_out)}


def synthesize_support_events(base_dir, master_data):
    """Full per-support-card event catalog -> data/support_events.json, keyed by support_card_id:
    {name, events: [{story_id, title}]}. Titles come from text_data category 181 (keyed by story_id);
    which card owns an event comes from single_mode_story_data.support_card_id. master.mdb has NO
    choice text and NO outcomes (those live in the story-timeline assets) -- this file is the
    name<->story_id bridge for matching an external outcomes dataset (e.g. GameTora) to the live
    event ids the API sends, and for showing a deck's events by name."""
    data_dir = Path(base_dir) / "data"
    titles = text_map(master_rows(master_data, "cat_181_text"))
    card_names = text_map(master_rows(master_data, "cat_75_text"))
    out, seen = {}, set()
    for row in master_rows(master_data, "single_mode_story_data"):
        scid = int(row.get("support_card_id") or 0)
        story_id = int(row.get("story_id") or 0)
        if not scid or not story_id or (scid, story_id) in seen:  # variant rows repeat a story_id
            continue
        seen.add((scid, story_id))
        entry = out.setdefault(str(scid), {"name": card_names.get(scid, ""), "events": []})
        entry["events"].append({"story_id": str(story_id), "title": titles.get(story_id, "")})
    for entry in out.values():
        entry["events"].sort(key=lambda e: e["story_id"])
    write_json(data_dir / "support_events.json", out)
    return {"file": "support_events.json", "support_cards": len(out),
            "events": sum(len(v["events"]) for v in out.values())}


def synthesize_legacy_jsons(base_dir, master_data):
    generated = [
        synthesize_skill_data(base_dir, master_data),
        synthesize_chara_list(base_dir, master_data),
        synthesize_support_list(base_dir, master_data),
        synthesize_race_map(base_dir, master_data),
        synthesize_factor_map(base_dir, master_data),
        synthesize_career_goals(base_dir, master_data),
        synthesize_support_events(base_dir, master_data),
        synthesize_succession_relation(base_dir, master_data),
        synthesize_grand_live_squares(base_dir, master_data),
    ]

    return {"generated": generated, "preserved": []}


def synthesize_grand_live_squares(base_dir, master_data):
    """Grand Live Master Square catalog -> data/grand_live_squares.json.

    Each square COSTS performance points (perf_type_N/perf_value_N) and PAYS a master bonus. Verified
    against the in-game panel: Makeup Basics = cost Visual 10 -> Guts +5; Vocal Training Basics =
    cost Vocal 10 -> Power +5. Claiming a square you cannot pay for is answered 205, so the strategy
    needs the costs at runtime to pick only affordable squares (scenarios/grand_live.py::can_afford).

    gain_type: 1 = stat gain (gain[0] = stat id 1 Spd / 2 Sta / 3 Pwr / 4 Guts / 5 Wit / 6 SP,
    gain[2] = amount), 2 = skill hint, 3 = energy recovery, 5 = song/live bonus.
    """
    data_dir = Path(base_dir) / "data"
    perf_name = {1: "dance", 2: "passion", 3: "vocal", 4: "visual", 5: "mental"}
    titles = text_map(master_rows(master_data, "cat_209_text"))
    bonuses = {int(b.get("id") or 0): b for b in master_rows(master_data, "single_mode_live_master_bonus")}

    squares = {}
    for row in master_rows(master_data, "single_mode_live_square"):
        sid = int(row.get("id") or 0)
        if not sid:
            continue
        cost = {}
        for i in range(1, 6):
            ptype, pval = row.get(f"perf_type_{i}"), row.get(f"perf_value_{i}")
            if ptype and pval:
                cost[perf_name.get(int(ptype), str(ptype))] = int(pval)
        bonus = bonuses.get(int(row.get("master_bonus_id") or 0)) or {}
        squares[str(sid)] = {
            "name": titles.get(int(row.get("square_title_text_id") or 0), ""),
            "type": row.get("square_type"),
            "cost": cost,
            "gain_type": bonus.get("master_bonus_gain_type_1"),
            "gain": [bonus.get("master_bonus_gain_value_1_1"),
                     bonus.get("master_bonus_gain_value_1_2"),
                     bonus.get("master_bonus_gain_value_1_3")],
        }
    write_json(data_dir / "grand_live_squares.json", {"schema": 1, "squares": squares})
    return {"file": "grand_live_squares.json", "squares": len(squares)}


def synthesize_succession_relation(base_dir, master_data):
    """succession_relation.json + succession_relation_member.json -- the inheritance-AFFINITY
    (compatibility) tables. The start-succession estimator uses these to compute the exact
    current_succession_rank_point from the parent+grandparent relation graph, instead of the crude
    rank_score//divisor guess the 102-sweep then tries (and often can't) to correct."""
    data_dir = Path(base_dir) / "data"
    rel = [{"relation_type": r.get("relation_type"), "relation_point": r.get("relation_point")}
           for r in (master_data["tables"].get("succession_relation") or [])]
    mem = [{"chara_id": r.get("chara_id"), "relation_type": r.get("relation_type")}
           for r in (master_data["tables"].get("succession_relation_member") or [])]
    write_json(data_dir / "succession_relation.json", rel)
    write_json(data_dir / "succession_relation_member.json", mem)
    return {"file": "succession_relation.json", "relations": len(rel), "members": len(mem)}


def load_master_data(cursor, existing_tables):
    master_data = {"tables": {}, "text": {}}
    extracted = []
    skipped = []

    for table in DIRECT_TABLES:
        if table not in existing_tables:
            skipped.append(table)
            continue
        rows = dump_table(cursor, table)
        master_data["tables"][table] = rows
        extracted.append({"table": table, "rows": len(rows)})

    if "text_data" in existing_tables:
        for filename, category in TEXT_DATA_CATEGORIES.items():
            rows = dump_text_data_category(cursor, category)
            master_data["text"][filename] = rows
            extracted.append({"table": filename, "rows": len(rows)})
    else:
        skipped.extend(TEXT_DATA_CATEGORIES)

    return master_data, extracted, skipped


def generate(base_dir, master_mdb_path=None):
    db_path = Path(master_mdb_path).expanduser() if master_mdb_path else configured_master_mdb_path(base_dir)
    exists, access_error = path_access(db_path)
    if not exists:
        detail = f"master.mdb not found at {db_path}"
        if access_error:
            detail = f"master.mdb could not be accessed at {db_path}: {access_error}"
        return {
            **status(base_dir),
            "success": False,
            "detail": detail,
        }

    with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        existing_tables = {row[0] for row in cursor.fetchall()}
        master_data, extracted, skipped = load_master_data(cursor, existing_tables)

    legacy = synthesize_legacy_jsons(base_dir, master_data)
    return {
        **status(base_dir),
        "success": True,
        "extracted": extracted,
        "skipped": skipped,
        "legacy": legacy,
    }
