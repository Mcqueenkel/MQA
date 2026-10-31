"""Is a MANT Training Application (150 coins, "+1 training level") worth buying?

THE OPEN QUESTION. `single_mode_free_shop_effect` confirms the item does `+1 level` to a facility,
but master.mdb does NOT carry the level -> gain curve (the client computes it), and the bot has
never bought one in 878 career logs -- so there is no before/after to learn from. Meanwhile the shop
offers ~688 coins/career of them that the bot never touches.

THE TRICK: we do not need to buy one to learn the curve. Facilities level up naturally from 1 to 5
during every career, and the per-turn log now records each facility's `level` alongside its `gains`.
So an ordinary career already contains the whole curve -- we just have to read it.

WHAT THIS DOES
  1. Derives, per facility, the mean stat gain at each training level (level 1..5).
  2. Turns that into the marginal value of +1 level.
  3. Estimates how many more times that facility gets trained after a given turn.
  4. Compares (marginal gain x remaining trainings) against the opportunity cost of 150 coins.
     Measured alternative: stat Scrolls convert at 0.500 stat points per coin, so 150 coins
     ~= 75 stat points. That is the number a Training Application has to beat.

REQUIRES the richer board logging (server_command_board entries carrying `level` and `gains`).
Careers logged before that landed are skipped, and the script says so rather than guessing.

Usage:
    python scripts/analyze_training_apps.py                 # all logs
    python scripts/analyze_training_apps.py --scenario 4    # MANT only
    python scripts/analyze_training_apps.py --coins 150 --coin-value 0.5
"""
import argparse
import glob
import json
import os
import statistics
import sys
from collections import defaultdict

# command_id -> (facility label, the stat key its gains use). Summer variants share the facility.
FACILITIES = {
    101: ("Speed", "speed"), 601: ("Speed", "speed"),
    105: ("Stamina", "stamina"), 602: ("Stamina", "stamina"),
    102: ("Power", "power"), 603: ("Power", "power"),
    103: ("Guts", "guts"), 604: ("Guts", "guts"),
    106: ("Wit", "wit"), 605: ("Wit", "wit"),
}
STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")

# Summer camp (mirrors SUMMER_TRAINING_TURNS in career_bot/scenarios/mant_items.py). EXCLUDED from
# the curve by default, and this is not a nicety: during camp EVERY facility is forced to level 5
# AND carries the camp's own bonuses (full support turnout, boosted gains). Verified in a real log --
# every single level-5 observation fell on turns 37-40 / 61-64 and nowhere else. Counting them makes
# "level 5" absorb the whole camp effect and overstates what +1 level is actually worth.
CAMP_TURNS = frozenset({37, 38, 39, 40, 61, 62, 63, 64})


def _logs(root, scenario, last=0):
    paths = sorted(glob.glob(os.path.join(root, "career_log_*.json")))
    if last:
        paths = paths[-last:]                  # newest N only -- the whole folder is GBs
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception:
            continue
        if scenario and int(doc.get("scenario_id") or 0) != scenario:
            continue
        yield path, doc


