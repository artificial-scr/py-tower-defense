"""Monster data: enemy stats, looks and mechanics, and the monster player's abilities and stat upgrades,
from monsters.json.

Read and checked once, at import. A mistake stops the game with a message naming the problem.
"""

import os

from towers import SHAPES, read_json

MONSTERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monsters.json")

ENEMY_FIELDS = ("name", "hp", "speed", "cost", "damage", "gap", "draft", "size", "color", "sides")
# Optional fields; their meaning is in the comment at the top of monsters.json.
ENEMY_EXTRAS = ("elite", "boss", "fatal", "shape", "inner", "armor", "heal_aura", "split", "phase", "slow_floor", "summon",
                "summon_max", "ward", "decoy", "enrage", "rebound", "sabotage", "loot",
                "speed_aura", "ambush", "follows", "layoff", "dividends", "severance", "bankrupts")
AMBUSH_FIELDS = ("from_level", "chance", "max")
AMBUSH_GROWTH = (("angered_by", "per_kill"), ("per_gold",))  # what an ambush's odds grow with: one of these
DRAFT = ("starter", "unlock", "boss", "never")

ABILITY_FIELDS = ("name", "desc", "target", "effect", "cooldown", "color")
ABILITY_EXTRAS = ("radius", "amount", "duration")
# effect -> the optional fields it needs
EFFECTS = {"disable": ("duration",), "range": ("amount", "duration"), "haste": ("amount", "duration"),
           "heal": ("amount",), "shield": ("amount", "duration")}
TARGETS = ("area", "all")
BUDGET_FIELDS = ("share_start", "starter_picks", "upgrade_price", "escort_per_wave", "max_lives_per_level",
                 "pace_per_life", "pace_max", "pace_min")
TIERS = ("weak", "normal", "strong")
TIER_FIELDS = ("cards", "rare", "share")
UPGRADE_FIELDS = ("name", "desc", "stat", "per_rank", "max")
UPGRADE_STATS = ("hp", "speed", "armor")
SPEED_UPGRADE_CAP = 0.5  # a speed upgrade's ranks add up to +50% speed at most
WARD_BREAK = 0.3  # seconds a Warded's ward is drawn shattering after it absorbs a hit


