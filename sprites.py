"""Pictures drawn in code: towers, enemies, eyes, shells and muzzle flashes. Nothing is loaded from files.

Each picture is drawn once, SUPERSAMPLE times larger than it will be on screen, then smoothly shrunk
(that's the anti-aliasing) and kept for the display scale, so drawing a tower or an enemy during the
game is a blit or two. The light comes from the top left, like the shadows in graphics.py: round
things are lit spheres and flat shapes are faceted gems. Because of that, a picture that turns is
drawn separately for each of ANGLES directions instead of being rotated (that would turn the
lighting with it); directions are drawn the first time they're needed.

This module works in logical units and knows nothing of the layout: graphics.py says where things go.
"""

import math

import pygame

from monsters import ENEMY_TYPES

V = pygame.Vector2
SUPERSAMPLE = 4
ANGLES = 72  # directions a turning picture is drawn in (every 5 degrees)
LIGHT = V(-0.6, -0.8)  # toward the light
WHITE = (255, 255, 255)
GOLD = (255, 210, 70)
METAL = (70, 72, 84)
PLATE = (52, 54, 64)
ENEMY_SQUASH = (1.15, 0.88)  # an enemy just hit is drawn this much wider and flatter
PHASED_ALPHA = 0.35  # how solid a Phantom out of reach looks
ILLUSION_ALPHA = 0.55  # how solid a Mirage's illusion looks (paler too, so players can tell; towers can't)

_cache = {}


def clear():
    """Forget every picture (they're per display scale)."""
    _cache.clear()


def cached(key, make):
    """The picture stored under `key`, made with make() the first time."""
    img = _cache.get(key)
    if img is None:
        img = _cache[key] = make()
    return img


# --------------------------------------------------------------------------
# Colors and shapes
# --------------------------------------------------------------------------
def shade(color, k):
    return tuple(min(255, int(c * k)) for c in color)


def mix(a, b, k):
    """Color `a` moved a share `k` of the way to color `b`."""
    return tuple(round(x + (y - x) * k) for x, y in zip(a, b))


def regular_polygon(center, radius, sides, rotation=0.0):
    return [center + V(radius, 0).rotate(rotation + 360 * i / sides) for i in range(sides)]


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
        return [center + V(r if i % 2 == 0 else r * 0.5, 0).rotate(rot + 36 * i) for i in range(10)]
    raise ValueError(shape)


def angle_step(angle):
    """The nearest of the ANGLES directions to `angle` (degrees)."""
    return round(angle * ANGLES / 360) % ANGLES


def step_angle(step):
    return step * 360 / ANGLES


class Canvas:
    """A square picture `size` logical units wide, drawn SUPERSAMPLE times larger. Points are
    logical, relative to the picture's center; widths are logical too."""

    def __init__(self, size, scale):
        self.size = size
        self.scale = scale
        self.k = scale * SUPERSAMPLE
        side = math.ceil(size * self.k)
        self.surf = pygame.Surface((side, side), pygame.SRCALPHA)
        self.c = V(side / 2, side / 2)

    def p(self, point):
        return self.c + V(point) * self.k

    def w(self, width):
        return max(1, round(width * self.k)) if width else 0

    def circle(self, color, center, r, width=0):
        pygame.draw.circle(self.surf, color, self.p(center), r * self.k, self.w(width))

    def polygon(self, color, points, width=0):
        pygame.draw.polygon(self.surf, color, [self.p(pt) for pt in points], self.w(width))

    def line(self, color, a, b, width=1):
        pygame.draw.line(self.surf, color, self.p(a), self.p(b), self.w(width))

    def rect(self, color, rect, width=0, radius=0):
        x, y, w, h = rect
        r = pygame.Rect(self.p((x, y)), (w * self.k, h * self.k))
        pygame.draw.rect(self.surf, color, r, self.w(width), round(radius * self.k))

    def done(self, size=None):
        """The picture shrunk to screen size (`size` = (w, h) in logical units to stretch it)."""
        w, h = size or (self.size, self.size)
        return pygame.transform.smoothscale(self.surf, (max(1, round(w * self.scale)), max(1, round(h * self.scale))))


def sphere(cv, color, center, r, rim=1.0):
    """A lit ball: discs from the shadow color to a highlight, each smaller and nearer the light."""
    center = V(center)
    steps = max(4, min(16, round(r * cv.k / 3)))
    dark, light = shade(color, 0.55), mix(color, WHITE, 0.55)
    for i in range(steps):
        k = i / (steps - 1)
        cv.circle(mix(dark, light, k ** 1.6), center + LIGHT * r * k * 0.5, r * (1 - k * 0.82))
    if rim:
        cv.circle(shade(color, 0.35), center, r, rim)


def gem(cv, color, center, points, rim=1.0):
    """A faceted polygon: a triangle per side, from the center, shaded by which way it faces."""
    center = V(center)
    dark, light = shade(color, 0.6), mix(color, WHITE, 0.35)
    for a, b in zip(points, points[1:] + points[:1]):
        out = (a + b) / 2 - center
        lit = 0.5 + 0.5 * out.normalize().dot(LIGHT) if out.length_squared() else 0.5
        cv.polygon(mix(dark, light, lit), [center, a, b])
    if rim:
        cv.polygon(shade(color, 0.35), points, rim)
    r = max((p - center).length() for p in points)
    cv.circle(mix(color, WHITE, 0.85), center + LIGHT * r * 0.35, max(0.6, r * 0.09))


def layer(cv, shape, center, r, color, rot, rim=1.0):
    if shape == "circle":
        sphere(cv, color, center, r, rim)
    else:
        gem(cv, color, center, shape_points(shape, V(center), r, rot), rim)


def glow(color, r, scale):
    """A soft round light, brightest in the middle, for blending on top of things."""
    def make():
        cv = Canvas(2 * r, scale)
        for i in range(12):
            k = i / 11
            cv.circle((*color, round(14 + 30 * k)), (0, 0), r * (1 - 0.85 * k))
        return cv.done()
    return cached(("glow", color, r, scale), make)


# --------------------------------------------------------------------------
# Towers: a metal plate, a turret on it, the tier pips on top
# --------------------------------------------------------------------------
PLATE_HALF = 17  # half the plate's width: a tile less 3 units a side
TURRET_SIZE = 58  # room for the longest barrel either way


def tower_plate(tier, rim, scale, tile):
    """The base every tower stands on: bevelled, with bolts; the rim shows the tier."""
    def make():
        cv = Canvas(tile, scale)
        h = PLATE_HALF
        cv.rect(shade(rim, 0.6), (-h, -h + 1, 2 * h, 2 * h), radius=6)
        cv.rect(PLATE, (-h, -h, 2 * h, 2 * h), radius=6)
        cv.rect(shade(PLATE, 0.78), (-h + 1.5, -h + 1.5, 2 * h - 3, 2 * h - 3), radius=5)
        cv.line(mix(PLATE, WHITE, 0.25), (-h + 6, -h + 1), (h - 6, -h + 1), 1)
        cv.rect(rim, (-h, -h, 2 * h, 2 * h), 3 if tier == 4 else 2, radius=6)
        for x, y in ((-h + 5, -h + 5), (h - 5, -h + 5), (h - 5, h - 5)):  # the pips take the fourth corner
            cv.circle((25, 25, 30), (x, y), 1.6)
            cv.circle((120, 122, 135), (x - 0.4, y - 0.4), 0.9)
        return cv.done()
    return cached(("plate", tier, rim, scale), make)


def tower_pips(tier, scale, tile):
    """Gold studs along the plate's bottom left, one per tier."""
    def make():
        cv = Canvas(tile, scale)
        for i in range(tier):
            sphere(cv, GOLD, (-PLATE_HALF + 6 + i * 7, PLATE_HALF - 5), 2.2, rim=0.6)
        return cv.done()
    return cached(("pips", tier, scale), make)


