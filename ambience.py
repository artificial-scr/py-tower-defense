"""What moves on the map without mattering to the game: drifting particles (pollen, snow, embers...),
a slow pulse on what glows (lava cracks, crystals, neon), the portal enemies come out of and the gate
they leave by.

Nothing here keeps state or rolls dice while playing: where a particle is comes from the game clock
and its number, so a moment always looks the same and a paused game stands still. Each particle lives
`life` seconds, fading in and out, then comes back somewhere else. Pictures are small and drawn once
(sprites.cached), so a frame is a few dozen blits. The "Ambient effects" setting turns particles and the
pulse off; the portal and gate stay, still.
"""

import math

import pygame

import sprites
from levels import COLS, ROWS, TILE
from sprites import V, Canvas, mix, shade, WHITE

MAP_W, MAP_H = COLS * TILE, ROWS * TILE

# --------------------------------------------------------------------------
# Particles
# --------------------------------------------------------------------------
# theme name -> its kinds of particle: (look, color, count, drift (logical px/s), sway (px), life (s), size)
AMBIENT = {
    "Meadow": [("mote", (255, 240, 150), 18, (7, -3), 8, 7.0, 1.8)],
    "Desert": [("speck", (252, 238, 205), 26, (70, 6), 4, 4.0, 1.5)],
    "Tundra": [("flake", WHITE, 40, (6, 22), 10, 9.0, 2.0)],
    "Volcano": [("ember", (255, 140, 50), 22, (4, -26), 9, 4.5, 1.5)],
    "Void": [("mote", (210, 160, 255), 20, (0, -4), 12, 8.0, 1.5)],
    "Swamp": [("firefly", (210, 240, 110), 12, (0, 0), 22, 8.0, 1.6)],
    "Coral Reef": [("bubble", (210, 250, 255), 16, (3, -20), 6, 6.0, 2.4)],
    "Autumn": [("leaf", (230, 120, 40), 9, (16, 18), 18, 8.0, 3.2), ("leaf", (200, 70, 35), 5, (16, 18), 18, 8.0, 3.0)],
    "Crystal Caves": [("glint", (220, 210, 255), 14, (0, 0), 2, 2.5, 4.0)],
    "Crimson Keep": [("ember", (255, 70, 50), 16, (6, -18), 10, 5.0, 1.3)],
    "Sakura": [("leaf", (255, 180, 205), 12, (14, 16), 16, 8.0, 2.6),
               ("leaf", (255, 238, 244), 5, (14, 16), 16, 8.0, 2.4)],
    "Jungle": [("firefly", (150, 255, 140), 12, (0, 0), 22, 8.0, 1.5)],
    "Salt Flats": [("speck", (175, 170, 160), 22, (55, 4), 4, 4.0, 1.5)],
    "Toxic Wastes": [("mote", (190, 255, 80), 18, (2, -14), 8, 6.0, 1.7)],
    "Midnight": [("firefly", (150, 190, 255), 12, (0, 0), 20, 8.0, 1.5)],
    "Badlands": [("speck", (230, 160, 110), 24, (60, 5), 4, 4.0, 1.5)],
    "Glacier": [("flake", (240, 250, 255), 30, (10, 26), 8, 8.0, 1.9)],
    "Ashlands": [("speck", (150, 145, 140), 22, (8, 14), 10, 7.0, 1.5),
                 ("ember", (255, 150, 50), 8, (4, -22), 8, 4.0, 1.3)],
    "Neon Grid": [("mote", (80, 245, 255), 18, (0, -18), 2, 5.0, 1.5)],
    "The Abyss": [("ember", (255, 205, 60), 14, (0, -10), 12, 7.0, 1.4)],
}
LEAF_TURNS = 8  # directions a falling leaf is drawn in
GLOWS = ("mote", "ember", "firefly", "glint")  # looks that are light: added onto the picture
LEVELS = 6  # brightness steps a light is drawn in (it can't be faded like the others)


