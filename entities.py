"""The things on the map: enemies, the projectiles towers fire, and towers.

They hold the combat rules (movement, damage, slow, burn, splash, chain, targeting), the
monster mechanics (armor, healing, splitting, phasing, buffs) and monster abilities, and the
per-tower / per-enemy numbers the balance log reports. Drawing is in graphics.py.
"""

import itertools
import random
from collections import defaultdict

import pygame

from balance_log import new_kind_stats
from graphics import Beam, Ring, tile_center
from monsters import ENEMY_TYPES
from towers import NO_TOWER_MODS, TOWER_LINES, TOWERS, fusion_options

ENEMY_IDS = itertools.count(1)
TOWER_IDS = itertools.count(1)
ARMOR_MIN_SHARE = 0.2  # armor never blocks more than 80% of a hit
SPLIT_SPREAD = 10  # pixels between the monsters a Splitter breaks into


NO_MODS = {"hp": 1.0, "speed": 1.0, "burn": 1.0, "thaw": 0.0, "armor": 1.0}


class Enemy:
    def __init__(self, kind, path_pts, hp_mult, mods=None):
        """`mods` are the monster player's buffs (and the tower player's counters to them):
        hp, speed and burn (damage taken from burns) multipliers, thaw (share of every slow
        ignored) and armor (multiplier on the type's armor). Missing keys mean no change."""
        self.uid = next(ENEMY_IDS)
        self.kind = kind
        self.spec = ENEMY_TYPES[kind]
        self.hp_mult = hp_mult
        self.mods = {**NO_MODS, **(mods or {})}
        self.max_hp = self.spec["hp"] * hp_mult * self.mods["hp"]
        self.hp = self.max_hp
        self.armor = self.spec.get("armor", 0) * self.mods["armor"]
        self.path = path_pts
        self.pos = path_pts[0].copy()
        self.idx = 1
        self.heading = pygame.Vector2(1, 0)
        self.travelled = 0.0
        self.spin = random.uniform(0, 360)
        self.slow_factor = 1.0
        self.slow_timer = 0.0
        self.burn_dps = 0.0
        self.burn_timer = 0.0
        self.haste = 0.0  # extra speed share while haste_timer runs
        self.haste_timer = 0.0
        self.shield = 0.0  # share of damage blocked while shield_timer runs
        self.shield_timer = 0.0
        self.phase_t = 0.0
        self.summon_timer = self.spec["summon"][2] if "summon" in self.spec else 0.0
        self.alive = True
        self.escaped = False
        # Balance-log bookkeeping. A damage source is a (tower, tower kind when it fired) pair.
        self.origin = "wave"
        self.wave = 0
        self.spawn_t = 0.0
        self.end_t = None
        self.burn_source = None
        self.slowed_seconds = 0.0
        self.burning_seconds = 0.0
        self.overkill = 0.0
        self.damage_from = defaultdict(float)
        self.killed_by = None

    def follow(self, leader):
        """Start at another enemy's spot on the path (used for summoned minions)."""
        self.pos = leader.pos.copy()
        self.idx = leader.idx
        self.travelled = leader.travelled
        self.heading = leader.heading.copy()

    @property
    def slowed(self):
        return self.slow_timer > 0

    @property
    def phased(self):
        """Phantoms spend the last `for` seconds of every `every` seconds out of reach of targeting."""
        if "phase" not in self.spec:
            return False
        every, duration = self.spec["phase"]
        return self.phase_t % every >= every - duration

    @property
    def speed(self):
        haste = 1 + self.haste if self.haste_timer > 0 else 1
        return self.spec["speed"] * self.mods["speed"] * self.slow_factor * haste

    def update(self, dt):
        if self.burn_timer > 0:
            self.burn_timer -= dt
            self.burning_seconds += dt
            self.hit(self.burn_dps * dt, self.burn_source, "burn")
            if not self.alive:
                return
        if self.slow_timer > 0:
            self.slow_timer -= dt
            self.slowed_seconds += dt
            if self.slow_timer <= 0:
                self.slow_factor = 1.0
        self.haste_timer -= dt
        self.shield_timer -= dt
        self.phase_t += dt
        self.advance(self.speed * dt)
        self.spin += dt * 120

    def advance(self, step):
        """Move `step` pixels along the path; escaping at its end."""
        while step > 0 and self.idx < len(self.path):
            to = self.path[self.idx] - self.pos
            dist = to.length()
            if dist <= step:
                self.pos = self.path[self.idx].copy()
                self.idx += 1
                step -= dist
                self.travelled += dist
            else:
                self.heading = to / dist
                self.pos += self.heading * step
                self.travelled += step
                step = 0
        if self.idx >= len(self.path):
            self.alive = False
            self.escaped = True

    def hit(self, damage, source=None, how="direct", bonus_frac=0.0):
        """Take damage. `bonus_frac` is the part of it that came from a vs_slowed multiplier.

        Armor blocks a flat amount of every hit except burns, but at least ARMOR_MIN_SHARE of a
        hit always gets through; a shield then blocks its share of what's left."""
        if not self.alive:
            return
        if self.armor and how != "burn":
            damage = max(damage - self.armor, damage * ARMOR_MIN_SHARE)
        if self.shield_timer > 0:
            damage *= 1 - self.shield
        effective = min(damage, self.hp)
        self.hp -= damage
        self.overkill += damage - effective
        if source:
            tower, kind = source
            self.damage_from[kind] += effective
            tower.record_hit(kind, self, damage, effective, how, bonus_frac)
        if self.hp <= 0:
            self.alive = False
            if source:
                self.killed_by = {"tower": tower.uid, "kind": kind, "how": how}
                tower.stats[kind]["kills"] += 1

    def apply_slow(self, factor, duration):
        factor = 1 - (1 - factor) * (1 - self.mods["thaw"])
        factor = max(factor, self.spec.get("slow_floor", 0))
        self.slow_factor = min(self.slow_factor, factor)
        self.slow_timer = max(self.slow_timer, duration)

    def apply_burn(self, dps, duration, source=None):
        dps *= self.mods["burn"]
        current = self.burn_dps if self.burn_timer > 0 else 0
        if dps >= current:
            self.burn_dps = dps
            self.burn_source = source
        self.burn_timer = max(self.burn_timer, duration)

    def heal(self, amount):
        if self.alive:
            self.hp = min(self.max_hp, self.hp + amount)

    def split(self):
        """The monsters a Splitter breaks into when it's killed, spread a little along the path."""
        if "split" not in self.spec or self.escaped:
            return []
        kind, count = self.spec["split"]
        children = []
        for i in range(count):
            child = Enemy(kind, self.path, self.hp_mult, self.mods)
            child.follow(self)
            child.advance(SPLIT_SPREAD * i)
            children.append(child)
        return children


