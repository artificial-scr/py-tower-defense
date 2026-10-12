"""The level maps, drawn once per level and display scale: textured ground with a faint tile grid, a
path styled for the theme, and shaded decoration on the free tiles.

Everything is seeded by the theme's name, so a level always looks the same. Nothing here moves: the
ground is soft noise (small grids of random values, smoothly enlarged), the path is drawn PATH_SUPERSAMPLE
times larger and shrunk (that's its anti-aliasing), and each kind of prop is a small picture drawn
once, like the sprites.
"""

import random

import pygame

import sprites
from levels import COLS, ROWS, TILE
from sprites import V, Canvas, blob, gem, mix, shade, sphere

MAP_W, MAP_H = COLS * TILE, ROWS * TILE
PATH_SUPERSAMPLE = 2
GRID_ALPHA = 34  # the always-on tile grid; GameView shows a clearer one while placing a tower
WHITE = (255, 255, 255)


def path_tiles(waypoints):
    tiles = set()
    for (x0, y0), (x1, y1) in zip(waypoints, waypoints[1:]):
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                tiles.add((x, y))
    return tiles


# --------------------------------------------------------------------------
# Ground
# --------------------------------------------------------------------------
# theme name -> the color of the patches its ground is mottled with
PATCHES = {
    "Meadow": (120, 150, 70), "Desert": (232, 200, 135), "Tundra": (180, 208, 235), "Volcano": (36, 20, 22),
    "Void": (48, 32, 86), "Swamp": (52, 72, 62), "Coral Reef": (28, 118, 140), "Autumn": (185, 125, 55),
    "Crystal Caves": (92, 76, 145), "Crimson Keep": (64, 22, 28), "Sakura": (250, 216, 226),
    "Jungle": (18, 70, 40), "Salt Flats": (214, 214, 208), "Toxic Wastes": (62, 72, 24), "Midnight": (30, 46, 88),
    "Badlands": (186, 96, 56), "Glacier": (150, 205, 236), "Ashlands": (66, 62, 60), "Neon Grid": (18, 18, 32),
    "The Abyss": (26, 10, 24),
}


def _noise(rng, size, scale, cell, color, strength, patchy=False):
    """A layer of `color` blotches about `cell` logical pixels apart: a coarse grid of random opacities,
    smoothly enlarged. `patchy` makes it on/off blotches instead of a soft wash."""
    cols, rows = MAP_W // cell + 2, MAP_H // cell + 2
    small = pygame.Surface((cols, rows), pygame.SRCALPHA)
    for y in range(rows):
        for x in range(cols):
            v = rng.random()
            alpha = (1.0 if v > 0.62 else 0.0) if patchy else v
            small.set_at((x, y), (*color, round(255 * strength * alpha)))
    big = pygame.transform.smoothscale(small, (round(cols * cell * scale), round(rows * cell * scale)))
    layer = pygame.Surface(size, pygame.SRCALPHA)
    layer.blit(big, (round(-cell * scale / 2), round(-cell * scale / 2)))
    return layer


def _ground(theme, scale, rng, size):
    surf = pygame.Surface(size)
    surf.fill(theme.ground)
    for color, cell, strength, patchy in ((shade(theme.ground, 0.86), 120, 0.55, False),
                                          (shade(theme.ground, 1.12), 70, 0.45, False),
                                          (PATCHES[theme.name], 46, 0.55, True),
                                          (shade(theme.ground, 0.82), 6, 0.2, False)):
        surf.blit(_noise(rng, size, scale, cell, color, strength, patchy), (0, 0))
    return surf


def grid_lines(scale, color, alpha):
    """The tile grid, as a see-through layer."""
    def make():
        layer = pygame.Surface((round(MAP_W * scale), round(MAP_H * scale)), pygame.SRCALPHA)
        width = max(1, round(scale))
        for tx in range(1, COLS):
            x = round(tx * TILE * scale)
            pygame.draw.line(layer, (*color, alpha), (x, 0), (x, layer.get_height()), width)
        for ty in range(1, ROWS):
            y = round(ty * TILE * scale)
            pygame.draw.line(layer, (*color, alpha), (0, y), (layer.get_width(), y), width)
        return layer
    return sprites.cached(("grid", color, alpha, scale), make)