def _dim(color, k):
    return tuple(round(c * k) for c in color)


def _light(cv, color, r, k, core=0.0):
    """A soft light of radius r, brightness k (0-1), on a light picture (black = no light); `core` adds a
    white-hot middle that big."""
    rings = 16
    for i in range(1, rings):
        f = i / rings  # 0 at the rim (no light) to 1 in the middle
        cv.circle(_dim(color, k * 0.6 * f * f), (0, 0), r * (1 - 0.9 * f))
    if core:
        cv.circle(_dim(mix(color, WHITE, 0.6), k), (0, 0), core)


def _paint_particle(cv, look, color, size, turn, k=1.0):
    if look in ("mote", "ember", "firefly"):
        halo = {"mote": 2.8, "ember": 2.2, "firefly": 4.0}[look]
        _light(cv, color, size * halo, k, size * 0.6)
    elif look == "flake":  # with a faint shadow, so it shows on snow too
        cv.circle((40, 60, 90, 70), (size * 0.5, size * 0.7), size)
        cv.circle((*color, 150), (0, 0), size)
        cv.circle(color, (0, 0), size * 0.65)
    elif look == "speck":
        cv.circle((*color, 200), (0, 0), size)
    elif look == "bubble":
        cv.circle((*color, 40), (0, 0), size)
        cv.circle((*color, 200), (0, 0), size, 0.6)
        cv.circle(WHITE, (-size * 0.35, -size * 0.35), size * 0.25)
    elif look == "leaf":
        f = V(1, 0).rotate(turn * 180 / LEAF_TURNS)  # a leaf looks the same turned half way round
        points = [f * size * math.cos(a) + f.rotate(90) * size * 0.45 * math.sin(a) * (1.2 if math.cos(a) > 0 else 0.8)
                  for a in (math.tau * i / 16 for i in range(16))]
        cv.polygon((40, 20, 20, 50), [p + V(1, 1.5) for p in points])
        cv.polygon(color, points)
        cv.polygon(shade(color, 0.8), points, 0.4)
        cv.line(shade(color, 0.7), -f * size * 0.8, f * size * 0.8, 0.5)
    elif look == "glint":
        _light(cv, color, size * 0.9, k * 0.6)
        for d in (V(1, 0), V(0, 1)):
            cv.polygon(_dim(color, k), [-d * size, d.rotate(90) * size * 0.14, d * size, -d.rotate(90) * size * 0.14])
        cv.circle(_dim(WHITE, k), (0, 0), size * 0.22)


def particle(look, color, size, turn, scale, level=LEVELS):
    """A particle's picture; lights (GLOWS) come in LEVELS brightness `level`s, the others fade with set_alpha."""
    def make():
        reach = size * (4.2 if look in ("mote", "ember", "firefly") else 1.2) + 2  # + 2: shadows
        cv = Canvas(2 * reach + 2, scale)
        _paint_particle(cv, look, color, size, turn, level / LEVELS)
        return cv.done()
    return sprites.cached(("particle", look, color, size, turn, scale, level), make)


def light(color, r, level, scale):
    """A soft light to add onto the picture (see GLOWS), `level` of LEVELS bright."""
    def make():
        cv = Canvas(2 * r, scale)
        _light(cv, color, r, level / LEVELS)
        return cv.done()
    return sprites.cached(("light", color, r, level, scale), make)


def _hash(n):
    """A repeatable number in [0, 1) for any number."""
    return math.sin(n * 12.9898 + 4.1414) * 43758.5453 % 1.0