def collect(root, scenario, last=0, min_turn=70, include_camp=False):
    """-> (samples, trained_after, stats) where samples[(facility, level)] = [total stat gain, ...]

    UNFINISHED careers are fine for the level -> gain CURVE: every offered facility on every turn is
    an independent observation, so a career that stopped at turn 20 still contributes 20 turns of
    honest data. They are NOT fine for the payoff window: "how many trainings are left after turn T"
    is measured per career, and a career that died at turn 30 contributes a 0 that drags the mean
    down and makes every item look worse than it is. So short careers are counted for the curve and
    EXCLUDED from the window (min_turn, default 70)."""
    samples = defaultdict(list)
    trained_after = defaultdict(list)          # facility -> [count of trainings after turn T]
    usable = skipped = short = 0

    for _path, doc in _logs(root, scenario, last):
        turns = doc.get("turns") or []
        board_rows = [t for t in turns if any(
            isinstance(c, dict) and "gains" in c for c in (t.get("server_command_board") or []))]
        if not board_rows:
            skipped += 1
            continue
        usable += 1

        # every offered facility on every turn is an observation of (level -> gain)
        for turn in turns:
            if not include_camp and int(turn.get("turn") or 0) in CAMP_TURNS:
                continue                        # camp forces Lv5 + adds its own bonuses
            for cmd in (turn.get("server_command_board") or []):
                if not isinstance(cmd, dict) or "gains" not in cmd:
                    continue
                fac = FACILITIES.get(int(cmd.get("command_id") or 0))
                level = cmd.get("level")
                if not fac or not level:
                    continue
                gains = cmd.get("gains") or {}
                total = sum(int(v) for k, v in gains.items() if k in STAT_KEYS)
                if total > 0:
                    samples[(fac[0], int(level))].append(total)

        # how often each facility was actually TRAINED, by turn -- for the payoff window
        picks = defaultdict(list)
        for turn in turns:
            reason = str(turn.get("decision_reason") or "")
            n = int(turn.get("turn") or 0)
            for cid, (label, _stat) in FACILITIES.items():
                if f" {cid}" in reason or reason.startswith(f"training {label}"):
                    picks[label].append(n)
                    break
        # Only a career that actually ran to the end can say how many trainings FOLLOW a given turn.
        final_turn = max([int(t.get("turn") or 0) for t in turns] or [0])
        if final_turn < min_turn:
            short += 1
            continue
        for label, turn_list in picks.items():
            trained_after[label].append(sorted(turn_list))

    return samples, trained_after, {"usable": usable, "skipped": skipped, "short": short}


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default=os.path.join(here, "uma_runtime", "bot_logs"))
    ap.add_argument("--scenario", type=int, default=0, help="0 = all scenarios, 4 = MANT")
    ap.add_argument("--coins", type=float, default=150.0, help="price of one Training Application")
    ap.add_argument("--coin-value", type=float, default=0.5,
                    help="stat points per coin from the best alternative (Scrolls measured at 0.500)")
    ap.add_argument("--buy-turn", type=int, default=30, help="turn the application would be bought")
    ap.add_argument("--last", type=int, default=0,
                    help="only read the newest N logs (the folder is GBs; 0 = all)")
    ap.add_argument("--include-camp", action="store_true",
                    help="include summer-camp turns (37-40/61-64). Off by default: camp forces Lv5 "
                         "AND adds its own bonuses, so it inflates the per-level slope")
    ap.add_argument("--min-turn", type=int, default=70,
                    help="a career must reach this turn to count toward 'trainings left' (default 70)")
    args = ap.parse_args()

    samples, trained_after, meta = collect(args.logs, args.scenario, args.last, args.min_turn,
                                          args.include_camp)
    print(f"careers with per-facility level+gain logging : {meta['usable']}")
    print(f"careers skipped (logged before that landed)  : {meta['skipped']}")
    print(f"  of the usable ones, too short for 'trains left' (< turn "
          f"{args.min_turn}, curve still counted) : {meta['short']}")
    if not samples:
        print("\nNo usable observations yet. The richer board logging only applies to careers run\n"
              "AFTER it landed -- run one career, then re-run this script.")
        return 1

    print(f"\n{'facility':<9} {'lvl':>3} {'n':>5} {'mean gain':>10} {'median':>7}")
    curves = {}
    for (facility, level) in sorted(samples):
        vals = samples[(facility, level)]
        mean = statistics.fmean(vals)
        curves.setdefault(facility, {})[level] = mean
        print(f"{facility:<9} {level:>3} {len(vals):>5} {mean:>10.1f} {statistics.median(vals):>7.1f}")

    breakeven = args.coins * args.coin_value
    print(f"\nA Training Application costs {args.coins:.0f} coins. Spent on Scrolls instead that is "
          f"~{breakeven:.0f} stat points.\nSo +1 level must return MORE than {breakeven:.0f} stats "
          f"over the rest of the career to be worth it.\n")

    print(f"{'facility':<9} {'+1 lvl gain':>12} {'trains left':>12} {'payoff':>9}   verdict")
    any_verdict = False
    for facility, curve in sorted(curves.items()):
        levels = sorted(curve)
        if len(levels) < 2:
            print(f"{facility:<9} {'?':>12} {'-':>12} {'-':>9}   only one level observed")
            continue
        # PER-LEVEL slope, not the raw gap between observed levels. Levels 3-4 are often unobserved
        # (a facility can jump 2 -> 5 in one career), and treating that gap as a single "+1 level"
        # step overstates the item by ~3x -- which flipped a verdict during development. Divide each
        # delta by the actual number of levels it spans, then average.
        deltas = [(curve[b] - curve[a]) / (b - a) for a, b in zip(levels, levels[1:])]
        delta = statistics.fmean(deltas)
        gaps = max(b - a for a, b in zip(levels, levels[1:]))
        runs = trained_after.get(facility) or []
        remaining = statistics.fmean(
            [len([t for t in lst if t >= args.buy_turn]) for lst in runs]) if runs else 0.0
        payoff = delta * remaining
        verdict = "WORTH IT" if payoff > breakeven else "not worth it"
        if gaps > 1:
            verdict += f"  (interpolated over a {gaps}-level gap -- weak)"
        any_verdict = True
        print(f"{facility:<9} {delta:>12.1f} {remaining:>12.1f} {payoff:>9.0f}   {verdict}")

    if any_verdict:
        print(f"\n(trains left = mean trainings of that facility from turn {args.buy_turn} onward, "
              f"measured across the same careers)")
        print("If a facility says WORTH IT, enable it for that build with:\n"
              '  "buy_training_applications": true   (plus "training_app_last_turn", default 45)')
    return 0


if __name__ == "__main__":
    sys.exit(main())
