"""Per-trainee career-goal solver.

Given a trainee CARD, cross its base aptitudes (data/card_aptitudes.json) with its character's unique
career goals (data/career_goals.json) and race distances (data/race_map.json -> program) to produce a
plan: per-goal aptitude fit + risk, a recommended running style, stat priorities, fan-farm suggestions,
and an overall solvability score.

Pure and offline -- no game or network. Career goals are shared per CHARACTER (card_id // 100); base
aptitudes are per CARD, so two cards of the same uma can get very different plans. The pure scoring
helpers are unit-tested in tests/test_goal_solver.py.
"""
import json
import os

# repo root: this file lives at career_bot/core/, so three dirnames up (was two before the core/ move)
BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
DATA = os.path.join(BASE_DIR, "data")

GRADE = {1: "G", 2: "F", 3: "E", 4: "D", 5: "C", 6: "B", 7: "A", 8: "S"}
STYLE_LABEL = {"nige": "Front-runner", "senko": "Pace-chaser", "sashi": "Late-surger", "oikomi": "End-closer"}
RISK_W = {"low": 0, "medium": 1, "high": 2}


def _grade(v):
    return GRADE.get(int(v or 0), "?")


def distance_band(distance):
    d = int(distance or 0)
    if d <= 1400:
        return "short"
    if d <= 1800:
        return "mile"
    if d <= 2400:
        return "middle"
    return "long"


def placement_demand(require):
    """1 (just finish) .. 5 (must win) from a goal's require string."""
    r = str(require or "").lower()
    if "top 1" in r or "win" in r or "1st" in r:
        return 5
    if "top 2" in r:
        return 4
    if "top 3" in r:
        return 3
    if "top 5" in r:
        return 2
    return 1  # Complete / debut / just show up


def goal_fit(distance_apt, ground_apt):
    """strong = both aptitudes >= A, ok = both >= B, weak = anything below B."""
    m = min(int(distance_apt or 0), int(ground_apt or 0))
    if m >= 7:
        return "strong"
    if m >= 6:
        return "ok"
    return "weak"


def goal_risk(fit, demand):
    if fit == "weak" and demand >= 3:
        return "high"
    if fit == "weak" or (fit == "ok" and demand >= 4):
        return "medium"
    return "low"


def stat_priority(bands, style):
    """Order [speed, stamina, power, guts, wit] by weight from the goal distance mix + running style."""
    w = {"speed": 3.0, "stamina": 1.0, "power": 1.5, "guts": 0.5, "wit": 1.0}  # baselines
    for b in bands:
        if b == "short":
            w["speed"] += 1.0; w["power"] += 1.0
        elif b == "mile":
            w["speed"] += 1.0; w["power"] += 0.7; w["stamina"] += 0.3
        elif b == "middle":
            w["speed"] += 0.7; w["stamina"] += 1.0; w["power"] += 0.5
        elif b == "long":
            w["stamina"] += 1.6; w["guts"] += 0.4
    if style == "nige":
        w["speed"] += 0.5
    elif style == "oikomi":
        w["power"] += 0.5; w["wit"] += 0.3
    return [s for s, _ in sorted(w.items(), key=lambda kv: -kv[1])]


def recommended_style(apt):
    styles = {k: int(apt.get(k) or 0) for k in ("nige", "senko", "sashi", "oikomi")}
    best = max(styles, key=styles.get)
    return best, STYLE_LABEL[best], _grade(styles[best])


def solve_card(card_id, goals, apt, programs):
    """apt = a card_aptitudes entry; goals = a career_goals[..]['goals'] list; programs = race_map['program']."""
    a = apt.get("aptitude") or {}
    solved, bands = [], []
    for g in goals:
        pinfo = programs.get(str(g.get("program_id") or "")) or {}
        dist = int(pinfo.get("distance") or 0)
        ground = int(pinfo.get("ground") or 1)  # 1 = turf, 2 = dirt
        band = distance_band(dist) if dist else None
        d_apt = a.get(band) if band else None
        g_apt = a.get("dirt") if ground == 2 else a.get("turf")
        demand = placement_demand(g.get("require"))
        if g.get("kind") == "race" and band:
            fit = goal_fit(d_apt, g_apt)
            risk = goal_risk(fit, demand)
            bands.append(band)
        else:
            fit, risk = None, "low"
        solved.append({
            "turn": g.get("turn"), "race": g.get("race"), "kind": g.get("kind"),
            "require": g.get("require"),
            "distance": dist or None, "ground": ("dirt" if ground == 2 else "turf") if dist else None,
            "band": band, "distance_apt": _grade(d_apt) if band else None,
            "ground_apt": _grade(g_apt) if dist else None, "fit": fit, "risk": risk,
        })

    style_key, style_label, style_grade = recommended_style(a)
    stat_pri = stat_priority(bands, style_key)

    # bands the card is A+ in but goals barely use -> good fan/spark farming lanes
    strong = [b for b in ("short", "mile", "middle", "long") if int(a.get(b) or 0) >= 7]
    farm = [b for b in strong if bands.count(b) <= 1]

    race_goals = [sg for sg in solved if sg["fit"]]
    penalty = sum(RISK_W[sg["risk"]] * placement_demand(sg["require"]) for sg in race_goals)
    max_pen = sum(2 * placement_demand(sg["require"]) for sg in race_goals) or 1
    score = round(100 * (1 - penalty / max_pen))
    high = [f"{sg['race']}: needs {sg['require']} but {sg['band']} aptitude is {sg['distance_apt']}"
            for sg in race_goals if sg["risk"] == "high"]

    return {
        "card_id": int(card_id), "chara_id": apt.get("chara_id"),
        "aptitude_grades": {k: _grade(v) for k, v in a.items()},
        "recommended_style": {"key": style_key, "label": style_label, "grade": style_grade},
        "stat_priority": stat_pri,
        "goals": solved,
        "fan_farm_bands": farm,
        "solvability": {
            "score": score,
            "verdict": "easy" if score >= 85 else "workable" if score >= 60 else "hard",
            "high_risk_goals": high,
        },
    }


def _load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


def solve_all():
    """Solve every card that has both aptitudes and a character with career goals."""
    goals_by_chara = _load("career_goals.json")   # keyed by chara_id
    apts = _load("card_aptitudes.json")            # keyed by card_id
    programs = (_load("race_map.json").get("program") or {})
    out = {}
    for card_id, apt in apts.items():
        entry = goals_by_chara.get(str(apt.get("chara_id")))
        if not entry:
            continue
        plan = solve_card(card_id, entry.get("goals") or [], apt, programs)
        plan["name"] = entry.get("name")
        out[card_id] = plan
    return out


def solve(card_id):
    """Solve a single card by id (int or str)."""
    apts = _load("card_aptitudes.json")
    apt = apts.get(str(card_id))
    if not apt:
        return None
    entry = _load("career_goals.json").get(str(apt.get("chara_id"))) or {}
    programs = (_load("race_map.json").get("program") or {})
    plan = solve_card(card_id, entry.get("goals") or [], apt, programs)
    plan["name"] = entry.get("name")
    return plan


def main():
    out = solve_all()
    path = os.path.join(DATA, "career_solver.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {path} -- {len(out)} trainee plans")


if __name__ == "__main__":
    main()