def _barrel(cv, start, d, length, width):
    side = d.rotate(90)
    if side.dot(LIGHT) < 0:
        side = -side  # side faces the light: the shine goes there
    w = width / 2
    a, b = start, start + d * length
    body = [a + side * w, b + side * w, b - side * w, a - side * w]
    cv.polygon(METAL, body)
    cv.line(mix(METAL, WHITE, 0.45), a + side * w * 0.45, b + side * w * 0.45, max(0.6, width * 0.22))
    cv.polygon((25, 25, 32), body, 0.8)
    cv.circle((35, 35, 42), b, w * 1.2)
    cv.circle((12, 12, 16), b, w * 0.6)


def tower_turret(spec, step, scale):
    """A tower's barrels and layers, aimed at one of the ANGLES directions."""
    def make():
        cv = Canvas(TURRET_SIZE, scale)
        aim = step_angle(step)
        d = V(1, 0).rotate(aim)
        count, length, width = spec["look"]["barrels"]
        for i in range(count):
            _barrel(cv, d.rotate(90) * (i - (count - 1) / 2) * (width + 2), d, length, width)
        for shape, r, color in spec["look"]["layers"]:
            layer(cv, shape, (0, 0), r, color, aim, 1 if r < 8 else 1.5)
        return cv.done()
    return cached(("turret", spec["name"], step, scale), make)


def muzzle_flash(step, r, scale):
    """A burst of fire pointing along one of the ANGLES directions, longest forward."""
    def make():
        cv = Canvas(4 * r, scale)
        d = V(1, 0).rotate(step_angle(step))
        for k, color in ((1.0, (255, 170, 50)), (0.65, (255, 235, 150)), (0.3, WHITE)):
            pts = [d.rotate(a) * r * k * (1.9 if a == 0 else 1.0 if a % 90 == 0 else 0.6) for a in range(0, 360, 45)]
            cv.polygon(color, pts)
        return cv.done()
    return cached(("flash", step, r, scale), make)


# --------------------------------------------------------------------------
# Enemies: little creatures. Each keeps its type's color and outline (circle, triangle, square...) and
# faces where it's walking; its painter draws one animation frame of it facing `f` (a unit vector).
# --------------------------------------------------------------------------
FRAMES = 8  # frames in an animation cycle


def ellipse_points(center, f, length, width, n=28):
    """An ellipse `length` along f (half-axes), `width` across it."""
    s = f.rotate(90)
    return [center + f * length * math.cos(a) + s * width * math.sin(a) for a in (math.tau * i / n for i in range(n))]


def blob(cv, color, center, f, length, width, rim=1.0):
    """A lit egg shape: a sphere stretched along f."""
    center = V(center)
    steps = max(4, min(14, round(max(length, width) * cv.k / 3)))
    dark, light = shade(color, 0.55), mix(color, WHITE, 0.55)
    for i in range(steps):
        k = i / (steps - 1)
        shrink = 1 - k * 0.82
        cv.polygon(mix(dark, light, k ** 1.6), ellipse_points(center + LIGHT * max(length, width) * k * 0.5, f,
                                                              length * shrink, width * shrink, 20))
    if rim:
        cv.polygon(shade(color, 0.35), ellipse_points(center, f, length, width), rim)


def _spikes(cv, color, f, sides, r, length, rot=0.0):
    """A dark spike out of each corner of a regular polygon (drawn before the body covers their roots)."""
    for corner in regular_polygon(V(), r, sides, f.as_polar()[1] + rot):
        out = corner.normalize()
        across = out.rotate(90) * r * 0.2
        cv.polygon(shade(color, 0.55), [corner * 0.8 + across, corner * length, corner * 0.8 - across], 0)


def _feet(cv, color, f, p, size, spread=0.85, foot=0.38, stride=0.45):
    """Two feet stepping in turn, poking out either side."""
    s = f.rotate(90)
    for k in (-1, 1):
        swing = math.sin(math.tau * p + (k > 0) * math.pi) * stride * size
        blob(cv, shade(color, 0.42), f * swing + s * k * spread * size, f, foot * size, foot * 0.72 * size, 0.6)


def paint_walker(cv, size, color, inner, f, p):
    """Basic: a round walker on two stepping feet."""
    _feet(cv, color, f, p, size)
    sphere(cv, color, (0, 0), size, 1.5)


def paint_slime(cv, size, color, inner, f, p):
    """Swarmling: a slime, stretching and squashing as it creeps, leaving drips."""
    q = math.sin(math.tau * p)
    for back, r in ((1.3, 0.28), (1.75, 0.17)):
        cv.circle((*color, 110), -f * size * back, size * r)
    blob(cv, color, f * size * 0.08 * q, f, size * (1 + 0.16 * q), size * (1 - 0.12 * q), 1)


def paint_dart(cv, size, color, inner, f, p):
    """Fast: a dart on beating wings, with a streak behind."""
    s = f.rotate(90)
    for i in (3, 2, 1):
        cv.circle((*mix(color, WHITE, 0.5), 140 - 35 * i), -f * (size * 0.6 + i * 3.4), size * (0.36 - 0.07 * i))
    flap = math.sin(math.tau * p)
    for k in (-1, 1):
        cv.polygon((*mix(color, WHITE, 0.65), 185),
                   [f * size * 0.25, -f * size * (0.2 - 0.25 * flap) + s * k * size * (1.05 + 0.25 * flap),
                    -f * size * 0.75 + s * k * size * 0.3])
    gem(cv, color, (0, 0), regular_polygon(V(), size, 3, f.as_polar()[1]), 1.5)


def paint_beetle(cv, size, color, inner, f, p):
    """Tank: a beetle scuttling on six legs, with a split shell and a dark head."""
    s = f.rotate(90)
    leg = shade(color, 0.3)
    for i, along in enumerate((-0.45, 0.05, 0.5)):
        for k in (-1, 1):
            swing = math.sin(math.tau * p + i * 2.1 + (k > 0) * math.pi) * 0.35
            root = f * along * size + s * k * size * 0.55
            cv.line(leg, root, root + (s * k).rotate(k * swing * 55) * size * 0.62 + f * along * size * 0.25,
                    max(1.0, size * 0.11))
    sphere(cv, mix(color, (20, 25, 40), 0.55), f * size * 0.95, size * 0.4, 1)
    shell = [f * x * size + s * y * size for x, y in ((0.75, 0), (0.6, 0.8), (-0.8, 0.78), (-1.05, 0),
                                                      (-0.8, -0.78), (0.6, -0.8))]
    gem(cv, color, -f * size * 0.1, shell, 1.5)
    cv.line(shade(color, 0.4), f * size * 0.6, -f * size * 1.0, 0.9)


def paint_tortoise(cv, size, color, inner, f, p):
    """Armored: a plated tortoise on four stubby legs; its plate is the type's inner square, riveted."""
    s = f.rotate(90)
    for i, (x, y) in enumerate(((0.6, 0.62), (-0.6, 0.62), (0.6, -0.62), (-0.6, -0.62))):
        step = math.sin(math.tau * p + (i in (1, 2)) * math.pi) * 0.15
        blob(cv, mix(color, (40, 40, 48), 0.5), f * (x + step) * size + s * y * size, f, size * 0.3, size * 0.24, 0.6)
    sphere(cv, mix(color, (95, 95, 105), 0.4), f * size * 1.0, size * 0.36, 1)
    a = f.as_polar()[1]
    gem(cv, color, (0, 0), regular_polygon(V(), size, 4, a + 45), 1.5)
    gem(cv, inner, (0, 0), regular_polygon(V(), size * 0.5, 4, a + 45), 1)
    for corner in regular_polygon(V(), size * 0.72, 4, a):
        cv.circle(mix(color, WHITE, 0.5), corner, max(0.6, size * 0.07))


