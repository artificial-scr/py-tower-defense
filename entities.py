"""The things on the map: enemies, the projectiles towers fire, and towers.

They hold the combat rules (movement, damage, slow, burn, splash, chain, targeting) and the
per-tower / per-enemy numbers the balance log reports. Drawing is in graphics.py.
"""

import itertools
import random
from collections import defaultdict

import pygame

from balance_log import new_kind_stats
from graphics import Beam, Ring, tile_center
from levels import ENEMY_TYPES
from towers import TOWERS, fusion_options

ENEMY_IDS = itertools.count(1)
TOWER_IDS = itertools.count(1)


class Enemy:
    def __init__(self, kind, path_pts, hp_mult):
        self.uid = next(ENEMY_IDS)
        self.kind = kind
        self.spec = ENEMY_TYPES[kind]
        self.max_hp = self.spec["hp"] * hp_mult
        self.hp = self.max_hp
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
        step = self.spec["speed"] * self.slow_factor * dt
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
        self.spin += dt * 120

    def hit(self, damage, source=None, how="direct", bonus_frac=0.0):
        """Take damage. `bonus_frac` is the part of it that came from a vs_slowed multiplier."""
        if not self.alive:
            return
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
        factor = max(factor, self.spec.get("slow_floor", 0))
        self.slow_factor = min(self.slow_factor, factor)
        self.slow_timer = max(self.slow_timer, duration)

    def apply_burn(self, dps, duration, source=None):
        current = self.burn_dps if self.burn_timer > 0 else 0
        if dps >= current:
            self.burn_dps = dps
            self.burn_source = source
        self.burn_timer = max(self.burn_timer, duration)


class Projectile:
    def __init__(self, tower, target):
        self.spec = tower.spec
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
            self.strike(e, spec["damage"], "splash" if splash else "direct")
        # Chain lightning jumps from the impact point to the nearest enemies not yet hit.
        hit = set(map(id, victims))
        last = self.pos
        damage = spec["damage"]
        for _ in range(spec.get("chain", 0)):
            candidates = [e for e in enemies if e.alive and id(e) not in hit and e.pos.distance_to(last) <= 100]
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
        return self.spec["range"]

    @property
    def sell_value(self):
        return int(self.spent * 0.7)

    def fusion_options(self, other):
        return [] if other is self else fusion_options(self.kind, other.kind)

    def move_to(self, tile):
        self.tile = tile
        self.pos = tile_center(*tile)

    def update(self, dt, enemies, projectiles, effects):
        self.cooldown -= dt
        in_range = [e for e in enemies if e.alive and e.pos.distance_to(self.pos) <= self.range]
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
