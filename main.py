"""A simple tower defense game built with pygame-ce.

Towers are never upgraded directly: they evolve by fusing.

  Tier 1  Gun, Cannon, Frost (bought from the panel)
  Tier 2  two identical tier 1 towers fuse into Rifle / Mortar / Chiller
  Tier 3  two identical tier 2 towers fuse, and you pick one of two branches
  Tier 4  two tier 3 towers from *different* lines fuse into one of 12 final,
          cross-type towers (press T in game to see the whole tree)

There are 20 levels, each with its own color theme and path. Levels 10 and 20
are boss levels: their last wave ends with a boss that summons minions, resists
slows, and costs the game if it gets through.

Controls
--------
1 / 2 / 3      pick a tower to build (Gun, Cannon, Frost)
Left click     place the picked tower / select an existing tower
Drag a tower   move it to any free tile, at any time; drop it on a tower it can
               fuse with to evolve it (dropping a bought tower works too)
Right click    cancel placement / deselect (Esc also works)
Esc            cancel / close; with nothing to cancel it asks to quit (Esc again quits)
S              sell the selected tower
T              show the evolution tree
Space          start the next wave (or continue to the next level)
F              cycle game speed: 1x, 2x, 4x, 10x (Shift+F goes back)
P              pause
O              settings (display scale); also shown at launch
R              restart after game over or victory

Every level writes a balance log (damage per tower, damage taken per enemy, waves,
economy, fusions...) to logs/<session>/ as JSON; see balance_log.py. Run with
--no-log to turn this off.
"""

import itertools
import json
import os
import random
import sys
from collections import defaultdict
from dataclasses import dataclass

import pygame

from balance_log import LevelLog, LogSession, new_kind_stats

# --------------------------------------------------------------------------
# Layout and rules
# --------------------------------------------------------------------------
TILE = 40
COLS, ROWS = 20, 16
MAP_W, MAP_H = COLS * TILE, ROWS * TILE
PANEL_W = 220
WIDTH, HEIGHT = MAP_W + PANEL_W, MAP_H
FPS = 60
SPEEDS = (1, 2, 4, 10)  # game steps per frame

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
# Display scales on offer. All of them keep TILE * scale a whole number of pixels.
SCALES = (0.75, 1.0, 1.25, 1.5, 1.75, 2.0)

WAVES_PER_LEVEL = 5
START_GOLD = 150
START_LIVES = 20

PANEL_BG = (28, 28, 34)
PANEL_LINE = (60, 60, 72)
TEXT = (235, 235, 240)
TEXT_DIM = (150, 150, 160)
GOOD = (90, 220, 110)
BAD = (235, 80, 80)
GOLD = (255, 210, 70)
TIER_RIM = {1: (15, 15, 20), 2: (176, 116, 64), 3: (205, 205, 220), 4: GOLD}


# --------------------------------------------------------------------------
# Levels: each one has its own color theme and path
# --------------------------------------------------------------------------
def shade(color, k):
    return tuple(min(255, int(c * k)) for c in color)


@dataclass(frozen=True)
class Theme:
    name: str
    ground: tuple
    path: tuple
    accent: tuple

    @property
    def ground_alt(self):
        return shade(self.ground, 0.92)

    @property
    def path_edge(self):
        return shade(self.path, 0.7)


THEMES = [
    Theme("Meadow", (62, 132, 70), (210, 188, 135), (120, 225, 120)),
    Theme("Desert", (214, 180, 110), (150, 105, 62), (255, 170, 60)),
    Theme("Tundra", (208, 226, 240), (120, 145, 170), (120, 200, 255)),
    Theme("Volcano", (62, 30, 28), (205, 85, 35), (255, 100, 50)),
    Theme("Void", (28, 22, 48), (112, 72, 176), (200, 120, 255)),
    Theme("Swamp", (74, 88, 52), (112, 96, 70), (170, 205, 90)),
    Theme("Coral Reef", (40, 140, 150), (240, 205, 170), (255, 130, 150)),
    Theme("Autumn", (160, 95, 40), (95, 65, 45), (255, 150, 50)),
    Theme("Crystal Caves", (70, 60, 110), (170, 150, 220), (190, 160, 255)),
    Theme("Crimson Keep", (48, 14, 18), (110, 100, 105), (230, 40, 50)),  # boss
    Theme("Sakura", (240, 200, 215), (170, 120, 140), (255, 120, 170)),
    Theme("Jungle", (25, 90, 45), (125, 88, 52), (60, 220, 110)),
    Theme("Salt Flats", (235, 232, 225), (170, 165, 160), (80, 200, 200)),
    Theme("Toxic Wastes", (40, 45, 30), (150, 190, 40), (180, 255, 60)),
    Theme("Midnight", (20, 30, 60), (70, 90, 140), (100, 150, 255)),
    Theme("Badlands", (160, 75, 45), (220, 160, 110), (255, 110, 60)),
    Theme("Glacier", (120, 180, 220), (230, 245, 255), (180, 240, 255)),
    Theme("Ashlands", (85, 80, 78), (40, 35, 35), (255, 140, 40)),
    Theme("Neon Grid", (12, 12, 20), (0, 150, 170), (0, 240, 255)),
    Theme("The Abyss", (10, 6, 12), (85, 25, 35), (255, 200, 40)),  # final boss
]

# Waypoints are tile coordinates; the first and last lie just off the map.
LAYOUTS = [
    [(-1, 3), (6, 3), (6, 11), (13, 11), (13, 5), (20, 5)],
    [(-1, 13), (4, 13), (4, 2), (10, 2), (10, 13), (16, 13), (16, 7), (20, 7)],
    [(3, -1), (3, 12), (9, 12), (9, 3), (15, 3), (15, 13), (20, 13)],
    [(-1, 2), (17, 2), (17, 6), (2, 6), (2, 10), (17, 10), (17, 14), (-1, 14)],
    [(10, -1), (10, 4), (2, 4), (2, 13), (8, 13), (8, 8), (14, 8), (14, 13), (18, 13), (18, 1), (20, 1)],
    [(1, -1), (1, 13), (5, 13), (5, 2), (9, 2), (9, 13), (13, 13), (13, 2), (17, 2), (17, 16)],
    [(-1, 1), (4, 1), (4, 4), (8, 4), (8, 7), (12, 7), (12, 10), (16, 10), (16, 13), (20, 13)],
    [(3, -1), (3, 8), (7, 8), (7, 1), (12, 1), (12, 14), (16, 14), (16, 4), (20, 4)],
    [(-1, 7), (3, 7), (3, 1), (9, 1), (9, 14), (15, 14), (15, 1), (18, 1), (18, 9), (20, 9)],
    [(-1, 1), (17, 1), (17, 4), (2, 4), (2, 7), (17, 7), (17, 10), (2, 10), (2, 13), (20, 13)],  # boss
]


def rotate_180(waypoints):
    return [(COLS - 1 - x, ROWS - 1 - y) for x, y in waypoints]


# Levels 11-20 reuse the first ten layouts rotated, so every level has its own path.
LEVELS = list(zip(THEMES, LAYOUTS + [rotate_180(w) for w in LAYOUTS]))
BOSS_LEVELS = {10: "warden", 20: "overlord"}  # 1-based level number -> boss that ends its last wave


# --------------------------------------------------------------------------
# Enemies
# --------------------------------------------------------------------------
ENEMY_TYPES = {
    "basic": dict(hp=30, speed=60, reward=5, size=11, color=(230, 70, 70), sides=0, damage=1, gap=0.8),
    "fast": dict(hp=18, speed=115, reward=6, size=11, color=(250, 215, 60), sides=3, damage=1, gap=0.45),
    "tank": dict(hp=110, speed=38, reward=12, size=13, color=(70, 130, 235), sides=4, damage=2, gap=1.1),
    "elite": dict(hp=400, speed=30, reward=80, size=19, color=(255, 90, 200), sides=6, damage=5, gap=2.0),
    # Bosses: huge, resist slows (slow_floor), summon minions (kind, count, every N seconds),
    # and end the game if they get through.
    "warden": dict(hp=1500, speed=22, reward=400, size=30, color=(200, 40, 50), sides=8, damage=START_LIVES,
                   gap=0, boss="The Warden", inner=("square", 13, (70, 12, 18)), summon=("fast", 3, 6.0),
                   slow_floor=0.6),
    "overlord": dict(hp=1300, speed=20, reward=1000, size=34, color=(255, 200, 40), sides=5, shape="star",
                     damage=START_LIVES, gap=0, boss="The Overlord", inner=("hexagon", 12, (60, 30, 10)),
                     summon=("tank", 2, 10.0), slow_floor=0.7),
}


