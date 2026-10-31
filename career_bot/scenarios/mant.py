"""MANT / Trackblazer (scenario_id 4) -- the ONLY place MANT-specific strategy logic may live.

MANT runs the shared training brain (career_bot/core/training_brain.py) unmodified: the brain IS the
scoring/rest/outing engine every scenario uses, so this file holds only what makes MANT different
from the other scenarios:

- ``scenario_id = 4`` -- selects the single_mode_free/* route family and switches ON the MANT-only
  machinery that lives, correctly gated by this id, in the composition root: the coin shop /
  cleat-hammer / megaphone / Glow Stick item engine (scenarios/mant_items.py, driven from
  runner._handle_items and runner._race).
- ``RACE_POLICY`` -- MANT's race-planning rules (free racing): the low-fan junior fan scramble and
  the Twinkle-Climax rival race-overwrite. The planner (core/races.py) is scenario-agnostic and only
  does what this policy switches on.
- ``_goal_stat_emphasis`` -- career-goal training emphasis is OFF for MANT by design (the user's
  rule: "playing MANT is the only way to disable the career-goal focus").

If you are adding behavior that only MANT should have, it belongs HERE (or behind a scenario_id == 4
gate in the composition root runner.py) -- never in the shared brain unconditionally.
"""
from career_bot.core.training_brain import BaseTrainingStrategy, TRAINING_COMMANDS
from career_bot.scenarios.mant_free_bonus import free_bonus_within


class MantStrategy(BaseTrainingStrategy):
    scenario_id = 4

    # MANT lets you race anywhere: scramble for fans on low-fan junior turns, and prefer the
    # same-turn scheduled race that carries a Twinkle-Climax rival.
    RACE_POLICY = {**BaseTrainingStrategy.RACE_POLICY, "fan_scramble": True, "rival_overwrite": True}

    # MANT's own per-stat caps [SPD, STA, PWR, GUT, WIT] = game base 1200 + MANT/TS-Climax's cap bonus
    # (+700 to STA, +300 to WIT, per master.mdb single_mode_scenario id 4 -- MANT pours cap into
    # Stamina). The bot trains each stat up to min(this, the LIVE in-game cap). Override per stat via
    # stat_caps; disable via scenario_stat_caps=False.
    DEFAULT_STAT_CAPS = (1200, 1900, 1200, 1200, 1500)

    def _goal_stat_emphasis(self, chara, preset):
        # MANT ignores the career-goal stat emphasis entirely (training follows raw scoring +
        # learned-loss emphasis only) -- the one sanctioned way to run goal-free.
        return {}

    def _rest_alternative(self, training, chara, preset, turn):
        """MANT: on a would-rest turn, train a safe Wit instead of burning a dead 0-stat turn.
        Policy + the energy-trap guard live in the shared base (_wit_rest_alternative).
        Toggles: mant_wit_over_rest / mant_wit_rest_max / wit_rest_skip_ratio."""
        return self._wit_rest_alternative(training, chara, preset, turn, "mant")

    def _free_mood_bonus(self, turn):
        # MANT's fixed-turn free-bonus calendar (the ONLY scenario with one). The shared brain calls
        # this to decide whether to wait for a free mood boost instead of spending a recreation turn.
        return free_bonus_within(turn, "mood")