# --------------------------------------------------------------------------
# The path
# --------------------------------------------------------------------------
# theme name -> path style: dirt (worn edges, ruts, pebbles), sand (ripples), stone (flagstones),
# ice (cracks and shine), crust (dark plates over glowing cracks), neon (a dark lane with bright edges)
PATH_STYLES = {
    "Meadow": "dirt", "Autumn": "dirt", "Jungle": "dirt", "Swamp": "dirt", "Sakura": "dirt", "Badlands": "dirt",
    "Desert": "sand", "Salt Flats": "sand", "Coral Reef": "sand",
    "Crimson Keep": "stone", "The Abyss": "stone", "Midnight": "stone", "Crystal Caves": "stone",
    "Tundra": "ice", "Glacier": "ice",
    "Volcano": "crust", "Ashlands": "crust", "Toxic Wastes": "crust",
    "Neon Grid": "neon", "Void": "neon",
}
EDGE = 5  # how far the path's floor is set in from its tiles' edges


class _Pen:
    """Draws on a surface in logical units at a given number of pixels per unit."""

    def __init__(self, surf, k):
        self.surf, self.k = surf, k

    def w(self, width):
        return max(1, round(width * self.k))

    def rect(self, color, rect):
        x, y, w, h = rect
        self.surf.fill(color, pygame.Rect(round(x * self.k), round(y * self.k), round(w * self.k), round(h * self.k)))

    def circle(self, color, c, r):
        pygame.draw.circle(self.surf, color, (c[0] * self.k, c[1] * self.k), r * self.k)

    def line(self, color, a, b, width=1):
        pygame.draw.line(self.surf, color, (a[0] * self.k, a[1] * self.k), (b[0] * self.k, b[1] * self.k),
                         self.w(width))

    def lines(self, color, points, width=1):
        pygame.draw.lines(self.surf, color, False, [(x * self.k, y * self.k) for x, y in points], self.w(width))

    def polygon(self, color, points):
        pygame.draw.polygon(self.surf, color, [(x * self.k, y * self.k) for x, y in points])


def _segments(waypoints):
    """Each leg of the path: (its rect of tiles in logical units, start and end tile centers)."""
    legs = []
    for (x0, y0), (x1, y1) in zip(waypoints, waypoints[1:]):
        left, top = min(x0, x1), min(y0, y1)
        rect = (left * TILE, top * TILE, (max(x0, x1) - left + 1) * TILE, (max(y0, y1) - top + 1) * TILE)
        legs.append((rect, V((x0 + 0.5) * TILE, (y0 + 0.5) * TILE), V((x1 + 0.5) * TILE, (y1 + 0.5) * TILE)))
    return legs


def _floor(rect, inset=EDGE):
    x, y, w, h = rect
    return x + inset, y + inset, w - 2 * inset, h - 2 * inset


def _along(rect, a, b, rng, step, inset):
    """Points spaced about `step` apart down the middle of a leg, with the direction across it."""
    d = (b - a).normalize()
    across = d.rotate(90)
    x, y, w, h = rect
    length = (w if d.x else h) - 2 * inset
    start = V(x + inset, y + h / 2) if d.x else V(x + w / 2, y + inset)
    axis = V(1, 0) if d.x else V(0, 1)
    n = max(1, int(length / step))
    return [(start + axis * (i + rng.uniform(0.2, 0.8)) * length / n, across) for i in range(n)]


def _worn_edges(pen, legs, color, rng, inset, bulge):
    """Bumps along the sides of each leg so its edge looks trodden rather than ruled."""
    for rect, a, b in legs:
        half = (TILE / 2 - inset)
        for c, across in _along(rect, a, b, rng, 4, 0):
            for k in (-1, 1):
                pen.circle(color, c + across * k * (half + rng.uniform(-1.5, bulge)), rng.uniform(1.8, 3.2))


