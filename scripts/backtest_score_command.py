"""Backtest harness for MantStrategy._score_command over real career logs.

Replays the training scorer against the actual training boards the bot saw each turn and
checks two things:

  1. DISTRIBUTION  -- what the bot actually did (per-stat trains, rests, races) + the final
     build, so you can eyeball whether training followed the intended focus.
  2. SCORER CONSISTENCY -- on each training turn, does the bot's actual pick rank at/near the
     TOP of _score_command on that board? A high rate means the scorer and the live decision
     agree; a sudden drop after a scorer change flags a regression.

The replay runs the scorer with foresight OFF and a default preset, so it is a STRUCTURAL
check, not an exact reproduction (live runs add CareerForecaster targets + the learned
emphasis + the real preset weights). Treat the consistency % as a trend to watch, not a
ground truth -- its value is catching a *change* in behaviour when you edit the scorer.

Usage:
    python scripts/backtest_score_command.py                 # newest uma_runtime logs
    python scripts/backtest_score_command.py "<glob>"        # custom log glob
    python scripts/backtest_score_command.py "<glob>" 12     # cap to N logs
"""
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_bot.scenarios.mant import MantStrategy, TRAINING_COMMANDS, TRAINING_NAMES  # noqa: E402

PRESET = {"ai_train_to_win": False}


def _board_and_chara(turn):
    """Pull the training board (home_info.command_info_array) + chara_info this turn saw,
    from the turn's captured api responses. Returns (commands, chara) or (None, None)."""
    for call in (turn.get("api_calls") or []):
        data = (call.get("data") or {}).get("data") or {}
        home = data.get("home_info") or {}
        cmds = home.get("command_info_array")
        chara = data.get("chara_info")
        if cmds and chara:
            return cmds, chara
    return None, None


def _replay_turn(strategy, turn):
    """Return ('match'|'top3'|'miss'|None, picked_stat). None = not a scorable training turn."""
    picked = turn.get("current_command") or {}
    if int(picked.get("command_type") or 0) != 1:
        return None, None
    cmds, chara = _board_and_chara(turn)
    if not cmds:
        return None, None
    trainings = [c for c in cmds if int(c.get("command_type") or 0) == 1
                 and c.get("command_id") in TRAINING_COMMANDS]
    if len(trainings) < 2:
        return None, None
    strategy._forecast = None
    scored = sorted(
        ((strategy._score_command(c, {"home_info": {"command_info_array": cmds}}, chara, PRESET), c)
         for c in trainings),
        key=lambda x: x[0], reverse=True,
    )
    order = [int(c.get("command_id") or 0) for _, c in scored]
    pick_id = int(picked.get("command_id") or 0)
    pick_stat = TRAINING_NAMES[TRAINING_COMMANDS.get(pick_id, 0)]
    if pick_id == order[0]:
        return "match", pick_stat
    if pick_id in order[:3]:
        return "top3", pick_stat
    return "miss", pick_stat


def backtest(paths):
    strat = MantStrategy()
    agg = Counter()
    actions = Counter()
    careers = 0
    for path in paths:
        try:
            doc = json.loads(open(path, encoding="utf-8").read())
        except Exception:
            continue
        careers += 1
        for turn in (doc.get("turns") or []):
            act = turn.get("selected_action") or ""
            if act:
                actions[act] += 1
            result, stat = _replay_turn(strat, turn)
            if result is None:
                continue
            agg[result] += 1
            if stat:
                agg[f"stat:{stat}"] += 1
    total = agg["match"] + agg["top3"] + agg["miss"]
    print(f"\n=== backtest over {careers} career log(s) ===")
    print(f"action mix: " + ", ".join(f"{a}={n}" for a, n in actions.most_common(8)))
    if total:
        print(f"\nscorer consistency on {total} scorable training turns "
              f"(foresight OFF -> structural check, not exact):")
        print(f"  pick == top-scored : {agg['match']:>4} ({100*agg['match']/total:.0f}%)")
        print(f"  pick in top-3      : {agg['match']+agg['top3']:>4} ({100*(agg['match']+agg['top3'])/total:.0f}%)")
        print(f"  pick outside top-3 : {agg['miss']:>4} ({100*agg['miss']/total:.0f}%)  <- foresight/emphasis/preset divergence")
        stats = {k.split(':',1)[1]: v for k, v in agg.items() if k.startswith('stat:')}
        if stats:
            print("\ntraining-pick distribution (which stat the bot trained):")
            for name in TRAINING_NAMES:
                print(f"  {name:8} {stats.get(name,0):>4}")
    else:
        print("no scorable training turns found (logs may lack the board) -- check the glob.")


if __name__ == "__main__":
    pattern = sys.argv[1] if len(sys.argv) > 1 else "uma_runtime/bot_logs/career_log_*.json"
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)[:cap]
    if not files:
        print(f"no logs matched: {pattern}")
        sys.exit(1)
    backtest(files)
