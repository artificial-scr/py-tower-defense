"""Levels, enemies and waves: the map grid, each level's color theme and path, enemy
types (bosses included), and how waves are built.
"""

import random
from dataclasses import dataclass

COLS, ROWS = 20, 16  # map size in tiles
WAVES_PER_LEVEL = 5
START_GOLD = 150
START_LIVES = 20


# --------------------------------------------------------------------------
# Levels: each one has its own color theme and path
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Theme:
    name: str
    ground: tuple
    path: tuple
    accent: tuple


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
# Paths and waves
# --------------------------------------------------------------------------
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