# --------------------------------------------------------------------------
# Towers and the evolution tree
# --------------------------------------------------------------------------
# Optional mechanics a tower can have:
#   splash      radius damaged around the impact point
#   slow        speed multiplier applied for slow_time seconds
#   burn        damage per second for burn_time seconds
#   chain       lightning jumps to this many extra enemies
#   multishot   number of targets fired at per shot
#   instant     hits immediately with a beam instead of a projectile
#   vs_slowed   damage multiplier against enemies that are already slowed
# `look` describes the geometry: barrels (count, length, width) under layered shapes (shape, radius, color).
def tower(name, tier, line, desc, range, damage, rate, look, proj_speed=400, cost=None, **mechanics):
    return dict(name=name, tier=tier, line=line, desc=desc, range=range, damage=damage, rate=rate,
                proj_speed=proj_speed, cost=cost, look=look, color=look["layers"][0][2], **mechanics)


def look(layers, barrels=(0, 0, 0)):
    return dict(layers=layers, barrels=barrels)


# Line colors, reused so final towers visibly combine their two parents.
C_GUN, C_RIFLE, C_MINI, C_SNIPE = (240, 240, 240), (255, 235, 150), (255, 215, 50), (220, 220, 255)
C_CANNON, C_MORTAR, C_BOMB, C_FIRE = (255, 140, 40), (240, 100, 40), (210, 60, 30), (255, 90, 20)
C_FROST, C_CHILL, C_BLIZ, C_SHAT = (110, 220, 255), (80, 180, 255), (190, 240, 255), (50, 120, 255)
WHITE, DARK = (255, 255, 255), (50, 40, 45)

TOWERS = {
    # Tier 1: bought
    "gun": tower("Gun", 1, "gun", "Rapid fire", 110, 10, 2.5, look([("circle", 9, C_GUN)], (1, 17, 4)),
                 proj_speed=450, cost=50),
    "cannon": tower("Cannon", 1, "cannon", "Splash", 100, 26, 0.8,
                    look([("square", 12, C_CANNON)], (1, 16, 8)), proj_speed=300, cost=90, splash=50),
    "frost": tower("Frost", 1, "frost", "Slows", 85, 4, 1.2,
                   look([("diamond", 13, C_FROST), ("circle", 4, WHITE)]), proj_speed=350, cost=70,
                   slow=0.5, slow_time=1.6),
    # Tier 2
    "rifle": tower("Rifle", 2, "gun", "Long range, hard hits", 130, 18, 3.0,
                   look([("circle", 10, C_RIFLE), ("circle", 4, DARK)], (1, 19, 3)), proj_speed=550),
    "mortar": tower("Mortar", 2, "cannon", "Long-range splash", 130, 50, 0.7,
                    look([("square", 13, C_MORTAR), ("circle", 7, DARK)]), proj_speed=260, splash=60),
    "chiller": tower("Chiller", 2, "frost", "Slows in a small area", 95, 9, 1.4,
                     look([("diamond", 14, C_CHILL), ("diamond", 7, (230, 250, 255))]), proj_speed=350,
                     splash=30, slow=0.4, slow_time=2.0),
    # Tier 3: two branches per line
    "minigun": tower("Minigun", 3, "gun", "Extremely fast fire", 125, 14, 9.0,
                     look([("hexagon", 11, C_MINI)], (3, 17, 3)), proj_speed=600),
    "sniper": tower("Sniper", 3, "gun", "Huge range, instant hits", 240, 160, 0.8,
                    look([("triangle", 13, C_SNIPE)], (1, 22, 3)), instant=True),
    "bombard": tower("Bombard", 3, "cannon", "Massive splash", 150, 110, 0.55,
                     look([("octagon", 14, C_BOMB), ("square", 6, DARK)], (2, 16, 7)), proj_speed=280, splash=95),
    "incinerator": tower("Incinerator", 3, "cannon", "Splash that sets on fire", 120, 32, 1.0,
                         look([("hexagon", 13, C_FIRE), ("circle", 6, (255, 220, 80))], (1, 13, 9)),
                         proj_speed=320, splash=60, burn=25, burn_time=3),
    "blizzard": tower("Blizzard", 3, "frost", "Slows everything nearby", 125, 14, 1.0,
                      look([("star", 15, C_BLIZ), ("circle", 5, WHITE)]), proj_speed=350,
                      splash=75, slow=0.35, slow_time=2.5),
    "shatter": tower("Shatter", 3, "frost", "3x damage to slowed foes", 115, 40, 1.2,
                     look([("triangle", 14, C_SHAT), ("diamond", 6, WHITE)], (1, 15, 4)), proj_speed=450,
                     slow=0.5, slow_time=1.5, vs_slowed=3),
    # Tier 4: cross-type finals (gun x cannon)
    "flak": tower("Flak Battery", 4, None, "3 explosive shots at once", 150, 45, 3.0,
                  look([("hexagon", 13, C_MINI), ("square", 7, C_BOMB)], (3, 15, 4)), proj_speed=500,
                  multishot=3, splash=45),
    "dragon": tower("Dragon", 4, None, "Rapid burning bursts", 135, 16, 9.0,
                    look([("hexagon", 13, C_FIRE), ("circle", 6, C_MINI)], (3, 14, 3)), proj_speed=550,
                    splash=30, burn=30, burn_time=3),
    "railgun": tower("Railgun", 4, None, "Instant, huge, explosive", 260, 600, 0.5,
                     look([("triangle", 14, C_SNIPE), ("square", 7, C_BOMB)], (2, 20, 3)), instant=True,
                     splash=60),
    "solar": tower("Solar Lance", 4, None, "Instant beam, heavy burn", 230, 180, 1.2,
                   look([("triangle", 14, (255, 200, 60)), ("circle", 6, C_FIRE)], (1, 20, 4)), instant=True,
                   burn=60, burn_time=4),
    # gun x frost
    "hailstorm": tower("Hailstorm", 4, None, "4 slowing shots at once", 140, 24, 4.0,
                       look([("star", 14, C_BLIZ), ("hexagon", 7, C_MINI)], (3, 14, 3)), proj_speed=500,
                       multishot=4, slow=0.5, slow_time=1.5),
    "tesla": tower("Tesla Coil", 4, None, "Lightning chains 6 foes", 140, 50, 2.0,
                   look([("hexagon", 14, (130, 130, 255)), ("star", 9, (240, 240, 120))]), instant=True,
                   chain=6, slow=0.7, slow_time=1.0),
    "zero": tower("Absolute Zero", 4, None, "Instant freezing blast", 240, 220, 0.8,
                  look([("triangle", 14, (220, 250, 255)), ("star", 8, C_CHILL)], (1, 20, 3)), instant=True,
                  splash=80, slow=0.3, slow_time=3),
    "lance": tower("Frost Lance", 4, None, "Slows, then 3x damage", 220, 180, 1.0,
                   look([("triangle", 14, C_SHAT), ("diamond", 7, C_SNIPE)], (1, 22, 3)), instant=True,
                   slow=0.5, slow_time=1.5, vs_slowed=3),
    # cannon x frost
    "avalanche": tower("Avalanche", 4, None, "Giant slowing splash", 150, 110, 0.6,
                       look([("square", 14, (170, 230, 255)), ("star", 8, C_BOMB)], (2, 15, 6)), proj_speed=280,
                       splash=110, slow=0.4, slow_time=2),
    "breaker": tower("Glacier Breaker", 4, None, "Splash, 2.5x vs slowed", 140, 100, 0.8,
                     look([("octagon", 14, C_BOMB), ("diamond", 8, C_SHAT)], (1, 16, 8)), proj_speed=300,
                     splash=80, slow=0.5, slow_time=1.5, vs_slowed=2.5),
    "thermal": tower("Thermal Shock", 4, None, "Burns and slows an area", 130, 45, 1.3,
                     look([("star", 14, C_FIRE), ("circle", 6, C_BLIZ)], (1, 12, 8)), proj_speed=320,
                     splash=70, burn=35, burn_time=3, slow=0.5, slow_time=2),
    "obsidian": tower("Obsidian", 4, None, "Burn, slow, 2x vs slowed", 130, 70, 1.0,
                      look([("octagon", 14, (130, 90, 150)), ("triangle", 8, C_FIRE)], (1, 12, 6)),
                      proj_speed=350, splash=60, burn=40, burn_time=3, slow=0.6, slow_time=1.5, vs_slowed=2),
}
TOWER_ORDER = ["gun", "cannon", "frost"]  # buyable, in hotkey order
LINES = {"gun": ("gun", "rifle", ("minigun", "sniper")),
         "cannon": ("cannon", "mortar", ("bombard", "incinerator")),
         "frost": ("frost", "chiller", ("blizzard", "shatter"))}

