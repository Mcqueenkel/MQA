"""How many check_event calls were genuinely WASTED -- a round-trip that accomplished nothing.

check_event is the biggest single cost in a career (~210 of 489 requests, 42%), and a career is ~96%
API round-trip time, so this is the only place a materially faster career could come from.

WHAT COUNTS AS WASTE -- this is the part an earlier version of this script got wrong:

    A response carrying `queued_events: 0` is NOT waste. It is the normal reply to the call that
    cleared the LAST event in a drain: the request carried an event_id, the event was processed, and
    the queue is empty afterwards. Counting those reported 43% waste in a career that had none.

    Real waste is a BARE POLL -- a request with no event_id that comes back with nothing queued. That
    is a round-trip spent asking a question whose answer was already known.

Unpaired responses (no matching request by req_id) are reported separately rather than folded into
either bucket, because they cannot be classified and silently counting them inflates the result.

Needs the `queued_events` field from report.compact_api_data, so it only works on careers run after
that was added.

    python scripts/check_event_waste.py                # newest career
    python scripts/check_event_waste.py --all          # every career that has the field
    python scripts/check_event_waste.py --scenario 1   # URA only
"""
import argparse
import collections
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SECONDS_PER_CALL = 0.96          # measured median check_event round-trip
NAMES = {1: "URA", 2: "Unity", 3: "Grand Live", 4: "MANT"}


def analyse(path):
    """Classify every check_event call in one career, or None when the log predates the field."""
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)

    stats = collections.Counter()
    per_turn = collections.Counter()
    waste_turns = collections.Counter()
    saw_field = False

    for turn in d.get("turns") or []:
        n = int(turn.get("turn") or 0)
        pairs = {}
        for call in turn.get("api_calls") or []:
            rid = call.get("req_id")
            if not rid:
                continue
            if not str(call.get("endpoint", "")).endswith("check_event"):
                continue
            pairs.setdefault(rid, {})[call.get("direction")] = call

        for rid, pair in pairs.items():
            req, res = pair.get("REQ"), pair.get("RES")
            if req is None:
                continue
            per_turn[n] += 1
            stats["total"] += 1
            if res is None:
                stats["unpaired"] += 1
                continue
            body = res.get("data") or {}
            if "queued_events" not in body:
                stats["no_field"] += 1
                continue
            saw_field = True
            queued = int(body.get("queued_events") or 0)
            had_event = bool((req.get("data") or {}).get("event_id"))
            if had_event:
                # processed an event; queued>0 means more remain, 0 means that was the last one
                stats["processed_more_queued" if queued else "processed_queue_cleared"] += 1
            elif queued:
                stats["poll_found_work"] += 1      # bare poll that DID surface events
            else:
                stats["wasted_poll"] += 1          # bare poll, nothing queued -> pure round-trip
                waste_turns[n] += 1

    if not saw_field:
        return None
    return {
        "file": os.path.basename(path),
        "scenario": NAMES.get(d.get("scenario_id"), d.get("scenario_id")),
        "preset": d.get("preset_name"),
        "turns": d.get("final_turn"),
        "stats": stats,
        "per_turn": per_turn,
        "waste_turns": waste_turns,
    }


def report(s):
    st = s["stats"]
    total = st["total"]
    wasted = st["wasted_poll"]
    print("\n=== %s  (%s / %s, %s turns) ===" % (s["file"], s["scenario"], s["preset"], s["turns"]))
    print("  check_event calls              : %d" % total)
    print("    processed an event, more left: %d" % st["processed_more_queued"])
    print("    processed an event, queue now clear: %d" % st["processed_queue_cleared"])
    print("    bare poll that found work    : %d" % st["poll_found_work"])
    print("    BARE POLL, nothing queued    : %d   <- the only waste" % wasted)
    if st["unpaired"]:
        print("    unpaired (no matching REQ)   : %d   (unclassifiable, excluded)" % st["unpaired"])
    if st["no_field"]:
        print("    response predates the field  : %d   (excluded)" % st["no_field"])

    classified = total - st["unpaired"] - st["no_field"]
    if classified:
        print("  waste: %d of %d classified (%.0f%%)  ~%.0fs (%.1f min)" %
              (wasted, classified, 100.0 * wasted / classified,
               wasted * SECONDS_PER_CALL, wasted * SECONDS_PER_CALL / 60))
    if s["per_turn"]:
        avg = total / max(1, len(s["per_turn"]))
        worst = ", ".join("t%d:%d" % t for t in s["per_turn"].most_common(5))
        print("  calls per turn                 : %.1f avg, worst %s" % (avg, worst))
    if s["waste_turns"]:
        print("  turns with >=2 wasted polls    : %d" %
              sum(1 for v in s["waste_turns"].values() if v >= 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="every career that has the field")
    ap.add_argument("--scenario", type=int, help="1 URA, 2 Unity, 3 Grand Live, 4 MANT")
    args = ap.parse_args()

    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "uma_runtime", "bot_logs")
    files = sorted(glob.glob(os.path.join(root, "career_log_*.json")), key=os.path.getmtime,
                   reverse=True)
    done = []
    for path in files:
        try:
            s = analyse(path)
        except Exception:
            continue
        if not s:
            continue
        if args.scenario and NAMES.get(args.scenario) != s["scenario"]:
            continue
        done.append(s)
        report(s)
        if not args.all:
            break

    if not done:
        print("No career log carries `queued_events` yet.")
        print("It is written by report.compact_api_data, so run ONE career and re-run this.")
        return
    if len(done) > 1:
        t = sum(s["stats"]["total"] for s in done)
        w = sum(s["stats"]["wasted_poll"] for s in done)
        print("\n=== %d careers ===" % len(done))
        print("  check_event %d, wasted bare polls %d, ~%.1f min recoverable" %
              (t, w, w * SECONDS_PER_CALL / 60))


if __name__ == "__main__":
    main()
