"""Tower balance numbers, worked out from towers.json, evolution.json and monsters.json (no game is played).

    uv run analytics/tower_stats.py                       # every table
    uv run analytics/tower_stats.py --level 8 --wave 5    # monsters as tough as that generated wave
    uv run analytics/tower_stats.py --monsters all        # every monster in the pass table
    uv run analytics/tower_stats.py --csv towers.csv      # the main table as CSV too

The model (the real rules are in entities.py):
  - a tower stands on the tile next to a straight stretch of path, so the path passes TILE px from its
    centre and runs through 2 * sqrt(range² - TILE²) px of its range (a corner gives it more)
  - monsters walk in single file, SPACINGS px apart: "1 target" is a lone monster, "wave" the usual
    gap in generated waves (speed x gap is 40-60 px), "swarm" Swarmlings and Spiderlings (~14 px)
  - DPS is sustained: a tower's own slow counts for its vs_slowed bonus when it hits again before the
    slow wears off (and its own burn for vs_burning); a partner's slow or burn isn't counted, and a burn counts in full when it's renewed before it runs out; burns don't stack
  - splash, multishot and chain hit an endless line of monsters; multishot can't pick more targets
    than are in range
  - tower cards, the monster player's buffs and abilities, healers and decoys are left out
The one-pass table comes within ~10% of the real game (tests/test_analytics.py plays it), running a little
high; against Warded it runs up to 2x high for slowing towers, as a hit the ward absorbs doesn't slow either.
"""

import argparse
import csv
import math
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from entities import ARMOR_MIN_SHARE
from levels import TILE, generated_hp_mult
from monsters import ENEMY_TYPES
from towers import CROSS, LINES, TOWERS

SPACINGS = {"1 target": math.inf, "wave": 50, "swarm": 15}
CHAIN_HOP = 100  # px a chain can jump (Projectile.impact)
CHAIN_FALLOFF = 0.85  # damage kept per jump
REF_SPEED = 60  # px/s, a Basic's speed, for the exposure columns
REF_ARMOR = 6  # an Armored's armor
DEFAULT_LEVEL, DEFAULT_WAVE = 5, 3  # mid-run: at level 1 one tower kills everything several times over
DEFAULT_MONSTERS = ("basic", "fast", "tank", "champion", "swarmling", "armored", "phantom", "juggernaut", "warded",
                    "berserker", "warden")


def tower_gold():
    """kind -> gold put into it: the tier 1 towers bought from the panel to make it."""
    gold = {}
    for t1, t2, branches in LINES.values():
        gold[t1] = TOWERS[t1]["cost"]
        gold[t2] = 2 * gold[t1]
        for b in branches:
            gold[b] = 2 * gold[t2]
    for parents, final in CROSS.items():
        gold[final] = sum(gold[p] for p in parents)
    return gold


def parents_of():
    """kind -> the two towers fused to make it (two of the same for tiers 2-3)."""
    parents = {}
    for t1, t2, branches in LINES.values():
        parents[t2] = (t1, t1)
        for b in branches:
            parents[b] = (t2, t2)
    for pair, final in CROSS.items():
        parents[final] = tuple(sorted(pair))
    return parents


def path_in_range(spec):
    """Px of a straight path, TILE px from the tower, inside its range."""
    return 2 * math.sqrt(max(0.0, spec["range"] ** 2 - TILE ** 2))


def keeps_slowed(spec):
    """Whether the tower's own hits keep a target slowed (it fires again before its slow wears off)."""
    return "slow" in spec and 1 / spec["rate"] < spec["slow_time"]


def keeps_burning(spec):
    """Whether the tower's own hits keep a target burning (it fires again before its burn wears off)."""
    return "burn" in spec and 1 / spec["rate"] < spec["burn_time"]


def slow_uptime(spec):
    return min(1.0, spec["rate"] * spec["slow_time"]) if "slow" in spec else 0.0


def after_armor(damage, armor):
    return max(damage - armor, damage * ARMOR_MIN_SHARE) if armor else damage


