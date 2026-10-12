"""Tower data: stats and looks from towers.json, the evolution tree from evolution.json.

Both files are read and checked once, at import. A mistake in either stops the game with
a message naming the file and the problem.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TOWERS_FILE = os.path.join(HERE, "towers.json")
EVOLUTION_FILE = os.path.join(HERE, "evolution.json")

# Shapes a tower layer can use (sprites.layer draws them).
SHAPES = ("circle", "square", "diamond", "triangle", "hexagon", "octagon", "star")
# Optional mechanics a tower can have:
#   splash      radius damaged around the impact point
#   slow        speed multiplier applied for slow_time seconds
#   burn        damage per second for burn_time seconds
#   chain       lightning jumps to this many extra enemies
#   multishot   number of targets fired at per shot
#   instant     hits immediately with a beam instead of a projectile
#   vs_slowed   damage multiplier against enemies that are already slowed
MECHANICS = ("splash", "slow", "slow_time", "burn", "burn_time", "chain", "multishot", "instant", "vs_slowed")
TOWER_FIELDS = ("name", "tier", "desc", "range", "damage", "rate", "proj_speed", "cost", "look")
REQUIRED_TOWER_FIELDS = ("name", "tier", "desc", "range", "damage", "rate", "look")


def read_json(path):
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as err:
            raise ValueError(f"{os.path.basename(path)}: {err}") from None


def load_towers(path):
    """Read tower stats and looks (see the comment at the top of towers.json)."""
    data = read_json(path)
    palette = {name: tuple(rgb) for name, rgb in data.get("palette", {}).items()}

    def fail(kind, message):
        raise ValueError(f"{os.path.basename(path)}: tower {kind!r}: {message}")

    def color(kind, c):
        if isinstance(c, str):
            if c not in palette:
                fail(kind, f"unknown palette color {c!r}")
            return palette[c]
        return tuple(c)

    towers = {}
    for kind, raw in data["towers"].items():
        missing = [f for f in REQUIRED_TOWER_FIELDS if f not in raw]
        unknown = [f for f in raw if f not in TOWER_FIELDS + MECHANICS]
        if missing or unknown:
            fail(kind, f"missing fields {missing}" if missing else f"unknown fields {unknown}")
        for mechanic, partner in (("slow", "slow_time"), ("burn", "burn_time")):
            if (mechanic in raw) != (partner in raw):
                fail(kind, f"{mechanic} and {partner} go together")
        layers = [(shape, r, color(kind, c)) for shape, r, c in raw["look"]["layers"]]
        if not layers or any(shape not in SHAPES for shape, _, _ in layers):
            fail(kind, f"look needs layers with shapes from {SHAPES}")
        towers[kind] = dict(
            name=raw["name"], tier=raw["tier"], line=None, desc=raw["desc"], range=raw["range"],
            damage=raw["damage"], rate=raw["rate"], proj_speed=raw.get("proj_speed", 400), cost=raw.get("cost"),
            look=dict(layers=layers, barrels=tuple(raw["look"].get("barrels", (0, 0, 0)))), color=layers[0][2],
            **{m: raw[m] for m in MECHANICS if m in raw})
    return towers


def load_evolution(path, towers):
    """Read the evolution tree (see the comment at the top of evolution.json) and set each tower's line.

    Returns (buyable kinds in order, lines, evolve, cross):
      lines   line -> (tier 1, tier 2, (tier 3 branch, tier 3 branch))
      evolve  kind -> what two of it fuse into (two kinds = a branch choice)
      cross   frozenset of two tier 3 kinds -> the final they fuse into
    """
    data = read_json(path)

    def fail(message):
        raise ValueError(f"{os.path.basename(path)}: {message}")

    def check(kind, tier, where):
        if kind not in towers:
            fail(f"{where}: {kind!r} is not in towers.json")
        if towers[kind]["tier"] != tier:
            fail(f"{where}: {kind!r} is tier {towers[kind]['tier']} in towers.json, expected tier {tier}")

    lines, evolve, cross = {}, {}, {}
    for line, steps in data["lines"].items():
        t1, t2, branches = steps["tier1"], steps["tier2"], tuple(steps["tier3"])
        if len(branches) != 2:
            fail(f"line {line!r}: tier3 needs exactly two branches")
        for kind, tier in ((t1, 1), (t2, 2), *((b, 3) for b in branches)):
            check(kind, tier, f"line {line!r}")
            if towers[kind]["line"]:
                fail(f"line {line!r}: {kind!r} is already in line {towers[kind]['line']!r}")
            towers[kind]["line"] = line
        if towers[t1]["cost"] is None:
            fail(f"line {line!r}: {t1!r} is bought from the panel, so it needs a cost in towers.json")
        lines[line] = (t1, t2, branches)
        evolve[t1] = [t2]
        evolve[t2] = list(branches)
    for final, parents in data["finals"].items():
        check(final, 4, f"final {final!r}")
        if len(parents) != 2:
            fail(f"final {final!r}: needs exactly two parents")
        a, b = parents
        for parent in parents:
            check(parent, 3, f"final {final!r}")
        if towers[a]["line"] == towers[b]["line"]:
            fail(f"final {final!r}: parents must come from different lines")
        if frozenset(parents) in cross:
            fail(f"final {final!r}: {a} + {b} already makes {cross[frozenset(parents)]!r}")
        cross[frozenset(parents)] = final
    unused = [k for k in towers if not towers[k]["line"] and k not in data["finals"]]
    if unused:
        fail(f"towers that can never be built: {unused}")
    return [t1 for t1, _, _ in lines.values()], lines, evolve, cross


TOWERS = load_towers(TOWERS_FILE)
TOWER_ORDER, LINES, EVOLVE, CROSS = load_evolution(EVOLUTION_FILE, TOWERS)
# kind -> the lines it belongs to: one for tiers 1-3, both parents' lines for a final
TOWER_LINES = {k: (s["line"],) if s["line"] else () for k, s in TOWERS.items()}
for parents, final in CROSS.items():
    TOWER_LINES[final] = tuple(sorted(TOWERS[p]["line"] for p in parents))

# What tower cards (unlocks.json) change, with no cards: damage multiplier per line, range multiplier,
# extra starting gold and lives, sell refund share, whether towers can target phased monsters, the
# armor multiplier towers impose on monsters, and how long area abilities last on towers.
NO_TOWER_MODS = {"damage": {line: 1.0 for line in LINES}, "range": 1.0, "gold": 0, "lives": 0, "refund": 0.7,
                 "detector": False, "armor": 1.0, "grounding": 1.0}


def fusion_options(a, b):
    """Tower kinds that fusing kinds `a` and `b` can produce (empty if they can't fuse)."""
    if a == b:
        return EVOLVE.get(a, [])
    result = CROSS.get(frozenset((a, b)))
    return [result] if result else []