def particles(theme, t):
    """(look, color, size, turn, center, alpha 0-1) of every particle at game time t."""
    out = []
    serial = 0
    for look, color, count, (vx, vy), sway, life, size in AMBIENT.get(theme.name, ()):
        for i in range(count):
            serial += 1
            n = serial * 7.31
            span = life * (0.75 + 0.5 * _hash(n + 1))
            lived = t + _hash(n + 2) * span
            cycle = math.floor(lived / span)
            age = lived - cycle * span
            seed = n + cycle * 131.7
            pace = 0.7 + 0.6 * _hash(n + 3)
            wobble = math.tau * _hash(n + 4)
            x = _hash(seed + 5) * MAP_W + vx * pace * age + sway * math.sin(age * 1.1 + wobble)
            y = _hash(seed + 6) * MAP_H + vy * pace * age + sway * 0.6 * math.cos(age * 0.8 + wobble)
            alpha = math.sin(math.pi * age / span)
            if look == "firefly":
                alpha *= max(0.0, math.sin(age * 2.2 + wobble)) ** 2
            elif look == "glint":
                alpha = alpha ** 3
            elif look == "ember":
                alpha *= 0.75 + 0.25 * math.sin(age * 9 + wobble)
            turn = int((age * 1.6 + wobble) * LEAF_TURNS / math.pi) % LEAF_TURNS if look == "leaf" else 0
            out.append((look, color, size, turn, V(x % MAP_W, y % MAP_H), alpha))
    return out


# --------------------------------------------------------------------------
# The pulse: soft light over what glows on some maps
# --------------------------------------------------------------------------
GLOWING = {"Volcano", "Ashlands", "Toxic Wastes", "Crystal Caves", "Neon Grid", "Void"}
PATH_GLOW = {"crust", "neon"}  # path styles with glowing cracks or edges: the light runs along them too
PULSE = 1.4  # radians per second