def hit_damage(spec, armor=0, slowed=None):
    """Damage one direct hit does; `slowed` None means as slowed as the tower keeps its targets."""
    damage = spec["damage"]
    if "vs_slowed" in spec and (keeps_slowed(spec) if slowed is None else slowed):
        damage *= spec["vs_slowed"]
    if "vs_burning" in spec and keeps_burning(spec):
        damage *= spec["vs_burning"]
    return after_armor(damage, armor)


def burn_dps(spec):
    """Burn damage per second on one monster, counting how much of the time the tower keeps it burning."""
    return spec.get("burn", 0) * min(1.0, spec["rate"] * spec.get("burn_time", 0))


def victims(spec, spacing):
    """(hit weights per shot, monsters burnt per shot): a weight is the share of the shot's damage a hit does."""
    in_range = math.floor(path_in_range(spec) / spacing) + 1 if spacing != math.inf else 1
    primary = min(spec.get("multishot", 1), in_range)
    per_impact = 1 + 2 * math.floor(spec["splash"] / spacing) if "splash" in spec and spacing != math.inf else 1
    weights = [1.0] * (primary * per_impact)
    if spacing <= CHAIN_HOP:
        weights += [CHAIN_FALLOFF ** k for k in range(1, spec.get("chain", 0) + 1)]
    return weights, len(weights)


def dps(spec, spacing=math.inf, armor=0):
    """Sustained damage per second, all monsters hit added up."""
    weights, burnt = victims(spec, spacing)
    shot = sum(after_armor(hit_damage(spec) * w, armor) for w in weights)
    return spec["rate"] * shot + burn_dps(spec) * burnt


def pass_damage(spec, enemy, hp_mult):
    """Share of a monster's hp one tower takes off it while it walks once through the tower's range."""
    phase_share = 1.0
    if "phase" in enemy:
        every, duration = enemy["phase"]
        phase_share = (every - duration) / every
    speed = enemy["speed"]
    immune = enemy.get("slow_floor", 0) >= 1  # never slowed, so no vs_slowed bonus either
    if "slow" in spec and not immune and keeps_slowed(spec):
        speed *= max(spec["slow"], enemy.get("slow_floor", 0))
    exposure = path_in_range(spec) / speed
    shots = (math.floor(exposure * spec["rate"]) + 1) * phase_share
    if "ward" in enemy:
        # A ward absorbs a hit, then the hits within `ward` seconds land and the next one is absorbed.
        shots *= 1 - 1 / max(1, math.ceil(enemy["ward"] * spec["rate"]))
    armor = enemy.get("armor", 0)
    # The first hit finds the monster unslowed.
    first = hit_damage(spec, armor, slowed=False)
    later = hit_damage(spec, armor, slowed=False if immune else None)
    damage = first + max(0.0, shots - 1) * later if shots else 0.0
    if "burn" in spec and shots:
        damage += burn_dps(spec) * (exposure * phase_share + spec["burn_time"])
    return damage / (enemy["hp"] * hp_mult)


def tower_rows():
    gold = tower_gold()
    rows = []
    for kind, spec in TOWERS.items():
        row = {"kind": kind, "tier": spec["tier"], "gold": gold[kind], "range": spec["range"]}
        for label, spacing in SPACINGS.items():
            row[f"dps {label}"] = dps(spec, spacing)
        row["dps/100g"] = 100 * row["dps 1 target"] / gold[kind]
        row["wave dps/100g"] = 100 * row["dps wave"] / gold[kind]
        row[f"armor {REF_ARMOR} kept"] = dps(spec, armor=REF_ARMOR) / row["dps 1 target"]
        row["slow"] = f"{1 - spec['slow']:.0%}x{slow_uptime(spec):.0%}" if "slow" in spec else ""
        row["flight s"] = 0.0 if spec.get("instant") else spec["range"] / spec["proj_speed"]
        row["exposure s"] = path_in_range(spec) / REF_SPEED
        row["dmg/pass"] = row["dps 1 target"] * row["exposure s"]
        rows.append(row)
    # How each tower's DPS per gold compares with its tier's median: far off either way is worth a look.
    for tier in {r["tier"] for r in rows}:
        same = [r for r in rows if r["tier"] == tier]
        for key in ("dps/100g", "wave dps/100g"):
            median = statistics.median(r[key] for r in same)
            for r in same:
                r[f"{key} vs tier"] = r[key] / median
    return rows


