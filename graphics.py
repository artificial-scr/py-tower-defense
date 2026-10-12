"""Everything the tower defense draws: layout, colors, display scaling, shapes, visual
effects, and GameView, the drawing half of main.Game.

The game runs in fixed logical units (the WIDTH x HEIGHT layout below); only drawing and
mouse input go through SCALE. Everything is drawn natively at the chosen size, so there is
no per-frame image scaling: changing the scale re-renders the map and fonts once.

This module doesn't import main (that would load the game twice when it's run as a
script); GameView reads the game state through `self`.
"""

import math
import os
import random

import pygame

from levels import COLS, ENEMY_TYPES, LEVELS, ROWS, WAVES_PER_LEVEL
from monsters import ABILITIES, REWARDS
from progress import UNLOCKS
from towers import CROSS, EVOLVE, LINES, TOWERS

# --------------------------------------------------------------------------
# Layout and colors
# --------------------------------------------------------------------------
TILE = 40
MAP_W, MAP_H = COLS * TILE, ROWS * TILE
PANEL_W = 220
WIDTH, HEIGHT = MAP_W + PANEL_W, MAP_H

# Display scales on offer. All of them keep TILE * scale a whole number of pixels.
SCALES = (0.75, 1.0, 1.25, 1.5, 1.75, 2.0)

# Orbitron (SIL Open Font License, see assets/fonts/OFL.txt): the Medium and Bold files from
# github.com/theleagueof/orbitron (pygame can't pick a weight from the variable font).
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
FONT_FILES = {"medium": os.path.join(FONT_DIR, "Orbitron-Medium.ttf"), "bold": os.path.join(FONT_DIR, "Orbitron-Bold.ttf")}

PANEL_BG = (28, 28, 34)
PANEL_LINE = (60, 60, 72)
TEXT = (235, 235, 240)
TEXT_DIM = (150, 150, 160)
GOOD = (90, 220, 110)
BAD = (235, 80, 80)
GOLD = (255, 210, 70)
TIER_RIM = {1: (15, 15, 20), 2: (176, 116, 64), 3: (205, 205, 220), 4: GOLD}
TIER_COLORS = {"weak": TEXT_DIM, "normal": TEXT, "strong": GOLD}  # record tiers on the reward screen


def wrap(text, width):
    """Split text into lines of at most `width` characters, at spaces."""
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + [line] if line else lines


_caps = {}  # font -> (top, bottom) of its capital letters within a rendered line, in pixels


def load_font(size, weight="medium"):
    """The game font at a logical size."""
    font = pygame.font.Font(FONT_FILES[weight], round(size * SCALE))
    ink = font.render("H", True, (255, 255, 255)).get_bounding_rect()
    _caps[font] = ink.top, ink.bottom
    return font


def cap_height(font):
    top, bottom = _caps[font]
    return bottom - top


def blit_text(surf, font, s, color, pos, anchor="topleft", alpha=None):
    """Draw `s` with its anchor point at `pos` (logical). Vertically, text is placed by its capital
    letters, not the font's line box: "top" is the top of the capitals, "bottom" the baseline,
    and centered text has its capitals centered, so labels sit in the middle of their buttons.
    Returns the capitals' box, in screen pixels."""
    img = font.render(s, True, color)
    if alpha is not None:
        img.set_alpha(alpha)
    top, bottom = _caps[font]
    box = pygame.Rect(0, 0, img.get_width(), bottom - top)
    setattr(box, anchor, (round(pos[0] * SCALE), round(pos[1] * SCALE)))
    surf.blit(img, (box.x, box.y - top))
    return box


def shade(color, k):
    return tuple(min(255, int(c * k)) for c in color)


def mix(a, b, k):
    """Color `a` moved a share `k` of the way to color `b`."""
    return tuple(round(x + (y - x) * k) for x, y in zip(a, b))


# --------------------------------------------------------------------------
# Display scale
# --------------------------------------------------------------------------
SCALE = 1.0  # read it as graphics.SCALE from other modules: set_scale rebinds it


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


# --------------------------------------------------------------------------
# Shapes, towers, enemies, the map
# --------------------------------------------------------------------------
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


SHADOW_OFFSET = pygame.Vector2(3, 4)  # the light comes from the top left
_shadows = {}


def draw_shadow(surf, pos, w, h, lift=1.0):
    """A soft dark blob under something w x h at `pos` (logical); `lift` pushes it further away, for
    things off the ground. The blurred sprites are made once per size and display scale."""
    key = (w, h, SCALE)
    img = _shadows.get(key)
    if img is None:
        pad = round(4 * SCALE)
        size = srect((0, 0, w, h)).size
        img = pygame.Surface((size[0] + 2 * pad, size[1] + 2 * pad), pygame.SRCALPHA)
        pygame.draw.rect(img, (0, 0, 0, 80), (pad, pad, *size), border_radius=min(size) // 2 if w == h else
                         round(6 * SCALE))
        img = _shadows[key] = pygame.transform.gaussian_blur(img, max(1, round(2 * SCALE)))
    surf.blit(img, img.get_rect(center=sp(pygame.Vector2(pos) + SHADOW_OFFSET * lift)))


def draw_tower_shadow(surf, pos, lift=1.0):
    draw_shadow(surf, pos, TILE - 6, TILE - 7, lift)


def draw_tower_shape(surf, spec, pos, aim=-90.0):
    """Draw a tower from its spec (an entry of towers.TOWERS)."""
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


