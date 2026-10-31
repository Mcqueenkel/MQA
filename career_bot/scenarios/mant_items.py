
from career_bot.scenarios.mant_free_bonus import free_bonus_within
from career_bot.core.training_brain import MASTER_CLEAT_CLIMAX_RESERVE

ITEM_NAMES = {
    1001: "Speed Notepad",
    1002: "Stamina Notepad",
    1003: "Power Notepad",
    1004: "Guts Notepad",
    1005: "Wit Notepad",
    1101: "Speed Manual",
    1102: "Stamina Manual",
    1103: "Power Manual",
    1104: "Guts Manual",
    1105: "Wit Manual",
    1201: "Speed Scroll",
    1202: "Stamina Scroll",
    1203: "Power Scroll",
    1204: "Guts Scroll",
    1205: "Wit Scroll",
    2001: "Vita 20",
    2002: "Vita 40",
    2003: "Vita 65",
    2101: "Royal Kale Juice",
    2201: "Energy Drink MAX",
    2202: "Energy Drink MAX EX",
    2301: "Plain Cupcake",
    2302: "Berry Sweet Cupcake",
    3001: "Yummy Cat Food",
    3101: "Grilled Carrots",
    4001: "Pretty Mirror",
    4002: "Reporter's Binoculars",
    4003: "Master Practice Guide",
    4004: "Scholar's Hat",
    4101: "Fluffy Pillow",
    4102: "Pocket Planner",
    4103: "Rich Hand Cream",
    4104: "Smart Scale",
    4105: "Aroma Diffuser",
    4106: "Practice Drills DVD",
    4201: "Miracle Cure",
    5001: "Speed Training Application",
    5002: "Stamina Training Application",
    5003: "Power Training Application",
    5004: "Guts Training Application",
    5005: "Wit Training Application",
    7001: "Reset Whistle",
    8001: "Coaching Megaphone",
    8002: "Motivating Megaphone",
    8003: "Empowering Megaphone",
    9001: "Speed Ankle Weights",
    9002: "Stamina Ankle Weights",
    9003: "Power Ankle Weights",
    9004: "Guts Ankle Weights",
    10001: "Good-Luck Charm",
    11001: "Artisan Cleat Hammer",
    11002: "Master Cleat Hammer",
    11003: "Glow Sticks",
}

DISPLAY_TO_ID = {v: k for k, v in ITEM_NAMES.items()}

# Stat-up items come in three tiers: Notepad (1001-1005, small) < Manual (1101-1105,
# medium) < Scroll (1201-1205, big). When `buy_stat_scrolls_only` is on (the default),
# the shop buys ONLY the Scroll tier for stats and skips these weaker tiers. Non-stat
# items (cupcakes, cleats, cures, megaphones, etc.) are unaffected.
STAT_LOWER_TIER_IDS = {1001, 1002, 1003, 1004, 1005, 1101, 1102, 1103, 1104, 1105}
MANUAL_STAT_IDS = {1101, 1102, 1103, 1104, 1105}  # the medium "Manual" tier (every stat)

SLUG_TO_DISPLAY = {name.lower().replace("'", "").replace(" ", "_"): name for name in ITEM_NAMES.values()}

SHOP_ITEM_COSTS = {
    "Speed Notepad": 10, "Stamina Notepad": 10, "Power Notepad": 10, "Guts Notepad": 10, "Wit Notepad": 10,
    "Speed Manual": 15, "Stamina Manual": 15, "Power Manual": 15, "Guts Manual": 15, "Wit Manual": 15,
    "Speed Scroll": 30, "Stamina Scroll": 30, "Power Scroll": 30, "Guts Scroll": 30, "Wit Scroll": 30,
    "Vita 20": 35, "Vita 40": 55, "Vita 65": 75, "Royal Kale Juice": 70,
    "Energy Drink MAX": 30, "Energy Drink MAX EX": 50,
    "Plain Cupcake": 30, "Berry Sweet Cupcake": 55,
    "Yummy Cat Food": 10, "Grilled Carrots": 40,
    "Pretty Mirror": 150, "Reporter's Binoculars": 150, "Master Practice Guide": 150, "Scholar's Hat": 280,
    "Fluffy Pillow": 15, "Pocket Planner": 15, "Rich Hand Cream": 15, "Smart Scale": 15,
    "Aroma Diffuser": 15, "Practice Drills DVD": 15, "Miracle Cure": 40,
    "Speed Training Application": 150, "Stamina Training Application": 150,
    "Power Training Application": 150, "Guts Training Application": 150, "Wit Training Application": 150,
    "Reset Whistle": 20,
    "Coaching Megaphone": 40, "Motivating Megaphone": 55, "Empowering Megaphone": 70,
    "Speed Ankle Weights": 50, "Stamina Ankle Weights": 50, "Power Ankle Weights": 50, "Guts Ankle Weights": 50,
    "Good-Luck Charm": 40,
    "Artisan Cleat Hammer": 25, "Master Cleat Hammer": 40,
    "Glow Sticks": 15,
}

AILMENT_CURE_MAP = {
    "Night Owl": "Fluffy Pillow",
    "Slacker": "Pocket Planner",
    "Skin Outbreak": "Rich Hand Cream",
    "Slow Metabolism": "Smart Scale",
    "Migraine": "Aroma Diffuser",
    "Practice Poor": "Practice Drills DVD",
}

BAD_EFFECT_NAMES = {
    1: "Night Owl",
    2: "Slacker",
    3: "Skin Outbreak",
    4: "Slow Metabolism",
    5: "Migraine",
    6: "Practice Poor",
}

AILMENT_CURE_ALL = "Miracle Cure"

CURE_ITEMS = set(AILMENT_CURE_MAP.values()) | {AILMENT_CURE_ALL}

# How many of each cure to keep stocked from the shop (default 1). User wants 2 of the
# cure-all (Miracle Cure) on hand -- it covers every ailment, so no other cure is stocked
# (Rich Hand Cream is on the never-buy blocklist). Overridable per preset via "cure_stock_targets".
DEFAULT_CURE_STOCK = {"Miracle Cure": 2, "Rich Hand Cream": 1}

# In-camp summer turns (Lv5 facilities) -- the high-yield turns to spend saved buffs on.
SUMMER_TRAINING_TURNS = {37, 38, 39, 40, 61, 62, 63, 64}
# Summer-camp megaphone schedule (saves megaphones): a Motivating (+40%, lasts 3 turns) at each
# camp START blankets the first 3 camp turns; an Empowering (+60%, lasts 2 turns) on each camp's
# LAST turn -- only when the board is strong -- caps it with the biggest boost. Together 1 Motivating
# + 1 Empowering cover the whole 4-turn camp (37-40 / 61-64), and the no-stack guard skips the
# in-between turns while the Motivating is still running.
SUMMER_MOTIVATING_TURNS = {37, 61}
SUMMER_EMPOWERING_TURNS = {40, 64}
# Always-train climax window (last 6 turns): top up energy + spend charm to keep training, like
# the Lv5 camp turns -- applies to all decks.
CLIMAX_TRAIN_TURNS = {73, 74, 75, 76, 77, 78}

# MANT/Trackblazer climax/finale races: climax-1 = turn 74, climax-2 = turn 76,
# climax-3 = turn 78. These races are NOT in race_map.json (the live game supplies them
# at runtime with race_instance_ids starting "9"), so _is_g1_program CANNOT classify them
# as G1. Item logic that must fire at the climax keys off these TURN NUMBERS directly.
CLIMAX_RACE_TURNS = (74, 76, 78)
# Per user (no fan data exists in the repo to verify): fan gain is climax-3 > climax-2 >
# climax-1, so glow sticks are reserved toward the later/bigger climax. How many glow
# sticks to KEEP when standing at each climax race (turns play in order, so holding now
# saves them for a higher-priority later race): use at t74 only if >=3, t76 if >=2, t78 if >=1.
GLOW_STICK_CLIMAX_RESERVE = {74: 2, 76: 1, 78: 0}
# From this turn on, hold the last 35% Master Cleat Hammer in reserve for the climax (the climax
# shop may not restock hammers). BEFORE this turn, spend any hammer freely on any G1.
MASTER_CLEAT_SAVE_FROM = 69

# Climax (the last 6 turns; TS climax races at 74/76/78). Hold CLIMAX_COIN_RESERVE coins through
# the senior lead-up (from CLIMAX_COIN_RESERVE_FROM) so the climax shop can be bought out, then
# spend freely from CLIMAX_SHOP_START on. The 35% Master Cleat Hammers are saved toward the
# biggest/latest climax: keep this many in hand at each climax for the later ones (1 Master ->
# t78 only; 2 -> t76 + t78; 3 -> t74/76/78), mirroring the glow-stick reserve.
CLIMAX_SHOP_START = 73
CLIMAX_COIN_RESERVE_FROM = 65
CLIMAX_COIN_RESERVE = 200
# MASTER_CLEAT_CLIMAX_RESERVE now lives in training_brain (imported above) so the shared brain doesn't
# depend on this MANT-only module -- the two must agree on the per-climax hammer reserve.

# Hard blocklist -- the bot NEVER buys these (user-flagged "inefficient" support gadgets).
# Notepads + Training Applications are already skipped elsewhere. Overridable per preset
# via "never_buy_items" (a list of exact item names replaces this default).
DEFAULT_NEVER_BUY = {
    "Pretty Mirror",
    "Reporter's Binoculars",
    "Master Practice Guide",
    "Yummy Cat Food",
    "Tips for Efficient Training",
    "Energy Drink MAX",
    "Energy Drink MAX EX",
    # User-flagged as completely useless -- never buy (2026-06-25).
    "Fluffy Pillow",
    "Aroma Diffuser",
    # Cure ONLY via the cure-all Miracle Cure (stock 2) + a single Rich Hand Cream (stock 1, see
    # DEFAULT_CURE_STOCK) -- never buy the other specific single-ailment cures. User request 2026-06-27.
    "Pocket Planner",
    "Smart Scale",
    "Practice Drills DVD",
}

INSTANT_USE_ITEMS = [
    "Grilled Carrots",
    "Yummy Cat Food",
    "Energy Drink MAX EX",
    "Pretty Mirror",
    "Scholar's Hat",
    "Reporter's Binoculars",
    "Master Practice Guide",
    "Speed Notepad", "Stamina Notepad", "Power Notepad", "Guts Notepad", "Wit Notepad",
    "Speed Manual", "Stamina Manual", "Power Manual", "Guts Manual", "Wit Manual",
    "Speed Scroll", "Stamina Scroll", "Power Scroll", "Guts Scroll", "Wit Scroll",
    "Speed Training Application", "Stamina Training Application",
    "Power Training Application", "Guts Training Application", "Wit Training Application",
]