def fusion_rows():
    """Each fused tower against the two it was made from: does fusing add DPS for the same gold?"""
    parents = parents_of()
    rows = []
    for kind, (a, b) in parents.items():
        row = {"kind": kind, "from": f"{a} + {b}"}
        for label, spacing in SPACINGS.items():
            before = dps(TOWERS[a], spacing) + dps(TOWERS[b], spacing)
            row[f"x dps {label}"] = dps(TOWERS[kind], spacing) / before
        row["range"] = TOWERS[kind]["range"] / max(TOWERS[a]["range"], TOWERS[b]["range"])
        rows.append(row)
    return sorted(rows, key=lambda r: (TOWERS[r["kind"]]["tier"], r["kind"]))


def pass_rows(monsters, hp_mult):
    return [{"kind": kind, **{m: pass_damage(spec, ENEMY_TYPES[m], hp_mult) for m in monsters}}
            for kind, spec in TOWERS.items()]


def fmt(value):
    if isinstance(value, float):
        return f"{value:.2f}" if abs(value) < 10 else f"{value:.0f}"
    return str(value)


def print_table(title, rows, columns, formats=None):
    formats = formats or {}
    cells = [[formats.get(c, fmt)(r[c]) for c in columns] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(columns)]
    print(f"\n{title}\n")
    print("  ".join(c.rjust(w) for c, w in zip(columns, widths)))
    print("  ".join("-" * w for w in widths))
    for row in cells:
        print("  ".join(v.rjust(w) for v, w in zip(row, widths)))


def percent(x):
    return f"{x:.0%}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--level", type=int, default=DEFAULT_LEVEL, help="1-based level the monsters' hp comes from")
    parser.add_argument("--wave", type=int, default=DEFAULT_WAVE, help="1-based wave the monsters' hp comes from")
    parser.add_argument("--monsters", default=",".join(DEFAULT_MONSTERS),
                        help="comma-separated monsters for the pass table, or 'all'")
    parser.add_argument("--csv", help="also write the main table to this CSV file")
    args = parser.parse_args(argv)

    rows = tower_rows()
    columns = ["kind", "tier", "gold", "range", *(f"dps {s}" for s in SPACINGS), "dps/100g", "dps/100g vs tier",
               "wave dps/100g", "wave dps/100g vs tier", f"armor {REF_ARMOR} kept", "slow", "flight s",
               "exposure s", "dmg/pass"]
    print_table("Towers (dps: sustained, all monsters hit added up; slow: speed lost x uptime on one target; "
                f"exposure: seconds a monster at {REF_SPEED} px/s spends in range)", rows, columns,
                {"dps/100g vs tier": percent, "wave dps/100g vs tier": percent, f"armor {REF_ARMOR} kept": percent})

    fusion = fusion_rows()
    print_table("Fusion: the fused tower's DPS and range as a multiple of the two towers fused into it "
                "(same gold, one tile freed)", fusion, ["kind", "from", *(f"x dps {s}" for s in SPACINGS), "range"])

    monsters = [m for m in ENEMY_TYPES if ENEMY_TYPES[m]["draft"] != "never"] if args.monsters == "all" \
        else args.monsters.split(",")
    hp_mult = generated_hp_mult(args.level - 1, args.wave - 1)
    print_table(f"One pass: share of a monster's hp one tower takes off it as it walks through its range "
                f"(level {args.level} wave {args.wave}: hp x{hp_mult:.1f}; 100%+ = it dies)",
                pass_rows(monsters, hp_mult), ["kind", *monsters], dict.fromkeys(monsters, percent))

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nWrote {args.csv}")


if __name__ == "__main__":
    main()