def _speckle(pen, legs, rng, colors, per_tile=10):
    for rect, _, _ in legs:
        x, y, w, h = _floor(rect, EDGE + 2)
        for _ in range(int(per_tile * w * h / TILE ** 2)):
            pen.circle(rng.choice(colors), (rng.uniform(x, x + w), rng.uniform(y, y + h)), rng.uniform(0.6, 1.3))


def _offset(points, off):
    """A polyline shifted sideways by `off`, its corners mitred so parallel lines turn together."""
    out = []
    for i, p in enumerate(points):
        normals = [(points[j + 1] - points[j]).normalize().rotate(90) for j in (i - 1, i) if 0 <= j < len(points) - 1]
        n = sum(normals, V())
        out.append(p + n * off / (1 + normals[0].dot(normals[-1])) if len(normals) == 2 else p + n * off)
    return out


def _dirt(pen, legs, theme, rng):
    centers = [legs[0][1]] + [b for _, _, b in legs]
    for k in (-1, 1):
        pen.lines(shade(theme.path, 0.86), _offset(centers, 7 * k), 3)
    _speckle(pen, legs, rng, (shade(theme.path, 0.8), mix(theme.path, WHITE, 0.15)))
    for rect, a, b in legs:  # pebbles near the edges
        for c, across in _along(rect, a, b, rng, 14, 0):
            p = c + across * rng.choice((-1, 1)) * rng.uniform(9, 13)
            r = rng.uniform(1.0, 1.8)
            pen.circle(shade(theme.path, 0.6), p + V(0.4, 0.5), r)
            pen.circle(mix(theme.path, WHITE, 0.25), p, r * 0.8)


def _sand(pen, legs, theme, rng):
    light, dark = mix(theme.path, WHITE, 0.22), shade(theme.path, 0.88)
    for rect, a, b in legs:
        for c, across in _along(rect, a, b, rng, 6, EDGE):
            wave = [c + across * t + (b - a).normalize() * rng.uniform(-0.8, 0.8) for t in (-13, -6, 0, 6, 13)]
            pen.lines(dark, [p + V(0.6, 0.6) for p in wave], 1.4)
            pen.lines(light, wave, 1.0)
    _speckle(pen, legs, rng, (shade(theme.path, 0.85),), 6)


def _stone(pen, legs, theme, rng):
    mortar = shade(theme.path, 0.76)
    for rect, a, b in legs:
        x, y, w, h = _floor(rect, EDGE + 1)
        d = (b - a).normalize()
        horizontal = bool(d.x)
        length, across = (w, h) if horizontal else (h, w)
        rows = max(1, round(length / 13))
        for i in range(rows):
            split = across * (0.5 + (0.17 if i % 2 else -0.17))
            for lo, hi in ((0, split), (split, across)):
                a0, a1 = i * length / rows, (i + 1) * length / rows
                stone = (x + a0, y + lo, a1 - a0, hi - lo) if horizontal else (x + lo, y + a0, hi - lo, a1 - a0)
                pen.rect(mortar, stone)
                sx, sy, sw, sh = stone
                pen.rect(shade(theme.path, rng.uniform(0.92, 1.08)), (sx + 0.8, sy + 0.8, sw - 1.6, sh - 1.6))
                pen.rect(mix(theme.path, WHITE, 0.12), (sx + 0.8, sy + 0.8, sw - 1.6, 0.8))