def paint_jelly(cv, size, color, inner, f, p):
    """Healer: a floating jelly trailing tentacles, its healing aura pulsing, a white gem inside."""
    s = f.rotate(90)
    pulse = 0.5 + 0.5 * math.sin(math.tau * p)
    cv.circle((*mix(color, WHITE, 0.4), round(70 + 80 * pulse)), (0, 0), size + 2.5 + 2 * pulse, 1.2)
    for j in range(4):
        across = (j - 1.5) * 0.36 * size
        pts = [-f * (0.55 + t * 0.26) * size + s * (across + math.sin(math.tau * p + t * 0.9 + j) * 0.17 * size)
               for t in range(6)]
        for a, b in zip(pts, pts[1:]):
            cv.line(shade(color, 0.7), a, b, max(0.8, size * 0.09))
    sphere(cv, color, (0, 0), size, 1.5)
    gem(cv, inner, -f * size * 0.3, regular_polygon(-f * size * 0.3, size * (0.36 + 0.05 * pulse), 4,
                                                    f.as_polar()[1]), 0.8)


def paint_cell(cv, size, color, inner, f, p):
    """Splitter: a wobbling cell with a glowing crack where it will split."""
    s = f.rotate(90)
    wob = math.sin(math.tau * p)
    gem(cv, color, (0, 0), regular_polygon(V(), size * (1 + 0.05 * wob), 5, f.as_polar()[1]), 1.5)
    crack = [-f * size * (0.15 + (0.14 if i % 2 else -0.06)) + s * size * (-0.8 + i * 0.32) for i in range(6)]
    glow_k = 0.55 + 0.35 * (0.5 + 0.5 * wob)
    for a, b in zip(crack, crack[1:]):
        cv.line(shade(color, 0.45), a, b, max(1.0, size * 0.14))
        cv.line(mix(color, WHITE, glow_k), a, b, max(0.6, size * 0.06))


def paint_ghost(cv, size, color, inner, f, p):
    """Phantom: a ghost with a rippling tail."""
    s = f.rotate(90)
    edge = []
    for t in range(7):
        x = (0.2 - t * 0.3) * size
        w = 0.85 * size * (1 - t / 7.5)
        edge.append((x, w, math.sin(math.tau * p + t * 1.1) * 0.16 * size))
    tail = [f * x + s * (w + wave) for x, w, wave in edge] + [f * x + s * (-w + wave) for x, w, wave in reversed(edge)]
    cv.polygon(shade(color, 0.8), tail)
    cv.polygon(shade(color, 0.45), tail, 1)
    blob(cv, color, f * size * 0.2, f, size * 0.8, size * 0.85, 1.2)


def paint_champion(cv, size, color, inner, f, p):
    """Elite: a spiked champion on heavy feet."""
    _feet(cv, color, f, p, size, spread=0.7, foot=0.3, stride=0.35)
    _spikes(cv, color, f, 6, size, 1.25 + 0.05 * math.sin(math.tau * p))
    gem(cv, color, (0, 0), regular_polygon(V(), size, 6, f.as_polar()[1]), 1.5)
    gem(cv, GOLD, f * size * 0.62, regular_polygon(f * size * 0.62, size * 0.2, 3, f.as_polar()[1]), 0.8)


def paint_golem(cv, size, color, inner, f, p):
    """Juggernaut: a rock golem swinging its fists, a dark stone core in its chest."""
    s = f.rotate(90)
    a = f.as_polar()[1]
    for k in (-1, 1):
        swing = math.sin(math.tau * p + (k > 0) * math.pi) * 0.35 * size
        fist = f * (0.25 * size + swing) + s * k * size * 1.0
        gem(cv, shade(color, 0.85), fist, regular_polygon(fist, size * 0.38, 8, a + 22.5), 1)
    gem(cv, color, (0, 0), regular_polygon(V(), size, 8, a + 22.5), 1.5)
    gem(cv, inner, -f * size * 0.1, regular_polygon(-f * size * 0.1, size * 0.45, 8, a + 22.5), 1)
    for x, y, dx, dy in ((-0.5, 0.55, -0.2, 0.25), (0.15, -0.65, 0.3, -0.15)):
        cv.line(shade(color, 0.5), f * x * size + s * y * size, f * (x + dx) * size + s * (y + dy) * size, 0.9)


IRON = (62, 60, 70)
BONE = (228, 214, 186)
RUBY = (220, 40, 60)


def paint_sentinel(cv, size, color, inner, f, p):
    """Warded: a squat copper sentinel on two feet, a blue ward crystal set in its chest and a little
    emitter on its brow that keeps the ward up."""
    s = f.rotate(90)
    a = f.as_polar()[1]
    _feet(cv, color, f, p, size, spread=0.72, foot=0.34, stride=0.4)
    for k in (-1, 1):  # shoulder plates
        pad = s * k * size * 0.78 - f * size * 0.1
        gem(cv, shade(color, 0.8), pad, regular_polygon(pad, size * 0.36, 6, a), 1)
    gem(cv, color, (0, 0), regular_polygon(V(), size, 6, a), 1.5)
    gem(cv, inner, -f * size * 0.12, regular_polygon(-f * size * 0.12, size * 0.42, 6, a + 30), 1)
    cv.circle(mix(inner, WHITE, 0.6), -f * size * 0.12 + LIGHT * size * 0.12, max(0.8, size * 0.1))
    emitter = f * size * 0.78
    gem(cv, mix(inner, WHITE, 0.25), emitter, regular_polygon(emitter, size * 0.2, 4, a + 45), 0.8)


def paint_mage(cv, size, color, inner, f, p):
    """Mirage: a hooded caster floating in a robe whose hem ripples behind it, holding out a crystal that
    pulses as it casts, with two motes circling it."""
    s = f.rotate(90)
    # the cloak: from the shoulders back to a hem that ripples across its width
    hem = [-f * size * (1.05 + 0.13 * math.sin(math.tau * p + i * 1.3)) + s * size * (0.8 - i * 0.32)
           for i in range(6)]
    cloak = [f * size * 0.1 + s * size * 0.62, *hem, f * size * 0.1 - s * size * 0.62]
    cv.polygon(shade(color, 0.55), cloak)
    cv.polygon(shade(color, 0.72), [f * size * 0.05 + s * size * 0.4, *[h * 0.8 for h in hem[1:-1]],
                                    f * size * 0.05 - s * size * 0.4])
    cv.polygon(shade(color, 0.35), cloak, 1)
    blob(cv, color, -f * size * 0.1, f, size * 0.8, size * 0.74, 1.5)
    sphere(cv, shade(color, 0.85), f * size * 0.28, size * 0.52, 1)
    pulse = 0.5 + 0.5 * math.sin(math.tau * p)
    focus = f * size * 0.95
    cv.circle((*mix(inner, WHITE, 0.3), round(90 + 100 * pulse)), focus, size * (0.34 + 0.12 * pulse))
    gem(cv, inner, focus, regular_polygon(focus, size * 0.24, 4, f.as_polar()[1]), 0.8)
    for k in range(2):
        mote = focus + V(size * 0.5, 0).rotate(360 * p + k * 180)
        cv.circle(mix(inner, WHITE, 0.5), mote, max(0.6, size * 0.08))


