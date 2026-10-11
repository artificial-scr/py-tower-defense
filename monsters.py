"""Monster data: enemy stats, looks and mechanics, and the monster player's abilities, from monsters.json.

Read and checked once, at import. A mistake stops the game with a message naming the problem.
"""

import os

from towers import SHAPES, read_json

MONSTERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monsters.json")

ENEMY_FIELDS = ("name", "hp", "speed", "cost", "damage", "gap", "draft", "size", "color", "sides")
# Optional fields; their meaning is in the comment at the top of monsters.json.
ENEMY_EXTRAS = ("boss", "fatal", "shape", "inner", "armor", "heal_aura", "split", "phase", "slow_floor", "summon")
DRAFT = ("starter", "unlock", "boss", "never")

ABILITY_FIELDS = ("name", "desc", "target", "effect", "cooldown", "color")
ABILITY_EXTRAS = ("radius", "amount", "duration")
# effect -> the optional fields it needs
EFFECTS = {"disable": ("duration",), "range": ("amount", "duration"), "haste": ("amount", "duration"),
           "heal": ("amount",), "shield": ("amount", "duration")}
TARGETS = ("area", "all")
BUDGET_FIELDS = ("share_start", "share_per_win", "starter_picks")


def load_monsters(path):
    """Return (enemy types, abilities, budget rules) from monsters.json."""
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
        if raw["hp"] <= 0 or raw["speed"] <= 0 or raw["cost"] <= 0:
            fail(what, "hp, speed and cost must be positive")
        for shape in [raw.get("shape"), raw.get("inner", [None])[0]]:
            if shape is not None and shape not in SHAPES:
                fail(what, f"unknown shape {shape!r}")
        spec = dict(raw, color=tuple(raw["color"]))
        if "inner" in raw:
            shape, r, color = raw["inner"]
            spec["inner"] = (shape, r, tuple(color))
        for f in ("heal_aura", "split", "phase", "summon"):
            if f in raw:
                spec[f] = tuple(raw[f])
        enemies[kind] = spec
    for kind, spec in enemies.items():
        for f in ("split", "summon"):
            if f in spec and spec[f][0] not in enemies:
                fail(f"enemy {kind!r}", f"{f} makes {spec[f][0]!r}, which isn't an enemy")

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
        fail("budget", "share_start, share_per_win and starter_picks must be numbers, 0 or more")
    return enemies, abilities, budget


ENEMY_TYPES, ABILITIES, BUDGET = load_monsters(MONSTERS_FILE)
