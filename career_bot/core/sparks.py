"""Colour-weighted inheritance-spark scoring for the end-of-career factor pick (+ optional TP reroll).

Every offered factor option is scored by the USER's per-colour priority (0-5, where 0 = ignore it
entirely and 5 = want it most), set in the Settings tab:

    blue  = stat sparks      (Speed / Stamina / Power / Guts / Wit)
    pink  = aptitude sparks  (distance / surface / running style)
    green = unique sparks    (the uma's own unique skill)
    white = skill sparks     (plus race + scenario sparks, which the game also shows white)

    score(option) = SUM over its factors of  weight[colour] * stars

The chooser compares EVERY option it has seen -- the ORIGINAL roll and any REROLLED one -- and keeps
the highest scorer, so spending TP on a reroll can never lose you a better original roll.
"""

# factor_map category -> spark colour. race/scenario/other render white in-game alongside skills.
COLOUR_BY_CATEGORY = {
    "stat": "blue",
    "aptitude": "pink",
    "unique": "green",
    "skill": "white",
    "race": "white",
    "scenario": "white",
    "other": "white",
}
COLOURS = ("blue", "pink", "green", "white")
# Sensible starting point: stats + aptitude matter most for inheritance, skills next, unique least.
DEFAULT_WEIGHTS = {"blue": 3, "pink": 3, "green": 1, "white": 2}
PRESET_KEYS = {c: f"spark_priority_{c}" for c in COLOURS}


def _as_int(value, default=0):
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_weights(preset):
    """Per-colour priorities from the preset, clamped to 0..5 (0 = don't care)."""
    preset = preset if isinstance(preset, dict) else {}
    out = {}
    for colour in COLOURS:
        raw = preset.get(PRESET_KEYS[colour])
        value = DEFAULT_WEIGHTS[colour] if raw is None or raw == "" else _as_int(raw, DEFAULT_WEIGHTS[colour])
        out[colour] = max(0, min(5, value))
    return out


def _factor_row(factor_map, factor_id):
    if not isinstance(factor_map, dict):
        return {}
    row = factor_map.get(str(factor_id)) or factor_map.get(factor_id)
    return row if isinstance(row, dict) else {}


def factor_colour(factor_map, factor_id):
    row = _factor_row(factor_map, factor_id)
    return COLOUR_BY_CATEGORY.get(str(row.get("category") or "").strip().lower(), "white")


def _option_factors(option):
    if not isinstance(option, dict):
        return []
    arr = option.get("factor_info_array")
    if not isinstance(arr, list):
        arr = option.get("factors") if isinstance(option.get("factors"), list) else []
    return arr


def score_option(option, factor_map, weights):
    """(score, breakdown) for one factor option. breakdown = {colour: summed stars} for logging."""
    breakdown = {c: 0 for c in COLOURS}
    score = 0.0
    for raw in _option_factors(option):
        raw = raw if isinstance(raw, dict) else {}
        factor_id = _as_int(raw.get("factor_id"), 0)
        row = _factor_row(factor_map, factor_id)
        # master stars win; fall back to whatever the option row carries
        stars = _as_int(row.get("stars"), 0) or _as_int(raw.get("level"), 0) or _as_int(raw.get("stars"), 0)
        stars = max(0, min(9, stars))
        colour = factor_colour(factor_map, factor_id)
        breakdown[colour] += stars
        score += weights.get(colour, 0) * stars
    return score, breakdown


def pick_best(options, factor_map, weights):
    """Highest-scoring option across everything offered (original roll + any reroll).

    Returns {"lottery_id", "score", "breakdown"} or None when there is nothing valid to pick.
    Ties keep the EARLIER option, so an equal-scoring reroll never displaces the original."""
    best = None
    for option in options or []:
        lottery_id = _as_int((option or {}).get("lottery_id"), 0)
        if lottery_id <= 0:
            continue
        score, breakdown = score_option(option, factor_map, weights)
        if best is None or score > best["score"]:
            best = {"lottery_id": lottery_id, "score": score, "breakdown": breakdown}
    return best


def extract_options(response):
    """All factor options in a factor_select / factor_lottery response: the ORIGINAL roll plus any
    rerolled set, so both can be compared. Tolerates the response being wrapped in `data`."""
    node = response if isinstance(response, dict) else {}
    common = None
    for _ in range(3):
        for key in ("single_mode_factor_select_common", "single_mode_factor_lottery_common"):
            if isinstance(node.get(key), dict):
                common = node[key]
                break
        if common is not None:
            break
        node = node.get("data") if isinstance(node.get("data"), dict) else {}
    if not isinstance(common, dict):
        return [], {}
    options = []
    for key in ("factor_select_info_array", "factor_relottery_info_array"):
        arr = common.get(key)
        if isinstance(arr, list):
            options.extend(a for a in arr if isinstance(a, dict))
    meta = {
        "lottery_remain_num": _as_int(common.get("lottery_remain_num"), 0),
        "tp_info": common.get("tp_info") if isinstance(common.get("tp_info"), dict) else {},
    }
    return options, meta