def paint_icicle(cv, size, color, inner, f, p):
    """Thawling: a chunk of ice scuttling on stubby feet, icicles down its back, a warm ember glowing
    through its middle (what thaws it), and a drip falling now and then."""
    s = f.rotate(90)
    a = f.as_polar()[1]
    _feet(cv, mix(color, (60, 90, 120), 0.4), f, p, size, spread=0.7, foot=0.3, stride=0.4)
    for k in (-1, 0, 1):  # icicles pointing back
        root = -f * size * 0.55 + s * k * size * 0.42
        tip = root - f * size * (0.75 - 0.2 * abs(k)) + s * k * size * 0.12
        cv.polygon(mix(color, WHITE, 0.4), [root + s * size * 0.16, tip, root - s * size * 0.16])
        cv.polygon(shade(color, 0.6), [root + s * size * 0.16, tip, root - s * size * 0.16], 0.7)
    gem(cv, color, (0, 0), regular_polygon(V(), size, 5, a), 1.5)
    core = -f * size * 0.1
    cv.circle((*mix(inner, WHITE, 0.2), 120), core, size * 0.5)
    cv.circle((*mix(inner, WHITE, 0.35), 200), core, size * 0.36)
    sphere(cv, mix(inner, (255, 230, 120), 0.4), core, size * 0.24, 0)
    for i, corner in enumerate(regular_polygon(V(), size * 0.72, 5, a + 36)):  # frost facets
        cv.line(mix(color, WHITE, 0.7), corner * 0.55, corner, max(0.6, size * 0.06))
    drip = (p * 2) % 1
    if drip < 0.6:
        cv.circle((*mix(color, WHITE, 0.3), 200), s * size * 0.75 - f * size * (0.2 + drip * 0.6), max(0.7, size * 0.1))


SABOTEUR_ANTENNA = (-1.05, 0.62)  # where a Saboteur's antenna tip is, in sizes back along and across it


def paint_saboteur(cv, size, color, inner, f, p):
    """Saboteur: a sneaking creature on quick feet, a hazard-striped charge strapped to its back and an
    antenna on the charge (graphics.py blinks its light)."""
    s = f.rotate(90)
    a = f.as_polar()[1]
    _feet(cv, color, f, p, size, spread=0.8, foot=0.32, stride=0.5)
    sphere(cv, color, (0, 0), size, 1.5)
    pack = -f * size * 0.42
    corners = [pack + (f * x + s * y) * size for x, y in ((0.35, 0.55), (-0.45, 0.55), (-0.45, -0.55), (0.35, -0.55))]
    cv.polygon(inner, corners)
    for i in range(4):  # black hazard stripes, slanted
        x0 = 0.35 - i * 0.22
        stripe = [pack + (f * x + s * y) * size for x, y in ((x0, 0.55), (x0 - 0.1, 0.55), (x0 - 0.3, -0.55), (x0 - 0.2, -0.55))]
        stripe = [pack + (pt - pack) for pt in stripe]
        cv.polygon((40, 38, 30), stripe)
    cv.polygon((40, 38, 30), corners, 1)
    cv.line((150, 150, 150), (corners[0] + corners[3]) / 2 + f * size * 0.05, (corners[1] + corners[2]) / 2,
            max(0.6, size * 0.08))  # the strap
    root = -f * size * 0.6 + s * size * 0.35
    tip = f * size * SABOTEUR_ANTENNA[0] + s * size * SABOTEUR_ANTENNA[1]
    cv.line((60, 60, 60), root, tip, max(0.6, size * 0.08))
    cv.circle((90, 20, 20), tip, max(0.8, size * 0.13))


def paint_looter(cv, size, color, inner, f, p):
    """Looter: a quick thief in a bandit mask, its tails fluttering, a bulging sack of gold over its back."""
    s = f.rotate(90)
    _feet(cv, color, f, p, size, spread=0.75, foot=0.3, stride=0.6)
    sack = -f * size * 0.95 + s * size * 0.15
    blob(cv, mix(inner, (200, 140, 40), 0.25), sack, f, size * 0.72, size * 0.82, 1)
    for k, (x, y) in enumerate(((-0.25, 0.3), (0.05, -0.2), (-0.45, -0.1))):  # coins peeking out
        coin = sack + (f * x + s * y) * size
        cv.circle(shade(inner, 0.6), coin, size * 0.24)
        cv.circle(mix(inner, WHITE, 0.35), coin, size * 0.19)
    sphere(cv, color, (0, 0), size, 1.5)
    knot = -f * size * 0.3 + s * size * 0.15
    cv.line((120, 85, 40), knot, sack + f * size * 0.5, max(0.8, size * 0.16))  # the sack's neck
    mask = (30, 24, 36)
    xs = [0.08 + 0.64 * i / 6 for i in range(7)]  # a band round the head, following its curve
    band = [f * size * x + s * size * 1.03 * math.sqrt(1 - x * x) for x in xs] + \
        [f * size * x - s * size * 1.03 * math.sqrt(1 - x * x) for x in reversed(xs)]
    cv.polygon(mask, band)
    flutter = math.sin(math.tau * p) * 0.15
    for k in (-1, 1):  # the mask's tails, streaming behind
        root = f * size * 0.35 + s * k * size * 0.92
        cv.polygon(mask, [root, root - f * size * 0.75 + s * k * size * (0.35 + flutter * k),
                          root - f * size * 0.55 + s * k * size * (0.05 + flutter * k)])


def paint_bearer(cv, size, color, inner, f, p):
    """Banner Bearer: a stout walker holding up a pole, its red pennant (gold-trimmed) streaming back and
    rippling as it marches."""
    s = f.rotate(90)
    _feet(cv, color, f, p, size, spread=0.8, foot=0.36, stride=0.42)
    sphere(cv, color, (0, 0), size, 1.5)
    top = s * size * 0.7 + f * size * 0.15  # the pole, seen from above: a short shaft ending in a finial
    cv.line((90, 60, 35), s * size * 0.45, top, max(1.0, size * 0.16))
    flag = []
    for i in range(7):
        t = i / 6
        wave = math.sin(math.tau * p + t * 3.2) * 0.3 * size * t
        flag.append(top - f * size * 2.0 * t + s * wave)
    lower = [pt + s * size * 1.0 * (1 - 0.6 * t) for pt, t in zip(flag, (i / 6 for i in range(7)))]
    pennant = flag + lower[::-1]
    cv.polygon(inner, pennant)
    cv.polygon(mix(inner, WHITE, 0.25), flag[:4] + [lower[3], lower[0]])
    cv.polygon(GOLD, pennant, max(0.6, size * 0.08))
    cv.circle(GOLD, top, max(1.0, size * 0.17))


def rally_ring(radius, scale):
    """The reach of a Banner Bearer's aura: a faint gold disc with a dashed rim."""
    def make():
        cv = Canvas(2 * radius + 4, scale)
        cv.circle((255, 200, 80, 34), (0, 0), radius)
        for i in range(24):
            if i % 2 == 0:
                a, b = V(radius, 0).rotate(i * 15), V(radius, 0).rotate(i * 15 + 12)
                cv.line((255, 215, 110, 190), a, b, 1.6)
        return cv.done()
    return cached(("rally", radius, scale), make)