def heal_auras(enemies, dt):
    """Healers mend the monsters around them (not themselves) every frame."""
    for healer in enemies:
        if not healer.alive or "heal_aura" not in healer.spec:
            continue
        radius, share = healer.spec["heal_aura"]
        for e in enemies:
            if e is not healer and e.alive and e.pos.distance_to(healer.pos) <= radius:
                e.heal(e.max_hp * share * dt)


def cast_ability(spec, pos, towers, enemies, effects, area_duration=1.0):
    """Apply a monster ability (monsters.ABILITIES) at `pos`. `area_duration` scales how long area
    effects on towers last (the Grounding tower card halves it)."""
    if spec["target"] == "area":
        effects.append(Ring(pygame.Vector2(pos), spec["radius"], spec["color"], 0.6))
        duration = spec["duration"] * area_duration
        for t in towers:
            if t.pos.distance_to(pos) > spec["radius"]:
                continue
            if spec["effect"] == "disable":
                t.disabled_timer = max(t.disabled_timer, duration)
            elif spec["effect"] == "range":
                t.smoke_timer = max(t.smoke_timer, duration)
                t.smoke = spec["amount"]
        return
    for e in enemies:
        if not e.alive:
            continue
        effects.append(Ring(e.pos, e.spec["size"] + 10, spec["color"], 0.4))
        if spec["effect"] == "haste":
            e.haste, e.haste_timer = spec["amount"], max(e.haste_timer, spec["duration"])
        elif spec["effect"] == "shield":
            e.shield, e.shield_timer = spec["amount"], max(e.shield_timer, spec["duration"])
        elif spec["effect"] == "heal":
            e.heal(e.max_hp * spec["amount"])


