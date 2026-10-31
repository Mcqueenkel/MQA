from dataclasses import dataclass


@dataclass
class Decision:
    action: str
    payload: dict
    reason: str


class ScenarioStrategy:
    scenario_id = 0

    # Race-planning policy: the NEUTRAL defaults every scenario inherits (they equal the planner's
    # behavior for an unknown/missing scenario_id, so an unbound planner acts exactly as before).
    # Each scenario file overrides ONLY the flags its scenario truly changes -- that keeps every
    # scenario-specific race rule in career_bot/scenarios/, never in core/races.py itself.
    # BaseTrainingStrategy.__init__ copies this onto the RacePlanner it receives.
    RACE_POLICY = {
        "goal_races_only": False,    # True: the trainee's CAREER GOALS are the schedule (extra_race_list ignored)
        "scheduled_override": True,  # False: forced race turns never swap to a user-scheduled race
        "optional_races": True,      # False: choose() never enters scheduled/optional races (mandatory-only)
        "fan_scramble": False,       # True: low-fan junior turns may race ANY runnable race for fans
        "rival_overwrite": False,    # True: prefer the same-turn wanted race carrying a rival (Twinkle-Climax)
        "optional_race_guard": False,  # True: skip a SCHEDULED race on bad aptitude / 3rd in a row /
                                       # near a goal race / bad mood (TrainingBrain._optional_race_veto)
    }

    # Per-scenario TRAIN-TO stat caps [Speed, Stamina, Power, Guts, Wit]: the scenario's OWN per-stat
    # caps -- game base 1200 + this scenario's cap bonuses (master.mdb single_mode_scenario). The bot
    # trains each stat UP to min(this, the stat's LIVE in-game cap), so a stat reaches its scenario cap
    # instead of being held at a lower number. Inheritance factors can raise the LIVE cap above the
    # scenario cap; the scenario cap then binds (trains to the scenario cap, not the factor headroom) --
    # lower a value to cap tighter still. None = neutral base default (train toward the live game cap /
    # foresight aim). Overridden per scenario in career_bot/scenarios/*.py (via _scenario_stat_caps).
    DEFAULT_STAT_CAPS = None

    def next_decision(self, state, preset):
        raise NotImplementedError