def _ice(pen, legs, theme, rng):
    for rect, _, _ in legs:
        x, y, w, h = _floor(rect, EDGE + 2)
        for _ in range(int(3 * w * h / TILE ** 2) + 1):  # shine
            p = V(rng.uniform(x, x + w - 8), rng.uniform(y + 4, y + h))
            pen.line(mix(theme.path, WHITE, 0.6), p, p + V(6, -4), 1)
        for _ in range(int(1.2 * w * h / TILE ** 2) + 1):  # cracks
            p = V(rng.uniform(x, x + w), rng.uniform(y, y + h))
            crack = [p]
            for _ in range(rng.randint(2, 4)):
                p = p + V(rng.uniform(-6, 6), rng.uniform(-6, 6))
                p = V(min(max(p.x, x), x + w), min(max(p.y, y), y + h))
                crack.append(p)
            pen.lines(shade(theme.path, 0.72), crack, 0.8)


def _crust(pen, legs, theme, rng):
    """Dark plates of cooled crust with the path color showing through the cracks between them."""
    for rect, _, _ in legs:
        x, y, w, h = _floor(rect, EDGE + 1)
        cell = 15
        nx, ny = max(1, round(w / cell)), max(1, round(h / cell))
        cw, ch = w / nx, h / ny
        for i in range(nx):
            for j in range(ny):
                corners = [V(x + (i + dx) * cw, y + (j + dy) * ch) for dx, dy in ((0, 0), (1, 0), (1, 1), (0, 1))]
                corners = [p + V(rng.uniform(-1.6, 1.6), rng.uniform(-1.6, 1.6)) for p in corners]
                mid = sum(corners, V()) / 4
                plate = [mid + (p - mid) * 0.88 for p in corners]
                pen.polygon(shade(theme.path, rng.uniform(0.28, 0.36)), plate)
                pen.line(shade(theme.path, 0.48), plate[0], plate[1], 0.8)


def _neon_lane(pen, legs, theme, rng):
    lane = mix(theme.ground, theme.path, 0.12)
    for rect, _, _ in legs:
        pen.rect(lane, _floor(rect, 3))
    for rect, _, _ in legs:
        x, y, w, h = _floor(rect, 3)
        for color, width, inset in (((*theme.path, 80), 4, 0), (mix(theme.path, WHITE, 0.25), 1.2, 0)):
            for a, b in (((x, y), (x + w, y)), ((x, y + h), (x + w, y + h)), ((x, y), (x, y + h)),
                         ((x + w, y), (x + w, y + h))):
                pen.line(color, a, b, width)
    for rect, _, _ in legs:  # cover the edge lines where legs overlap, so corners stay open
        pen.rect(lane, _floor(rect, 5))
    for rect, a, b in legs:
        d = (b - a).normalize()
        for i in range(int(a.distance_to(b) / 12) + 1):
            p = a + d * i * 12
            pen.line(mix(lane, theme.path, 0.5), p, p + d * 5, 1)


DETAIL = {"dirt": _dirt, "sand": _sand, "stone": _stone, "ice": _ice, "crust": _crust, "neon": _neon_lane}


def _path(theme, waypoints, scale, rng, size):
    style = PATH_STYLES[theme.name]
    k = scale * PATH_SUPERSAMPLE
    layer = pygame.Surface((size[0] * PATH_SUPERSAMPLE, size[1] * PATH_SUPERSAMPLE), pygame.SRCALPHA)
    pen = _Pen(layer, k)
    legs = _segments(waypoints)
    if style != "neon":
        # an edge band, then the floor sunk into it: a shaded strip along its top and left
        edge = shade(theme.path, 0.32 if style == "crust" else 0.7)
        for rect, _, _ in legs:
            pen.rect(edge, _floor(rect, 1))
        if style in ("dirt", "sand"):
            _worn_edges(pen, legs, edge, rng, 1, 2.0)
        for rect, _, _ in legs:
            pen.rect(shade(theme.path, 0.82), _floor(rect))
        floor = mix(theme.path, (255, 210, 90), 0.15) if style == "crust" else theme.path
        for rect, _, _ in legs:
            x, y, w, h = _floor(rect)
            pen.rect(floor, (x + 3, y + 3, w - 3, h - 3))
    DETAIL[style](pen, legs, theme, rng)
    return pygame.transform.smoothscale(layer, size)


