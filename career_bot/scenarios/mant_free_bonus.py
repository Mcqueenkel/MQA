"""Free scenario calendar bonuses (mood / energy) that land automatically on fixed
career turns in the MANT scenario. Used so the bot doesn't waste a cupcake,
recreation, or energy item the turn before a free bonus arrives -- it just waits.

Turns come from the MANT calendar (career_bot.master_data.race_turn):
year_offset (Junior=0, Classic=24, Senior=48) + (month - 1) * 2 + half (Early=1, Late=2).
"""

# turn -> {"mood": n} and/or {"energy": n}  (free, automatic on that turn).
# THIS CALENDAR IS MANT-ONLY (Trackblazer, scenario 4). URA Finale (1) and Aoharu/Unity (2) have their
# OWN event calendars, not the same fixed turns -- applying MANT's here made a URA/Unity career "wait"
# for a turn-27/29/42... bonus that never arrives. Those scenarios are unmapped, so they get NO assumed
# free bonuses (the bot recovers mood/energy itself instead). Add their calendars here when captured.
SCENARIO_FREE_BONUSES = {
    27: {"mood": 1},     # Classic Early Feb  (+1 Mood)
    29: {"energy": 20},  # Classic Early Mar  (+20 Energy)
    42: {"mood": 1},     # Classic Late Sep   (+1 Mood)
    60: {"energy": 20},  # Senior Late Jun    (+20 Energy)
    68: {"mood": 1},     # Senior Late Oct    (+1 Mood)
    72: {"energy": 30},  # Senior Late Dec    (+30 Energy)
}


def free_bonus_within(turn, kind, lookahead=1, schedule=None):
    """Total free `kind` ("mood" or "energy") on MANT's fixed-turn calendar arriving within the next
    `lookahead` turns (default: just the immediate next turn). MANT-ONLY: callers must gate on scenario
    4 before consulting this -- URA/Unity have their own calendars and never call it. Returns 0 on bad
    input / none."""
    sched = SCENARIO_FREE_BONUSES if schedule is None else schedule
    try:
        turn = int(turn or 0)
        lookahead = max(1, int(lookahead or 1))
    except (TypeError, ValueError):
        return 0
    return sum(int((sched.get(t) or {}).get(kind, 0))
               for t in range(turn + 1, turn + 1 + lookahead))