def paint_brood(cv, size, color, inner, f, p):
    """The Brood Mother: a huge brood queen creeping on eight jointed, clawed legs. A ridged, spiny carapace;
    a head crowned with horns, curved mandibles and a cluster of small red eyes; and behind, a swollen,
    see-through egg sac whose eggs glow and swell in turn."""
    s = f.rotate(90)
    dark, leg = shade(color, 0.5), shade(color, 0.32)
    for i, along in enumerate((0.5, 0.2, -0.1, -0.4)):  # legs: thigh, shin, claw
        for k in (-1, 1):
            swing = math.sin(math.tau * p + i * 1.6 + (k > 0) * math.pi) * 0.28
            root = f * along * size + s * k * size * 0.5
            knee = root + (s * k).rotate(k * (swing * 40 - 30 + i * 18)) * size * 0.62
            foot = knee + (s * k).rotate(k * (swing * 40 + 30 + i * 18)) * size * 0.5
            claw = foot + (foot - knee).normalize().rotate(k * 35) * size * 0.14
            cv.line(leg, root, knee, max(1.2, size * 0.1))
            cv.line(leg, knee, foot, max(1.0, size * 0.075))
            cv.line(shade(color, 0.2), foot, claw, max(0.8, size * 0.05))
            cv.circle(dark, knee, max(0.8, size * 0.06))
    sac = -f * size * 0.75  # the egg sac, swollen and see-through
    blob(cv, mix(color, inner, 0.35), sac, f, size * 0.72, size * 0.7, 1.2)
    cv.polygon((*mix(inner, WHITE, 0.4), 60), ellipse_points(sac, f, size * 0.62, size * 0.6))
    for i, (x, y) in enumerate(((0.0, 0.0), (0.25, 0.32), (0.25, -0.32), (-0.28, 0.25), (-0.28, -0.25),
                                (0.42, 0.0), (-0.48, 0.0), (0.05, 0.5), (0.05, -0.5))):
        swell = 1 + 0.18 * math.sin(math.tau * p + i * 0.9)
        egg = sac + (f * x + s * y) * size
        cv.circle((*mix(inner, WHITE, 0.3), 70), egg, size * 0.15 * swell)
        sphere(cv, inner, egg, size * 0.1 * swell, 0.5)
    shell = [f * size * x + s * size * y for x, y in ((0.55, 0), (0.42, 0.5), (0.0, 0.62), (-0.35, 0.5), (-0.45, 0),
                                                      (-0.35, -0.5), (0.0, -0.62), (0.42, -0.5))]
    gem(cv, color, f * size * 0.05, shell, 1.5)
    for x in (0.28, 0.0, -0.28):  # ridges and spines down the carapace
        cv.line(dark, f * size * x + s * size * 0.45, f * size * x - s * size * 0.45, max(0.8, size * 0.05))
        spine = f * size * x
        cv.polygon(shade(color, 0.35), [spine + s * size * 0.07, spine - f * size * 0.2, spine - s * size * 0.07])
    head = f * size * 0.78
    clack = 0.5 + 0.5 * math.sin(math.tau * p * 2)  # the mandibles open and snap shut as she walks
    for k in (-1, 1):  # mandibles, then horns
        root = head + f * size * 0.2 + s * k * size * 0.16
        _tapered(cv, shade(color, 0.6), root, root + f * size * 0.32 + s * k * size * (0.18 + 0.1 * clack),
                 root + f * size * 0.36 - s * k * size * (0.08 - 0.14 * clack), size * 0.07)
    sphere(cv, shade(color, 0.85), head, size * 0.33, 1.2)
    for k, spread in ((-1, 1.0), (1, 1.0), (-1, 0.45), (1, 0.45)):  # a crown of horns, sweeping back
        root = head - f * size * 0.24 + s * k * size * 0.12 * spread
        _tapered(cv, (230, 225, 190), root, root - f * size * 0.2 + s * k * size * 0.3 * spread,
                 root - f * size * 0.5 + s * k * size * 0.42 * spread, size * 0.065)
    for k in (-1, 1):  # the small red eyes, beside the big pair graphics.py draws
        for j, (x, y) in enumerate(((0.16, 0.3), (0.0, 0.33))):
            cv.circle((230, 40, 40), head + f * size * x + s * k * size * y, max(0.7, size * (0.045 - j * 0.01)))


def paint_spiderling(cv, size, color, inner, f, p):
    """Spiderling: one of the Brood Mother's young, skittering on eight quick legs, a pale spot on its back."""
    s = f.rotate(90)
    for i, along in enumerate((0.45, 0.15, -0.15, -0.45)):
        for k in (-1, 1):
            swing = math.sin(math.tau * p + i * 1.7 + (k > 0) * math.pi) * 0.4
            root = f * along * size + s * k * size * 0.4
            knee = root + (s * k).rotate(k * (swing * 45 - 25 + i * 16)) * size * 0.7
            foot = knee + (s * k).rotate(k * (swing * 45 + 40 + i * 16)) * size * 0.55
            cv.line(shade(color, 0.35), root, knee, max(0.7, size * 0.12))
            cv.line(shade(color, 0.35), knee, foot, max(0.6, size * 0.1))
    blob(cv, color, -f * size * 0.3, f, size * 0.75, size * 0.65, 1)
    sphere(cv, shade(color, 0.85), f * size * 0.5, size * 0.45, 0.8)
    cv.circle(inner, -f * size * 0.35, max(0.6, size * 0.22))


def maw(size, step, gape, scale):
    """The Brood Mother's maw, facing one of the ANGLES directions: `gape` 0 is shut (a grim line of fangs),
    up to 2, wide open in a shriek."""
    def make():
        cv = Canvas(size * 0.9, scale)
        f = V(1, 0).rotate(step_angle(step))
        s = f.rotate(90)
        w, h = size * 0.2, size * (0.03 + 0.07 * gape)
        mouth = ellipse_points(V(), f, h, w, 16)
        cv.polygon((40, 8, 12), mouth)
        if gape:
            cv.polygon((200, 60, 40), ellipse_points(-f * h * 0.2, f, h * 0.5, w * 0.6, 12))  # its throat
        for k in (-1, 1):  # two fangs, longer as it gapes
            root = s * k * w * 0.45 - f * h * 0.6
            cv.polygon((245, 240, 220), [root + s * size * 0.035, root - s * size * 0.035,
                                         root + f * size * (0.08 + 0.05 * gape)])
        return cv.done()
    return cached(("maw", size, step, gape, scale), make)


def steam_puff(r, scale):
    """A soft white puff of steam (a Thawling sprinting off its thaw)."""
    def make():
        cv = Canvas(2 * r + 2, scale)
        for i in range(8):
            k = i / 7
            cv.circle((235, 245, 255, round(40 + 150 * k)), LIGHT * r * 0.25 * k, r * (1 - 0.7 * k))
        return cv.done()
    return cached(("steam", r, scale), make)


def rage_aura(size, frame, scale):
    """A Berserker's rage: a hot red glow with flame tongues licking out, one of FRAMES flickers."""
    def make():
        r = size + 10
        cv = Canvas(2 * r + 4, scale)
        for i in range(10):
            k = i / 9
            cv.circle((255, round(60 + 120 * k), 30, round(40 + 90 * k)), (0, 0), r * (1 - 0.6 * k))
        for j in range(9):
            a = j * 40 + frame * 13
            length = r * (0.95 + 0.2 * math.sin(frame * 1.7 + j * 2.3))
            base = V(size * 0.85, 0).rotate(a)
            cv.polygon((255, 140, 40, 150), [base.rotate(-9), V(length, 0).rotate(a + 6), base.rotate(9)])
        return cv.done()
    return cached(("rage", size, frame, scale), make)


def ward_bubble(size, scale):
    """The hexagonal ward a Warded keeps up around itself: see-through, with a bright rim and a glint."""
    def make():
        r = size + 6
        cv = Canvas(2 * r + 4, scale)
        hexagon = regular_polygon(V(), r, 6, 30)
        cv.polygon((120, 190, 255, 64), hexagon)
        cv.polygon((120, 190, 255, 70), regular_polygon(V(), r * 0.82, 6, 30), 1.2)
        cv.polygon((200, 235, 255, 235), hexagon, 1.8)
        glint = [V(-0.55, -0.62) * r, V(-0.12, -0.84) * r, V(-0.2, -0.7) * r, V(-0.62, -0.46) * r]
        cv.polygon((235, 248, 255, 170), glint)
        return cv.done()
    return cached(("ward", size, scale), make)


