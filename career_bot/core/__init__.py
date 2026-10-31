"""Reusable engine modules -- everything here is scenario-neutral.

RULE: core/ must NEVER import from career_bot.scenarios (the composition root runner.py binds the
two). One place for reusable code; per-scenario logic lives in career_bot/scenarios/ only.
"""