# --------------------------------------------------------------------------
# Props: small shaded pictures scattered on free tiles. Each is drawn round (0, 0), the spot it
# stands on, in a few variants; `rng` gives a variant its shape.
# --------------------------------------------------------------------------
PROP_SIZE = 26
SHADOW = (0, 0, 0, 60)


def _shadow(cv, w, h):
    cv.polygon(SHADOW, sprites.ellipse_points(V(1.5, 1.5), V(1, 0), w, h, 16))


def _tuft(cv, rng, color):
    tip = mix(color, WHITE, 0.25)
    for _ in range(rng.randint(3, 5)):
        x, lean, height = rng.uniform(-4.5, 4.5), rng.uniform(-2.5, 2.5), rng.uniform(5, 9)
        cv.polygon(color, [V(x - 1.1, 0), V(x + lean, -height), V(x + 1.1, 0)])
        cv.line(tip, V(x + lean * 0.5, -height * 0.5), V(x + lean, -height), 0.6)


def _flower(cv, rng, color):
    for i in range(5):
        p = V(2.2, 0).rotate(i * 72 + rng.uniform(0, 72))
        cv.circle(shade(color, 0.8), p + V(0.3, 0.3), 1.7)
        cv.circle(color, p, 1.5)
    sphere(cv, (250, 215, 80), (0, 0), 1.3, 0.4)


def _pebble(cv, rng, color):
    r = rng.uniform(2, 3.8)
    _shadow(cv, r * 1.2, r * 0.8)
    blob(cv, color, (0, 0), V(1, 0).rotate(rng.uniform(-30, 30)), r * 1.2, r * 0.85, 0.5)


def _crack(cv, rng, color):
    pts = [V(-7, rng.uniform(-3, 3))] + [V(-7 + i * 4.7, rng.uniform(-4, 4)) for i in range(1, 4)]
    for a, b in zip(pts, pts[1:]):
        cv.line((*mix(color, WHITE, 0.35), 110), a + V(0, 0.9), b + V(0, 0.9), 0.8)
    for a, b in zip(pts, pts[1:]):
        cv.line(color, a, b, 1.6)


def _star(cv, rng, color):
    r = rng.uniform(1.8, 3.4)
    cv.circle((*color, 60), (0, 0), r * 0.9)
    cv.polygon(color, [V(r, 0), V(0, r * 0.25), V(-r, 0), V(0, -r * 0.25)])
    cv.polygon(color, [V(0, r), V(r * 0.25, 0), V(0, -r), V(-r * 0.25, 0)])


def _crystal(cv, rng, color):
    _shadow(cv, 5, 2.4)
    for lean, height, x in sorted(((rng.uniform(-25, 25), rng.uniform(5, 9), rng.uniform(-3, 3))
                                   for _ in range(rng.randint(2, 3))), key=lambda s: -s[1]):
        up = V(0, -1).rotate(lean)
        base = V(x, 1)
        gem(cv, color, base + up * height * 0.45, [base - up.rotate(90) * 1.8, base + up * height * 0.75,
                                                    base + up * height, base + up.rotate(90) * 1.8], 0.5)


def _drift(cv, rng, color):
    _shadow(cv, 6, 2.5)
    for x, r in ((-3, 3.2), (2, 4), (5, 2.6)):
        blob(cv, color, (x + rng.uniform(-0.8, 0.8), -r * 0.4), V(1, 0), r * 1.1, r * 0.75, 0)
    cv.polygon((*shade(color, 0.8), 255), sprites.ellipse_points(V(0.5, 1.2), V(1, 0), 7.5, 1.2, 16))


def _leaf(cv, rng, color):
    d = V(1, 0).rotate(rng.uniform(0, 360))
    gem(cv, color, (0, 0), [d * 3.6, d.rotate(90) * 1.7, -d * 3.6, -d.rotate(90) * 1.7], 0.5)
    cv.line(shade(color, 0.6), d * 3, -d * 3, 0.5)