# Fusing two identical towers evolves them along their line; tier 2 -> 3 branches.
EVOLVE = {"gun": ["rifle"], "rifle": ["minigun", "sniper"],
          "cannon": ["mortar"], "mortar": ["bombard", "incinerator"],
          "frost": ["chiller"], "chiller": ["blizzard", "shatter"]}
# Fusing two tier 3 towers of different lines gives a cross-type final.
CROSS = {frozenset(pair): result for pair, result in [
    (("minigun", "bombard"), "flak"), (("minigun", "incinerator"), "dragon"),
    (("sniper", "bombard"), "railgun"), (("sniper", "incinerator"), "solar"),
    (("minigun", "blizzard"), "hailstorm"), (("minigun", "shatter"), "tesla"),
    (("sniper", "blizzard"), "zero"), (("sniper", "shatter"), "lance"),
    (("bombard", "blizzard"), "avalanche"), (("bombard", "shatter"), "breaker"),
    (("incinerator", "blizzard"), "thermal"), (("incinerator", "shatter"), "obsidian"),
]}


def fusion_options(a, b):
    """Tower kinds that fusing kinds `a` and `b` can produce (empty if they can't fuse)."""
    if a == b:
        return EVOLVE.get(a, [])
    result = CROSS.get(frozenset((a, b)))
    return [result] if result else []


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=1)
    except OSError as err:
        print(f"Could not save settings: {err}")


# The game runs in fixed logical units (the WIDTH x HEIGHT layout above); only drawing
# and mouse input go through SCALE. Everything is drawn natively at the chosen size, so
# there is no per-frame image scaling: changing the scale re-renders the map and fonts once.
SCALE = 1.0


def set_scale(scale):
    global SCALE
    SCALE = scale


def window_size(scale=None):
    k = SCALE if scale is None else scale
    return round(WIDTH * k), round(HEIGHT * k)


def sp(pos):
    """Logical point -> screen point."""
    return pos[0] * SCALE, pos[1] * SCALE


def srect(rect):
    """Logical rect -> screen rect; edges are rounded separately so neighbouring rects never leave gaps."""
    x, y, w, h = rect
    left, top = round(x * SCALE), round(y * SCALE)
    return pygame.Rect(left, top, round((x + w) * SCALE) - left, round((y + h) * SCALE) - top)


def to_logical(pos):
    return int(pos[0] / SCALE), int(pos[1] / SCALE)


def mouse_pos():
    return to_logical(pygame.mouse.get_pos())


class ScaledDraw:
    """pygame.draw (plus fill) taking logical coordinates and drawing at SCALE."""

    @staticmethod
    def width(w):
        return max(1, round(w * SCALE)) if w else 0

    def circle(self, surf, color, center, radius, width=0):
        return pygame.draw.circle(surf, color, sp(center), radius * SCALE, self.width(width))

    def line(self, surf, color, a, b, width=1):
        return pygame.draw.line(surf, color, sp(a), sp(b), self.width(width))

    def rect(self, surf, color, rect, width=0, border_radius=0):
        return pygame.draw.rect(surf, color, srect(rect), self.width(width), round(border_radius * SCALE))

    def polygon(self, surf, color, points, width=0):
        return pygame.draw.polygon(surf, color, [sp(p) for p in points], self.width(width))

    def fill(self, surf, color, rect):
        return surf.fill(color, srect(rect))


sdraw = ScaledDraw()


def tile_center(tx, ty):
    return pygame.Vector2(tx * TILE + TILE / 2, ty * TILE + TILE / 2)


def regular_polygon(center, radius, sides, rotation=0.0):
    return [center + pygame.Vector2(radius, 0).rotate(rotation + 360 * i / sides) for i in range(sides)]


def shape_points(shape, center, r, rot):
    if shape == "square":
        return regular_polygon(center, r, 4, rot + 45)
    if shape == "diamond":
        return regular_polygon(center, r, 4, rot)
    if shape == "triangle":
        return regular_polygon(center, r, 3, rot)
    if shape == "hexagon":
        return regular_polygon(center, r, 6, rot)
    if shape == "octagon":
        return regular_polygon(center, r, 8, rot + 22.5)
    if shape == "star":
        return [center + pygame.Vector2(r if i % 2 == 0 else r * 0.5, 0).rotate(rot + 36 * i) for i in range(10)]
    raise ValueError(shape)


def draw_shape(surf, shape, center, r, color, rot=0.0, outline=2):
    if shape == "circle":
        sdraw.circle(surf, color, center, r)
        sdraw.circle(surf, (20, 20, 20), center, r, outline)
    else:
        pts = shape_points(shape, center, r, rot)
        sdraw.polygon(surf, color, pts)
        sdraw.polygon(surf, (20, 20, 20), pts, outline)


def draw_tower_shape(surf, kind, pos, aim=-90.0):
    spec = TOWERS[kind]
    tier = spec["tier"]
    base = pygame.Rect(0, 0, TILE - 6, TILE - 6)
    base.center = pos
    sdraw.rect(surf, (45, 45, 55), base, border_radius=6)
    sdraw.rect(surf, TIER_RIM[tier], base, 3 if tier == 4 else 2, border_radius=6)
    direction = pygame.Vector2(1, 0).rotate(aim)
    side = direction.rotate(90)
    count, length, width = spec["look"]["barrels"]
    for i in range(count):
        offset = side * (i - (count - 1) / 2) * (width + 2)
        start = pygame.Vector2(pos) + offset
        sdraw.line(surf, (75, 75, 88), start, start + direction * length, width)
    for shape, r, color in spec["look"]["layers"]:
        draw_shape(surf, shape, pos, r, color, aim, outline=1 if r < 8 else 2)
    for i in range(tier):
        sdraw.circle(surf, GOLD, (base.left + 6 + i * 7, base.bottom - 5), 2)


def build_path_cells(waypoints):
    cells = set()
    for (x0, y0), (x1, y1) in zip(waypoints, waypoints[1:]):
        dx = (x1 > x0) - (x1 < x0)
        dy = (y1 > y0) - (y1 < y0)
        x, y = x0, y0
        while True:
            if 0 <= x < COLS and 0 <= y < ROWS:
                cells.add((x, y))
            if (x, y) == (x1, y1):
                break
            x += dx
            y += dy
    return cells


def render_map(theme, waypoints):
    surf = pygame.Surface(sp((MAP_W, MAP_H)))
    for ty in range(ROWS):
        for tx in range(COLS):
            color = theme.ground if (tx + ty) % 2 == 0 else theme.ground_alt
            sdraw.fill(surf, color, (tx * TILE, ty * TILE, TILE, TILE))
    # Path: an edge-colored band with the path color inset, so corners join cleanly.
    for inset, color in ((0, theme.path_edge), (5, theme.path)):
        for (x0, y0), (x1, y1) in zip(waypoints, waypoints[1:]):
            left, right = min(x0, x1), max(x0, x1)
            top, bottom = min(y0, y1), max(y0, y1)
            rect = pygame.Rect(left * TILE + inset, top * TILE + inset,
                               (right - left + 1) * TILE - 2 * inset, (bottom - top + 1) * TILE - 2 * inset)
            sdraw.fill(surf, color, rect)
    return surf