class Projectile:
    def __init__(self, tower, target):
        self.spec = tower.spec
        self.damage = tower.damage  # card bonuses included
        self.source = (tower, tower.kind)  # credited even if the tower evolves mid-flight
        self.pos = tower.pos.copy()
        self.target = target
        self.dest = target.pos.copy()
        self.color = self.spec["color"]
        self.done = False

    def update(self, dt, enemies, effects):
        if self.target.alive:
            self.dest = self.target.pos.copy()
        to = self.dest - self.pos
        dist = to.length()
        step = self.spec["proj_speed"] * dt
        if dist > step:
            self.pos += to / dist * step
            return
        self.pos = self.dest
        self.done = True
        self.impact(enemies, effects)

    def strike(self, enemy, damage, how):
        spec = self.spec
        bonus_frac = 0.0
        if enemy.slowed and "vs_slowed" in spec:
            damage *= spec["vs_slowed"]
            bonus_frac = 1 - 1 / spec["vs_slowed"]
        enemy.hit(damage, self.source, how, bonus_frac)
        if "slow" in spec:
            enemy.apply_slow(spec["slow"], spec["slow_time"])
        if "burn" in spec:
            enemy.apply_burn(spec["burn"], spec["burn_time"], self.source)

    def impact(self, enemies, effects):
        spec = self.spec
        splash = spec.get("splash")
        if splash:
            victims = [e for e in enemies if e.alive and e.pos.distance_to(self.pos) <= splash]
            effects.append(Ring(self.pos, splash, self.color, 0.3))
        elif self.target.alive:
            victims = [self.target]
            if "slow" in spec:
                effects.append(Ring(self.pos, 16, (160, 230, 255), 0.25))
        else:
            return
        for e in victims:
            self.strike(e, self.damage, "splash" if splash else "direct")
        # Chain lightning jumps from the impact point to the nearest enemies not yet hit.
        hit = set(map(id, victims))
        last = self.pos
        damage = self.damage
        for _ in range(spec.get("chain", 0)):
            candidates = [e for e in enemies if e.alive and id(e) not in hit and e.pos.distance_to(last) <= 100
                          and self.source[0].can_target(e)]
            if not candidates:
                break
            nxt = min(candidates, key=lambda e: e.pos.distance_to(last))
            damage *= 0.85
            effects.append(Beam(last, nxt.pos, (240, 240, 120), 0.2, 2))
            self.strike(nxt, damage, "chain")
            hit.add(id(nxt))
            last = nxt.pos.copy()


class Tower:
    def __init__(self, kind, tile, spent=None):
        """`spent` is the gold put into the tower; only towers bought from the panel have a cost of their own."""
        self.kind = kind
        self.tile = tile
        self.pos = tile_center(*tile)
        self.cooldown = 0.0
        self.aim = -90.0
        self.spent = TOWERS[kind]["cost"] if spent is None else spent
        self.uid = next(TOWER_IDS)
        self.stats = defaultdict(new_kind_stats)  # tower kind -> stats while it was that kind
        self.status = "active"
        self.history = []
        self.disabled_timer = 0.0  # EMP: no firing while it runs
        self.smoke = 0.0  # Smokescreen: share of range lost while smoke_timer runs
        self.smoke_timer = 0.0
        self.mods = NO_TOWER_MODS  # tower card bonuses (towers.NO_TOWER_MODS)

    def record_hit(self, kind, enemy, raw, effective, how, bonus_frac):
        s = self.stats[kind]
        s["damage"] += effective
        s["overkill"] += raw - effective
        s["vs_slowed_bonus"] += effective * bonus_frac
        s["by_source"][how] += effective
        s["vs_enemy"][enemy.kind] += effective
        if how != "burn":
            s["hits"] += 1

    @property
    def spec(self):
        return TOWERS[self.kind]

    @property
    def tier(self):
        return self.spec["tier"]

    @property
    def range(self):
        return self.spec["range"] * self.mods["range"] * (1 - self.smoke if self.smoke_timer > 0 else 1)

    @property
    def damage(self):
        """Damage per hit with the damage cards of the tower's line(s): a final gets both lines' bonuses."""
        bonus = sum(self.mods["damage"].get(line, 1.0) - 1 for line in TOWER_LINES[self.kind])
        return self.spec["damage"] * (1 + bonus)

    @property
    def disabled(self):
        return self.disabled_timer > 0

    def can_target(self, enemy):
        return not enemy.phased or self.mods["detector"]

    @property
    def sell_value(self):
        return int(self.spent * self.mods["refund"])

    def fusion_options(self, other):
        return [] if other is self else fusion_options(self.kind, other.kind)

    def move_to(self, tile):
        self.tile = tile
        self.pos = tile_center(*tile)

    def update(self, dt, enemies, projectiles, effects):
        self.cooldown -= dt
        self.smoke_timer -= dt
        if self.disabled_timer > 0:
            self.disabled_timer -= dt
            return
        in_range = [e for e in enemies
                    if e.alive and e.pos.distance_to(self.pos) <= self.range and self.can_target(e)]
        if not in_range:
            return
        in_range.sort(key=lambda e: e.travelled, reverse=True)  # closest to escaping first
        self.aim = (in_range[0].pos - self.pos).as_polar()[1]
        if self.cooldown > 0:
            return
        self.cooldown = 1 / self.spec["rate"]
        for target in in_range[: self.spec.get("multishot", 1)]:
            self.stats[self.kind]["shots"] += 1
            p = Projectile(self, target)
            if self.spec.get("instant"):
                effects.append(Beam(self.pos, target.pos, self.spec["color"], 0.15, 3))
                p.pos = target.pos.copy()
                p.update(0, enemies, effects)
            else:
                projectiles.append(p)