def draw_enemy_icon(surf, spec, pos, size):
    """A small still picture of an enemy type, for lists and the draft queue."""
    if "shape" in spec:
        draw_shape(surf, spec["shape"], pos, size, spec["color"], -90, outline=1)
    elif spec["sides"] == 0:
        sdraw.circle(surf, spec["color"], pos, size)
    else:
        sdraw.polygon(surf, spec["color"], regular_polygon(pos, size + 1, spec["sides"], -90))
    if "inner" in spec:
        shape, r, color = spec["inner"]
        draw_shape(surf, shape, pos, max(2, r * size / spec["size"]), color, outline=1)


def draw_tower_status(surf, fx, tower):
    """EMP: a dark tile crossed out. Smokescreen: a grey haze on the effects layer."""
    if tower.disabled:
        r = TILE // 2 - 3
        sdraw.fill(fx, (10, 10, 30, 150), (tower.pos.x - r, tower.pos.y - r, 2 * r, 2 * r))
        for a, b in (((-1, -1), (1, 1)), ((-1, 1), (1, -1))):
            sdraw.line(surf, (120, 200, 255), tower.pos + pygame.Vector2(a) * (r - 4),
                       tower.pos + pygame.Vector2(b) * (r - 4), 3)
    if tower.smoke_timer > 0:
        sdraw.circle(fx, (150, 150, 150, 90), tower.pos, TILE * 0.7)


def draw_enemy_shadow(surf, enemy):
    if not enemy.phased:
        d = enemy.spec["size"] * 2
        draw_shadow(surf, enemy.pos, d, d, 1.3)