def _tapered(cv, color, base, mid, tip, width, rim=0.8):
    """A curved horn or claw: a quadratic curve from base through mid to tip, thinning to a point."""
    n = 8
    pts = [base * (1 - t) ** 2 + mid * 2 * t * (1 - t) + tip * t * t for t in (i / n for i in range(n + 1))]
    left, right = [], []
    for i, pt in enumerate(pts):
        ahead = (pts[min(i + 1, n)] - pts[max(i - 1, 0)]).normalize()
        w = width * (1 - i / n) ** 0.8
        left.append(pt + ahead.rotate(90) * w)
        right.append(pt - ahead.rotate(90) * w)
    outline = left + right[::-1]
    cv.polygon(shade(color, 0.7), outline)
    cv.polygon(mix(color, WHITE, 0.3), left[: n // 2 + 1] + [pts[n // 2]] + pts[n // 2::-1][1:])  # lit half
    cv.polygon(shade(color, 0.4), outline, rim)


def paint_brute(cv, size, color, inner, f, p):
    """Berserker: a hunched brute on heavy feet, two horns curling forward, a war-paint chevron on its back."""
    s = f.rotate(90)
    _feet(cv, color, f, p, size, spread=0.75, foot=0.36, stride=0.5)
    for k in (-1, 1):
        root = f * size * 0.35 + s * k * size * 0.62
        _tapered(cv, (235, 225, 200), root, root + s * k * size * 0.55 + f * size * 0.15,
                 root + s * k * size * 0.35 + f * size * 0.75, size * 0.2)
    sphere(cv, color, (0, 0), size, 1.5)
    mane = []  # a dark spiky ridge down its back
    for i in range(7):
        t = i / 6
        width = size * 0.42 * math.sin(math.pi * (0.15 + 0.7 * t))
        tip = 0.22 * size if i % 2 else 0
        mane.append((-f * size * (0.05 + 0.85 * t), width + tip))
    ridge = [c + s * w for c, w in mane] + [c - s * w for c, w in reversed(mane)]
    cv.polygon(shade(color, 0.55), ridge)
    cv.polygon(shade(color, 0.35), ridge, 1)
    cv.circle(inner, f * size * 0.62 + s * size * 0.0, max(0.8, size * 0.1))  # a hot glint between the horns


def _chain(cv, start, end, sag, size):
    """Iron links from start to end, sagging sideways by `sag`, ending in a ball."""
    along = (end - start).normalize()
    links = 6
    for i in range(links):
        t = (i + 0.5) / links
        c = start.lerp(end, t) + along.rotate(90) * sag * math.sin(math.pi * t)
        long_, wide = (size * 0.1, size * 0.06) if i % 2 == 0 else (size * 0.07, size * 0.035)
        cv.polygon(shade(IRON, 0.6), ellipse_points(c, along, long_, wide, 12))
        cv.polygon(mix(IRON, WHITE, 0.35), ellipse_points(c, along, long_, wide, 12), 0.7)
    sphere(cv, IRON, end + along * size * 0.12, size * 0.2, 1)


def paint_warden(cv, size, color, inner, f, p):
    """The Warden, the jailer: chains with iron balls dragging behind, horns, spiked shoulder plates, a
    riveted dome and a glowing visor slit; its boots kick up dust where they land."""
    s = f.rotate(90)
    a = f.as_polar()[1]
    swing = math.sin(math.tau * p)
    for k in (-1, 1):
        sway = math.sin(math.tau * p + k) * 0.1 * size
        _chain(cv, -f * size * 0.55 + s * k * size * 0.45, -f * size * 1.55 + s * k * size * 0.62 + s * sway,
               sway * 0.6, size)
    for k in (-1, 1):  # boots, with dust as each one lands at the front of its stride
        out = math.sin(math.tau * p + (k > 0) * math.pi)
        boot = f * out * 0.3 * size + s * k * 0.62 * size
        if out > 0.85:
            for j in range(5):
                puff = boot + V(size * 0.32, 0).rotate(a + j * 72 + 20) * (1 + (out - 0.85) * 3)
                cv.circle((205, 195, 175, 120), puff, size * 0.09)
        blob(cv, shade(IRON, 0.8), boot + f * size * 0.08, f, size * 0.3, size * 0.2, 0.8)
    for k in (-1, 1):
        _tapered(cv, BONE, f * size * 0.45 + s * k * size * 0.4, f * size * 0.95 + s * k * size * 0.85,
                 f * size * 1.35 + s * k * size * 0.6, size * 0.13)
    gem(cv, color, (0, 0), regular_polygon(V(), size, 8, a + 22.5), 2)
    for corner in regular_polygon(V(), size * 0.86, 8, a + 22.5):
        cv.circle(shade(color, 0.4), corner, size * 0.06)
        cv.circle(mix(color, WHITE, 0.55), corner + LIGHT * size * 0.015, size * 0.035)
    gem(cv, mix(color, WHITE, 0.08), (0, 0), regular_polygon(V(), size * 0.62, 8, a + 22.5), 1.2)
    for k in (-1, 1):  # shoulder plates, rising and falling with the stride
        c = s * k * size * 0.78 + f * size * 0.04 * swing * k
        arc = [c + (s * k).rotate(t) * size * 0.34 for t in range(-90, 91, 30)]
        for t in (-45, 0, 45):
            d = (s * k).rotate(t)
            cv.polygon(shade(IRON, 0.7), [c + d.rotate(90) * size * 0.07 + d * size * 0.3,
                                          c + d * size * 0.5, c - d.rotate(90) * size * 0.07 + d * size * 0.3])
        gem(cv, shade(color, 0.85), c, arc, 1.2)
    slit = [f * size * x + s * size * y for x, y in ((0.52, 0.42), (0.34, 0.46), (0.34, -0.46), (0.52, -0.42))]
    cv.polygon(inner, slit)
    cv.polygon(shade(inner, 0.5), slit, 1)
    glow = [f * size * x + s * size * y for x, y in ((0.47, 0.34), (0.39, 0.36), (0.39, -0.36), (0.47, -0.34))]
    cv.polygon((255, 90, 40), glow)


def paint_overlord(cv, size, color, inner, f, p):
    """The Overlord's body, a spinning golden star (its spin is `f`), two layers deep, with a ruby in each
    point. Its face, crown and corona are drawn separately (overlord_face, overlord_corona) so they can
    turn on their own."""
    a = f.as_polar()[1]
    gem(cv, color, (0, 0), shape_points("star", V(), size, a), 2)
    gem(cv, mix(color, WHITE, 0.25), (0, 0), shape_points("star", V(), size * 0.62, a + 36), 1)
    for tip in shape_points("star", V(), size * 0.74, a)[::2]:
        gem(cv, RUBY, tip, regular_polygon(tip, size * 0.08, 4, a), 0.7)


def overlord_face(cv, size, color, inner, f):
    """A dark head that keeps looking where the Overlord goes, a ruby-set crown round the back of it."""
    back = -f
    cv.circle(shade(inner, 0.8), (0, 0), size * 0.56)
    for t in (-80, -40, 0, 40, 80):  # the crown's points
        d = back.rotate(t)
        tip = d * size * (0.86 if t == 0 else 0.76)
        cv.polygon(shade(GOLD, 0.45), [d.rotate(13) * size * 0.5, tip, d.rotate(-13) * size * 0.5])
        gem(cv, GOLD, d * size * 0.58, [d.rotate(11) * size * 0.5, tip * 0.97, d.rotate(-11) * size * 0.5], 0)
    band = [back.rotate(t) * size * 0.58 for t in range(-100, 101, 10)]
    band += [back.rotate(t) * size * 0.45 for t in range(100, -101, -10)]
    cv.polygon(mix(GOLD, WHITE, 0.15), band)
    cv.polygon(shade(GOLD, 0.45), band, 0.8)
    for t in (-60, 0, 60):
        c = back.rotate(t) * size * 0.515
        gem(cv, RUBY, c, regular_polygon(c, size * 0.06, 4, f.as_polar()[1] + t), 0.5)
    gem(cv, inner, (0, 0), regular_polygon(V(), size * 0.38, 6, f.as_polar()[1] + 30), 1.2)


def overlord_corona(cv, size, color, f):
    """A ring of light rays round the Overlord, turned by `f`."""
    a = f.as_polar()[1]
    light = mix(color, WHITE, 0.5)
    cv.circle((*light, 70), (0, 0), size * 1.18, 1.2)
    for i in range(12):
        d = V(1, 0).rotate(a + i * 30)
        long_ = 1.42 if i % 2 == 0 else 1.3
        cv.polygon((*light, 150 if i % 2 == 0 else 100),
                   [d.rotate(4) * size * 1.08, d * size * long_, d.rotate(-4) * size * 1.08])


# kind -> how it's drawn and animated:
#   paint     the painter
#   clock     "walk": the animation follows the distance walked (one cycle per `stride` sizes walked),
#             "time": it plays at `rate` cycles a second
#   move      "hop" (bounces as it walks), "hover" (bobs in the air) or None
#   eyes      (forward, apart, radius) as shares of the size, and the style: "round", "angry", "glow", "hollow"
#   spins     faces its spin instead of where it walks, so it's drawn for every direction (frames: 1)
#   alpha     how solid it is
#   halo      a pulsing glow underneath
#   face      a painter for a part that faces where it walks even though the body spins (drawn on top)
#   corona    a painter for a ring turning against the spin (drawn underneath)
#   orbs      [(color, radius)] of gems circling it, `orbit` sizes out
#   reach     how far out from its middle it can reach (feet, spikes, tentacles), as a share of its size
CREATURES = {
    "basic": {"paint": paint_walker, "clock": "walk", "stride": 2.6, "move": "hop", "reach": 1.25,
              "eyes": (0.4, 0.34, 0.27, "round")},
    "fast": {"paint": paint_dart, "clock": "time", "rate": 7.0, "move": None, "reach": 1.9,
             "eyes": (0.12, 0.3, 0.24, "angry")},
    "swarmling": {"paint": paint_slime, "clock": "walk", "stride": 2.2, "move": None, "reach": 2.0,
                  "eyes": (0.3, 0.42, 0.33, "round")},
    "tank": {"paint": paint_beetle, "clock": "walk", "stride": 1.4, "move": None, "reach": 1.4,
             "eyes": (1.05, 0.2, 0.17, "round")},
    "armored": {"paint": paint_tortoise, "clock": "walk", "stride": 2.0, "move": None, "reach": 1.4,
                "eyes": (1.08, 0.17, 0.15, "round")},
    "healer": {"paint": paint_jelly, "clock": "time", "rate": 1.2, "move": "hover", "reach": 1.9,
               "eyes": (0.42, 0.36, 0.25, "round")},
    "splitter": {"paint": paint_cell, "clock": "time", "rate": 1.6, "move": "hop", "reach": 1.1,
                 "eyes": (0.45, 0.32, 0.24, "round")},
    "phantom": {"paint": paint_ghost, "clock": "time", "rate": 1.8, "move": "hover", "reach": 2.0, "alpha": 0.8,
                "eyes": (0.32, 0.3, 0.24, "hollow")},
    "brood": {"paint": paint_brood, "clock": "walk", "stride": 1.2, "move": None, "reach": 1.75, "halo": True,
              "eyes": (0.84, 0.17, 0.14, "queen"), "maw": True},  # see graphics.draw_eyes
    "spiderling": {"paint": paint_spiderling, "clock": "walk", "stride": 1.6, "move": None, "reach": 1.7,
                   "eyes": (0.62, 0.22, 0.2, "round")},
    "bearer": {"paint": paint_bearer, "clock": "walk", "stride": 2.2, "move": "hop", "reach": 2.4,
               "eyes": (0.4, 0.34, 0.24, "round")},
    "looter": {"paint": paint_looter, "clock": "walk", "stride": 2.8, "move": "hop", "reach": 1.8,
               "eyes": (0.4, 0.34, 0.24, "round")},
    "saboteur": {"paint": paint_saboteur, "clock": "walk", "stride": 2.4, "move": "hop", "reach": 1.4,
                 "eyes": (0.45, 0.32, 0.22, "round")},
    "thawling": {"paint": paint_icicle, "clock": "walk", "stride": 1.8, "move": None, "reach": 1.45,
                 "eyes": (0.4, 0.32, 0.22, "round")},
    "berserker": {"paint": paint_brute, "clock": "walk", "stride": 2.2, "move": "hop", "reach": 1.45,
                  "eyes": (0.5, 0.3, 0.2, "round")},  # angrier as it rages: see graphics.draw_eyes
    "mirage": {"paint": paint_mage, "clock": "time", "rate": 1.4, "move": "hover", "reach": 1.5,
               "eyes": (0.32, 0.26, 0.2, "round")},
    "warded": {"paint": paint_sentinel, "clock": "walk", "stride": 2.3, "move": "hop", "reach": 1.3,
               "eyes": (0.42, 0.3, 0.2, "round")},
    "elite": {"paint": paint_champion, "clock": "walk", "stride": 2.4, "move": "hop", "reach": 1.3,
              "eyes": (0.3, 0.3, 0.2, "angry")},
    "juggernaut": {"paint": paint_golem, "clock": "walk", "stride": 2.0, "move": "hop", "reach": 1.45,
                   "eyes": (0.55, 0.3, 0.14, "glow")},
    "warden": {"paint": paint_warden, "clock": "walk", "stride": 1.6, "move": "hop", "reach": 1.75,
               "eyes": (0.43, 0.2, 0.09, "glow")},
    "overlord": {"paint": paint_overlord, "clock": None, "move": None, "reach": 1.05, "spins": True, "halo": True,
                 "face": overlord_face, "corona": overlord_corona, "orbit": 1.6,
                 "orbs": [(RUBY, 3.5), ((60, 130, 240), 3.5), ((60, 200, 120), 3.5)],
                 "eyes": (0.08, 0.17, 0.1, "angry")},
}
DEFAULT_EYES = (0.4, 0.34, 0.27, "round")  # for kinds added without a design here


def _paint_shape(cv, spec, size, rot, color, inner):
    """A kind with no creature design: its plain shape, lit, spinning."""
    rim = 1.5 if size > 9 else 1
    if "shape" in spec:
        layer(cv, spec["shape"], (0, 0), size, color, rot, 2)
    elif spec["sides"] == 0:
        sphere(cv, color, (0, 0), size, rim)
    else:
        gem(cv, color, (0, 0), regular_polygon(V(), size, spec["sides"], rot), rim)
    if inner:
        shape, r, inner_color = spec["inner"]
        layer(cv, shape, (0, 0), max(2, r * size / spec["size"]), inner_color, -rot, 1)


def _paint_enemy(cv, kind, size, angle, frame, whiten=0.0):
    spec = ENEMY_TYPES[kind]
    color = mix(spec["color"], WHITE, whiten)
    inner = mix(spec["inner"][2], WHITE, whiten) if "inner" in spec else None
    design = CREATURES.get(kind)
    if design:
        design["paint"](cv, size, color, inner, V(1, 0).rotate(angle), frame / FRAMES)
    else:
        _paint_shape(cv, spec, size, angle, color, inner)


def _reach(kind):
    return CREATURES.get(kind, {}).get("reach", 1.1)


def enemy_body(kind, step, scale, look="normal", frame=0):
    """An enemy facing one of the ANGLES directions, at one frame of its animation. `look`: "normal",
    "hit" (whitened and squashed, for a moment after a hit), "phased" (see-through) or "illusion" (pale and
    see-through)."""
    def make():
        spec = ENEMY_TYPES[kind]
        half = spec["size"] * _reach(kind) + 3
        cv = Canvas(2 * half, scale)
        whiten = {"hit": 0.65, "illusion": 0.3}.get(look, 0.0)
        _paint_enemy(cv, kind, spec["size"], step_angle(step), frame, whiten)
        if look == "hit":
            return cv.done((2 * half * ENEMY_SQUASH[0], 2 * half * ENEMY_SQUASH[1]))
        img = cv.done()
        alpha = CREATURES.get(kind, {}).get("alpha", 1.0) * {"phased": PHASED_ALPHA,
                                                             "illusion": ILLUSION_ALPHA}.get(look, 1.0)
        if alpha < 1:
            img.fill((255, 255, 255, round(255 * alpha)), special_flags=pygame.BLEND_RGBA_MULT)
        return img
    return cached(("enemy", kind, step, frame, scale, look), make)


def enemy_icon(kind, size, scale):
    """A still enemy `size` units in radius, facing up with its eyes open, for lists and the draft queue."""
    def make():
        cv = Canvas(2 * size * _reach(kind) + 4, scale)
        _paint_enemy(cv, kind, size, -90, 0)
        if "face" in CREATURES.get(kind, {}):
            spec = ENEMY_TYPES[kind]
            CREATURES[kind]["face"](cv, size, spec["color"], spec["inner"][2], V(0, -1))
        icon_eyes(cv, kind, size)
        return cv.done()
    return cached(("icon", kind, size, scale), make)


def enemy_face(kind, step, scale, look="normal"):
    """The part of a spinning creature that keeps facing one of the ANGLES directions (see CREATURES)."""
    def make():
        spec = ENEMY_TYPES[kind]
        cv = Canvas(2 * spec["size"] + 6, scale)
        whiten = 0.65 if look == "hit" else 0.0
        CREATURES[kind]["face"](cv, spec["size"], mix(spec["color"], WHITE, whiten),
                                mix(spec["inner"][2], WHITE, whiten), V(1, 0).rotate(step_angle(step)))
        return cv.done()
    return cached(("face", kind, step, scale, look), make)


def enemy_corona(kind, step, scale):
    def make():
        spec = ENEMY_TYPES[kind]
        cv = Canvas(3 * spec["size"], scale)
        CREATURES[kind]["corona"](cv, spec["size"], spec["color"], V(1, 0).rotate(step_angle(step)))
        return cv.done()
    return cached(("corona", kind, step, scale), make)


def orb(color, r, scale):
    """A small lit gem-ball."""
    return cached(("orb", color, r, scale), lambda: _orb(color, r, scale))


def _orb(color, r, scale):
    cv = Canvas(2 * r + 2, scale)
    sphere(cv, color, (0, 0), r, 0.7)
    return cv.done()


def eye_layout(kind, size, ahead):
    """(radius, style, [(center, side)]) of a kind's two eyes when it faces `ahead` (centers relative to it)."""
    spec = ENEMY_TYPES[kind]
    forward, apart, r, style = CREATURES.get(kind, {}).get("eyes", DEFAULT_EYES)
    if kind not in CREATURES and spec["sides"] == 3:
        forward = 0.15
    r = min(4.5, max(1.6, size * r))
    gap = max(r * 1.15, size * apart)
    return r, style, [(ahead * size * forward + ahead.rotate(90) * gap * k, k) for k in (-1, 1)]


def icon_eyes(cv, kind, size):
    r, style, eyes = eye_layout(kind, size, V(0, -1))
    for center, k in eyes:
        _paint_eye(cv, center, r * 0.85, V(0, -1), False, style, k)


EYE_LOOKS = 16  # directions an eye can look in
INK = (25, 18, 30)


def _paint_eye(cv, c, r, d, closed, style, k):
    """An eye at c looking along d; k (-1 or 1) is which side of the face it's on, for angry brows."""
    c = V(c)
    if style in ("glow", "queen", "queen_rage"):
        hot = style == "queen_rage"
        cv.circle((255, 40, 20) if hot else (255, 120, 30), c, r)
        cv.circle(((255, 150, 120) if hot else (255, 215, 90)) if not closed else (150, 70, 20), c, r * 0.7)
        if not closed:
            cv.circle(WHITE, c + d * r * 0.15, r * 0.3)
        if style != "glow":  # a heavy brow, slanting down toward the middle of the face
            _brow(cv, c, r, d, k, (35, 45, 25))
        return
    if style == "hollow":
        cv.polygon(INK, ellipse_points(c, d, r * 1.15, r * 0.8, 14))
        cv.circle(mix(INK, WHITE, 0.35), c + LIGHT * r * 0.35, max(0.4, r * 0.18))
        return
    side = d.rotate(90)
    if closed:
        cv.line(INK, c + side * r * 0.9, c - side * r * 0.9, max(0.8, r * 0.35))
        return
    cv.circle(INK, c, r + 0.5)
    cv.circle(WHITE if style != "furious" else (255, 225, 210), c, r)
    if style == "furious":  # a red-hot iris round a pinprick pupil
        cv.circle((230, 40, 20), c + d * r * 0.38, r * 0.6)
        cv.circle(INK, c + d * r * 0.42, r * 0.22)
    else:
        cv.circle(INK, c + d * r * 0.38, r * 0.55)
    cv.circle(WHITE, c + d * r * 0.38 + LIGHT * r * 0.25, max(0.4, r * 0.18))
    if style in ("angry", "furious"):  # a lid over the back of the eye, slanting down toward the middle of the face
        _brow(cv, c, r, d, k, INK)


def _brow(cv, c, r, d, k, color):
    """An angry lid over the back of an eye looking along d, slanting down toward the middle of the face."""
    n = (-d * 0.6 + d.rotate(90) * k * -0.8).normalize()
    h = 0.1  # the lid's edge, as a share of r from the center
    a, span = n.as_polar()[1], math.degrees(math.acos(h))
    arc = [c + V(r + 0.6, 0).rotate(a + span * (i / 6 * 2 - 1)) for i in range(7)]
    cv.polygon(color, arc)


def eye(r, look, closed, scale, style="round", k=1):
    """One eye of radius r looking toward direction `look` (of EYE_LOOKS); closed, it's a lid line."""
    def make():
        cv = Canvas(2 * r + 3, scale)
        _paint_eye(cv, (0, 0), r, V(1, 0).rotate(look * 360 / EYE_LOOKS), closed, style, k)
        return cv.done()
    return cached(("eye", r, look, closed, style, k if style in ("angry", "furious", "queen", "queen_rage") else 0,
                   scale), make)


def snarl(size, step, scale):
    """A Berserker's snarl at its fury's height: a dark mouth of bared teeth, facing one of the ANGLES
    directions, centered where it goes (in front of the eyes)."""
    def make():
        cv = Canvas(size * 1.2, scale)
        f = V(1, 0).rotate(step_angle(step))
        s = f.rotate(90)
        w, h = size * 0.34, size * 0.11
        cv.polygon(INK, [s * w, f * h + s * w * 0.6, f * h * 1.2 - s * w * 0.6, -s * w, -f * h - s * w * 0.6,
                         -f * h * 1.2 + s * w * 0.6])
        for i in range(4):  # teeth, top and bottom in turn
            x = (i - 1.5) / 1.5 * w * 0.7
            edge = -1 if i % 2 else 1
            cv.polygon(WHITE, [s * (x - w * 0.14) + f * h * edge, s * (x + w * 0.14) + f * h * edge, s * x])
        return cv.done()
    return cached(("snarl", size, step, scale), make)


def shell(color, r, scale):
    """A cannonball: a dark, lit ball tinted with the tower's color."""
    return cached(("shell", color, r, scale), lambda: _shell(color, r, scale))


def _shell(color, r, scale):
    cv = Canvas(2 * r + 2, scale)
    sphere(cv, mix(color, (40, 40, 46), 0.45), (0, 0), r, 0.8)
    return cv.done()


def ice_shard(step, color, scale):
    """A sliver of ice flying along one of the ANGLES directions."""
    def make():
        cv = Canvas(14, scale)
        a = step_angle(step)
        gem(cv, color, (0, 0), [V(6, 0).rotate(a), V(0, 2.4).rotate(a), V(-4, 0).rotate(a), V(0, -2.4).rotate(a)], 0.6)
        return cv.done()
    return cached(("ice", step, color, scale), make)
