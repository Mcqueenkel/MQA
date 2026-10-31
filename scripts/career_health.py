"""Post-run health check: did the bot spend its turns well?

One table per career -- training distribution, wasted turns, final stats, rank. This is the view
that caught a real regression: after Wit-over-rest shipped, Speed trainings fell 15 -> 9 while Wit
rose 21 -> 30, final Speed collapsed 1082 -> 774 and the run dropped A+ -> A, all while the rest
count sat unchanged at 5. None of that is visible from the rank alone.

WHAT TO LOOK AT
  Spd/Wit/other  trainings by facility. For a Speed build, Speed should lead. If a support facility
                 overtakes it, something is diverting live turns (that was the bug above).
  rest           turns that produced ~0 stats. Measured cost: a MANT rest yields 13.0 stats against
                 40.8 for a training and 42.6 for a race. Some rest is correct -- it banks the
                 energy that pays for a big board -- but a rising count with FALLING top-stat is the
                 warning sign.
  cap%           how close the top stat is to its LIVE in-game cap. Once it reads ~100% that stat is
                 finished and further points must go elsewhere.
  total vs rank  these move independently, and that is the point. Two real careers: 3612 total ->
                 11,963 rank, and 3812 total -> 13,957. +5% total, +17% rank -- the difference was
                 distribution (Speed 774/Wit 856 versus Speed 1189/Wit 596). Concentration pays.

Needs the per-turn board logging (career_bot/runner.py::_debug_command_board); careers logged before
that landed are skipped rather than silently half-counted.

Usage:
    python scripts/career_health.py                    # newest 15, any scenario
    python scripts/career_health.py --scenario 4 -n 30
    python scripts/career_health.py --all              # every career, not just richly-logged ones
"""
import argparse
import glob
import json
import os
import statistics
import sys
from collections import Counter

SCEN = {1: "URA", 2: "Unity", 3: "GrandLive", 4: "MANT"}
STATS = ("speed", "stamina", "power", "guts", "wit")
# command_id -> short label. 6xx are the summer-camp variants of the same facilities.
FACILITY = {101: "Spd", 601: "Spd", 105: "Sta", 602: "Sta", 102: "Pow", 603: "Pow",
            104: "Gut", 604: "Gut", 103: "Gut", 106: "Wit", 605: "Wit"}


def _classify(turn):
    """-> 'rest' | 'race' | a facility label | 'other'. decision_reason is the source of truth:
    a rest is logged as action 'command' with reason 'rest 701', not as its own action."""
    reason = str(turn.get("decision_reason") or "").lower()
    action = str(turn.get("selected_action") or "")
    if reason.startswith("rest"):
        return "rest"
    if action == "race":
        return "race"
    if action != "command":
        return "other"
    for cid, label in FACILITY.items():
        if f" {cid}" in reason:
            return label
    for label in ("Spd", "Sta", "Pow", "Gut", "Wit"):
        if f"training {label.lower()}" in reason:
            return label
    return "other"


def rows(root, scenario, limit, require_rich):
    out = []
    for path in sorted(glob.glob(os.path.join(root, "career_log_*.json")))[-limit * 4:]:
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception:
            continue
        if scenario and int(doc.get("scenario_id") or 0) != scenario:
            continue
        turns = doc.get("turns") or []
        rich = any(isinstance(c, dict) and "gains" in c
                   for t in turns for c in (t.get("server_command_board") or []))
        if require_rich and not rich:
            continue
        counts = Counter(_classify(t) for t in turns)
        summary = doc.get("summary") or {}
        final = summary.get("final_stats") or {}
        caps = next((t.get("stat_caps") for t in reversed(turns) if t.get("stat_caps")), None)
        top = max(final, key=lambda k: final.get(k) or 0) if final else None
        cap_pct = None
        if top and caps:
            cap = caps.get("max_" + ("wiz" if top == "wit" else top))
            if cap:
                cap_pct = 100.0 * (final.get(top) or 0) / cap
        out.append({
            "id": os.path.basename(path)[11:26],
            "scen": SCEN.get(int(doc.get("scenario_id") or 0), "?"),
            "counts": counts, "final": final, "top": top, "cap_pct": cap_pct,
            "total": summary.get("stat_total"), "rank": summary.get("rank_letter"),
            "score": summary.get("rank_score"), "rich": rich,
            "status": doc.get("status"), "turns": len(turns),
        })
    return out[-limit:]


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default=os.path.join(here, "uma_runtime", "bot_logs"))
    ap.add_argument("--scenario", type=int, default=0, help="0 = all, 1 URA, 2 Unity, 3 GL, 4 MANT")
    ap.add_argument("-n", "--limit", type=int, default=15)
    ap.add_argument("--all", action="store_true",
                    help="include careers logged before per-turn board logging landed")
    args = ap.parse_args()

    data = rows(args.logs, args.scenario, args.limit, not args.all)
    if not data:
        print("No matching careers. Try --all, a different --scenario, or run one career first.")
        return 1

    print(f"{'career':<16}{'scen':<10}{'Spd':>4}{'Wit':>4}{'Pow':>4}{'Sta':>4}{'Gut':>4}"
          f"{'rest':>5}{'race':>5} | {'topstat':>12}{'cap%':>6}{'total':>7}  rank")
    for r in data:
        c = r["counts"]
        top = f"{r['top'] or '-'} {r['final'].get(r['top']) if r['top'] else ''}".strip()
        cap = f"{r['cap_pct']:.0f}%" if r["cap_pct"] is not None else "-"
        rank = f"{r['rank'] or '?'} {r['score'] or ''}".strip()
        flag = "" if r["status"] == "finished" else f"  [{r['status']}]"
        print(f"{r['id']:<16}{r['scen']:<10}{c['Spd']:>4}{c['Wit']:>4}{c['Pow']:>4}{c['Sta']:>4}"
              f"{c['Gut']:>4}{c['rest']:>5}{c['race']:>5} | {top:>12}{cap:>6}"
              f"{str(r['total'] or '-'):>7}  {rank}{flag}")

    done = [r for r in data if r["status"] == "finished" and r["score"]]
    if len(done) >= 2:
        print(f"\nacross {len(done)} finished careers:")
        for label, vals in (
            ("Speed trainings", [r["counts"]["Spd"] for r in done]),
            ("Wit trainings", [r["counts"]["Wit"] for r in done]),
            ("rest turns", [r["counts"]["rest"] for r in done]),
            ("stat total", [r["total"] for r in done if r["total"]]),
            ("rank score", [r["score"] for r in done]),
        ):
            if vals:
                print(f"  {label:<16} mean {statistics.fmean(vals):8.1f}   best {max(vals):>6}")
        best = max(done, key=lambda r: r["score"])
        print(f"  best run: {best['id']} -> {best['rank']} {best['score']} "
              f"({best['counts']['Spd']} Speed / {best['counts']['Wit']} Wit / "
              f"{best['counts']['rest']} rest)")
    skipped = args.limit - len(data)
    if skipped > 0 and not args.all:
        print(f"\n(careers without per-turn board logging were skipped -- pass --all to include them)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