def load_monsters(path):
    """Return (enemy types, abilities, budget rules, stat upgrades, reward tiers) from monsters.json."""
    data = read_json(path)
    name = os.path.basename(path)

    def fail(what, message):
        raise ValueError(f"{name}: {what}: {message}")

    def check_fields(what, raw, required, extras):
        missing = [f for f in required if f not in raw]
        unknown = [f for f in raw if f not in required + extras]
        if missing or unknown:
            fail(what, f"missing fields {missing}" if missing else f"unknown fields {unknown}")

    enemies = {}
    for kind, raw in data["enemies"].items():
        what = f"enemy {kind!r}"
        check_fields(what, raw, ENEMY_FIELDS, ENEMY_EXTRAS)
        if raw["draft"] not in DRAFT:
            fail(what, f"draft must be one of {DRAFT}")
        if ("boss" in raw) != (raw["draft"] == "boss"):
            fail(what, "bosses need both a boss name and draft: boss")
        if "elite" in raw and not (raw["elite"] is True and "boss" not in raw):
            fail(what, "elite must be true, on a monster that isn't a boss")
        if raw["hp"] <= 0 or raw["speed"] <= 0 or raw["cost"] <= 0:
            fail(what, "hp, speed and cost must be positive")
        if "ward" in raw and not (isinstance(raw["ward"], (int, float)) and raw["ward"] > 0):
            fail(what, "ward must be a positive number of seconds")
        if "decoy" in raw and not (len(raw["decoy"]) == 3 and all(isinstance(x, (int, float)) and x > 0
                                                                 for x in raw["decoy"])):
            fail(what, "decoy must be [every, ahead, life], all positive")
        if "enrage" in raw and not (isinstance(raw["enrage"], (int, float)) and raw["enrage"] > 0):
            fail(what, "enrage must be a positive speed share")
        if "rebound" in raw and not (len(raw["rebound"]) == 2 and all(isinstance(x, (int, float)) and x > 0
                                                                     for x in raw["rebound"])):
            fail(what, "rebound must be [speed share, seconds], both positive")
        if "sabotage" in raw and not (len(raw["sabotage"]) == 2 and all(isinstance(x, (int, float)) and x > 0
                                                                       for x in raw["sabotage"])):
            fail(what, "sabotage must be [radius, seconds], both positive")
        if "loot" in raw and not (len(raw["loot"]) == 2 and 0 < raw["loot"][0] <= 1 and raw["loot"][1] >= 0):
            fail(what, "loot must be [share of gold, 0 to 1; budget multiple, 0 or more]")
        if "layoff" in raw and not (len(raw["layoff"]) == 3 and all(isinstance(x, (int, float)) and x > 0
                                                                   for x in raw["layoff"])):
            fail(what, "layoff must be [every, radius, seconds], all positive")
        for f in ("dividends", "severance"):
            if f in raw and not (isinstance(raw[f], (int, float)) and raw[f] > 0):
                fail(what, f"{f} must be a positive number")
        if "bankrupts" in raw and not (raw["bankrupts"] is True and "boss" in raw and not raw.get("fatal")):
            fail(what, "bankrupts must be true, on a boss that isn't fatal")
        if "severance" in raw and raw["severance"] > 1:
            fail(what, "severance is a share of the gold stolen, at most 1")
        if "speed_aura" in raw and not (len(raw["speed_aura"]) == 2 and all(isinstance(x, (int, float)) and x > 0
                                                                           for x in raw["speed_aura"])):
            fail(what, "speed_aura must be [radius, speed share], both positive")
        for shape in [raw.get("shape"), raw.get("inner", [None])[0]]:
            if shape is not None and shape not in SHAPES:
                fail(what, f"unknown shape {shape!r}")
        spec = dict(raw, color=tuple(raw["color"]))
        if "inner" in raw:
            shape, r, color = raw["inner"]
            spec["inner"] = (shape, r, tuple(color))
        for f in ("heal_aura", "split", "phase", "summon", "decoy", "rebound", "sabotage", "loot",
                  "speed_aura", "layoff"):
            if f in raw:
                spec[f] = tuple(raw[f])
        enemies[kind] = spec
    for kind, spec in enemies.items():
        for f in ("split", "summon"):
            for k in summon_kinds(spec[f]) if f in spec else ():
                if k not in enemies:
                    fail(f"enemy {kind!r}", f"{f} makes {k!r}, which isn't an enemy")
        if "summon_max" in spec and not ("summon" in spec and isinstance(spec["summon_max"], int)
                                         and spec["summon_max"] >= spec["summon"][1]):
            fail(f"enemy {kind!r}", "summon_max needs a summon, and must be a whole number, at least its count")
        if "summon" in spec and len(spec["summon"]) == 4 and len(spec["summon"][3]) != spec["summon"][1]:
            fail(f"enemy {kind!r}", "summon offsets need one per summoned monster")
        if "follows" in spec:
            follows = spec["follows"]
            if not ("boss" in spec and sorted(follows) == ["announce", "boss", "chance"]
                    and "boss" in enemies.get(follows["boss"], {}) and follows["boss"] != kind):
                fail(f"enemy {kind!r}", "only bosses follow, only another boss, with boss, chance and announce")
            if not 0 <= follows["chance"] <= 1:
                fail(f"enemy {kind!r}", "follows: chance must be between 0 and 1")
        if "ambush" in spec:
            ambush = spec["ambush"]
            if "boss" not in spec or not any(sorted(ambush) == sorted(AMBUSH_FIELDS + g) for g in AMBUSH_GROWTH):
                fail(f"enemy {kind!r}", f"only bosses ambush, with {AMBUSH_FIELDS} and one of {AMBUSH_GROWTH}")
            if not (ambush["from_level"] >= 1 and 0 <= ambush["chance"] <= ambush["max"] <= 1):
                fail(f"enemy {kind!r}", "ambush: from_level at least 1, and 0 <= chance <= max <= 1")
            if ambush.get("per_gold", 0) < 0 or ambush.get("per_kill", 0) < 0:
                fail(f"enemy {kind!r}", "ambush: per_kill and per_gold can't be negative")
            for k in ambush.get("angered_by", ()):
                if k not in enemies:
                    fail(f"enemy {kind!r}", f"ambush: angered_by {k!r}, which isn't an enemy")

    abilities = {}
    for key, raw in data["abilities"].items():
        what = f"ability {key!r}"
        check_fields(what, raw, ABILITY_FIELDS, ABILITY_EXTRAS)
        if raw["effect"] not in EFFECTS:
            fail(what, f"effect must be one of {tuple(EFFECTS)}")
        if raw["target"] not in TARGETS:
            fail(what, f"target must be one of {TARGETS}")
        needs = EFFECTS[raw["effect"]] + (("radius",) if raw["target"] == "area" else ())
        missing = [f for f in needs if f not in raw]
        if missing:
            fail(what, f"{raw['effect']} on {raw['target']} needs {missing}")
        abilities[key] = dict(raw, color=tuple(raw["color"]))

    budget = data["budget"]
    check_fields("budget", budget, BUDGET_FIELDS, ())
    if not all(isinstance(budget[f], (int, float)) and budget[f] >= 0 for f in BUDGET_FIELDS):
        fail("budget", f"{', '.join(BUDGET_FIELDS)} must be numbers, 0 or more")

    upgrades = {}
    for key, raw in data["upgrades"].items():
        what = f"upgrade {key!r}"
        check_fields(what, raw, UPGRADE_FIELDS, ())
        if raw["stat"] not in UPGRADE_STATS:
            fail(what, f"stat must be one of {UPGRADE_STATS}")
        if not (raw["per_rank"] > 0 and isinstance(raw["max"], int) and raw["max"] >= 1):
            fail(what, "per_rank must be positive and max a whole number, 1 or more")
        if raw["stat"] == "speed" and raw["per_rank"] * raw["max"] > SPEED_UPGRADE_CAP + 1e-9:
            fail(what, f"speed can go up by {SPEED_UPGRADE_CAP:.0%} at most (per_rank x max)")
        upgrades[key] = dict(raw)

    rewards = data["rewards"]
    check_fields("rewards", rewards, ("tiers",) + TIERS, ())
    for side in ("monsters", "towers"):
        bounds = rewards["tiers"].get(side)
        if not (isinstance(bounds, list) and len(bounds) == 2 and 0 <= bounds[0] <= bounds[1]):
            fail("rewards", f"tiers.{side} must be [weak below, strong from], in order")
    for tier in TIERS:
        check_fields(f"rewards tier {tier!r}", rewards[tier], TIER_FIELDS, ())
        if not (isinstance(rewards[tier]["cards"], int) and rewards[tier]["cards"] >= 1):
            fail(f"rewards tier {tier!r}", "cards must be a whole number, 1 or more")
    return enemies, abilities, budget, upgrades, rewards


def summon_kinds(summon):
    """The kinds a split or summon makes, in turn: its kind, or its list of kinds."""
    return [summon[0]] if isinstance(summon[0], str) else list(summon[0])


def summon_count(spec, level_idx, levels):
    """How many minions a summoner calls at a level (0-based, of `levels`): its summon count, or with
    summon_max, rising evenly from the count on the first level to summon_max on the last."""
    count = spec["summon"][1]
    if "summon_max" not in spec or levels < 2:
        return count
    return round(count + (spec["summon_max"] - count) * min(level_idx, levels - 1) / (levels - 1))


def summon_offsets(offsets, count):
    """Where `count` minions land along the path: the listed offsets if there are that many, or else spread
    evenly from the furthest behind to the furthest ahead."""
    if len(offsets) == count or count < 2:
        return list(offsets[:count])
    lo, hi = min(offsets), max(offsets)
    return [lo + (hi - lo) * i / (count - 1) for i in range(count)]


ENEMY_TYPES, ABILITIES, BUDGET, UPGRADES, REWARDS = load_monsters(MONSTERS_FILE)