ONE_TIME_BUFF_ITEMS = {
    "Pretty Mirror",
    "Scholar's Hat",
    "Reporter's Binoculars",
    "Master Practice Guide",
}

ENERGY_ITEMS = {
    "Vita 20": 20,
    "Vita 40": 40,
    "Vita 65": 65,
    "Royal Kale Juice": 100,
}

# Turns just before each Summer Camp (camp is ~36-40 and ~60-64). During this window the
# bot proactively stockpiles the camp-prep items (energy / charm / Empowering Megaphone /
# Ankle Weights -- off-deck ankles are already dropped by _skip_buy) so the boosted Lv5
# camp turns run high-gain and low-failure.
PRE_SUMMER_TURNS = {31, 32, 33, 34, 35, 55, 56, 57, 58, 59}

MEGAPHONE_TIERS = {
    "Coaching Megaphone": (1, 4),
    "Motivating Megaphone": (2, 3),
    "Empowering Megaphone": (3, 2),
}

TRAINING_TYPE_ANKLET = {
    101: "Speed Ankle Weights",
    601: "Speed Ankle Weights",
    105: "Stamina Ankle Weights",
    602: "Stamina Ankle Weights",
    102: "Power Ankle Weights",
    603: "Power Ankle Weights",
    103: "Guts Ankle Weights",
    604: "Guts Ankle Weights",
}

TRAINING_ITEM_DECK_TYPE_INDEX = {
    "Speed Ankle Weights": 0,
    "Stamina Ankle Weights": 1,
    "Power Ankle Weights": 2,
    "Guts Ankle Weights": 3,
    "Speed Training Application": 0,
    "Stamina Training Application": 1,
    "Power Training Application": 2,
    "Guts Training Application": 3,
    "Wit Training Application": 4,
}

DEFAULT_ITEM_TIERS = {
    # Stat Scrolls and Manuals are ALWAYS separated: Scrolls (big stat gain) at tier 2, Manuals
    # (lesser gain) at tier 3. Notepads are omitted entirely -- _skip_buy never buys them.
    "speed_scroll": 2,
    "stamina_scroll": 2,
    "power_scroll": 2,
    "guts_scroll": 2,
    "wit_scroll": 2,
    "speed_manual": 3,
    "stamina_manual": 3,
    "power_manual": 3,
    "guts_manual": 3,
    "wit_manual": 3,
    "vita_20": 3,
    "vita_40": 2,
    "vita_65": 2,
    "royal_kale_juice": 3,
    "plain_cupcake": 3,
    "berry_sweet_cupcake": 4,
    "yummy_cat_food": 7,
    "grilled_carrots": 4,
    "pretty_mirror": 7,
    "reporters_binoculars": 8,
    "master_practice_guide": 7,
    "scholars_hat": 1,
    "fluffy_pillow": 7,
    "pocket_planner": 7,
    "rich_hand_cream": 5,
    "smart_scale": 7,
    "aroma_diffuser": 7,
    "practice_drills_dvd": 8,
    "miracle_cure": 5,
    "speed_training_application": 7,
    "stamina_training_application": 7,
    "power_training_application": 7,
    "guts_training_application": 7,
    "wit_training_application": 7,
    "reset_whistle": 1,
    "coaching_megaphone": 999,
    "motivating_megaphone": 3,
    "empowering_megaphone": 2,
    "speed_ankle_weights": 7,
    "stamina_ankle_weights": 7,
    "power_ankle_weights": 7,
    "guts_ankle_weights": 7,
    "good-luck_charm": 3,
    "artisan_cleat_hammer": 1,
    "master_cleat_hammer": 1,
    "glow_sticks": 8,
}

# Junior year (turns 1..JUNIOR_LAST_TURN) shop priority -- overrides DEFAULT_ITEM_TIERS on those
# turns only. Junior is the bond-building phase, so: TIER 1 = energy + mood + stat SCROLLS (the
# big-stat item, worth grabbing early); TIER 2 = training buffs (Empowering megaphone, charm,
# whistle) + the MAIN-stat anklet (handled dynamically via _junior_ankle_tier); TIER 3 = stat
# MANUALS (lesser stat item) + OFF-stat anklets. Anything not listed inherits its DEFAULT tier.
JUNIOR_LAST_TURN = 24
JUNIOR_ITEM_TIERS = {
    "grilled_carrots": 1,
    "vita_20": 1, "vita_40": 1, "vita_65": 1, "royal_kale_juice": 1,
    "plain_cupcake": 1, "berry_sweet_cupcake": 1,
    "speed_scroll": 1, "stamina_scroll": 1, "power_scroll": 1, "guts_scroll": 1, "wit_scroll": 1,
    "empowering_megaphone": 2, "good-luck_charm": 2, "reset_whistle": 2,
    "speed_manual": 3, "stamina_manual": 3, "power_manual": 3, "guts_manual": 3, "wit_manual": 3,
}


def display_to_slug(name):
    return str(name or "").lower().replace("'", "").replace(" ", "_")