def _bubble(cv, rng, color):
    r = rng.uniform(2, 3.6)
    cv.circle((*color, 200), (0, 0), r, 0.8)
    cv.circle((255, 255, 255, 200), V(-r * 0.35, -r * 0.35), max(0.5, r * 0.22))


def _cactus(cv, rng, color):
    _shadow(cv, 4, 2)
    lean = rng.uniform(-0.5, 0.5)
    blob(cv, color, V(lean, -3.5), V(0, -1), 5.5, 2.0, 0.5)
    for x, y, h in ((-3.8, -4.5, 2.4), (3.6, -5.5, 2.0)):
        blob(cv, color, V(x * 0.6 + lean, y + 1.5), V(1, 0), 1.6, 0.9, 0)
        blob(cv, color, V(x + lean, y), V(0, -1), h, 0.95, 0.4)
    for i in range(4):
        cv.circle(mix(color, WHITE, 0.6), V(lean + (-0.8 if i % 2 else 0.8), -7 + i * 2.2), 0.35)


def _stone(cv, rng, color):
    _shadow(cv, 6, 3)
    w, h = rng.uniform(4, 6), rng.uniform(2.4, 3.4)
    slab = [V(-w, -h * 0.6), V(-w * 0.4, -h), V(w * 0.7, -h * 0.9), V(w, h * 0.2), V(w * 0.3, h), V(-w * 0.8, h * 0.8)]
    gem(cv, color, (0, 0), [p + V(rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5)) for p in slab], 0.6)


PROPS = {"tuft": _tuft, "flower": _flower, "pebble": _pebble, "crack": _crack, "star": _star, "crystal": _crystal,
         "drift": _drift, "leaf": _leaf, "bubble": _bubble, "cactus": _cactus, "stone": _stone}
PROP_VARIANTS = 4
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


def prop(kind, color, variant, scale):
    def make():
        cv = Canvas(PROP_SIZE, scale)
        PROPS[kind](cv, random.Random(f"{kind}:{variant}"), color)
        return cv.done()
    return sprites.cached(("prop", kind, color, variant, scale), make)


def _props(surf, theme, waypoints, scale, rng):
    """Scatter the theme's props; returns the centers of those in its accent color."""
    colors = {"dark": shade(theme.ground, 0.78), "light": shade(theme.ground, 1.25), "accent": theme.accent}
    props = DECOR[theme.name]
    on_path = path_tiles(waypoints)
    accents = []
    for ty in range(ROWS):
        for tx in range(COLS):
            if (tx, ty) in on_path or rng.random() >= DECOR_DENSITY:
                continue
            kind, color = rng.choice(props)
            img = prop(kind, colors.get(color, color), rng.randrange(PROP_VARIANTS), scale)
            x, y = tx * TILE + rng.uniform(11, 29), ty * TILE + rng.uniform(15, 29)
            surf.blit(img, img.get_rect(center=(round(x * scale), round(y * scale))))
            if color == "accent":
                accents.append(V(x, y))
    return accents


def render_map(theme, waypoints, scale):
    """The level's ground, grid, props and path at a display scale, the same every time."""
    return map_layers(theme, waypoints, scale)[0]


def map_layers(theme, waypoints, scale):
    """render_map's picture, and the centers of the props in the theme's accent color (ambience.py
    makes the glowing ones pulse)."""
    rng = random.Random(theme.name)
    size = (round(MAP_W * scale), round(MAP_H * scale))
    surf = _ground(theme, scale, rng, size)
    if theme.name == "Neon Grid":
        surf.blit(grid_lines(scale, shade(theme.accent, 0.3), 255), (0, 0))
    else:
        surf.blit(grid_lines(scale, shade(theme.ground, 0.6), GRID_ALPHA), (0, 0))
    accents = _props(surf, theme, waypoints, scale, rng)
    surf.blit(_path(theme, waypoints, scale, rng, size), (0, 0))
    return surf, accents