def make_wave(level_idx, wave_idx):
    """Return (enemy kinds, hp multiplier) for a wave. Difficulty grows across all levels."""
    d = level_idx * WAVES_PER_LEVEL + wave_idx
    hp_mult = 1 + 0.5 * d + 0.04 * d * d
    kinds = []
    for _ in range(8 + min(d, 64) // 2):
        r = random.random()
        if d >= 2 and r < 0.25:
            kinds.append("fast")
        elif d >= 4 and r < 0.25 + min(0.3, 0.03 * d):
            kinds.append("tank")
        else:
            kinds.append("basic")
    if wave_idx == WAVES_PER_LEVEL - 1:
        kinds.append(BOSS_LEVELS.get(level_idx + 1, "elite"))
    return kinds, hp_mult


# --------------------------------------------------------------------------
# Game objects
# --------------------------------------------------------------------------
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

    def draw(self, surf):
        size = self.spec["size"]
        color = self.spec["color"]
        sides = self.spec["sides"]
        if "shape" in self.spec:
            draw_shape(surf, self.spec["shape"], self.pos, size, color, self.spin, outline=3)
        elif sides == 0:
            sdraw.circle(surf, color, self.pos, size)
            sdraw.circle(surf, (20, 20, 20), self.pos, size, 2)
        else:
            # Triangles point where they're going; other shapes slowly spin.
            rot = self.heading.as_polar()[1] if sides == 3 else self.spin
            pts = regular_polygon(self.pos, size, sides, rot)
            sdraw.polygon(surf, color, pts)
            sdraw.polygon(surf, (20, 20, 20), pts, 2)
        if "inner" in self.spec:
            shape, r, inner_color = self.spec["inner"]
            draw_shape(surf, shape, self.pos, r, inner_color, -self.spin)
        if self.burn_timer > 0:
            sdraw.circle(surf, (255, 120, 20), self.pos, max(3, size // 3))
        if self.slowed:
            sdraw.circle(surf, (150, 230, 255), self.pos, size + 4, 2)
        if self.hp < self.max_hp:
            w = size * 2 + 4
            bar = pygame.Rect(0, 0, w, 4)
            bar.midbottom = (self.pos.x, self.pos.y - size - 5)
            sdraw.rect(surf, (40, 0, 0), bar)
            bar.width = max(1, int(w * self.hp / self.max_hp))
            sdraw.rect(surf, GOOD, bar)


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

    def draw(self, surf):
        r = 5 if self.spec.get("splash", 0) >= 50 else 3
        sdraw.circle(surf, self.color, self.pos, r)
        sdraw.circle(surf, (20, 20, 20), self.pos, r, 1)


class Tower:
    def __init__(self, kind, tile):
        self.kind = kind
        self.tile = tile
        self.pos = tile_center(*tile)
        self.cooldown = 0.0
        self.aim = -90.0
        self.spent = TOWERS[kind]["cost"]
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

    def draw(self, surf):
        draw_tower_shape(surf, self.kind, self.pos, self.aim)


class Ring:
    """An expanding, fading ring."""

    def __init__(self, pos, radius, color, duration):
        self.pos = pygame.Vector2(pos)
        self.radius = radius
        self.color = color
        self.duration = duration
        self.t = 0.0

    def update(self, dt):
        self.t += dt
        return self.t < self.duration

    def draw(self, surf):
        k = self.t / self.duration
        r = max(2, int(self.radius * (0.3 + 0.7 * k)))
        sdraw.circle(surf, (*self.color, int(220 * (1 - k))), self.pos, r, 3)


class Beam:
    """A fading line, for instant hits and chain lightning."""

    def __init__(self, a, b, color, duration, width):
        self.a = pygame.Vector2(a)
        self.b = pygame.Vector2(b)
        self.color = color
        self.duration = duration
        self.width = width
        self.t = 0.0

    def update(self, dt):
        self.t += dt
        return self.t < self.duration

    def draw(self, surf):
        alpha = int(255 * (1 - self.t / self.duration))
        sdraw.line(surf, (*self.color, alpha), self.a, self.b, self.width)


class Popup:
    """Floating text such as '+5'."""

    def __init__(self, pos, text, color):
        self.pos = pygame.Vector2(pos)
        self.text = text
        self.color = color
        self.t = 0.0

    def update(self, dt):
        self.t += dt
        self.pos.y -= 30 * dt
        return self.t < 0.8


# --------------------------------------------------------------------------
# Game
# --------------------------------------------------------------------------
class Button:
    def __init__(self, rect, label):
        self.rect = pygame.Rect(rect)
        self.label = label


def spec_snapshot():
    """Tower and enemy stats without drawing details, stored in every balance log."""
    return {"towers": {k: {f: v for f, v in s.items() if f not in ("look", "color")} for k, s in TOWERS.items()},
            "enemies": {k: {f: v for f, v in s.items() if f not in ("color", "inner", "shape", "sides", "size")}
                        for k, s in ENEMY_TYPES.items()}}


class Game:
    def __init__(self, screen, log_dir=LOG_DIR):
        self.screen = screen
        self.log_session = LogSession(log_dir) if log_dir else None
        self.log = None
        self.show_settings = False
        self.confirm_quit = False
        self.build_view()

        x = MAP_W + 12
        w = PANEL_W - 24
        third = (w - 8) // 3
        self.tower_buttons = {k: Button((x, 196 + i * 58, w, 52), k) for i, k in enumerate(TOWER_ORDER)}
        self.sell_button = Button((x, 470, w, 36), "Sell")
        self.wave_button = Button((x, HEIGHT - 98, w, 40), "Next wave")
        self.speed_button = Button((x, HEIGHT - 50, third, 38), "Speed")
        self.pause_button = Button((x + third + 4, HEIGHT - 50, third, 38), "Pause")
        self.tree_button = Button((x + 2 * (third + 4), HEIGHT - 50, third, 38), "Tree")
        self.reset()

    def build_view(self):
        """Everything whose size depends on the display scale. Done once per scale change."""
        self.font_s = pygame.font.Font(None, round(20 * SCALE))
        self.font = pygame.font.Font(None, round(26 * SCALE))
        self.font_l = pygame.font.Font(None, round(40 * SCALE))
        self.font_xl = pygame.font.Font(None, round(72 * SCALE))
        self.fx_layer = pygame.Surface(sp((MAP_W, MAP_H)), pygame.SRCALPHA)
        if hasattr(self, "theme"):
            self.map_surface = render_map(self.theme, self.waypoints)

    def apply_scale(self, scale):
        if scale == SCALE:
            return
        set_scale(scale)
        self.screen = pygame.display.set_mode(window_size())
        self.build_view()

    # ---- state ------------------------------------------------------------
    def reset(self):
        self.finish_log("abandoned")
        if self.log_session:
            self.log_session.run += 1
        self.gold = START_GOLD
        self.lives = START_LIVES
        self.speed = 1
        self.paused = False
        self.show_tree = False
        self.load_level(0)

    def load_level(self, idx):
        self.clock = 0.0  # game time in this level; unaffected by pauses, sped up by the speed setting
        self.level_idx = idx
        self.theme, self.waypoints = LEVELS[idx]
        self.path_pts = [tile_center(x, y) for x, y in self.waypoints]
        self.path_cells = build_path_cells(self.waypoints)
        self.map_surface = render_map(self.theme, self.waypoints)
        self.towers = {}
        self.enemies = []
        self.projectiles = []
        self.effects = []
        self.popups = []
        self.wave_idx = 0
        self.spawn_queue = []
        self.spawn_timer = 0.0
        self.hp_mult = 1.0
        self.state = "build"  # build | wave | level_complete | game_over | victory
        self.banner_timer = 3.5 if self.is_boss_level else 3.0
        self.boss_alert = 0.0
        self.build_kind = None
        self.selected = None
        self.dragging = None
        self.choice = None  # (tower, [kind, kind]) while the player picks a branch
        if self.log_session:
            path_length = sum(a.distance_to(b) for a, b in zip(self.path_pts, self.path_pts[1:]))
            self.log = LevelLog(self.log_session, idx + 1, self.theme.name, self.is_boss_level, path_length,
                                self.lives, self.gold, spec_snapshot())

    # ---- balance log ------------------------------------------------------
    def log_event(self, event_type, **data):
        if self.log:
            self.log.event(self.clock, event_type, **data)

    def finish_log(self, outcome):
        """Write the current level's log (once). A level quit before any wave isn't worth a file."""
        if not self.log or self.log.written or (outcome in ("quit", "abandoned") and not self.log.waves):
            return None
        for t in self.towers.values():
            self.log.add_tower(t)
        path = self.log.finish(outcome, self.clock, self.lives, self.gold)
        print(f"Balance log written: {path}")
        return path

    def register_enemy(self, enemy, origin):
        enemy.origin = origin
        enemy.wave = self.wave_idx
        enemy.spawn_t = self.clock
        self.enemies.append(enemy)
        if self.log:
            self.log.enemies.append(enemy)
            if origin != "wave":
                self.log.current_wave()["summoned"] += 1

    @property
    def is_boss_level(self):
        return self.level_idx + 1 in BOSS_LEVELS

    @property
    def frozen(self):
        return self.paused or self.show_tree or self.show_settings or self.confirm_quit or self.choice is not None

    def next_level(self):
        # The map changes, so every tower is refunded at full price.
        self.gold += sum(t.spent for t in self.towers.values())
        self.load_level(self.level_idx + 1)

    def start_wave(self):
        if self.state != "build" or self.wave_idx >= WAVES_PER_LEVEL:
            return
        self.spawn_queue, self.hp_mult = make_wave(self.level_idx, self.wave_idx)
        self.wave_idx += 1
        self.spawn_timer = 0.0
        self.state = "wave"
        if self.log:
            self.log.start_wave(self.clock, self.wave_idx, self.hp_mult, self.spawn_queue, self.lives, self.gold)

    def is_free(self, tile):
        tx, ty = tile
        return 0 <= tx < COLS and 0 <= ty < ROWS and tile not in self.path_cells and tile not in self.towers

    def can_place(self, tile):
        """A new tower can go on a free tile, or straight onto a tower it can fuse with."""
        if self.gold < TOWERS[self.build_kind]["cost"]:
            return False
        other = self.towers.get(tile)
        if other:
            return bool(fusion_options(self.build_kind, other.kind))
        return self.is_free(tile)

    def place_tower(self, tile):
        tower = Tower(self.build_kind, tile)
        self.gold -= tower.spent
        other = self.towers.get(tile)
        tower.history.append({"t": round(self.clock, 2), "event": "bought", "kind": tower.kind})
        if self.log:
            self.log.add_tower(tower)
            self.log.spent["towers"] += tower.spent
        self.log_event("buy", tower=tower.uid, kind=tower.kind, tile=list(tile), cost=tower.spent,
                       onto=other.uid if other else None)
        if other:
            self.fuse(tower, other)
        else:
            self.towers[tile] = tower
        if self.gold < TOWERS[self.build_kind]["cost"]:
            self.build_kind = None

    def fuse(self, tower, target):
        """Merge `tower` into `target`, which keeps its spot. Branching fusions ask the player to choose."""
        options = tower.fusion_options(target)
        if self.towers.get(tower.tile) is tower:
            del self.towers[tower.tile]
        target.spent += tower.spent
        self.selected = target
        tower.status = f"fused_into:{target.uid}"
        tower.history.append({"t": round(self.clock, 2), "event": "fused_into", "tower": target.uid})
        if self.log:
            self.log.add_tower(target)
        self.log_event("fuse", consumed=tower.uid, consumed_kind=tower.kind, target=target.uid,
                       target_kind=target.kind, options=options)
        if len(options) == 1:
            self.evolve(target, options[0])
        else:
            self.choice = (target, options)
            self.build_kind = None

    def evolve(self, tower, kind):
        tower.history.append({"t": round(self.clock, 2), "event": "evolved", "from": tower.kind, "to": kind})
        self.log_event("evolve", tower=tower.uid, frm=tower.kind, to=kind, tier=TOWERS[kind]["tier"])
        tower.kind = kind
        tower.cooldown = 0.0
        self.effects.append(Ring(tower.pos, 36, GOLD, 0.45))
        self.popups.append(Popup(tower.pos, tower.spec["name"] + "!", GOLD))

    def choose(self, index):
        tower, options = self.choice
        self.choice = None
        self.log_event("branch_choice", tower=tower.uid, options=options, chosen=options[index])
        self.evolve(tower, options[index])

    def drop_dragged(self, pos):
        """Finish a drag: move the tower to a free tile or fuse it with a matching tower."""
        t, self.dragging = self.dragging, None
        if t is None or self.towers.get(t.tile) is not t or pos[0] >= MAP_W:
            return
        tile = (pos[0] // TILE, pos[1] // TILE)
        other = self.towers.get(tile)
        if other is t:
            return
        if other:
            if t.fusion_options(other):
                self.fuse(t, other)
        elif self.is_free(tile):
            self.log_event("move", tower=t.uid, kind=t.kind, frm=list(t.tile), to=list(tile),
                           during_wave=self.state == "wave")
            del self.towers[t.tile]
            t.move_to(tile)
            self.towers[tile] = t

    def sell_selected(self):
        t = self.selected
        if t:
            t.status = "sold"
            t.history.append({"t": round(self.clock, 2), "event": "sold", "value": t.sell_value})
            self.log_event("sell", tower=t.uid, kind=t.kind, value=t.sell_value)
            if self.log:
                self.log.add_tower(t)
                self.log.earned["sells"] += t.sell_value
            self.gold += t.sell_value
            self.popups.append(Popup(t.pos, f"+{t.sell_value}", GOLD))
            del self.towers[t.tile]
            self.selected = None
            self.dragging = None

    # ---- update -----------------------------------------------------------
    def update(self, dt):
        # banners are read in real time, so they don't flash past at high speed
        self.banner_timer -= dt / self.speed
        self.boss_alert -= dt / self.speed
        self.effects = [e for e in self.effects if e.update(dt)]
        self.popups = [p for p in self.popups if p.update(dt)]
        if self.state not in ("build", "wave"):
            return
        self.clock += dt
        if self.state == "wave":
            for t in self.towers.values():
                t.stats[t.kind]["wave_seconds"] += dt

        if self.state == "wave" and self.spawn_queue:
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                kind = self.spawn_queue.pop(0)
                self.register_enemy(Enemy(kind, self.path_pts, self.hp_mult), "wave")
                self.spawn_timer = ENEMY_TYPES[kind]["gap"]
                if "boss" in ENEMY_TYPES[kind]:
                    self.boss_alert = 3.0
                elif self.spawn_queue and "boss" in ENEMY_TYPES[self.spawn_queue[0]]:
                    self.spawn_timer = 4.0  # a breather before the boss walks in

        for e in self.enemies:
            e.update(dt)
        self.summon_minions(dt)
        for t in self.towers.values():
            t.update(dt, self.enemies, self.projectiles, self.effects)
        for p in self.projectiles:
            p.update(dt, self.enemies, self.effects)
        self.projectiles = [p for p in self.projectiles if not p.done]

        wave_log = self.log.current_wave() if self.log else None
        for e in self.enemies:
            if e.alive:
                continue
            e.end_t = self.clock
            if e.escaped:
                self.lives -= e.spec["damage"]
                self.effects.append(Ring(e.pos, 30, BAD, 0.4))
                if wave_log:
                    wave_log["leaks"] += 1
                    wave_log["lives_lost"] += e.spec["damage"]
            else:
                self.gold += e.spec["reward"]
                self.popups.append(Popup(e.pos, f"+{e.spec['reward']}", GOLD))
                self.effects.append(Ring(e.pos, e.spec["size"] + 8, e.spec["color"], 0.3))
                if wave_log:
                    wave_log["kills"] += 1
                    wave_log["kill_gold"] += e.spec["reward"]
                    self.log.earned["kills"] += e.spec["reward"]
        self.enemies = [e for e in self.enemies if e.alive]

        if self.lives <= 0:
            self.lives = 0
            self.state = "game_over"
            self.finish_log("lost")
        elif self.state == "wave" and not self.spawn_queue and not self.enemies:
            bonus = 20 + 5 * self.wave_idx
            self.gold += bonus
            if self.log:
                self.log.earned["wave_bonus"] += bonus
                self.log.end_wave(self.clock, self.lives, self.gold, bonus)
            self.popups.append(Popup((MAP_W / 2, MAP_H / 2), f"Wave cleared! +{bonus}", GOLD))
            self.projectiles.clear()
            if self.wave_idx < WAVES_PER_LEVEL:
                self.state = "build"
            else:
                self.state = "level_complete" if self.level_idx + 1 < len(LEVELS) else "victory"
                self.finish_log("cleared")

    def summon_minions(self, dt):
        for boss in [e for e in self.enemies if e.alive and "summon" in e.spec]:
            boss.summon_timer -= dt
            if boss.summon_timer > 0:
                continue
            kind, count, interval = boss.spec["summon"]
            boss.summon_timer = interval
            for _ in range(count):
                minion = Enemy(kind, self.path_pts, self.hp_mult)
                minion.follow(boss)
                self.register_enemy(minion, f"summon:{boss.kind}")
            self.effects.append(Ring(boss.pos, boss.spec["size"] + 30, boss.spec["color"], 0.5))

    # ---- input ------------------------------------------------------------
    def handle_event(self, event):
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            event = pygame.event.Event(event.type, {**event.dict, "pos": to_logical(event.pos)})
        if self.confirm_quit:
            self.handle_quit_event(event)
        elif self.show_settings:
            self.handle_settings_event(event)
        elif self.choice:
            self.handle_choice_event(event)
        elif event.type == pygame.KEYDOWN:
            self.handle_key(event.key)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if self.show_tree:
                self.show_tree = False
            elif event.button == 3:
                self.build_kind = None
                self.selected = None
                self.dragging = None
            elif event.button == 1:
                self.handle_click(event.pos)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.drop_dragged(event.pos)

    def handle_choice_event(self, event):
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_1, pygame.K_2):
            self.choose(event.key - pygame.K_1)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, rect in enumerate(self.choice_cards()):
                if rect.collidepoint(event.pos):
                    self.choose(i)

    def handle_quit_event(self, event):
        """Esc / Enter / Y confirms; any other key or a click keeps playing."""
        if event.type == pygame.KEYDOWN:
            self.confirm_quit = False
            if event.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_y):
                pygame.event.post(pygame.event.Event(pygame.QUIT))  # main() writes the log and exits
        elif event.type == pygame.MOUSEBUTTONDOWN:
            self.confirm_quit = False

    def handle_settings_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_MINUS, pygame.K_EQUALS, pygame.K_PLUS):
                step = -1 if event.key in (pygame.K_LEFT, pygame.K_MINUS) else 1
                fitting = [k for k in SCALES if self.scale_fits(k)]
                i = fitting.index(SCALE) if SCALE in fitting else 0
                self.apply_scale(fitting[max(0, min(len(fitting) - 1, i + step))])
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_ESCAPE, pygame.K_o):
                self.close_settings()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for scale, rect in self.scale_buttons():
                if rect.collidepoint(event.pos) and self.scale_fits(scale):
                    self.apply_scale(scale)
            if self.settings_close_button().collidepoint(event.pos):
                self.close_settings()

    def close_settings(self):
        self.show_settings = False
        settings = load_settings()
        if settings.get("scale") != SCALE:
            save_settings({**settings, "scale": SCALE})

    @staticmethod
    def scale_fits(scale):
        """Whether a window at this scale fits on the desktop (leaving room for title bar and taskbar)."""
        if scale <= 1.0:
            return True
        try:
            desk_w, desk_h = pygame.display.get_desktop_sizes()[0]
        except (pygame.error, IndexError):
            return True
        w, h = window_size(scale)
        return w <= desk_w and h <= desk_h - 80

    def handle_key(self, key):
        if key == pygame.K_o:
            self.show_settings = True
        elif key == pygame.K_t:
            self.show_tree = not self.show_tree
        elif self.show_tree:
            if key == pygame.K_ESCAPE:
                self.show_tree = False
        elif key == pygame.K_r and self.state in ("game_over", "victory"):
            self.reset()
        elif key == pygame.K_SPACE:
            self.advance()
        elif key == pygame.K_p:
            self.paused = not self.paused
        elif key == pygame.K_f:
            self.cycle_speed(-1 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 1)
        elif key == pygame.K_ESCAPE:
            if not (self.build_kind or self.selected or self.dragging):
                self.confirm_quit = True
            self.build_kind = None
            self.selected = None
            self.dragging = None
        elif key == pygame.K_s:
            self.sell_selected()
        elif pygame.K_1 <= key <= pygame.K_3:
            self.pick_tower(TOWER_ORDER[key - pygame.K_1])

    def cycle_speed(self, step):
        self.speed = SPEEDS[(SPEEDS.index(self.speed) + step) % len(SPEEDS)]

    def advance(self):
        if self.state == "build":
            self.start_wave()
        elif self.state == "level_complete":
            self.next_level()
        elif self.state in ("game_over", "victory"):
            self.reset()

    def pick_tower(self, kind):
        if self.build_kind == kind:
            self.build_kind = None
        elif self.gold >= TOWERS[kind]["cost"]:
            self.build_kind = kind
            self.selected = None

    def handle_click(self, pos):
        if pos[0] < MAP_W:
            if self.state in ("level_complete", "game_over", "victory"):
                self.advance()
                return
            tile = (pos[0] // TILE, pos[1] // TILE)
            if self.build_kind:
                if self.can_place(tile):
                    self.place_tower(tile)
            else:
                self.selected = self.dragging = self.towers.get(tile)
            return
        for kind, b in self.tower_buttons.items():
            if b.rect.collidepoint(pos):
                self.pick_tower(kind)
        if self.sell_button.rect.collidepoint(pos):
            self.sell_selected()
        elif self.wave_button.rect.collidepoint(pos):
            self.advance()
        elif self.speed_button.rect.collidepoint(pos):
            self.cycle_speed(1)
        elif self.pause_button.rect.collidepoint(pos):
            self.paused = not self.paused
        elif self.tree_button.rect.collidepoint(pos):
            self.show_tree = True

    # ---- drawing ----------------------------------------------------------
    def text(self, font, s, color, pos, anchor="topleft"):
        img = font.render(s, True, color)
        rect = img.get_rect(**{anchor: sp(pos)})
        self.screen.blit(img, rect)
        return rect  # in screen pixels

    def draw(self):
        screen = self.screen
        screen.blit(self.map_surface, (0, 0))
        screen.set_clip(srect((0, 0, MAP_W, MAP_H)))

        fx = self.fx_layer
        fx.fill((0, 0, 0, 0))
        if self.selected and not self.dragging:
            self.draw_range(fx, self.selected.pos, self.selected.range, (255, 255, 255))
        self.draw_ghost(fx)
        self.draw_drag_preview(fx)

        for t in self.towers.values():
            if t is not self.dragging:
                t.draw(screen)
        for e in self.enemies:
            e.draw(screen)
        for p in self.projectiles:
            p.draw(screen)
        for ef in self.effects:
            ef.draw(fx)
        screen.blit(fx, (0, 0))
        mx, my = mouse_pos()
        hover = tile_center(mx // TILE, my // TILE)
        if self.build_kind and mx < MAP_W:
            draw_tower_shape(screen, self.build_kind, hover)
        if self.dragging:
            t = self.dragging
            draw_tower_shape(screen, t.kind, hover if mx < MAP_W else t.pos, t.aim)
        self.draw_fusion_label()
        for p in self.popups:
            img = self.font.render(p.text, True, p.color)
            img.set_alpha(int(255 * (1 - p.t / 0.8)))
            screen.blit(img, img.get_rect(center=sp(p.pos)))

        self.draw_boss_bar()
        if not (self.show_settings or self.confirm_quit or self.show_tree or self.choice):
            self.draw_banner()
        if not self.confirm_quit:
            self.draw_overlay()
        if self.show_settings:
            self.draw_settings()
        elif self.confirm_quit:
            self.draw_quit_prompt()
        elif self.choice:
            self.draw_choice()
        elif self.show_tree:
            self.draw_tree()
        screen.set_clip(None)
        self.draw_panel()

    def draw_range(self, surf, pos, radius, color):
        sdraw.circle(surf, (*color, 40), pos, radius)
        sdraw.circle(surf, (*color, 140), pos, radius, 2)

    def hovered_fusion(self):
        """(kind being fused, kind under the cursor, options) for the current drag or build, if any."""
        mx, my = mouse_pos()
        if mx >= MAP_W:
            return None
        other = self.towers.get((mx // TILE, my // TILE))
        if not other:
            return None
        if self.dragging and other is not self.dragging:
            return self.dragging.kind, other.kind, fusion_options(self.dragging.kind, other.kind)
        if self.build_kind:
            return self.build_kind, other.kind, fusion_options(self.build_kind, other.kind)
        return None

    def draw_ghost(self, fx):
        if not self.build_kind:
            return
        mx, my = mouse_pos()
        if mx >= MAP_W:
            return
        tile = (mx // TILE, my // TILE)
        if not self.can_place(tile):
            color = BAD
        else:
            color = GOLD if tile in self.towers else GOOD
        sdraw.fill(fx, (*color, 90), (tile[0] * TILE, tile[1] * TILE, TILE, TILE))
        self.draw_range(fx, tile_center(*tile), TOWERS[self.build_kind]["range"], color)

    def draw_drag_preview(self, fx):
        """While dragging: outline fusion partners in gold and color the tile under the cursor."""
        t = self.dragging
        if not t:
            return
        for other in self.towers.values():
            if t.fusion_options(other):
                sdraw.rect(fx, (*GOLD, 220), (other.tile[0] * TILE, other.tile[1] * TILE, TILE, TILE),
                                 3, border_radius=6)
        sdraw.rect(fx, (255, 255, 255, 90), (t.tile[0] * TILE, t.tile[1] * TILE, TILE, TILE),
                         2, border_radius=6)
        mx, my = mouse_pos()
        if mx >= MAP_W:
            return
        tile = (mx // TILE, my // TILE)
        other = self.towers.get(tile)
        radius = t.range
        if other is t:
            color = (255, 255, 255)
        elif other and t.fusion_options(other):
            color = GOLD
            radius = max(TOWERS[k]["range"] for k in t.fusion_options(other))
        elif not other and self.is_free(tile):
            color = GOOD
        else:
            color = BAD
        sdraw.fill(fx, (*color, 90), (tile[0] * TILE, tile[1] * TILE, TILE, TILE))
        self.draw_range(fx, tile_center(*tile), radius, color)

    def draw_fusion_label(self):
        """A tag next to the cursor naming what a fusion would produce."""
        fusion = self.hovered_fusion()
        if not fusion:
            return
        _, _, options = fusion
        if options:
            label, color = "-> " + " / ".join(TOWERS[k]["name"] for k in options), GOLD
        else:
            label, color = "Can't fuse", BAD
        img = self.font_s.render(label, True, color)
        mx, my = mouse_pos()
        rect = img.get_rect(bottomleft=sp((mx + 14, my - 10))).inflate(10 * SCALE, 6 * SCALE)
        rect.clamp_ip(srect((0, 0, MAP_W, MAP_H)))
        pygame.draw.rect(self.screen, (20, 20, 26), rect, border_radius=round(4 * SCALE))
        self.screen.blit(img, img.get_rect(center=rect.center))

    def draw_boss_bar(self):
        """Health bar across the top of the map while a boss is on the field."""
        boss = next((e for e in self.enemies if "boss" in e.spec), None)
        if not boss:
            return
        spec = boss.spec
        bar = pygame.Rect(MAP_W / 2 - 220, 26, 440, 14)
        sdraw.rect(self.screen, (20, 20, 26), bar.inflate(6, 6), border_radius=5)
        sdraw.rect(self.screen, (60, 10, 14), bar)
        sdraw.rect(self.screen, spec["color"], (*bar.topleft, bar.width * boss.hp / boss.max_hp, bar.height))
        self.text(self.font, spec["boss"].upper(), spec["color"], (bar.centerx, bar.top - 5), "midbottom")
        if self.boss_alert > 0:
            band = pygame.Surface(sp((MAP_W, 90)), pygame.SRCALPHA)
            band.fill((0, 0, 0, 150))
            img = self.font_xl.render(f"{spec['boss'].upper()} APPROACHES", True, spec["color"])
            band.blit(img, img.get_rect(center=sp((MAP_W / 2, 45))))
            band.set_alpha(int(255 * min(1.0, self.boss_alert)))
            self.screen.blit(band, sp((0, MAP_H / 2 - 45)))

    def draw_banner(self):
        """Big level title shown when a level starts, in the level's accent color."""
        if self.banner_timer <= 0:
            return
        alpha = int(255 * min(1.0, self.banner_timer / 0.8))
        band = pygame.Surface(sp((MAP_W, 110)), pygame.SRCALPHA)
        band.fill((0, 0, 0, int(alpha * 0.55)))
        title = self.font_xl.render(f"LEVEL {self.level_idx + 1}: {self.theme.name.upper()}", True, self.theme.accent)
        if self.is_boss_level:
            boss = ENEMY_TYPES[BOSS_LEVELS[self.level_idx + 1]]["boss"]
            sub = self.font.render(f"BOSS LEVEL - {boss} waits at the end of wave {WAVES_PER_LEVEL}",
                                   True, self.theme.accent)
        else:
            sub = self.font.render("Build towers, then press Space to send the first wave", True, TEXT)
        band.blit(title, title.get_rect(center=sp((MAP_W / 2, 42))))
        band.blit(sub, sub.get_rect(center=sp((MAP_W / 2, 88))))
        band.set_alpha(alpha)
        self.screen.blit(band, sp((0, MAP_H / 2 - 55)))

    def shade_map(self, alpha=160):
        shade = pygame.Surface(sp((MAP_W, MAP_H)), pygame.SRCALPHA)
        shade.fill((0, 0, 0, alpha))
        self.screen.blit(shade, (0, 0))

    def draw_overlay(self):
        if self.state == "level_complete":
            nxt = LEVELS[self.level_idx + 1][0]
            lines = [(f"{self.theme.name} cleared!", self.theme.accent, self.font_xl),
                     (f"Next up: {nxt.name}", nxt.accent, self.font_l),
                     ("Towers are refunded in full. Press Space or click to continue.", TEXT, self.font)]
        elif self.state == "game_over":
            lines = [("GAME OVER", BAD, self.font_xl),
                     (f"You reached level {self.level_idx + 1}, wave {self.wave_idx}", TEXT, self.font_l),
                     ("Press R or click to try again", TEXT, self.font)]
        elif self.state == "victory":
            lines = [("VICTORY!", GOLD, self.font_xl),
                     (f"All {len(LEVELS)} levels defended with {self.lives} lives left", TEXT, self.font_l),
                     ("Press R or click to play again", TEXT, self.font)]
        elif self.paused:
            lines = [("PAUSED", TEXT, self.font_xl), ("Press P to resume", TEXT_DIM, self.font)]
        else:
            return
        self.shade_map()
        y = MAP_H / 2 - 60
        for s, color, font in lines:
            r = self.text(font, s, color, (MAP_W / 2, y), "midtop")
            y = r.bottom / SCALE + 14

    def draw_quit_prompt(self):
        self.shade_map(190)
        self.text(self.font_xl, "QUIT?", BAD, (MAP_W / 2, MAP_H / 2 - 70), "midtop")
        self.text(self.font, "Esc or Enter to quit, any other key to keep playing", TEXT,
                  (MAP_W / 2, MAP_H / 2 + 10), "midtop")

    def choice_cards(self):
        return [pygame.Rect(MAP_W / 2 - 280 + i * 290, MAP_H / 2 - 90, 270, 190) for i in range(2)]

    def draw_choice(self):
        tower, options = self.choice
        self.shade_map(190)
        self.text(self.font_l, f"{tower.spec['name']} evolves - choose a branch", GOLD,
                  (MAP_W / 2, MAP_H / 2 - 140), "midtop")
        mouse = mouse_pos()
        for i, (rect, kind) in enumerate(zip(self.choice_cards(), options)):
            spec = TOWERS[kind]
            hover = rect.collidepoint(mouse)
            sdraw.rect(self.screen, (55, 55, 68) if hover else (38, 38, 48), rect, border_radius=10)
            sdraw.rect(self.screen, spec["color"], rect, 3, border_radius=10)
            draw_tower_shape(self.screen, kind, pygame.Vector2(rect.centerx, rect.top + 38))
            self.text(self.font_l, spec["name"], spec["color"], (rect.centerx, rect.top + 66), "midtop")
            self.text(self.font_s, spec["desc"], TEXT, (rect.centerx, rect.top + 100), "midtop")
            self.text(self.font_s, self.stat_line(spec), TEXT_DIM, (rect.centerx, rect.top + 122), "midtop")
            self.text(self.font, f"[{i + 1}]", GOLD, (rect.centerx, rect.bottom - 12), "midbottom")

    @staticmethod
    def stat_line(spec):
        return f"Dmg {spec['damage']:.0f}  Rng {spec['range']:.0f}  Rate {spec['rate']:.1f}/s"

    def draw_tree(self):
        """Full-screen evolution chart over the map."""
        self.shade_map(225)
        self.text(self.font_l, "EVOLUTION TREE", GOLD, (MAP_W / 2, 14), "midtop")
        self.text(self.font_s, "Fuse two identical towers to evolve them. Tier 2 -> 3 lets you pick a branch.",
                  TEXT_DIM, (MAP_W / 2, 46), "midtop")
        cols = (40, 230, 440)
        for row, (t1, t2, branches) in enumerate(LINES.values()):
            y = 100 + row * 92
            self.tree_node(t1, cols[0], y)
            self.text(self.font_s, "x2 ->", TEXT_DIM, (cols[1] - 66, y), "midleft")
            self.tree_node(t2, cols[1], y)
            self.text(self.font_s, "x2 ->", TEXT_DIM, (cols[2] - 66, y), "midleft")
            self.tree_node(branches[0], cols[2], y - 22)
            self.tree_node(branches[1], cols[2], y + 22)
        top = 368
        self.text(self.font, "FINAL FORMS: fuse two tier 3 towers from different lines", GOLD, (MAP_W / 2, top),
                  "midtop")
        for i, (pair, kind) in enumerate(CROSS.items()):
            x = 30 + (i // 6) * 390
            y = top + 44 + (i % 6) * 38
            a, b = sorted(pair, key=list(TOWERS).index)
            draw_tower_shape(self.screen, kind, pygame.Vector2(x + 16, y))
            spec = TOWERS[kind]
            self.text(self.font, spec["name"], spec["color"], (x + 42, y - 16))
            self.text(self.font_s, f"{TOWERS[a]['name']} + {TOWERS[b]['name']}: {spec['desc']}", TEXT_DIM,
                      (x + 42, y + 3))
        self.text(self.font_s, "Press T or click to close", TEXT_DIM, (MAP_W - 10, MAP_H - 8), "bottomright")

    def tree_node(self, kind, x, y):
        spec = TOWERS[kind]
        draw_tower_shape(self.screen, kind, pygame.Vector2(x + 16, y))
        self.text(self.font, spec["name"], spec["color"], (x + 42, y), "midleft")

    def scale_buttons(self):
        w = 90
        x0 = MAP_W / 2 - (len(SCALES) * (w + 10) - 10) / 2
        return [(k, pygame.Rect(x0 + i * (w + 10), 250, w, 50)) for i, k in enumerate(SCALES)]

    @staticmethod
    def settings_close_button():
        return pygame.Rect(MAP_W / 2 - 110, 420, 220, 50)

    def draw_settings(self):
        self.shade_map(225)
        self.text(self.font_xl, "SETTINGS", GOLD, (MAP_W / 2, 90), "midtop")
        self.text(self.font_l, "Display scale", TEXT, (MAP_W / 2, 200), "midtop")
        mouse = mouse_pos()
        for scale, rect in self.scale_buttons():
            fits = self.scale_fits(scale)
            current = scale == SCALE
            bg = (90, 90, 108) if fits and rect.collidepoint(mouse) else (55, 55, 68) if fits else (32, 32, 40)
            sdraw.rect(self.screen, bg, rect, border_radius=8)
            sdraw.rect(self.screen, GOLD if current else PANEL_LINE, rect, 3 if current else 1, border_radius=8)
            self.text(self.font, f"{scale * 100:.0f}%", (TEXT if fits else TEXT_DIM) if not current else GOLD,
                      rect.center, "center")
        w, h = window_size()
        self.text(self.font, f"Window {w} x {h}", TEXT, (MAP_W / 2, 320), "midtop")
        self.text(self.font_s, "Left / Right or click to change. Greyed-out sizes don't fit your screen.",
                  TEXT_DIM, (MAP_W / 2, 350), "midtop")
        self.text(self.font_s, "The game is drawn natively at the chosen size; changing it costs one re-render.",
                  TEXT_DIM, (MAP_W / 2, 370), "midtop")
        b = self.settings_close_button()
        sdraw.rect(self.screen, (90, 90, 108) if b.collidepoint(mouse) else (70, 70, 85), b, border_radius=8)
        sdraw.rect(self.screen, self.theme.accent, b, 3, border_radius=8)
        label = "Play  [Enter]" if self.state == "build" and self.wave_idx == 0 and not self.towers else \
            "Resume  [Enter]"
        self.text(self.font, label, TEXT, b.center, "center")
        self.text(self.font_s, "Press O in game to come back here. The choice is saved for next time.",
                  TEXT_DIM, (MAP_W / 2, 500), "midtop")

    def draw_button(self, b, label, enabled=True, active=False, font=None):
        hover = b.rect.collidepoint(mouse_pos())
        bg = (70, 70, 85) if enabled else (40, 40, 48)
        if enabled and hover:
            bg = (90, 90, 108)
        sdraw.rect(self.screen, bg, b.rect, border_radius=6)
        border = self.theme.accent if active else PANEL_LINE
        sdraw.rect(self.screen, border, b.rect, 3 if active else 1, border_radius=6)
        self.text(font or self.font, label, TEXT if enabled else TEXT_DIM, b.rect.center, "center")

    def evolve_hint(self, t):
        if t.tier == 4:
            return "Final form"
        if t.tier == 3:
            return "+ Tier 3 of another line"
        options = EVOLVE[t.kind]
        return f"+ {t.spec['name']} -> " + " / ".join(TOWERS[k]["name"] for k in options)

    def draw_panel(self):
        screen = self.screen
        x0 = MAP_W
        sdraw.fill(screen, PANEL_BG, (x0, 0, PANEL_W, HEIGHT))
        sdraw.line(screen, self.theme.accent, (x0, 0), (x0, HEIGHT), 4)
        x = x0 + 12

        # Level header in the level's accent color.
        header = pygame.Rect(x, 12, PANEL_W - 24, 56)
        sdraw.rect(screen, self.theme.accent, header, border_radius=8)
        name_font = self.font_l if self.font_l.size(self.theme.name)[0] <= (header.width - 12) * SCALE else self.font
        self.text(name_font, self.theme.name, (20, 20, 25), (header.centerx, header.top + 20), "center")
        level_label = f"Level {self.level_idx + 1} of {len(LEVELS)}" + ("  -  BOSS" if self.is_boss_level else "")
        self.text(self.font_s, level_label, (20, 20, 25), (header.centerx, header.bottom - 6), "midbottom")

        self.text(self.font, f"Wave  {self.wave_idx} / {WAVES_PER_LEVEL}", TEXT, (x, 84))
        self.text(self.font, f"Lives  {self.lives}", BAD if self.lives <= 5 else TEXT, (x, 110))
        self.text(self.font, f"Gold  {self.gold}", GOLD, (x, 136))
        self.text(self.font_s, "TOWERS", TEXT_DIM, (x, 176))

        for i, (kind, b) in enumerate(self.tower_buttons.items()):
            spec = TOWERS[kind]
            affordable = self.gold >= spec["cost"]
            active = self.build_kind == kind
            bg = (70, 70, 85) if b.rect.collidepoint(mouse_pos()) else (48, 48, 58)
            sdraw.rect(screen, bg, b.rect, border_radius=6)
            sdraw.rect(screen, self.theme.accent if active else PANEL_LINE, b.rect,
                             3 if active else 1, border_radius=6)
            draw_tower_shape(screen, kind, pygame.Vector2(b.rect.left + 28, b.rect.centery))
            self.text(self.font, f"{spec['name']}  [{i + 1}]", TEXT if affordable else TEXT_DIM,
                      (b.rect.left + 56, b.rect.top + 7))
            self.text(self.font_s, f"{spec['cost']}g - {spec['desc']}", GOLD if affordable else TEXT_DIM,
                      (b.rect.left + 56, b.rect.top + 30))

        if self.selected:
            t = self.selected
            spec = t.spec
            self.text(self.font, spec["name"], spec["color"], (x, 378))
            self.text(self.font_s, f"Tier {t.tier}", TIER_RIM[t.tier] if t.tier > 1 else TEXT_DIM,
                      (x + PANEL_W - 24, 382), "topright")
            self.text(self.font_s, spec["desc"], TEXT, (x, 402))
            self.text(self.font_s, f"Dmg {spec['damage']:.0f}  Rng {spec['range']:.0f}  Rate {spec['rate']:.1f}",
                      TEXT_DIM, (x, 422))
            self.text(self.font_s, self.evolve_hint(t), GOLD, (x, 444))
            self.draw_button(self.sell_button, f"Sell {t.sell_value}g  [S]", True)
        else:
            self.text(self.font_s, "Drag towers to move them", TEXT_DIM, (x, 380))
            self.text(self.font_s, "Drop two matching towers", TEXT_DIM, (x, 400))
            self.text(self.font_s, "together to evolve them", TEXT_DIM, (x, 418))
            self.text(self.font_s, "T: see the evolution tree", GOLD, (x, 444))

        self.text(self.font_s, "Enemies", TEXT_DIM, (x, 520))
        for i, spec in enumerate(s for s in ENEMY_TYPES.values() if "boss" not in s):
            c = pygame.Vector2(x + 74 + i * 30, 526)
            if spec["sides"] == 0:
                sdraw.circle(screen, spec["color"], c, 8)
            else:
                sdraw.polygon(screen, spec["color"], regular_polygon(c, 9, spec["sides"], -90))

        if self.state == "build":
            label, enabled = f"Send wave {self.wave_idx + 1}  [Space]", True
        elif self.state == "level_complete":
            label, enabled = "Next level  [Space]", True
        elif self.state in ("game_over", "victory"):
            label, enabled = "Restart  [R]", True
        else:
            left = len(self.enemies) + len(self.spawn_queue)
            label, enabled = f"{left} {'enemy' if left == 1 else 'enemies'} left", False
        self.draw_button(self.wave_button, label, enabled, active=enabled)
        self.draw_button(self.speed_button, f"{self.speed}x [F]", True, active=self.speed > 1, font=self.font_s)
        self.draw_button(self.pause_button, "Pause [P]", True, active=self.paused, font=self.font_s)
        self.draw_button(self.tree_button, "Tree [T]", True, active=self.show_tree, font=self.font_s)


def main():
    pygame.init()
    # The saved scale, or the largest one below it that fits this screen.
    saved = load_settings().get("scale", 1.0)
    saved = saved if isinstance(saved, (int, float)) else 1.0
    set_scale(max([k for k in SCALES if k <= saved and Game.scale_fits(k)] or [1.0]))
    screen = pygame.display.set_mode(window_size())
    pygame.display.set_caption("Tower Defense")
    clock = pygame.time.Clock()
    game = Game(screen, log_dir=None if "--no-log" in sys.argv else LOG_DIR)
    game.show_settings = True  # start on the settings screen; Enter to play
    while True:
        dt = min(clock.tick(FPS) / 1000, 0.05)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                game.finish_log("quit")
                pygame.quit()
                sys.exit()
            game.handle_event(event)
        if not game.frozen:
            for _ in range(game.speed):
                game.update(dt)
        game.draw()
        pygame.display.flip()


if __name__ == "__main__":
    main()