class MantItemManager:
    def __init__(self):
        self.used_buffs = set()
        self.failed_exchange_this_snapshot = set()
        self.failed_use_this_turn = set()
        self.current_turn = None
        self.whistled_turn = None   # turn a Reset Whistle reshuffled the board (the runner re-runs items)
        self.shop_snapshot_key = None
        self.recover_after_exchange_error = False
        self.recover_after_use_error = False
        self.last_buy_options = []
        self.last_buy_selected = []
        self.last_buy_attempt = []
        self.last_buy_result = {}
        self.last_use_options = []
        self.last_use_selected = []
        self.last_use_attempt = []
        self.last_use_result = {}
        self.last_pre_race_use_selected = []
        self.last_pre_race_use_attempt = []
        self.last_pre_race_use_result = {}
        self.buy_attempt_events = []
        self.use_attempt_events = []

    def reset_scoped_failures(self):
        self.failed_exchange_this_snapshot = set()
        self.failed_use_this_turn = set()
        self.current_turn = None
        self.whistled_turn = None   # turn a Reset Whistle reshuffled the board (the runner re-runs items)
        self.shop_snapshot_key = None
        self.last_buy_options = []
        self.last_buy_selected = []
        self.last_buy_attempt = []
        self.last_buy_result = {}
        self.last_use_options = []
        self.last_use_selected = []
        self.last_use_attempt = []
        self.last_use_result = {}
        self.buy_attempt_events = []
        self.use_attempt_events = []

    def _set_turn(self, turn):
        turn = int(turn or 0)
        if self.current_turn != turn:
            self.current_turn = turn
            self.failed_use_this_turn = set()

    def _set_shop_snapshot(self, rows):
        key = tuple(
            (
                int(row.get("shop_item_id") or 0),
                int(row.get("item_id") or 0),
                int(row.get("coin_num") or 0),
                int(row.get("item_buy_num") or 0),
                int(row.get("limit_buy_count") or 0),
                int(row.get("limit_turn") or 0),
            )
            for row in rows or []
        )
        if self.shop_snapshot_key != key:
            self.shop_snapshot_key = key
            self.failed_exchange_this_snapshot = set()

    def handle(self, client, state, preset, best_command=None, status=None, race_planner=None):
        current = state
        self.recover_after_exchange_error = False
        current, bought = self.buy_shop_items(client, current, preset, race_planner)

        self.recover_after_use_error = False
        current, used = self.use_items(client, current, preset, best_command, status, race_planner)

        return current, bought, used

    def handle_pre_race(self, client, state, preset, payload, status=None, race_planner=None):
        self.recover_after_exchange_error = False
        current, bought = self.buy_shop_items(client, state, preset, race_planner)

        self.recover_after_use_error = False
        current, instant_used = self.use_items(client, current, preset, None, status, race_planner)
        data = current.get("data") or {}
        free = data.get("free_data_set") or {}
        chara = data.get("chara_info") or {}
        owned = self._owned_map(free)
        self.last_pre_race_use_selected = []
        self.last_pre_race_use_attempt = []
        self.last_pre_race_use_result = {}

        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)
        program_id = int((payload or {}).get("program_id") or 0)

        if not owned:
            self.last_pre_race_use_result = {"skip": "no_owned"}
            return current, instant_used

        targets = []

        vital = int(chara.get("vital") or 0)
        if owned.get("Energy Drink MAX", 0) > 0 and vital <= 1:
            targets.append(("Energy Drink MAX", 1))

        is_g1 = self._is_g1_program(program_id, race_planner)
        # Cleat Hammer (Artisan 20% / Master 35%) fires on G1 races AND on the climax
        # races. The climax races aren't in race_map.json so is_g1 is always False there
        # -- without this turn-based bypass the hammer would sit unused at the biggest
        # races (confirmed in career logs: 3 hammers owned at the climax, none used).
        if is_g1 or turn in CLIMAX_RACE_TURNS:
            cleat_choice = self._old_ui_cleat_before_race(owned, turn, program_id, race_planner)
            if cleat_choice:
                targets.append((cleat_choice, 1))
        # Glow Sticks: the marquee races (Arima Kinen, Japan Cup) plus the climax races,
        # with the climax supply reserved toward the highest-fan climax (3 > 2 > 1).
        if self._should_use_glow_stick(turn, owned.get("Glow Sticks", 0), program_id, race_planner):
            targets.append(("Glow Sticks", 1))

        targets = self._merge_targets(targets, owned)
        self.last_pre_race_use_selected = [{"name": name, "item_id": DISPLAY_TO_ID.get(name), "use_num": count} for name, count in targets]
        if not targets:
            self.last_pre_race_use_result = {"skip": "no_targets"}
            return current, instant_used

        use_payload = []
        for name, count in targets:
            item_id = DISPLAY_TO_ID.get(name)
            if not item_id or item_id in self.failed_use_this_turn:
                continue
            item_count = int(owned.get(name) or 0)
            if item_count <= 0:
                continue
            use_payload.append({"item_id": item_id, "use_num": min(count, item_count), "current_num": item_count})

        if use_payload:
            self.last_pre_race_use_attempt = list(use_payload)
            event = {
                "turn": turn,
                "selected": list(self.last_pre_race_use_selected),
                "attempt": list(use_payload),
                "payload": list(use_payload),
                "result": {},
            }
            self.use_attempt_events.append(event)
            try:
                self.last_pre_race_use_result = client.use_items(use_payload, turn)
                current = self._merge_state(current, self.last_pre_race_use_result)
                self.last_pre_race_use_result = {"result": "ok", "turn": turn, "payload": use_payload}
                event["result"] = self.last_pre_race_use_result
                return current, instant_used + len(use_payload)
            except Exception as exc:
                print(f"Pre-Race Item Use Error at turn {turn}: {exc}")
                if "205" in str(exc):
                    for item in use_payload:
                        self.failed_use_this_turn.add(item["item_id"])
                self.last_pre_race_use_result = {"result": "failed", "turn": turn, "error": str(exc), "payload": use_payload}
                event["result"] = self.last_pre_race_use_result
                return current, instant_used

        return current, instant_used

    def _junior_ankle_tier(self, deck_count):
        """Junior-year shop tier for a stat's Ankle Weights: MAIN stat (>=2 deck cards) -> tier 2,
        OFF stat (<2 cards) -> tier 3. Keeps coin spend on anklets modest early -- they pay off
        less before rainbows exist."""
        return 2 if int(deck_count or 0) >= 2 else 3

    def buy_shop_items(self, client, state, preset, race_planner=None):
        data = state.get("data") or {}
        free = data.get("free_data_set") or {}
        chara = data.get("chara_info") or {}
        current_turn = int(chara.get("turn") or 0)
        pickups = free.get("pick_up_item_info_array") or []
        self._set_turn(current_turn)
        self._set_shop_snapshot(pickups)
        cfg = self._mant_cfg(preset)
        tiers = cfg.get("item_tiers") or DEFAULT_ITEM_TIERS
        tier_count = int(cfg.get("tier_count") or 8)
        # Stats-via-Scrolls-only: skip the weaker Notepad/Manual stat tiers (default on).
        scrolls_only = bool(cfg.get("buy_stat_scrolls_only", True))
        # ...but buy every stat Manual (all 5 types) by default -- the Manual tier is worth taking
        # alongside Scrolls. Set buy_stat_manuals False to revert to Scrolls-only for the Manual tier.
        buy_manuals = bool(cfg.get("buy_stat_manuals", True))
        coin_val = free.get("coin_num")
        if coin_val is None:
            coin_val = free.get("gained_coin_num")
        budget = int(coin_val or 0)
        is_climax_shop = current_turn >= CLIMAX_SHOP_START
        # Junior year (turns 1-24): override the shop priority -- energy/mood first, buffs second,
        # stats/off-anklets last (anklets handled per-stat in the deck-match block below).
        is_junior = (not is_climax_shop) and 0 < current_turn <= JUNIOR_LAST_TURN
        if is_junior:
            tiers = {**tiers, **JUNIOR_ITEM_TIERS}
        # Hold CLIMAX_COIN_RESERVE through the senior lead-up so the climax shop has money to buy
        # out; the reserve is released once the climax shop opens.
        if CLIMAX_COIN_RESERVE_FROM <= current_turn < CLIMAX_SHOP_START:
            budget = max(0, budget - CLIMAX_COIN_RESERVE)
        start_budget = budget
        self.last_buy_options = []
        self.last_buy_selected = []
        self.last_buy_attempt = []
        self.last_buy_result = {"mant_coin": budget}
        self.buy_attempt_events = []
        if not pickups:
            self.last_buy_result = {"skip": "no_pickups", "mant_coin": budget}
            return state, 0
        if budget <= 0:
            self.last_buy_result = {"skip": "no_mant_coin", "mant_coin": budget}
            return state, 0

        owned = self._owned_map(free)
        any_sale = any(int(row.get("coin_num") or 0) < int(row.get("original_coin_num") or 0) for row in pickups if int(row.get("original_coin_num") or 0) > 0)
        sale_modifier = 0.9 if any_sale else 1.0
        # Per-stat support-card counts [Speed, Stamina, Power, Guts, Wit] of the running
        # deck -- used to prioritize stat-specific shop items toward the deck's focus.
        deck_counts = preset.get("_deck_type_counts") or []
        motivation = int(chara.get("motivation") or 3)
        non_rainbow_count = 0
        for row in chara.get("evaluation_info_array") or []:
            if int(row.get("target_id") or 0) in {1, 2, 3, 4, 5, 6} and int(row.get("evaluation") or 0) < 80:
                non_rainbow_count += 1
        # Grilled-carrot bond aggression for a Team Sirius / Heirs to the Throne deck. ASSUMPTION
        # (verify against a captured evaluation_info_array -- see MantStrategy._dump_recreation_debug):
        # these two "Group" cards rainbow via a different mechanic than bond, so they're expected to
        # sit in slots 1-6 below 80 and keep the unmaxxed count >= ~2. IF that holds, threshold 4
        # buys carrots hard until the 4 normal cards are bonded, then stops (count <= 2 < 4). If the
        # Group cards do NOT occupy slots 1-6, threshold 4 is too strict (count maxes at 4) and this
        # should be lowered -- revisit once the capture confirms. Non-group decks keep 3.
        deck_ids = {int(c.get("support_card_id") or 0) for c in (chara.get("support_card_array") or [])}
        group_deck = bool(deck_ids & {30067, 30081})
        bbq_threshold = int(cfg.get("bbq_unmaxxed_cards") or (4 if group_deck else 3))
        bbq_shift = non_rainbow_count - bbq_threshold
        charm_owned = owned.get("Good-Luck Charm", 0)
        is_senior_or_later = current_turn > 48
        charm_stop_qty = 2 if is_senior_or_later else 3
        charm_stop = charm_owned >= charm_stop_qty
        cupcake_names = {"Plain Cupcake", "Berry Sweet Cupcake"}
        total_cupcakes = sum(owned.get(n, 0) for n in cupcake_names)
        skip_cupcakes = total_cupcakes >= 2 or (is_senior_or_later and total_cupcakes >= 1) or motivation >= 5
        cupcake_shift = total_cupcakes - 1 if skip_cupcakes else 0
        active_ailments = self._active_bad_statuses(data)
        has_miracle = owned.get("Miracle Cure", 0) > 0

        available = []
        for row in pickups:
            shop_item_id = int(row.get("shop_item_id") or 0)
            item_id = int(row.get("item_id") or 0)
            name = ITEM_NAMES.get(item_id)
            if not name:
                continue
            cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(name, 9999))
            limit_turn = int(row.get("limit_turn") or 0)
            limit = int(row.get("limit_buy_count") or 1)
            current_num = int(row.get("item_buy_num") or 0)
            skip_reason = None
            if shop_item_id <= 0 or shop_item_id in self.failed_exchange_this_snapshot:
                skip_reason = "failed_snapshot"
            elif limit_turn > 0 and limit_turn < current_turn:
                skip_reason = "expired"
            elif current_num >= limit:
                skip_reason = "limit_reached"
            elif is_climax_shop:
                # Climax shop (last 6 turns): unspent coins are wasted, so buy EVERYTHING
                # purchasable -- only the hard never-buy junk is still skipped.
                if name in set(preset.get("never_buy_items") or DEFAULT_NEVER_BUY):
                    skip_reason = "never_buy"
            elif scrolls_only and item_id in STAT_LOWER_TIER_IDS and not (buy_manuals and item_id in MANUAL_STAT_IDS):
                skip_reason = "scrolls_only"
            elif self._skip_buy(name, owned, preset, current_turn, start_budget, data, race_planner):
                skip_reason = "skip_buy"
            self.last_buy_options.append({
                "name": name,
                "item_id": item_id,
                "shop_item_id": shop_item_id,
                "cost": cost,
                "current_num": current_num,
                "limit": limit,
                "limit_turn": limit_turn,
                "turns_left": (limit_turn - current_turn) if limit_turn > 0 else None,
                "skip_reason": skip_reason,
            })
            if not skip_reason:
                available.append((name, row))

        if not available:
            self.last_buy_result = {"skip": "no_available", "mant_coin": budget}
            return state, 0

        pre_summer = bool(preset.get("pre_summer_stock", True)) and current_turn in (cfg.get("pre_summer_window") or PRE_SUMMER_TURNS)
        effective_rows = []
        for name, row in available:
            slug = display_to_slug(name)
            base_t = int(tiers.get(slug) or 999)
            # Training Applications sit at tier 7, i.e. effectively unreachable -- so merely setting
            # buy_training_applications would still never buy one and the experiment would silently
            # measure nothing. When the knob is ON, promote them to training_app_tier (default 3).
            if slug.endswith("_training_application") and preset.get("buy_training_applications", False):
                base_t = int(preset.get("training_app_tier", 3))
            eff_t = base_t
            for ailment in active_ailments:
                specific_cure = AILMENT_CURE_MAP.get(ailment)
                if specific_cure and name == specific_cure and not has_miracle and owned.get(name, 0) <= 0:
                    eff_t = 1
            if slug == "miracle_cure" and active_ailments and not has_miracle:
                eff_t = 1
            if slug == "miracle_cure" and owned.get(name, 0) <= 0:
                eff_t = 1
            if slug == "grilled_carrots":
                eff_t = min(eff_t, base_t - bbq_shift)
            elif slug == "good-luck_charm":
                eff_t = 999 if charm_stop else min(eff_t, base_t - charm_owned)
            elif slug in {"plain_cupcake", "berry_sweet_cupcake"}:
                eff_t = min(eff_t, base_t - cupcake_shift)
            elif slug in {"artisan_cleat_hammer", "master_cleat_hammer"}:
                eff_t = 999
            elif name in TRAINING_ITEM_DECK_TYPE_INDEX:
                # Deck-match priority: a stat item (Ankle Weights / Training Application)
                # whose stat the deck is built around gets a higher priority (lower tier)
                # than a borderline secondary stat. So a Speed-heavy deck (4 cards) buys
                # Speed Ankle Weights before Power ones (2 cards), instead of treating all
                # stat items at the same tier. Items for stats with < min cards were
                # already dropped by _skip_buy, so this only orders the ones worth buying.
                if preset.get("deck_match_stat_items", True):
                    type_idx = TRAINING_ITEM_DECK_TYPE_INDEX.get(name)
                    dc = int(deck_counts[type_idx]) if (deck_counts and type_idx is not None and 0 <= type_idx < len(deck_counts)) else 0
                    if is_junior and name.endswith("Ankle Weights"):
                        # Junior: main-stat anklet (>=2 cards) -> tier 2, off-stat (<2) -> tier 3.
                        eff_t = self._junior_ankle_tier(dc)
                    else:
                        bump = max(0, dc - int(preset.get("deck_match_min_count") or 2))
                        eff_t = max(1, base_t - bump)
            if pre_summer:
                boost = self._pre_summer_boost_tier(name, owned, cfg)
                if boost is not None:
                    eff_t = min(eff_t, boost)
            effective_rows.append((max(1, eff_t), name, row))

        targets = []
        selected_ids = set()
        if is_climax_shop:
            # Buy out the climax shop: every available item, cheapest first so the most fit in
            # the saved coins. Hammers included -> the use-timing reserve then spends the 35%
            # Masters at t76/t78.
            for name, row in sorted(available, key=lambda nr: int(nr[1].get("coin_num") or SHOP_ITEM_COSTS.get(nr[0], 9999))):
                if id(row) in selected_ids:
                    continue
                cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(name, 9999))
                if cost <= budget:
                    targets.append(row)
                    selected_ids.add(id(row))
                    budget -= cost
        else:
            cleat_row = self._old_ui_cleat_shop_target(available, owned, budget, current_turn)
            if cleat_row:
                cleat_name = ITEM_NAMES.get(int(cleat_row.get("item_id") or 0), "")
                cleat_cost = int(cleat_row.get("coin_num") or SHOP_ITEM_COSTS.get(cleat_name, 9999))
                if cleat_cost <= budget:
                    targets.append(cleat_row)
                    selected_ids.add(id(cleat_row))
                    budget -= cleat_cost

            for tier in range(1, tier_count + 1):
                tier_rows = [(name, row) for eff_t, name, row in effective_rows if eff_t == tier and id(row) not in selected_ids]
                tier_rows.sort(key=lambda item: (int(item[1].get("limit_turn") or 99), int(item[1].get("coin_num") or SHOP_ITEM_COSTS.get(item[0], 9999))))
                for name, row in tier_rows:
                    cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(name, 9999))
                    remaining = budget - cost
                    if remaining < 0:
                        continue
                    threshold = 0
                    thresholds = cfg.get("tier_thresholds") or {}
                    if tier > 1 and current_turn <= 64:
                        raw_threshold = int(thresholds.get(str(tier), thresholds.get(tier, (tier - 1) * 50)) or 0)
                        threshold = int(raw_threshold * sale_modifier)
                    floor = self._buy_floor(name, tier, current_turn, start_budget, budget, threshold, cfg)
                    if remaining < floor:
                        continue
                    targets.append(row)
                    selected_ids.add(id(row))
                    budget = remaining

            # Late-career surplus sweep. From CLIMAX_COIN_RESERVE_FROM the 200-coin climax fund has
            # already been carved out of `budget` above, so anything still sitting here is pure
            # surplus that otherwise dies unspent at turn 78 (measured: 279 coins/career across 60
            # careers; turns 73-78 earn no coins at all). Convert it to instant stat items, highest
            # CURRENT stat first so the points land where the score curve is steepest.
            # ponytail: measured recovery is only ~4 coins/career -- by this point the shop has no
            # stat items left on the shelf. Kept as free insurance, NOT as the fix for coin waste
            # (that was the anklet over-buy, handled in _skip_buy).
            if current_turn >= CLIMAX_COIN_RESERVE_FROM and budget > 0:
                def _sweep_rank(item):
                    prefix = display_to_slug(item[0]).split("_")[0]
                    pair = self._STAT_ITEM_KEYS.get(prefix)
                    return -int((chara or {}).get(pair[0]) or 0) if pair else 0

                sweep_rows = [(nm, rw) for nm, rw in available
                              if id(rw) not in selected_ids
                              and self._is_instant_stat_item(nm)
                              and self._stat_item_has_headroom(nm, chara)]
                for name, row in sorted(sweep_rows, key=_sweep_rank):
                    cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(name, 9999))
                    if cost <= budget:
                        targets.append(row)
                        selected_ids.add(id(row))
                        budget -= cost

        if not targets:
            self.last_buy_result = {"skip": "no_targets", "mant_coin": budget, "start_mant_coin": start_budget}
            return state, 0

        self.last_buy_selected = [{
            "name": ITEM_NAMES.get(int(row.get("item_id") or 0), ""),
            "item_id": int(row.get("item_id") or 0),
            "shop_item_id": int(row.get("shop_item_id") or 0),
            "cost": int(row.get("coin_num") or SHOP_ITEM_COSTS.get(ITEM_NAMES.get(int(row.get("item_id") or 0), ""), 9999)),
            "current_num": int(row.get("item_buy_num") or 0),
            "limit_turn": int(row.get("limit_turn") or 0),
        } for row in targets]

        payload = []
        for row in targets:
            sid = int(row.get("shop_item_id") or 0)
            if sid > 0 and sid not in self.failed_exchange_this_snapshot:
                payload.append({"shop_item_id": sid, "current_num": 0})

        if not payload:
            self.last_buy_result = {"skip": "empty_payload", "mant_coin": budget, "start_mant_coin": start_budget}
            return state, 0

        return self._exchange_batch(client, state, payload, current_turn)

    def _exchange_batch(self, client, state, payload, current_turn):
        if not payload:
            return state, 0

        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        source_turn = int(chara.get("turn") or 0)

        if source_turn != current_turn:
            self.last_buy_result = {"skip": "stale_turn_detected", "request_current_turn": current_turn, "source_state_turn": source_turn}
            return state, 0

        free = data.get("free_data_set") or {}
        coin_val = free.get("coin_num")
        if coin_val is None:
            coin_val = free.get("gained_coin_num")
        budget = int(coin_val or 0)

        valid_shop_rows = {int(row.get("shop_item_id") or 0): row for row in free.get("pick_up_item_info_array") or []}

        owned_by_id = {}
        for row in free.get("user_item_info_array") or []:
            owned_by_id[int(row.get("item_id") or 0)] = int(row.get("num") or row.get("current_num") or row.get("item_num") or 0)

        valid_payload = []
        attempt_items = []
        total_cost = 0
        for item in payload:
            shop_item_id = int(item.get("shop_item_id") or 0)
            if shop_item_id <= 0:
                continue
            shop_row = valid_shop_rows.get(shop_item_id)
            if not shop_row:
                continue
            cost = int(shop_row.get("coin_num") or SHOP_ITEM_COSTS.get(ITEM_NAMES.get(int(shop_row.get("item_id") or 0), ""), 9999))
            limit_turn = int(shop_row.get("limit_turn") or 0)
            if limit_turn > 0 and limit_turn < current_turn:
                continue
            if int(shop_row.get("item_buy_num") or 0) >= int(shop_row.get("limit_buy_count") or 1):
                continue
            if total_cost + cost > budget:
                continue
            total_cost += cost

            valid_payload.append({
                "shop_item_id": shop_item_id,
                "current_num": owned_by_id.get(int(shop_row.get("item_id") or 0), 0)
            })
            attempt_items.append({
                "shop_item_id": shop_item_id,
                "cost": cost,
                "current_num": owned_by_id.get(int(shop_row.get("item_id") or 0), 0)
            })

        if not valid_payload:
            self.last_buy_result = {"skip": "preflight_failed", "mant_coin": budget}
            return state, 0

        self.last_buy_attempt = list(valid_payload)
        event = {
            "turn": current_turn,
            "selected": list(self.last_buy_selected),
            "attempt": list(attempt_items),
            "payload": list(valid_payload),
            "result": {},
        }
        self.buy_attempt_events.append(event)
        try:
            result = client.exchange_items(valid_payload, current_turn)
            self.last_buy_result = {"result": "ok", "turn": current_turn, "payload": valid_payload}
            event["result"] = self.last_buy_result
            self.failed_exchange_this_snapshot = set()
            return self._merge_state(state, result), len(valid_payload)
        except Exception as e:
            print(f"Item Exchange Error at turn {current_turn}: {e}")
            if any(code in str(e) for code in ("201", "205", "208")):
                self.recover_after_exchange_error = True
            for item in valid_payload:
                self.failed_exchange_this_snapshot.add(int(item.get("shop_item_id") or 0))
            self.last_buy_result = {"result": "failed", "turn": current_turn, "error": str(e), "payload": valid_payload}
            event["result"] = self.last_buy_result
            return state, 0

    def _is_g1_program(self, program_id, race_planner):
        if not race_planner or not program_id:
            return False
        info = (race_planner.program or {}).get(program_id) or {}
        race_inst = str(info.get("race_instance_id") or "")
        return race_inst.startswith("1")

    def _should_use_glow_stick(self, turn, owned_count, program_id, race_planner):
        """Decide whether to spend a Glow Stick before this race.

        Marquee races (Arima Kinen, Japan Cup): spend greedily, as before. Climax races
        (turns 74/76/78): spend toward the highest-fan climax first (3 > 2 > 1 per the
        user). Since turns play in order, hold sticks at the earlier climax for the later,
        bigger one -- use at t74 only if we hold >=3, at t76 if >=2, at t78 if >=1."""
        if int(owned_count or 0) <= 0:
            return False
        turn = int(turn or 0)
        if turn in CLIMAX_RACE_TURNS:
            return owned_count > GLOW_STICK_CLIMAX_RESERVE.get(turn, 0)
        # Non-climax marquee races, identified by name.
        if not race_planner or not program_id:
            return False
        name = str(((race_planner.program or {}).get(int(program_id or 0)) or {}).get("name") or "").lower()
        return "arima kinen" in name or "japan cup" in name

    def _old_ui_cleat_before_race(self, owned, turn, program_id, race_planner):
        """Use a Cleat Hammer on every G1 race and at the climax. The caller only invokes
        this on a G1 or climax race, so reaching here means "spend a hammer if we own one"
        -- with one reserve: from after Senior summer camp onward, keep the LAST Master in
        hand for the climax (the climax shop may not restock hammers)."""
        master_qty = owned.get("Master Cleat Hammer", 0)
        artisan_qty = owned.get("Artisan Cleat Hammer", 0)
        if master_qty + artisan_qty <= 0:
            return None

        # Climax races: save the 35% Masters toward the biggest/latest climax -- keep
        # MASTER_CLEAT_CLIMAX_RESERVE in hand at each climax for the later ones (1 Master ->
        # t78 only; 2 -> t76 + t78; 3 -> t74/76/78). Fall back to a weaker Artisan when no
        # Master is free to spend this climax.
        if turn in CLIMAX_RACE_TURNS:
            if master_qty > MASTER_CLEAT_CLIMAX_RESERVE.get(turn, 0):
                return "Master Cleat Hammer"
            if artisan_qty > 0:
                return "Artisan Cleat Hammer"
            return None

        # Every other G1: spend the weaker Artisan (20%) first.
        if artisan_qty > 0:
            return "Artisan Cleat Hammer"

        # Only Masters left. From MASTER_CLEAT_SAVE_FROM (turn 69) on, hold the last Master in
        # reserve for the climax. Before turn 69, spend any hammer freely on any G1.
        if turn >= MASTER_CLEAT_SAVE_FROM and master_qty <= 1:
            return None
        return "Master Cleat Hammer"

    def _old_ui_cleat_shop_target(self, available, owned, budget, current_turn):
        CLASSIC_YEAR_END = 48
        SENIOR_YEAR_END = 72

        master_qty = owned.get("Master Cleat Hammer", 0)
        artisan_qty = owned.get("Artisan Cleat Hammer", 0)
        total_cleats = master_qty + artisan_qty
        is_senior = CLASSIC_YEAR_END < current_turn <= SENIOR_YEAR_END
        is_climax = current_turn > SENIOR_YEAR_END
        if not (is_senior or is_climax):
            return None

        available_by_name = {name: row for name, row in available}
        if is_senior:
            if total_cleats >= 2:
                return None
            for candidate in ("Master Cleat Hammer", "Artisan Cleat Hammer"):
                row = available_by_name.get(candidate)
                if not row:
                    continue
                cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(candidate, 9999))
                if cost <= budget:
                    return row
            return None

        if total_cleats >= 3:
            return None
        if total_cleats < 2 and budget < 40:
            return None
        for candidate in ("Master Cleat Hammer", "Artisan Cleat Hammer"):
            row = available_by_name.get(candidate)
            if not row:
                continue
            cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(candidate, 9999))
            if cost > budget:
                continue
            if total_cleats < 2 and budget - cost < 40:
                continue
            return row
        return None

    def use_items(self, client, state, preset, best_command=None, status=None, race_planner=None):
        data = state.get("data") or {}
        free = data.get("free_data_set") or {}
        chara = data.get("chara_info") or {}
        owned = self._owned_map(free)
        current_turn = int(chara.get("turn") or 0)
        self._set_turn(current_turn)
        self.last_use_options = []
        self.last_use_selected = []
        self.last_use_attempt = []
        self.last_use_result = {}
        self.use_attempt_events = []
        if not owned:
            self.last_use_result = {"skip": "no_owned"}
            return state, 0
        targets = []
        for name in INSTANT_USE_ITEMS:
            qty = owned.get(name, 0)
            if qty <= 0:
                continue
            if DISPLAY_TO_ID.get(name) in self.failed_use_this_turn:
                continue
            if name in ONE_TIME_BUFF_ITEMS:
                if name in self.used_buffs:
                    continue
                targets.append((name, 1))
            else:
                # Notepad/Manual/Scroll give flat PERMANENT stats that are truncated to +0
                # once the stat hits its in-game cap -- dumping them on a capped stat wastes
                # them. Skip an instant stat item when its stat has no headroom left.
                if (preset.get("skip_capped_stat_items", True)
                        and not self._stat_item_has_headroom(name, chara)):
                    continue
                targets.append((name, qty))

        energy_targets = self._energy_targets(chara, owned, preset)
        targets.extend(energy_targets)
        rescue_targets = self._rescue_energy_target(chara, owned, preset, best_command)
        targets.extend(rescue_targets)
        targets.extend(self._ailment_cure_targets(data, owned))
        mood_target = self._mood_target(chara, owned, preset)
        if mood_target:
            targets.append(mood_target)

        whistle = (None if self.whistled_turn == current_turn
                   else self._whistle_target(best_command, owned, preset, status, current_turn))
        if whistle:
            targets = [whistle]
        else:
            # Vita-first, charm-fallback: if any energy item is already being used this
            # turn, it covers the failure -- only reach for the scarce charm otherwise.
            vita_covered = bool(energy_targets) or bool(rescue_targets)
            charm = self._charm_target(best_command, owned, preset, status, chara, vita_covered)
            if charm:
                targets.append(charm)
            mega = self._megaphone_target(state, best_command, owned, preset, status, current_turn, race_planner)
            if mega:
                targets.append(mega)
            anklet = self._anklet_target(state, best_command, owned, preset)
            if anklet:
                targets.append(anklet)

        # Royal Kale Juice gives a big energy boost but DRAINS mood, so whenever it's being
        # used (to power a desired training the bot is too tired for), pair a cupcake to offset
        # the mood hit (see _kale_mood_offset: +1 Plain first, +2 Berry Sweet only if no Plain).
        kale_cup = self._kale_mood_offset({n for n, _ in targets}, owned)
        if kale_cup:
            targets.append(kale_cup)

        targets = self._merge_targets(targets, owned)
        selected_names = {name for name, _ in targets}
        for name, count in sorted(owned.items()):
            item_id = DISPLAY_TO_ID.get(name)
            if not item_id or count <= 0:
                continue
            failed = item_id in self.failed_use_this_turn
            selected = name in selected_names and not failed
            reason = None if selected else ("failed_this_turn" if failed else "not_useful_now")
            self.last_use_options.append({
                "name": name,
                "item_id": item_id,
                "current_num": int(count),
                "selected": selected,
                "skip_reason": reason,
                "reason": "selected" if selected else reason,
                "turn": current_turn,
                "context": {
                    "command_type": int((best_command or {}).get("command_type") or 0),
                    "command_id": int((best_command or {}).get("command_id") or 0),
                    "command_group_id": int((best_command or {}).get("command_group_id") or 0),
                },
            })
        if not targets:
            self.last_use_result = {"skip": "no_targets"}
            return state, 0

        payload = []
        valid_targets = []
        for name, count in targets:
            item_id = DISPLAY_TO_ID.get(name)
            if not item_id or item_id in self.failed_use_this_turn:
                continue
            have = int(owned.get(name) or 0)
            if have < count or have <= 0:
                continue

            valid_targets.append((name, count))
            payload.append({
                "item_id": item_id,
                "use_num": count,
                "current_num": have
            })

        if not payload:
            self.last_use_result = {"skip": "empty_payload"}
            return state, 0

        self.last_use_selected = [{"name": name, "item_id": DISPLAY_TO_ID.get(name), "use_num": count} for name, count in valid_targets]
        self.last_use_attempt = list(payload)
        event = {
            "turn": current_turn,
            "selected": list(self.last_use_selected),
            "attempt": list(payload),
            "payload": list(payload),
            "result": {},
        }
        self.use_attempt_events.append(event)
        try:
            res = client.use_items(payload, current_turn)
            self.failed_use_this_turn = set()
            if any(name == "Reset Whistle" for name, _ in valid_targets):
                self.whistled_turn = current_turn
            for name, _ in valid_targets:
                if name in ONE_TIME_BUFF_ITEMS:
                    self.used_buffs.add(name)
            self.last_use_result = {"result": "ok", "turn": current_turn, "payload": payload}
            event["result"] = self.last_use_result
            return self._merge_state(state, res), len(payload)
        except Exception as exc:
            print(f"Item Use Error at turn {current_turn}: {exc}")
            if any(code in str(exc) for code in ("201", "205", "208")):
                self.recover_after_use_error = True
                # A batched multi_item_use fails wholesale if ANY single item is currently
                # invalid (e.g. a megaphone/charm that needs a training context). Don't
                # blacklist the always-valid instant stat items + energy bundled into the same
                # call -- only the context-sensitive ones -- so the recovery retry can still
                # use owned Scrolls/Vita instead of wrongly skipping them for the whole turn.
                for item in payload:
                    iid = int(item.get("item_id") or 0)
                    nm = ITEM_NAMES.get(iid, "")
                    if self._is_instant_stat_item(nm) or nm in ENERGY_ITEMS:
                        continue
                    self.failed_use_this_turn.add(iid)
            self.last_use_result = {"result": "failed", "turn": current_turn, "error": str(exc), "payload": payload}
            event["result"] = self.last_use_result
            return state, 0

    def _merge_state(self, state, res):
        if res and isinstance(res, dict) and "data" in res:
            if not state: state = {}
            if "data" not in state: state["data"] = {}
            for k, v in res["data"].items():
                if isinstance(v, dict) and isinstance(state["data"].get(k), dict):
                    state["data"][k].update(v)
                else:
                    state["data"][k] = v
        return state

    def _is_instant_stat_item(self, name):
        slug = display_to_slug(name)
        return slug.endswith("_notepad") or slug.endswith("_manual") or slug.endswith("_scroll")

    # Per-stat (current, cap) chara_info keys -- Wit maps to wiz/max_wiz, matching mant.py.
    _STAT_ITEM_KEYS = {
        "speed": ("speed", "max_speed"), "stamina": ("stamina", "max_stamina"),
        "power": ("power", "max_power"), "guts": ("guts", "max_guts"), "wit": ("wiz", "max_wiz"),
    }

    def _stat_item_has_headroom(self, name, chara):
        """For an instant flat-stat item, is its stat below its in-game cap? Returns True
        (don't block) for non-stat items or when cap info is missing -- only a genuinely
        capped stat returns False, so the use path skips a scroll that would gain nothing."""
        if not self._is_instant_stat_item(name):
            return True
        prefix = display_to_slug(name).split("_")[0]
        pair = self._STAT_ITEM_KEYS.get(prefix)
        if not pair:
            return True
        cur = int((chara or {}).get(pair[0]) or 0)
        cap = int((chara or {}).get(pair[1]) or 0)
        if cap <= 0:
            return True  # no cap info -> never block
        return cur < cap

    def _coin_reserve(self, turn, budget, cfg):
        if turn <= 20:
            reserve = 160
        elif turn <= 35:
            reserve = 220
        elif turn <= 45:
            reserve = 180
        elif turn <= 55:
            reserve = 120
        elif turn <= 64:
            reserve = 80
        elif turn <= 72:
            reserve = 40
        else:
            reserve = 0
        reserve = int(cfg.get("mant_coin_reserve", reserve) if "mant_coin_reserve" in cfg else reserve)
        cap = self._coin_cap(turn, cfg)
        if cap and budget > cap:
            reserve = min(reserve, max(0, cap // 2))
        if turn >= 73:
            return 0
        if turn >= 65 and budget > 300:
            return min(reserve, 40)
        if turn >= 56 and budget > 220:
            return min(reserve, 60)
        if turn >= 46 and budget > 260:
            return min(reserve, 80)
        if turn >= 36 and budget > 320:
            return min(reserve, 120)
        return reserve

    def _coin_cap(self, turn, cfg):
        if turn <= 20:
            return int(cfg.get("mant_coin_cap_t20", 999999))
        if turn <= 35:
            return int(cfg.get("mant_coin_cap_t35", 300))
        if turn <= 45:
            return int(cfg.get("mant_coin_cap_t45", 260))
        if turn <= 55:
            return int(cfg.get("mant_coin_cap_t55", 200))
        if turn <= 64:
            return int(cfg.get("mant_coin_cap_t64", 140))
        if turn <= 72:
            return int(cfg.get("mant_coin_cap_t72", 80))
        return int(cfg.get("mant_coin_cap_final", 0))

    def _buy_floor(self, name, tier, turn, start_budget, budget, threshold, cfg):
        reserve = self._coin_reserve(turn, start_budget, cfg)
        cap = self._coin_cap(turn, cfg)
        floor = max(int(threshold or 0), reserve) if tier > 1 else 0
        if self._is_instant_stat_item(name):
            if turn >= 46:
                return 0
            if turn >= 36 and start_budget > cap:
                return min(floor, 40)
            if start_budget > cap:
                return min(floor, reserve // 2)
            return min(floor, reserve)
        if turn >= 73:
            return 0
        if start_budget > cap:
            floor = min(floor, max(0, reserve // 2))
        if start_budget >= reserve + 400:
            floor = min(floor, max(0, reserve // 3))
        elif start_budget >= reserve + 250:
            floor = min(floor, max(0, reserve // 2))
        if turn >= 65:
            floor = min(floor, 40)
        elif turn >= 56:
            floor = min(floor, 80)
        elif turn >= 46:
            floor = min(floor, 120)
        return max(0, int(floor))

    def _mant_cfg(self, preset):
        cfg = dict((preset or {}).get("mant_config") or {})
        cfg.setdefault("item_tiers", DEFAULT_ITEM_TIERS)
        cfg.setdefault("tier_count", 8)
        cfg.setdefault("tier_thresholds", {"3": 31, "7": 100, "8": 99999999999})
        cfg.setdefault("charm_failure_rate", 30)
        cfg.setdefault("charm_min_stat", 27)
        cfg.setdefault("mega_small_threshold", 11)
        cfg.setdefault("mega_medium_threshold", 21)
        cfg.setdefault("mega_large_threshold", 35)
        cfg.setdefault("mega_late_buy_buffer", 5)
        cfg.setdefault("training_weights_threshold", 40)
        return cfg

    def _owned_map(self, free):
        result = {}
        for row in free.get("user_item_info_array") or []:
            item_id = int(row.get("item_id") or 0)
            name = ITEM_NAMES.get(item_id)
            if name:

                qty = int(row.get("num") or row.get("current_num") or row.get("item_num") or 0)
                result[name] = result.get(name, 0) + qty
        return result

    def _active_bad_statuses(self, data):
        result = []
        for effect_id in (data.get("chara_info") or {}).get("chara_effect_id_array") or []:
            try:
                effect_id = int(effect_id)
            except (TypeError, ValueError):
                continue
            name = BAD_EFFECT_NAMES.get(effect_id)
            if name:
                result.append(name)
        return result

    def _needed_cures(self, data, owned):
        result = []
        if owned.get(AILMENT_CURE_ALL, 0) > 0:
            return result
        for ailment in self._active_bad_statuses(data):
            cure = AILMENT_CURE_MAP.get(ailment)
            if cure and owned.get(cure, 0) <= 0:
                result.append(cure)
        return result

    def _ailment_cure_targets(self, data, owned):
        result = []
        active_ailments = self._active_bad_statuses(data)
        if not active_ailments:
            return result

        unhandled_ailments = []
        for ailment in active_ailments:
            cure = AILMENT_CURE_MAP.get(ailment)
            if cure and owned.get(cure, 0) > 0:
                result.append((cure, 1))
            else:
                unhandled_ailments.append(ailment)

        if unhandled_ailments and owned.get(AILMENT_CURE_ALL, 0) > 0:
            result.append((AILMENT_CURE_ALL, 1))
        return result

    def _energy_targets(self, chara, owned, preset):
        result = []
        hp = int(chara.get("vital") or 0)
        max_hp = int(chara.get("max_vital") or 100)
        gap = max_hp - hp
        if gap < 20:
            return result
        cfg = self._mant_cfg(preset)
        threshold = int(cfg.get("energy_recovery_threshold") or 30)
        if hp > threshold:
            return result

        candidates = []
        has_cupcake = owned.get("Plain Cupcake", 0) > 0 or owned.get("Berry Sweet Cupcake", 0) > 0
        for name, value in ENERGY_ITEMS.items():
            qty = owned.get(name, 0)
            if qty > 0:
                # Royal Kale Juice (+100 energy) drains a mood tier -- only spend it when a cupcake
                # is held to offset that mood hit (paired by _kale_mood_offset).
                if name == "Royal Kale Juice" and not has_cupcake:
                    continue
                candidates.append({"name": name, "value": value, "qty": qty})

        candidates.sort(key=lambda x: x["value"], reverse=True)

        remaining_gap = gap
        for c in candidates:
            if remaining_gap <= 5: break
            num_to_use = min(c["qty"], (remaining_gap + 5) // c["value"])
            if num_to_use > 0:
                result.append((c["name"], num_to_use))
                remaining_gap -= num_to_use * c["value"]

        return result

    def _rescue_energy_target(self, chara, owned, preset, best_command):
        """Top up energy (smallest sufficient Vita, stacking drinks if one isn't enough --
        see _cover_to_target) so a STRONG training at up to just-below-50% failure (the
        chosen best_command) can run this turn instead of being rested away for low energy.
        Mirrors MantStrategy._can_rescue_training so the post-item re-decision actually
        trains it. Very-low energy (<= reactive floor) is left to the normal _energy_targets;
        here we only handle the 'a bit too tired for a great turn' band."""
        if not (preset or {}).get("rescue_good_training", True):
            return []
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return []
        vital = int(chara.get("vital") or 0)
        cfg = self._mant_cfg(preset)
        reactive_floor = int(cfg.get("energy_recovery_threshold") or 30)
        if vital <= reactive_floor:
            return []  # reactive _energy_targets already refills critically low energy
        rest_threshold = int((preset or {}).get("rest_threshold") or 48)
        margin = int((preset or {}).get("rescue_vital_margin") or 12)
        target = rest_threshold + margin
        if vital >= target:
            return []  # already enough energy to train without resting
        failure = int(best_command.get("failure_rate") or 0)
        # Mirror mant.py's failure hard-cap: above the cap an energy bump is NOT trusted to
        # clear the failure, so the energy rescue does not fire (only a charm may, via
        # _charm_target). Keeps this half in agreement with _can_rescue_training.
        if failure >= int((preset or {}).get("failure_hard_cap") or 50):
            return []
        at_risk = vital <= rest_threshold or failure >= int(cfg.get("rescue_failure") or 30)
        if not at_risk:
            return []
        gain = self._command_stat_gain(best_command)
        rainbow = self._rainbow_count(best_command, chara)
        turn = int((chara or {}).get("turn") or 0)
        # All-out: the TS climax (last 6 turns) and the summer Lv5 camp -- now for EVERY deck (the camp
        # facilities are Lv5 regardless of card type), not just group decks. Top up energy for ANY
        # positive-gain training there, not just rainbow/big turns -- mirrors training_brain's camp
        # force-train, which falls through to train these and relies on this top-up actually firing.
        # Without it the two halves disagree and the turn trains at low energy with the item unused.
        all_out = (((preset or {}).get("climax_all_out", True) and turn in CLIMAX_TRAIN_TURNS)
                   or ((preset or {}).get("summer_all_out", True) and turn in SUMMER_TRAINING_TURNS))
        if rainbow < 1 and gain < int(cfg.get("rescue_train_stat") or 27) and not (all_out and gain > 0):
            return []
        has_cupcake = owned.get("Plain Cupcake", 0) > 0 or owned.get("Berry Sweet Cupcake", 0) > 0
        return self._cover_to_target(vital, target, owned, has_cupcake)

    def _cover_to_target(self, vital, target, owned, has_cupcake=False):
        """Smallest set of owned energy drinks that lifts `vital` past `target` (the safe
        zone, ~0% fail). Prefer ONE drink -- the smallest single Vita that reaches it; only
        when no single drink is enough do we STACK largest-first (e.g. a Vita 40 plus a Vita
        20) until it clears. Royal Kale (drains a mood tier) is skipped unless a cupcake is
        held to offset it, and is the last resort even then. Returns a list of (name, count);
        empty if even all usable drinks fall short."""
        usable = {n: v for n, v in ENERGY_ITEMS.items()
                  if owned.get(n, 0) > 0 and (n != "Royal Kale Juice" or has_cupcake)}
        # 1) smallest single sufficient drink (preserves the old one-drink behaviour)
        best = None
        for name, value in usable.items():
            if vital + value > target and (best is None or value < usable[best]):
                best = name
        if best:
            return [(best, 1)]
        # 2) no single drink reaches the target -> stack largest-first, Kale last
        combo, cur = [], vital
        for name in sorted(usable, key=lambda n: (n == "Royal Kale Juice", -usable[n])):
            if cur > target:
                break
            value = usable[name]
            use = min(owned[name], (target - cur) // value + 1)
            if use > 0:
                combo.append((name, use))
                cur += use * value
        return combo if cur > target else []

    def _kale_mood_offset(self, target_names, owned):
        """Cupcake to offset Royal Kale Juice's mood drain when the kale is being used this
        turn: a +1 Plain Cupcake first, a +2 Berry Sweet only if no Plain is owned. Returns
        None when the kale isn't used or a cupcake is already in play (no double-cupcaking)."""
        if "Royal Kale Juice" not in target_names:
            return None
        if target_names & {"Plain Cupcake", "Berry Sweet Cupcake"}:
            return None
        if owned.get("Plain Cupcake", 0) > 0:
            return ("Plain Cupcake", 1)
        if owned.get("Berry Sweet Cupcake", 0) > 0:
            return ("Berry Sweet Cupcake", 1)
        return None

    def _mood_target(self, chara, owned, preset=None):
        motivation = int(chara.get("motivation") or 3)
        if motivation >= 5:
            return None

        needed = 5 - motivation

        # Don't burn a cupcake the turn before a free mood bonus that already closes the
        # gap -- just wait for it next turn. (Tunable: wait_for_free_bonus, default on.)
        if (preset or {}).get("wait_for_free_bonus", True) and \
                free_bonus_within(chara.get("turn"), "mood") >= needed:
            return None

        if owned.get("Berry Sweet Cupcake", 0) > 0:
            return ("Berry Sweet Cupcake", 1)

        if owned.get("Plain Cupcake", 0) > 0:
            use_num = min(owned.get("Plain Cupcake"), needed)
            return ("Plain Cupcake", use_num)

        return None

    def _hold_for_summer(self, item_name, owned, turn, preset):
        """True if this buff (megaphone / ankle / Reset Whistle) should be SAVED for an
        upcoming summer camp instead of used now -- a camp is still ahead and using it
        would drop to/below the reserve. Spares above the reserve stay usable. Off inside
        the camp turns and after the last camp. Tunable: prioritize_summer_buffs (default
        on) + summer_mega_stock / summer_ankle_stock / summer_whistle_stock."""
        if not (preset or {}).get("prioritize_summer_buffs", True):
            return False
        turn = int(turn or 0)
        if turn in SUMMER_TRAINING_TURNS or turn >= max(SUMMER_TRAINING_TURNS):
            return False  # in-camp, or past the last camp -> spend freely
        cfg = self._mant_cfg(preset)
        if item_name in MEGAPHONE_TIERS:
            return self._owned_megaphone_count(owned) <= int(cfg.get("summer_mega_stock") or 2)
        if str(item_name).endswith("Ankle Weights"):
            # Reserve 0, NOT 1. _skip_buy now caps anklet stock at 1 per stat, so a summer reserve
            # of 1 would make this "owned(1) <= 1" True on every pre-camp turn and freeze the only
            # anklet for the whole year -- turning a buy-side fix into a use-side regression. Spend
            # it now; _pre_summer_boost_tier still restocks to summer_ankle_stock before camp.
            return int(owned.get(item_name, 0) or 0) <= int(cfg.get("summer_ankle_stock") or 0)
        if item_name == "Reset Whistle":
            return int(owned.get(item_name, 0) or 0) <= int(cfg.get("summer_whistle_stock") or 1)
        return False

    def _whistle_target(self, best_command, owned, preset, status, turn):
        if owned.get("Reset Whistle", 0) <= 0:
            return None
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None
        if self._hold_for_summer("Reset Whistle", owned, turn, preset):
            return None

        score = self._command_stat_gain(best_command)
        cfg = self._mant_cfg(preset)
        threshold = int(cfg.get("whistle_score_threshold") or 35)
        if score < threshold and turn <= 72:
             return ("Reset Whistle", 1)
        return None

    def _charm_target(self, best_command, owned, preset, status, chara=None, vita_covered=False):
        # Good-Luck Charm is a scarce item that forces 0% failure. Spend it ONLY on a
        # strong training whose failure a cheaper Vita can't cover -- the user's rule:
        # "good training + risky failure -> use Vita if it covers it, else the charm."
        if owned.get("Good-Luck Charm", 0) <= 0:
            return None
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None
        fail_rate = int(best_command.get("failure_rate") or 0)
        cfg = self._mant_cfg(preset)
        if fail_rate < int(cfg.get("charm_failure_rate") or 30):
            return None
        # Above the failure hard-cap, _can_rescue_training only let this strong turn train
        # BECAUSE a charm is owned (energy isn't trusted that high), so the charm MUST fire
        # here regardless of Vita-coverage or the stat-gain gate -- otherwise the turn would
        # run unmitigated at a dangerous failure. Below the cap, keep the Vita-first +
        # strong-turn rules.
        above_cap = fail_rate >= int((preset or {}).get("failure_hard_cap") or 50)
        # VERY good training (>= 2 rainbows or a big stat gain) at a risky failure (>= charm_failure_rate,
        # i.e. >30%): ALWAYS spend the charm to force 0% -- the turn is too valuable to gamble or to
        # defer to a Vita. Tunable: charm_very_good_rainbow (2), charm_very_good_gain (40).
        if chara is not None and (
                self._rainbow_count(best_command, chara) >= int(cfg.get("charm_very_good_rainbow") or 2)
                or self._command_stat_gain(best_command) >= int(cfg.get("charm_very_good_gain") or 40)):
            return ("Good-Luck Charm", 1)
        # Vita-first: if an energy item is already topping up this turn (which lowers the
        # failure), the cheap Vita is covering it -- don't burn the charm.
        if vita_covered and not above_cap:
            return None
        # Only worth a charm on a genuinely strong turn (a rainbow or a big stat gain),
        # not a mediocre training.
        if chara is not None and not above_cap:
            rainbow = self._rainbow_count(best_command, chara)
            gain = self._command_stat_gain(best_command)
            # Climax window: spend the charm to carry ANY positive training, not just a strong one.
            in_climax = ((preset or {}).get("climax_all_out", True)
                         and int(chara.get("turn") or 0) in CLIMAX_TRAIN_TURNS)
            if rainbow < 1 and gain < int(cfg.get("charm_min_stat") or 27) and not (in_climax and gain > 0):
                return None
        return ("Good-Luck Charm", 1)

    def _megaphone_target(self, state, best_command, owned, preset, status, turn, race_planner):
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None

        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        # "Strong board" = the same bar the strategy uses to skip a G2/G3 for training (>= the
        # rainbow min OR >= the total-stat min). The user requires a megaphone on these turns, so a
        # strong board BYPASSES the summer-reserve hold AND is treated as at least a 'large' board
        # for the tier selection below (picks the best owned megaphone even on a modest stat number).
        rainbow_min = int((preset or {}).get("strong_train_rainbow_min") or 2)
        stat_min = float((preset or {}).get("strong_train_stat_total_min") or 40)
        strong = (self._rainbow_count(best_command, chara) >= rainbow_min
                  or self._command_stat_gain(best_command) >= stat_min)

        # Save megaphones for the summer camps -- only spend the spare stock before then, unless
        # this is a strong board the user requires a megaphone on.
        if not strong and self._hold_for_summer("Coaching Megaphone", owned, turn, preset):
            return None

        free_data = data.get("free_data_set") or {}
        item_effects = free_data.get("item_effect_array") or []
        current_mega_tier = self._active_megaphone_tier(state)
        # Never stack megaphones: if one is already running, wait until its turns expire before
        # using another. Re-applying on top would waste the active megaphone's remaining duration
        # (Coaching lasts 4 turns, Motivating 3, Empowering 2).
        if current_mega_tier > 0:
            return None

        # Summer-camp schedule: Motivating (+40%, 3 turns) at the camp START blankets the first
        # 3 camp turns; an Empowering (+60%, 2 turns) on the LAST camp turn -- only on a strong
        # board -- caps it. 2 megaphones cover the whole camp; the no-stack guard above skips the
        # in-between turns. Falls back to the best owned tier if the preferred one isn't held.
        if turn in SUMMER_MOTIVATING_TURNS:
            for nm in ("Motivating Megaphone", "Empowering Megaphone", "Coaching Megaphone"):
                if owned.get(nm, 0) > 0:
                    return (nm, 1)
            return None
        if turn in SUMMER_EMPOWERING_TURNS:
            if not strong:
                return None   # weak last-camp board -> hold the Empowering for a better turn
            for nm in ("Empowering Megaphone", "Motivating Megaphone", "Coaching Megaphone"):
                if owned.get(nm, 0) > 0:
                    return (nm, 1)
            return None

        score = self._command_stat_gain(best_command, sp_weight=0.5)
        cfg = self._mant_cfg(preset)
        small_threshold = float(cfg.get("mega_small_threshold") or 11)
        medium_threshold = float(cfg.get("mega_medium_threshold") or 21)
        large_threshold = float(cfg.get("mega_large_threshold") or 35)
        if strong:
            score = max(score, large_threshold)
        dump_mode = self._megaphone_dump_mode(data, owned, turn, race_planner, preset)
        slots_left = self._remaining_megaphone_slots(data, turn, race_planner, preset)
        owned_count = self._owned_megaphone_count(owned)
        inventory_pressure = slots_left > 0 and owned_count >= slots_left
        has_upgrade_pair = owned.get("Motivating Megaphone", 0) > 0 and owned.get("Empowering Megaphone", 0) > 0 and slots_left >= 2

        target_tier = 0
        if current_mega_tier <= 0:
            if has_upgrade_pair and score >= medium_threshold:
                return ("Motivating Megaphone", 1)
            if score >= large_threshold and owned.get("Empowering Megaphone", 0) > 0:
                return ("Empowering Megaphone", 1)
            if score >= medium_threshold and owned.get("Motivating Megaphone", 0) > 0:
                return ("Motivating Megaphone", 1)
            if score >= small_threshold and owned.get("Coaching Megaphone", 0) > 0:
                return ("Coaching Megaphone", 1)
            if inventory_pressure or dump_mode:
                if has_upgrade_pair:
                    return ("Motivating Megaphone", 1)
                if owned.get("Empowering Megaphone", 0) > 0:
                    return ("Empowering Megaphone", 1)
                if score >= medium_threshold and owned.get("Motivating Megaphone", 0) > 0:
                    return ("Motivating Megaphone", 1)
                if score >= small_threshold and owned.get("Coaching Megaphone", 0) > 0:
                    return ("Coaching Megaphone", 1)
                if owned.get("Coaching Megaphone", 0) > 0:
                    return ("Coaching Megaphone", 1)
                if owned.get("Motivating Megaphone", 0) > 0:
                    return ("Motivating Megaphone", 1)
                if owned.get("Empowering Megaphone", 0) > 0:
                    return ("Empowering Megaphone", 1)
            else:
                if score >= large_threshold:
                    target_tier = 3
                elif score >= medium_threshold:
                    target_tier = 2
                elif score >= small_threshold:
                    target_tier = 1

        if target_tier >= 3 and current_mega_tier < 3 and owned.get("Empowering Megaphone", 0) > 0:
            return ("Empowering Megaphone", 1)
        if target_tier >= 2 and current_mega_tier < 2 and owned.get("Motivating Megaphone", 0) > 0:
            return ("Motivating Megaphone", 1)
        if target_tier >= 1 and current_mega_tier < 1 and owned.get("Coaching Megaphone", 0) > 0:
            return ("Coaching Megaphone", 1)

        return None

    def _megaphone_dump_mode(self, data, owned, turn, race_planner, preset):
        training_turns_left = self._remaining_megaphone_slots(data, turn, race_planner, preset)
        total_duration = 0
        for name, (_, duration) in MEGAPHONE_TIERS.items():
            total_duration += int(owned.get(name, 0) or 0) * duration
        return training_turns_left > 0 and total_duration >= training_turns_left

    def _owned_megaphone_count(self, owned):
        total = 0
        for name in MEGAPHONE_TIERS:
            total += int(owned.get(name, 0) or 0)
        return total

    def _megaphone_buy_surplus(self, data, owned, turn, race_planner, preset):
        slots_left = self._remaining_megaphone_slots(data, turn, race_planner, preset)
        if slots_left <= 0:
            return False
        cfg = self._mant_cfg(preset)
        buffer = int(cfg.get("mega_late_buy_buffer") or 3)
        target = max(0, slots_left - buffer)
        return self._owned_megaphone_count(owned) >= target

    def _remaining_megaphone_slots(self, data, turn, race_planner, preset):
        return self._remaining_training_turns_to_77(data, turn, race_planner, preset)

    def _remaining_training_turns_to_77(self, data, turn, race_planner, preset):
        planned_race_turns = self._planned_race_turns_to_77(data, turn, race_planner, preset)
        race_condition_array = data.get("race_condition_array") or []
        remaining = 0
        for t in range(int(turn or 0), 77):
            if t in (74, 76):
                continue
            if t not in planned_race_turns:
                remaining += 1
        return remaining

    def _planned_race_turns_to_77(self, data, turn, race_planner, preset):
        current_turn = int(turn or 0)
        wanted_pids = set()
        if race_planner and preset:
            wanted_pids = race_planner.wanted_programs(preset)
        result = set()
        for item in data.get("race_condition_array") or []:
            item_turn = int(item.get("turn") or 0)
            program_id = int(item.get("program_id") or 0)
            if item_turn >= current_turn and item_turn < 77 and (not wanted_pids or program_id in wanted_pids):
                result.add(item_turn)
        if race_planner and wanted_pids:
            for program_id in wanted_pids:
                info = (race_planner.program or {}).get(int(program_id or 0)) or {}
                race_turn = self._program_turn_from_month_half(info, current_turn)
                if race_turn >= current_turn and race_turn < 77:
                    result.add(race_turn)
        return result

    def _program_turn_from_month_half(self, program_info, current_turn):
        month = int((program_info or {}).get("month") or 0)
        half = int((program_info or {}).get("half") or 0)
        if month <= 0 or half <= 0:
            return 0
        base_turn = (month - 1) * 2 + half
        candidates = [base_turn + 24 * year for year in range(4)]
        for candidate in candidates:
            if candidate >= int(current_turn or 0):
                return candidate
        return candidates[-1]

    def _anklet_target(self, state, best_command, owned, preset):
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None

        cmd_id = int(best_command.get("command_id") or 0)
        anklet = TRAINING_TYPE_ANKLET.get(cmd_id)
        if not anklet or owned.get(anklet, 0) <= 0:
            return None

        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        # "Strong board" = the same bar the strategy uses to skip a G2/G3 for training (>= the
        # rainbow min OR >= the total-stat min). On these turns the user requires the matching-type
        # anklet to be used, so a strong board BYPASSES the summer-reserve hold -- otherwise the
        # hold would silently withhold the very anklet the gate skipped the race to amplify.
        rainbow_min = int((preset or {}).get("strong_train_rainbow_min") or 2)
        stat_min = float((preset or {}).get("strong_train_stat_total_min") or 40)
        strong = (self._rainbow_count(best_command, chara) >= rainbow_min
                  or self._command_stat_gain(best_command) >= stat_min)

        turn = int(chara.get("turn") or 0)
        if not strong and self._hold_for_summer(anklet, owned, turn, preset):
            return None

        item_effects = (data.get("free_data_set") or {}).get("item_effect_array") or []
        for eff in item_effects:
            if eff.get("item_id") in (9001, 9002, 9003, 9004, 9005):
                return None  # an anklet buff is already active this turn

        score = self._command_stat_gain(best_command, sp_weight=0.5)
        threshold = 30 * (1 - (0.2 * self._active_megaphone_tier(state)))
        if strong or score > threshold:
            return (anklet, 1)
        return None

    def _active_megaphone_tier(self, state):
        current_mega_tier = 0
        for eff in ((state.get("data") or {}).get("free_data_set") or {}).get("item_effect_array") or []:
            item_id = eff.get("item_id")
            if item_id == 8001: current_mega_tier = max(current_mega_tier, 1)
            elif item_id == 8002: current_mega_tier = max(current_mega_tier, 2)
            elif item_id == 8003: current_mega_tier = max(current_mega_tier, 3)
        return current_mega_tier

    def _rainbow_count(self, command, chara):
        """Deck supports at max bond (>=80) present on this training = rainbows.
        Used to recognise a 'good training' worth spending a Vita/charm to run."""
        if not command or not chara:
            return 0
        bonds = {}
        for row in chara.get("evaluation_info_array") or []:
            bonds[int(row.get("target_id") or 0)] = int(row.get("evaluation") or 0)
        count = 0
        for pid in command.get("training_partner_array") or []:
            pid = int(pid or 0)
            if pid in {1, 2, 3, 4, 5, 6} and bonds.get(pid, 0) >= 80:
                count += 1
        return count

    def _command_stat_gain(self, cmd, sp_weight=0):
        if not cmd: return 0
        total = 0
        for item in cmd.get("params_inc_dec_info_array") or []:
            tt = item.get("target_type")
            if tt in [1, 2, 3, 4, 5]:
                total += int(item.get("value") or 0)
            elif (tt == 6 or tt == 30) and sp_weight > 0:
                total += int(item.get("value") or 0) * sp_weight
        if total == 0:
            for field in ["speed", "stamina", "power", "guts", "wiz"]:
                total += int(cmd.get(field) or 0)
            if sp_weight > 0:
                total += int(cmd.get("lp") or cmd.get("skill_point") or 0) * sp_weight
        return total

    def _merge_targets(self, targets, owned):
        counts = {}
        for name, count in targets:
            counts[name] = counts.get(name, 0) + count
        result = []
        for name, count in counts.items():
            actual = min(count, owned.get(name, 0))
            if actual > 0:
                result.append((name, actual))
        return result

    def _pre_summer_boost_tier(self, name, owned, cfg):
        """During the pre-camp window, give summer-prep items that are still under their
        target owned-count a high buy priority (low tier number) so the Lv5 camp turns are
        stocked. Returns the boosted tier, or None for items not being stockpiled. All
        targets are tunable via mant_config."""
        tier = int(cfg.get("pre_summer_tier") or 2)
        if name == "Empowering Megaphone" and owned.get(name, 0) < int(cfg.get("summer_mega_stock") or 2):
            return tier
        if name == "Good-Luck Charm" and owned.get(name, 0) < int(cfg.get("summer_charm_stock") or 2):
            return tier
        if name in ENERGY_ITEMS and sum(owned.get(n, 0) for n in ENERGY_ITEMS) < int(cfg.get("summer_energy_stock") or 3):
            return tier
        if name.endswith("Ankle Weights") and owned.get(name, 0) < int(cfg.get("summer_ankle_stock") or 1):
            return tier
        return None

    def _skip_buy(self, name, owned, preset=None, turn=0, budget=0, data=None, race_planner=None):
        # Notepads (+3 stat) are poor value per coin -- never buy them by default
        # (tunable via preset "buy_notepads"). Scrolls/Manuals stay must-buy.
        # Hard blocklist -- user-flagged "inefficient" items the bot never buys.
        if name in ((preset or {}).get("never_buy_items") or DEFAULT_NEVER_BUY):
            return True
        if name.endswith("Notepad") and not (preset or {}).get("buy_notepads", False):
            return True
        # Training Applications (+1 training level for a stat, 150 coins) are OFF by default and
        # unmeasured: master.mdb defines the effect but not the level -> gain curve (the client
        # computes it), and the bot has never bought one in 878 career logs, so there is no
        # before/after to learn from. Meanwhile the shop offers ~688 coins/career of them.
        # To settle it, run scripts/analyze_training_apps.py -- it derives the level -> gain curve
        # from ordinary careers (facilities level 1->5 naturally, and the per-turn log now records
        # each facility's level next to its gains), so NO purchase is needed to get the answer.
        # If that says WORTH IT, set buy_training_applications: true.
        if name.endswith("Training Application"):
            if not (preset or {}).get("buy_training_applications", False):
                return True
            # A level-up only pays back over the trainings that FOLLOW it, so late buys are dead
            # money. Default window: before turn 45, leaving ~25+ training turns to earn it back.
            if int(turn or 0) > int((preset or {}).get("training_app_last_turn", 45)):
                return True
        # Motivating Megaphone is the BACKUP for when no Empowering Megaphone is on offer:
        # cap it (default 2) and spend the rest on Empowering (which is now the lower/preferred
        # tier). Empowering and Coaching are unaffected by this cap.
        if name == "Motivating Megaphone" and owned.get(name, 0) >= int((preset or {}).get("motivating_megaphone_cap", 2)):
            return True
        if name in MEGAPHONE_TIERS and self._megaphone_buy_surplus(data or {}, owned, turn, race_planner, preset):
            return True
        if name in CURE_ITEMS:
            cure_stock = (preset or {}).get("cure_stock_targets") or DEFAULT_CURE_STOCK
            target = int(cure_stock.get(name, 1))
            if owned.get(name, 0) >= target:
                return True
            # A specific cure is redundant if a Miracle Cure (cure-all) is owned -- but not
            # for cures we deliberately stock to a target (e.g. Rich Hand Cream).
            if name not in cure_stock and name != AILMENT_CURE_ALL and owned.get(AILMENT_CURE_ALL, 0) > 0:
                return True
        type_idx = TRAINING_ITEM_DECK_TYPE_INDEX.get(name)
        if type_idx is not None:
            counts = (preset or {}).get("_deck_type_counts") or []
            count = int(counts[type_idx] or 0) if len(counts) > type_idx else 0
            if name.endswith("Ankle Weights"):
                # An anklet is a ONE-TURN, non-stacking buff: at most one can ever be spent per
                # turn, so held stock above 1 per stat is dead weight. Deck-card count turned out to
                # be a poor proxy for "will this facility actually be trained" -- measured over 60
                # MANT careers, Stamina/Power got ~1.4 matching training turns but 2-3 anklets each,
                # while Wit (11.3 trainings/career) has no anklet at all. Net: 10.2 anklets bought
                # vs 3.0 used per career, ~350 coins burned. The USE gate is fine; the BUY was not.
                # ankle_offdeck_stock now defaults to 0 (never stock a stat with no deck cards) and
                # ankle_max_stock (default 1) hard-caps held stock per stat.
                # ponytail: still a stock cap, not a forecast. If the brain ever exposes "planned
                # facility for the remaining turns", gate on that instead.
                per_card = int((preset or {}).get("ankle_per_deck_card", 2))
                cap = per_card * count if count > 0 else int((preset or {}).get("ankle_offdeck_stock", 0))
                cap = min(cap, int((preset or {}).get("ankle_max_stock", 1)))
                return owned.get(name, 0) >= cap
            # Training Applications keep the stricter deck-focus threshold (>=2 cards).
            if count < 2:
                return True
            return False
        if name in ONE_TIME_BUFF_ITEMS and name in self.used_buffs:
            return True
        return False