def draw_enemy(surf, enemy):
    spec = enemy.spec
    size = spec["size"]
    color = mix(spec["color"], (255, 255, 255), 0.65) if enemy.flash > 0 else spec["color"]
    sides = spec["sides"]
    if enemy.phased:  # out of reach: just a faint outline
        if sides == 0:
            sdraw.circle(surf, color, enemy.pos, size, 2)
        else:
            sdraw.polygon(surf, color, regular_polygon(enemy.pos, size, sides, enemy.heading.as_polar()[1]), 2)
        return
    if "shape" in spec:
        draw_shape(surf, spec["shape"], enemy.pos, size, color, enemy.spin, outline=3)
    elif sides == 0:
        sdraw.circle(surf, color, enemy.pos, size)
        sdraw.circle(surf, (20, 20, 20), enemy.pos, size, 2)
    else:
        # Triangles point where they're going; other shapes slowly spin.
        rot = enemy.heading.as_polar()[1] if sides == 3 else enemy.spin
        pts = regular_polygon(enemy.pos, size, sides, rot)
        sdraw.polygon(surf, color, pts)
        sdraw.polygon(surf, (20, 20, 20), pts, 2)
    if "inner" in spec:
        shape, r, inner_color = spec["inner"]
        draw_shape(surf, shape, enemy.pos, r, inner_color, -enemy.spin)
    if enemy.burn_timer > 0:
        sdraw.circle(surf, (255, 120, 20), enemy.pos, max(3, size // 3))
    if enemy.slowed:
        sdraw.circle(surf, (150, 230, 255), enemy.pos, size + 4, 2)
    if enemy.shield_timer > 0:
        sdraw.circle(surf, (240, 220, 120), enemy.pos, size + 7, 2)
    if enemy.haste_timer > 0:
        tail = enemy.pos - enemy.heading * (size + 8)
        sdraw.line(surf, (255, 120, 60), enemy.pos - enemy.heading * size, tail, 3)
    if enemy.hp < enemy.max_hp:
        w = size * 2 + 4
        bar = pygame.Rect(0, 0, w, 4)
        bar.midbottom = (enemy.pos.x, enemy.pos.y - size - 5)
        sdraw.rect(surf, (40, 0, 0), bar)
        bar.width = max(1, int(w * enemy.hp / enemy.max_hp))
        sdraw.rect(surf, GOOD, bar)


def draw_projectile(surf, projectile):
    r = 5 if projectile.spec.get("splash", 0) >= 50 else 3
    sdraw.circle(surf, projectile.color, projectile.pos, r)
    sdraw.circle(surf, (20, 20, 20), projectile.pos, r, 1)


def path_tiles(waypoints):
    tiles = set()
    for (x0, y0), (x1, y1) in zip(waypoints, waypoints[1:]):
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                tiles.add((x, y))
    return tiles


# Ground decoration. A prop is drawn around (x, y), the logical center of a spot on a free tile.
def _tuft(surf, rng, x, y, color):
    for base, lean, height in ((-4, -2, 5), (0, 1, 8), (4, 2, 6)):
        sdraw.line(surf, color, (x + base, y), (x + base + lean, y - height), 2)


def _flower(surf, rng, x, y, color):
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
        sdraw.circle(surf, color, (x + dx, y + dy), 1.6)
    sdraw.circle(surf, (250, 220, 90), (x, y), 1.2)


def _pebble(surf, rng, x, y, color):
    r = rng.uniform(2, 4)
    sdraw.circle(surf, color, (x, y), r)
    sdraw.circle(surf, shade(color, 1.3), (x - r / 3, y - r / 3), r / 3)


def _crack(surf, rng, x, y, color):
    pts = [(x - 7, y + rng.uniform(-3, 3))]
    for i in range(1, 4):
        pts.append((x - 7 + i * 5, y + rng.uniform(-4, 4)))
    for a, b in zip(pts, pts[1:]):
        sdraw.line(surf, color, a, b, 2)


def _star(surf, rng, x, y, color):
    if rng.random() < 0.5:
        sdraw.fill(surf, color, (x - 1, y - 1, 2, 2))
        return
    sdraw.line(surf, color, (x - 3, y), (x + 3, y), 1)
    sdraw.line(surf, color, (x, y - 3), (x, y + 3), 1)


def _crystal(surf, rng, x, y, color):
    r = rng.uniform(3, 5)
    pts = [(x, y - r * 1.6), (x + r * 0.7, y), (x, y + r * 0.6), (x - r * 0.7, y)]
    sdraw.polygon(surf, color, pts)
    sdraw.line(surf, shade(color, 1.4), pts[0], pts[2], 1)


def _drift(surf, rng, x, y, color):
    sdraw.circle(surf, color, (x - 3, y), 3)
    sdraw.circle(surf, color, (x + 2, y - 1), 4)
    sdraw.fill(surf, color, (x - 3, y, 9, 3))


def _leaf(surf, rng, x, y, color):
    sdraw.polygon(surf, color, regular_polygon(pygame.Vector2(x, y), 3, 4, rng.uniform(0, 90)))


def _bubble(surf, rng, x, y, color):
    sdraw.circle(surf, color, (x, y), rng.uniform(2, 4), 1)


def _cactus(surf, rng, x, y, color):
    sdraw.rect(surf, color, (x - 1.5, y - 8, 3, 11), border_radius=1)
    sdraw.rect(surf, color, (x - 5, y - 5, 2, 4))
    sdraw.rect(surf, color, (x + 3, y - 6, 2, 3))
    sdraw.line(surf, color, (x - 5, y - 2), (x, y - 2), 2)
    sdraw.line(surf, color, (x, y - 4), (x + 5, y - 4), 2)


def _stone(surf, rng, x, y, color):
    sdraw.rect(surf, color, (x - 5, y - 3, 10, 6), border_radius=1)
    sdraw.rect(surf, shade(color, 0.7), (x - 5, y - 3, 10, 6), 1, border_radius=1)


PROPS = {"tuft": _tuft, "flower": _flower, "pebble": _pebble, "crack": _crack, "star": _star, "crystal": _crystal,
         "drift": _drift, "leaf": _leaf, "bubble": _bubble, "cactus": _cactus, "stone": _stone}
# theme name -> the props scattered on it, with their colors: "dark" / "light" are the ground shaded,
# "accent" the theme's accent; or an RGB color
DECOR = {
    "Meadow": [("tuft", "dark"), ("tuft", "light"), ("flower", (245, 240, 225)), ("flower", (230, 120, 170)),
               ("pebble", "dark")],
    "Desert": [("cactus", (95, 140, 70)), ("pebble", "dark"), ("crack", "dark")],
    "Tundra": [("drift", (250, 252, 255)), ("pebble", "dark"), ("crack", "dark")],
    "Volcano": [("crack", "accent"), ("crack", "light"), ("pebble", "light")],
    "Void": [("star", "light"), ("star", (230, 220, 255)), ("star", "accent")],
    "Swamp": [("tuft", "dark"), ("bubble", "light"), ("pebble", "dark")],
    "Coral Reef": [("bubble", "light"), ("flower", "accent"), ("pebble", (240, 205, 170))],
    "Autumn": [("leaf", "accent"), ("leaf", (200, 60, 30)), ("leaf", (235, 200, 70)), ("tuft", "dark")],
    "Crystal Caves": [("crystal", "accent"), ("crystal", "light"), ("pebble", "dark")],
    "Crimson Keep": [("stone", (95, 45, 50)), ("stone", (75, 35, 40)), ("crack", (100, 50, 55))],
    "Sakura": [("leaf", (255, 165, 195)), ("leaf", (255, 240, 245)), ("tuft", "dark")],
    "Jungle": [("tuft", "light"), ("tuft", "dark"), ("leaf", "dark"), ("flower", "accent")],
    "Salt Flats": [("crack", "dark"), ("pebble", "dark")],
    "Toxic Wastes": [("bubble", "accent"), ("crack", "accent"), ("pebble", "light")],
    "Midnight": [("star", "light"), ("star", (200, 215, 255)), ("tuft", "light")],
    "Badlands": [("crack", "dark"), ("pebble", "dark"), ("cactus", (110, 120, 60))],
    "Glacier": [("crack", "light"), ("crystal", "accent"), ("drift", (245, 250, 255))],
    "Ashlands": [("crack", "accent"), ("pebble", "dark"), ("pebble", "light")],
    "Neon Grid": [("star", "accent")],
    "The Abyss": [("crack", "accent"), ("star", (90, 70, 110))],
}
DECOR_DENSITY = 0.4  # share of free tiles with a prop


def render_map(theme, waypoints):
    """The level's ground and path, drawn once: tiles in a faint checkerboard with a little
    variation, the path sunk into the ground, and the theme's props on free tiles. The same
    level always looks the same (the variation is seeded by the theme's name)."""
    surf = pygame.Surface(sp((MAP_W, MAP_H)))
    rng = random.Random(theme.name)
    for ty in range(ROWS):
        for tx in range(COLS):
            k = (1.0 if (tx + ty) % 2 == 0 else 0.95) * rng.uniform(0.975, 1.025)
            sdraw.fill(surf, shade(theme.ground, k), (tx * TILE, ty * TILE, TILE, TILE))
    if theme.name == "Neon Grid":
        for tx in range(COLS + 1):
            sdraw.line(surf, shade(theme.accent, 0.3), (tx * TILE, 0), (tx * TILE, MAP_H), 1)
        for ty in range(ROWS + 1):
            sdraw.line(surf, shade(theme.accent, 0.3), (0, ty * TILE), (MAP_W, ty * TILE), 1)
    colors = {"dark": shade(theme.ground, 0.78), "light": shade(theme.ground, 1.25), "accent": theme.accent}
    props = DECOR.get(theme.name, [("tuft", "dark"), ("pebble", "dark")])
    on_path = path_tiles(waypoints)
    for ty in range(ROWS):
        for tx in range(COLS):
            if (tx, ty) in on_path or rng.random() >= DECOR_DENSITY:
                continue
            kind, color = rng.choice(props)
            x, y = tx * TILE + rng.uniform(11, 29), ty * TILE + rng.uniform(13, 29)
            PROPS[kind](surf, rng, x, y, colors.get(color, color))
    # Path: an edge-colored band, then a shaded inset, then the path color offset down-right, so the
    # path looks sunk into the ground (shadow along its top and left) and corners join cleanly.
    segments = []
    for (x0, y0), (x1, y1) in zip(waypoints, waypoints[1:]):
        left, top = min(x0, x1), min(y0, y1)
        segments.append((left * TILE, top * TILE, (max(x0, x1) - left + 1) * TILE, (max(y0, y1) - top + 1) * TILE))
    for inset, shift, color in ((0, 0, shade(theme.path, 0.7)), (5, 0, shade(theme.path, 0.82)),
                                (5, 3, theme.path)):
        for x, y, w, h in segments:
            sdraw.fill(surf, color, (x + inset + shift, y + inset + shift, w - 2 * inset - shift, h - 2 * inset - shift))
    return surf


# --------------------------------------------------------------------------
# Visual effects (they only age; they don't affect the game)
# --------------------------------------------------------------------------
class CastWarning:
    """A pulsing circle marking where a monster ability is about to land."""

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
        pulse = 0.5 + 0.5 * math.sin(self.t * 14)
        sdraw.circle(surf, (*self.color, int(30 + 40 * pulse)), self.pos, self.radius)
        sdraw.circle(surf, (*self.color, 220), self.pos, self.radius * (1 - 0.6 * self.t / self.duration), 2)


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


class Shards:
    """A dead enemy's pieces flying apart and fading. The spread comes from the enemy's spin, not a
    random roll, so drawing stays repeatable."""

    duration = 0.45

    def __init__(self, pos, color, size, angle):
        self.pos = pygame.Vector2(pos)
        self.color = color
        self.size = size
        self.t = 0.0
        n = 5 + size // 6
        self.pieces = [(pygame.Vector2(1, 0).rotate(angle + 360 * i / n + (i * 47) % 25), 0.7 + (i * 3) % 7 / 10)
                       for i in range(n)]

    def update(self, dt):
        self.t += dt
        return self.t < self.duration

    def draw(self, surf):
        k = self.t / self.duration
        ease = 1 - (1 - k) ** 2
        r = max(2.5, self.size * 0.55 * (1 - 0.4 * k))
        color = (*self.color, int(255 * (1 - k * k)))
        for direction, speed in self.pieces:
            center = self.pos + direction * (self.size * 0.4 + 36 * speed * ease)
            sdraw.polygon(surf, color, regular_polygon(center, r, 3, direction.as_polar()[1] + 500 * k * speed))


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


class Button:
    def __init__(self, rect, label):
        self.rect = pygame.Rect(rect)
        self.label = label


# --------------------------------------------------------------------------
# The game screen
# --------------------------------------------------------------------------
class GameView:
    """The drawing half of main.Game.

    Game provides the state: towers, enemies, theme, selection, overlays and so on.
    """

    def build_view(self):
        """Everything whose size depends on the display scale. Done once per scale change."""
        _caps.clear()
        self.font_s = load_font(11)
        self.font = load_font(14)
        self.font_l = load_font(22, "bold")
        self.font_xl = load_font(36, "bold")
        self.fx_layer = pygame.Surface(sp((MAP_W, MAP_H)), pygame.SRCALPHA)
        if hasattr(self, "theme"):
            self.map_surface = render_map(self.theme, self.waypoints)

    def apply_scale(self, scale):
        if scale == SCALE:
            return
        set_scale(scale)
        self.screen = pygame.display.set_mode(window_size())
        self.build_view()

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

    @staticmethod
    def fit_font(s, width, *fonts):
        """The first of `fonts` that fits `s` in `width` (logical units), else the last one."""
        return next((f for f in fonts if f.size(s)[0] <= width * SCALE), fonts[-1])

    def text(self, font, s, color, pos, anchor="topleft"):
        return blit_text(self.screen, font, s, color, pos, anchor)

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
                draw_tower_shadow(screen, t.pos)
        for e in self.enemies:
            draw_enemy_shadow(screen, e)
        for t in self.towers.values():
            if t is not self.dragging:
                draw_tower_shape(screen, t.spec, t.pos, t.aim)
                draw_tower_status(screen, fx, t)
        for e in self.enemies:
            draw_enemy(screen, e)
        for p in self.projectiles:
            draw_projectile(screen, p)
        for ef in self.effects:
            ef.draw(fx)
        if self.side == "monsters":
            self.draw_attack_map(fx)
        screen.blit(fx, (0, 0))
        if self.side == "monsters":
            self.draw_queue_text()
        mx, my = mouse_pos()
        hover = tile_center(mx // TILE, my // TILE)
        if self.build_kind and mx < MAP_W:
            draw_tower_shadow(screen, hover, 2.5)
            draw_tower_shape(screen, TOWERS[self.build_kind], hover)
        if self.dragging:
            t = self.dragging
            pos = hover if mx < MAP_W else t.pos
            draw_tower_shadow(screen, pos, 2.5)
            draw_tower_shape(screen, t.spec, pos, t.aim)
        self.draw_fusion_label()
        for p in self.popups:
            blit_text(screen, self.font, p.text, p.color, p.pos, "center", int(255 * (1 - p.t / 0.8)))

        self.draw_boss_bar()
        if not (self.show_settings or self.confirm_quit or self.show_tree or self.choice or self.reward_cards
                or self.picking_side):
            self.draw_banner()
        if not (self.confirm_quit or self.reward_cards or self.picking_side):
            self.draw_overlay()
        if self.show_settings:
            self.draw_settings()
        elif self.confirm_quit:
            self.draw_quit_prompt()
        elif self.picking_side:
            self.draw_side_pick()
        elif self.reward_cards:
            self.draw_rewards()
        elif self.choice:
            self.draw_choice()
        elif self.show_tree:
            self.draw_tree()
        screen.set_clip(None)
        self.draw_panel()

    def draw_range(self, surf, pos, radius, color):
        sdraw.circle(surf, (*color, 40), pos, radius)
        sdraw.circle(surf, (*color, 140), pos, radius, 2)

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
        mx, my = mouse_pos()
        rect = pygame.Rect(0, 0, self.font_s.size(label)[0] / SCALE + 14, cap_height(self.font_s) / SCALE + 12)
        rect.bottomleft = (mx + 14, my - 10)
        rect.clamp_ip((0, 0, MAP_W, MAP_H))
        sdraw.rect(self.screen, (20, 20, 26), rect, border_radius=4)
        self.text(self.font_s, label, color, rect.center, "center")

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
            title = f"{spec['boss'].upper()} APPROACHES"
            blit_text(band, self.fit_font(title, MAP_W - 32, self.font_xl, self.font_l), title, spec["color"],
                      (MAP_W / 2, 45), "center")
            band.set_alpha(int(255 * min(1.0, self.boss_alert)))
            self.screen.blit(band, sp((0, MAP_H / 2 - 45)))

    def draw_banner(self):
        """Big level title shown when a level starts, in the level's accent color."""
        if self.banner_timer <= 0:
            return
        alpha = int(255 * min(1.0, self.banner_timer / 0.8))
        band = pygame.Surface(sp((MAP_W, 110)), pygame.SRCALPHA)
        band.fill((0, 0, 0, int(alpha * 0.55)))
        pass_label = f"PASS {self.pass_no}  -  " if self.pass_no > 1 else ""
        title = f"{pass_label}LEVEL {self.level_idx + 1}: {self.theme.name.upper()}"
        sub_color = TEXT
        if self.side == "monsters":
            sub = "MONSTERS: draft a wave in the panel, then press Space to send it"
        elif self.finale_on and self.level_idx == self.last_level_idx:
            boss = ENEMY_TYPES[self.level_boss]["boss"]
            sub, sub_color = f"FINAL LEVEL - {boss} joins wave {self.level_waves}, where your monsters won", \
                self.theme.accent
        elif self.is_boss_level:
            boss = ENEMY_TYPES[self.level_boss]["boss"]
            sub, sub_color = f"BOSS LEVEL - {boss} waits at the end of wave {WAVES_PER_LEVEL}", self.theme.accent
        elif self.rebuild_layout:
            sub = "Press B to rebuild your towers, then Space to send the first wave"
        else:
            sub = "Build towers, then press Space to send the first wave"
        blit_text(band, self.fit_font(title, MAP_W - 32, self.font_xl, self.font_l), title, self.theme.accent,
                  (MAP_W / 2, 38), "center")
        blit_text(band, self.fit_font(sub, MAP_W - 32, self.font, self.font_s), sub, sub_color, (MAP_W / 2, 80),
                  "center")
        band.set_alpha(alpha)
        self.screen.blit(band, sp((0, MAP_H / 2 - 55)))

    def shade_map(self, alpha=160):
        shade = pygame.Surface(sp((MAP_W, MAP_H)), pygame.SRCALPHA)
        shade.fill((0, 0, 0, alpha))
        self.screen.blit(shade, (0, 0))

    def draw_overlay(self):
        run_over = [(f"Levels won this run: {self.levels_won}   (best: {self.profile.best_run})", TEXT, self.font_l),
                    ("Records and unlocks are kept. Press R or click for a new run.", TEXT, self.font)]
        if self.state == "level_complete" and self.side == "monsters":
            lines = [(f"{self.theme.name} breached!", self.theme.accent, self.font_xl),
                     (f"The towers lost {self.lives_taken} lives here: {self.lives} left for "
                      f"{self.levels_left} more levels", TEXT, self.font_l),
                     (f"Next up: {LEVELS[self.level_idx + 1][0].name}. Press Space or click to continue.", TEXT,
                      self.font)]
        elif self.state == "level_complete":
            nxt = LEVELS[self.level_idx + 1][0]
            lines = [(f"{self.theme.name} cleared!", self.theme.accent, self.font_xl),
                     (f"Next up: {nxt.name}", nxt.accent, self.font_l),
                     ("Towers are refunded in full. Press Space or click to continue.", TEXT, self.font)]
        elif self.state == "game_over" and self.side == "monsters":
            why = (f"The last level is over and they still have {self.lives} lives" if self.lives_taken else
                   f"Level {self.level_idx + 1}: they didn't lose a single life")
            lines = [("THE TOWERS HELD - RUN OVER", BAD, self.font_xl), (why, TEXT, self.font)] + run_over
        elif self.state == "game_over":
            lines = [("RUN OVER", BAD, self.font_xl),
                     (f"Lost at level {self.level_idx + 1}, wave {self.wave_idx}", TEXT, self.font)] + run_over
        elif self.state == "victory" and self.side == "monsters":
            lines = [("EVERY DEFENSE BROKEN!", GOLD, self.font_xl),
                     (f"Their last life went at level {self.level_idx + 1}, wave {self.wave_idx}. "
                      f"Pass {self.pass_no} complete.", TEXT, self.font_l),
                     ("Next: defend against your own waves, up to this very wave,", TEXT, self.font),
                     ("where The Warden joins them.", TEXT, self.font),
                     ("Press Space or click to switch sides.", TEXT, self.font)]
        elif self.state == "victory":
            held = (f"The Warden fell: held to level {self.level_idx + 1}, wave {self.wave_idx}." if self.finale_on
                    else f"All {len(LEVELS)} levels defended.")
            lines = [("PASS COMPLETE!", GOLD, self.font_xl), (held, TEXT, self.font_l),
                     ("Next: break your own defenses. Press Space or click to switch sides.", TEXT, self.font)]
        elif self.paused:
            lines = [("PAUSED", TEXT, self.font_xl), ("Press P to resume", TEXT_DIM, self.font)]
        else:
            return
        self.shade_map()
        smaller = {self.font_xl: self.font_l, self.font_l: self.font, self.font: self.font_s}
        fitted = []
        for s, color, font in lines:
            while font in smaller and font.size(s)[0] > (MAP_W - 32) * SCALE:
                font = smaller[font]
            fitted.append((s, color, font))
        gap = 14
        y = (MAP_H - sum(cap_height(f) / SCALE for _, _, f in fitted) - gap * (len(fitted) - 1)) / 2
        for s, color, font in fitted:
            r = self.text(font, s, color, (MAP_W / 2, y), "midtop")
            y = r.bottom / SCALE + gap

    def side_pick_rects(self):
        return [(side, pygame.Rect(MAP_W / 2 - 330 + i * 340, MAP_H / 2 - 100, 320, 230))
                for i, side in enumerate(("towers", "monsters"))]

    def draw_side_pick(self):
        """The new-run screen: start on the Towers or the Monsters side."""
        self.shade_map(225)
        self.text(self.font_xl, "NEW RUN", GOLD, (MAP_W / 2, 90), "midtop")
        self.text(self.font, f"Pick the side you start on. Best run so far: {self.profile.best_run} levels won.",
                  TEXT_DIM, (MAP_W / 2, 160), "midtop")
        about = {"towers": ("TOWERS", ["Build and fuse towers to hold", f"all {len(LEVELS)} levels against your own",
                                       "recorded monster waves."]),
                 "monsters": ("MONSTERS", ["Draft waves and use abilities", "to break your own recorded",
                                           "tower defenses, level by level."])}
        mouse = mouse_pos()
        for i, (side, rect) in enumerate(self.side_pick_rects()):
            title, desc = about[side]
            sdraw.rect(self.screen, (55, 55, 68) if rect.collidepoint(mouse) else (38, 38, 48), rect, border_radius=12)
            sdraw.rect(self.screen, self.theme.accent, rect, 3, border_radius=12)
            icon = pygame.Vector2(rect.centerx, rect.top + 46)
            if side == "towers":
                draw_tower_shape(self.screen, TOWERS["railgun"], icon)
            else:
                draw_enemy_icon(self.screen, ENEMY_TYPES["juggernaut"], icon, 16)
            self.text(self.font_l, title, TEXT, (rect.centerx, rect.top + 80), "midtop")
            for j, line in enumerate(desc):
                self.text(self.font_s, line, TEXT_DIM, (rect.centerx, rect.top + 124 + j * 20), "midtop")
            self.text(self.font, f"[{i + 1}]", GOLD, (rect.centerx, rect.bottom - 12), "midbottom")

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
            draw_tower_shape(self.screen, spec, pygame.Vector2(rect.centerx, rect.top + 38))
            self.text(self.font_l, spec["name"], spec["color"], (rect.centerx, rect.top + 66), "midtop")
            self.text(self.font_s, spec["desc"], TEXT, (rect.centerx, rect.top + 100), "midtop")
            self.text(self.font_s, self.stat_line(spec), TEXT_DIM, (rect.centerx, rect.top + 122), "midtop")
            self.text(self.font, f"[{i + 1}]", GOLD, (rect.centerx, rect.bottom - 12), "midbottom")

    def reward_card_rects(self):
        n = len(self.reward_cards)
        return [pygame.Rect(MAP_W / 2 - (n * 240 - 20) / 2 + i * 240, MAP_H / 2 - 110, 220, 250) for i in range(n)]

    def draw_rewards(self):
        """Pick one of three unlock cards after a win."""
        self.shade_map(200)
        monster = self.reward_pool == "monster"
        self.text(self.font_l, "VICTORY SPOILS - PICK ONE", GOLD, (MAP_W / 2, MAP_H / 2 - 190), "midtop")
        note = "Monster unlocks: for your waves on the Monsters side" if monster else \
            "Tower cards: they power up your towers"
        self.text(self.font_s, note, TEXT_DIM, (MAP_W / 2, MAP_H / 2 - 150), "midtop")
        if self.starter_picks is None:  # a win, not the starter pack: say what the record's tier gave
            self.text(self.font_s, self.tier_note(), TIER_COLORS[self.reward_tier], (MAP_W / 2, MAP_H / 2 - 132),
                      "midtop")
        mouse = mouse_pos()
        for i, (rect, key) in enumerate(zip(self.reward_card_rects(), self.reward_cards)):
            card = UNLOCKS[self.reward_pool][key]
            rank = self.profile.rank(self.reward_pool, key)
            hover = rect.collidepoint(mouse)
            sdraw.rect(self.screen, (55, 55, 68) if hover else (38, 38, 48), rect, border_radius=10)
            sdraw.rect(self.screen, GOLD if card["rare"] else PANEL_LINE, rect, 4 if card["rare"] else 2,
                       border_radius=10)
            icon = pygame.Vector2(rect.centerx, rect.top + 44)
            if card["effect"] == "type":
                draw_enemy_icon(self.screen, ENEMY_TYPES[card["type"]], icon, 16)
            elif card["effect"] == "ability":
                sdraw.circle(self.screen, ABILITIES[card["ability"]]["color"], icon, 16)
            else:
                sdraw.circle(self.screen, GOLD if card["rare"] else TEXT_DIM, icon, 12, 3)
            self.text(self.font, card["name"], GOLD if card["rare"] else TEXT, (rect.centerx, rect.top + 76), "midtop")
            y = rect.top + 106
            for line in wrap(card["desc"], 26):
                self.text(self.font_s, line, TEXT, (rect.centerx, y), "midtop")
                y += 20
            if card["max"] > 1:
                label = f"Rank {rank + 1} of {card['max']}" if rank else f"New - up to {card['max']} ranks"
                self.text(self.font_s, label, TEXT_DIM, (rect.centerx, rect.bottom - 64), "midtop")
            if card["rare"]:
                self.text(self.font_s, "RARE", GOLD, (rect.right - 10, rect.top + 8), "topright")
            self.text(self.font, f"[{i + 1}]", GOLD, (rect.centerx, rect.bottom - 12), "midbottom")

    def tier_note(self):
        spec = REWARDS[self.reward_tier]
        gave = [f"{spec['cards']} cards"] + (["a sure rare"] if spec["rare"] else [])
        if self.reward_pool == "monster":
            gave.append(f"+{spec['share']:.0%} budget share")
        return f"{self.reward_tier.capitalize()} record ({self.record_ratio:.1f}x par): " + ", ".join(gave)

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
            spec = TOWERS[kind]
            draw_tower_shape(self.screen, spec, pygame.Vector2(x + 16, y))
            r = self.text(self.font, spec["name"], spec["color"], (x + 42, y - 14))
            self.text(self.font_s, f"{TOWERS[a]['name']} + {TOWERS[b]['name']}", TEXT,
                      (r.right / SCALE + 10, r.bottom / SCALE), "bottomleft")
            self.text(self.font_s, spec["desc"], TEXT_DIM, (x + 42, y + 3))
        self.text(self.font_s, "Press T or click to close", TEXT_DIM, (MAP_W - 10, MAP_H - 8), "bottomright")

    def tree_node(self, kind, x, y):
        spec = TOWERS[kind]
        draw_tower_shape(self.screen, spec, pygame.Vector2(x + 16, y))
        self.text(self.font, spec["name"], spec["color"], (x + 42, y), "midleft")

    def scale_buttons(self):
        w = 90
        x0 = MAP_W / 2 - (len(SCALES) * (w + 10) - 10) / 2
        return [(k, pygame.Rect(x0 + i * (w + 10), 250, w, 50)) for i, k in enumerate(SCALES)]

    @staticmethod
    def settings_close_button():
        return pygame.Rect(MAP_W / 2 - 110, 420, 220, 50)

    @staticmethod
    def settings_continue_button():
        return pygame.Rect(MAP_W / 2 - 150, 482, 300, 50)

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
        label = "Play  [Enter]" if self.untouched else "Resume  [Enter]"
        hint_y = 500
        if self.can_continue:
            label = "New game  [Enter]"
            c = self.settings_continue_button()
            theme = LEVELS[self.save["level"]][0]
            sdraw.rect(self.screen, (90, 90, 108) if c.collidepoint(mouse) else (70, 70, 85), c, border_radius=8)
            sdraw.rect(self.screen, theme.accent, c, 3, border_radius=8)
            self.text(self.font, f"Continue: level {self.save['level'] + 1}, {theme.name}  [C]", TEXT, c.center,
                      "center")
            hint_y = 560
        self.text(self.font, label, TEXT, b.center, "center")
        self.text(self.font_s, "Press O in game to come back here. The choice is saved for next time.",
                  TEXT_DIM, (MAP_W / 2, hint_y), "midtop")

    def draw_button(self, b, label, enabled=True, active=False, font=None):
        hover = b.rect.collidepoint(mouse_pos())
        bg = (70, 70, 85) if enabled else (40, 40, 48)
        if enabled and hover:
            bg = (90, 90, 108)
        sdraw.rect(self.screen, bg, b.rect, border_radius=6)
        border = self.theme.accent if active else PANEL_LINE
        sdraw.rect(self.screen, border, b.rect, 3 if active else 1, border_radius=6)
        font = self.fit_font(label, b.rect.width - 8, font or self.font, self.font_s)
        self.text(font, label, TEXT if enabled else TEXT_DIM, b.rect.center, "center")

    def evolve_hint(self, t):
        if t.tier == 4:
            return "Final form"
        if t.tier == 3:
            return "+ Tier 3 of another line"
        options = EVOLVE[t.kind]
        return f"+ {t.spec['name']} -> " + " / ".join(TOWERS[k]["name"] for k in options)

    def draw_panel(self):
        if self.side == "monsters":
            self.draw_attack_panel()
            return
        screen = self.screen
        x = MAP_W + 12
        self.draw_panel_header()
        self.text(self.font, f"Wave {self.wave_idx} / {self.level_waves}", TEXT, (x, 84))
        self.text(self.font, f"Lives {self.lives}", BAD if self.lives <= 5 else TEXT, (x, 110))
        self.text(self.font, f"Gold {self.gold}", GOLD, (x, 136))
        self.text(self.font_s, "TOWERS", TEXT_DIM, (x, 176))

        for i, (kind, b) in enumerate(self.tower_buttons.items()):
            spec = TOWERS[kind]
            affordable = self.gold >= spec["cost"]
            active = self.build_kind == kind
            bg = (70, 70, 85) if b.rect.collidepoint(mouse_pos()) else (48, 48, 58)
            sdraw.rect(screen, bg, b.rect, border_radius=6)
            sdraw.rect(screen, self.theme.accent if active else PANEL_LINE, b.rect,
                       3 if active else 1, border_radius=6)
            draw_tower_shape(screen, spec, pygame.Vector2(b.rect.left + 28, b.rect.centery))
            self.text(self.font, f"{spec['name']} [{i + 1}]", TEXT if affordable else TEXT_DIM,
                      (b.rect.left + 56, b.rect.centery - 8), "midleft")
            self.text(self.font_s, f"{spec['cost']}g - {spec['desc']}", GOLD if affordable else TEXT_DIM,
                      (b.rect.left + 56, b.rect.centery + 10), "midleft")

        if self.selected:
            t = self.selected
            spec = t.spec
            self.text(self.font, spec["name"], spec["color"], (x, 388), "bottomleft")
            self.text(self.font_s, f"Tier {t.tier}", TIER_RIM[t.tier] if t.tier > 1 else TEXT_DIM,
                      (x + PANEL_W - 24, 388), "bottomright")
            self.text(self.font_s, spec["desc"], TEXT, (x, 401))
            self.text(self.font_s, f"Dmg {spec['damage']:.0f} Rng {spec['range']:.0f} Rate {spec['rate']:.1f}",
                      TEXT_DIM, (x, 419))
            self.text(self.font_s, self.evolve_hint(t), GOLD, (x, 441))
            self.draw_button(self.sell_button, f"Sell {t.sell_value}g  [S]", True)
        else:
            self.text(self.font_s, "Drag towers to move them", TEXT_DIM, (x, 380))
            self.text(self.font_s, "Drop two matching towers", TEXT_DIM, (x, 398))
            self.text(self.font_s, "together to evolve them", TEXT_DIM, (x, 416))
            self.text(self.font_s, "T: see the evolution tree", GOLD, (x, 441))
            if self.can_rebuild:
                n = len(self.rebuild_layout)
                affordable = self.gold >= min(e["spent"] for e in self.rebuild_layout)
                self.draw_button(self.rebuild_button, f"Rebuild {n} tower{'s' * (n > 1)}  [B]", affordable,
                                 active=affordable and self.state == "build" and self.wave_idx == 0)

        self.text(self.font_s, "Enemies", TEXT_DIM, (x, 526), "midleft")
        for i, spec in enumerate(s for s in ENEMY_TYPES.values() if s["draft"] == "starter"):
            c = pygame.Vector2(x + 74 + i * 30, 526)
            if spec["sides"] == 0:
                sdraw.circle(screen, spec["color"], c, 8)
            else:
                sdraw.polygon(screen, spec["color"], regular_polygon(c, 9, spec["sides"], -90))

        self.draw_panel_footer()

    def draw_panel_header(self):
        """Panel background and the level header in the level's accent color."""
        screen = self.screen
        sdraw.fill(screen, PANEL_BG, (MAP_W, 0, PANEL_W, HEIGHT))
        sdraw.line(screen, self.theme.accent, (MAP_W, 0), (MAP_W, HEIGHT), 4)
        header = pygame.Rect(MAP_W + 12, 12, PANEL_W - 24, 56)
        sdraw.rect(screen, self.theme.accent, header, border_radius=8)
        name_font = self.font_l if self.font_l.size(self.theme.name)[0] <= (header.width - 12) * SCALE else self.font
        self.text(name_font, self.theme.name, (20, 20, 25), (header.centerx, header.top + 20), "center")
        level_label = (f"Level {self.level_idx + 1} of {self.last_level_idx + 1}"
                       + ("  -  BOSS" if self.is_boss_level else ""))
        self.text(self.font_s, level_label, (20, 20, 25), (header.centerx, header.bottom - 12), "midbottom")

    def draw_panel_footer(self):
        """The wave button and the speed / pause / tree row."""
        if self.state == "build":
            label, enabled = f"Send wave {self.wave_idx + 1} [Space]", self.wave_lock <= 0
        elif self.state == "level_complete":
            label, enabled = "Next level [Space]", True
        elif self.state == "victory":
            label, enabled = "Switch sides [Space]", True
        elif self.state == "game_over":
            label, enabled = "New run [R]", True
        else:
            left = len(self.enemies) + len(self.spawn_queue)
            label, enabled = f"{left} {'enemy' if left == 1 else 'enemies'} left", False
        self.draw_button(self.wave_button, label, enabled, active=enabled)
        self.draw_button(self.speed_button, f"F:{self.speed}x", True, active=self.speed > 1, font=self.font_s)
        self.draw_button(self.pause_button, "P:Pause", True, active=self.paused, font=self.font_s)
        self.draw_button(self.tree_button, "T:Tree", True, active=self.show_tree, font=self.font_s)