def glow_spots(theme, path_style, waypoints, accents):
    """(center, radius, phase) of the lights a map pulses with: its accent props, and every
    tile of the path when the path glows (a wave of light runs along it)."""
    if theme.name not in GLOWING:
        return []
    spots = [(V(p), 14, _hash(p.x * 3.1 + p.y) * math.tau) for p in accents]
    if path_style in PATH_GLOW:
        tiles = []
        for (x0, y0), (x1, y1) in zip(waypoints, waypoints[1:]):
            n = max(abs(x1 - x0), abs(y1 - y0))
            tiles += [(x0 + (x1 - x0) * i // n, y0 + (y1 - y0) * i // n) for i in range(n)]
        for k, (tx, ty) in enumerate(tiles):
            if 0 <= tx < COLS and 0 <= ty < ROWS:
                spots.append((V(tx * TILE + TILE / 2, ty * TILE + TILE / 2), 32, k * 0.25))
    return spots


# --------------------------------------------------------------------------
# The portal and the gate
# --------------------------------------------------------------------------
PORTAL_R = 17
PORTAL_ARMS = 3
PORTAL_STEPS = 24  # pictures in a third of a turn (the arms repeat after that)
PORTAL_SPIN = 50  # degrees per second
GATE_COLOR = (130, 210, 255)


def portal(color, step, scale):
    """A swirl with PORTAL_ARMS arms, turned `step` of PORTAL_STEPS through a third of a turn."""
    def make():
        cv = Canvas(2 * PORTAL_R + 6, scale)
        for i in range(10):
            k = i / 9
            fill = (*mix((12, 6, 20), color, 0.15 + 0.35 * k), round(200 + 55 * k))  # dark, lighter inward
            cv.circle(fill, (0, 0), PORTAL_R * (1 - 0.75 * k))
        turn = step * 360 / PORTAL_ARMS / PORTAL_STEPS
        for arm in range(PORTAL_ARMS):
            points = []
            for j in range(14):
                k = j / 13
                points.append(V(PORTAL_R * (0.15 + 0.85 * k), 0).rotate(turn + arm * 360 / PORTAL_ARMS + k * 200))
            for a, b, j in zip(points, points[1:], range(13)):
                cv.line((*mix(color, WHITE, 0.55 * (1 - j / 13)), round(255 - 10 * j)), a, b, 2.8 - j * 0.16)
        cv.circle((*mix(color, WHITE, 0.4), 220), (0, 0), PORTAL_R, 1.4)
        cv.circle((*shade(color, 0.15), 255), (0, 0), PORTAL_R * 0.18)
        return cv.done()
    return sprites.cached(("portal", color, step, scale), make)


def gate(across, scale):
    """Two posts either side of the path's end, `across` being the unit vector from one to the other,
    with a bar of light between them."""
    def make():
        cv = Canvas(TILE + 8, scale)
        f = V(across)
        half = TILE / 2 - 3
        cv.line((*GATE_COLOR, 70), -f * half, f * half, 7)
        cv.line((*GATE_COLOR, 150), -f * half, f * half, 3.5)
        cv.line(mix(GATE_COLOR, WHITE, 0.7), -f * half, f * half, 1.4)
        for side in (-1, 1):
            sprites.sphere(cv, (150, 150, 165), f * side * half, 4.5, 0.8)
            cv.circle(mix(GATE_COLOR, WHITE, 0.5), f * side * half + V(-1, -1), 1.3)
        return cv.done()
    return sprites.cached(("gate", tuple(across), scale), make)


def ends(waypoints):
    """((portal center, heading in), (gate center, heading out)): the first and last tiles on the map."""
    (a, b), (c, d) = waypoints[:2], waypoints[-2:]
    into, out = (V(b) - V(a)).normalize(), (V(d) - V(c)).normalize()
    first, last = V(a) + into, V(d) - out
    center = lambda tile: V(tile.x * TILE + TILE / 2, tile.y * TILE + TILE / 2)  # noqa: E731
    return (center(first), into), (center(last), out)


class Scenery:
    """One level's ambience: build it per level (it's cheap), draw it every frame."""

    def __init__(self, theme, path_style, waypoints, accents):
        self.theme = theme
        self.spots = glow_spots(theme, path_style, waypoints, accents)
        (self.portal_at, _), (self.gate_at, out) = ends(waypoints)
        self.gate_across = (round(-out.y), round(out.x))

    def draw_under(self, surf, t, scale, moving=True):
        """The pulse and the portal and gate: on the ground, under towers and enemies."""
        accent = self.theme.accent
        if moving:
            for center, r, phase in self.spots:
                level = round((0.45 + 0.35 * math.sin(t * PULSE + phase)) * LEVELS)
                if level:
                    img = light(accent, r, level, scale)
                    surf.blit(img, img.get_rect(center=(center.x * scale, center.y * scale)),
                              special_flags=pygame.BLEND_RGB_ADD)
        level = round((0.6 + 0.25 * math.sin(t * 3)) * LEVELS) if moving else LEVELS // 2
        img = light(accent, PORTAL_R + 10, level, scale)
        surf.blit(img, img.get_rect(center=(self.portal_at.x * scale, self.portal_at.y * scale)),
                  special_flags=pygame.BLEND_RGB_ADD)
        step = int(t * PORTAL_SPIN * PORTAL_ARMS * PORTAL_STEPS / 360) % PORTAL_STEPS if moving else 0
        for img, at in ((portal(accent, step, scale), self.portal_at), (gate(self.gate_across, scale), self.gate_at)):
            surf.blit(img, img.get_rect(center=(at.x * scale, at.y * scale)))

    def draw_over(self, surf, t, scale):
        """The particles: over everything on the map."""
        for look, color, size, turn, center, alpha in particles(self.theme, t):
            if look in GLOWS:
                level = round(alpha * LEVELS)
                if level:
                    img = particle(look, color, size, turn, scale, level)
                    surf.blit(img, img.get_rect(center=(center.x * scale, center.y * scale)),
                              special_flags=pygame.BLEND_RGB_ADD)
            else:
                img = particle(look, color, size, turn, scale)
                img.set_alpha(round(255 * alpha))
                surf.blit(img, img.get_rect(center=(center.x * scale, center.y * scale)))
