"""Visual effects: short-lived pictures the game adds to its effects and popups lists (rings,
beams, explosions, sparks, shards, cast warnings, floating text). They only age and draw; they
don't affect the game. Each has update(dt), which returns False once it's over, and draw(surf)
(Popup is drawn by graphics.GameView, in the game font).
"""

import math

import pygame

from graphics import jagged, sdraw
from sprites import mix, regular_polygon, shade


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
    """A fading line with a glow, for instant hits; `bolt` makes it a jagged lightning bolt."""

    def __init__(self, a, b, color, duration, width, bolt=False):
        self.a = pygame.Vector2(a)
        self.b = pygame.Vector2(b)
        self.color = color
        self.duration = duration
        self.width = width
        self.points = jagged(self.a, self.b, int(self.a.x + self.b.y)) if bolt else [self.a, self.b]
        self.t = 0.0

    def update(self, dt):
        self.t += dt
        return self.t < self.duration

    def draw(self, surf):
        alpha = 1 - self.t / self.duration
        core = mix(self.color, (255, 255, 255), 0.6)
        for color, width, k in ((self.color, self.width + 3, 0.35), (core, max(1, self.width - 1), 1.0)):
            for p, q in zip(self.points, self.points[1:]):
                sdraw.line(surf, (*color, int(255 * alpha * k)), p, q, width)


class Explosion:
    """A shell's blast: a white-hot flash, a ring going out to the splash radius, and flying debris.
    The debris directions come from where it landed, not a random roll, so drawing stays repeatable."""

    duration = 0.4

    def __init__(self, pos, radius, color):
        self.pos = pygame.Vector2(pos)
        self.radius = radius
        self.color = color
        self.t = 0.0
        self.spin = (self.pos.x * 7.3 + self.pos.y * 3.1) % 360

    def update(self, dt):
        self.t += dt
        return self.t < self.duration

    def draw(self, surf):
        k = self.t / self.duration
        ease = 1 - (1 - k) ** 2
        if k < 0.35:
            f = k / 0.35
            sdraw.circle(surf, (*mix((255, 250, 220), self.color, f), int(210 * (1 - f))), self.pos,
                         self.radius * (0.25 + 0.3 * f))
        sdraw.circle(surf, (*self.color, int(220 * (1 - k))), self.pos, max(2, self.radius * (0.3 + 0.7 * ease)), 3)
        debris = (*shade(self.color, 0.7), int(255 * (1 - k)))
        for i in range(7):
            d = pygame.Vector2(1, 0).rotate(self.spin + i * 360 / 7 + (i * 29) % 20)
            reach = self.radius * (0.4 + 0.25 * (i % 3)) * ease
            sdraw.circle(surf, debris, self.pos + d * reach, 2.5 * (1 - k) + 0.5)


class Sparks:
    """A few streaks (or, with `chips`, little ice diamonds) flying out of a hit point."""

    duration = 0.25

    def __init__(self, pos, color, count=3, reach=12, chips=False):
        self.pos = pygame.Vector2(pos)
        self.color = color
        self.count = count
        self.reach = reach
        self.chips = chips
        self.spin = (self.pos.x * 7.3 + self.pos.y * 3.1) % 360
        self.t = 0.0

    def update(self, dt):
        self.t += dt
        return self.t < self.duration

    def draw(self, surf):
        k = self.t / self.duration
        ease = 1 - (1 - k) ** 2
        color = (*self.color, int(255 * (1 - k)))
        for i in range(self.count):
            d = pygame.Vector2(1, 0).rotate(self.spin + i * 360 / self.count + (i * 47) % 30)
            tip = self.pos + d * self.reach * ease
            if self.chips:
                sdraw.polygon(surf, color, regular_polygon(tip, 2.2 * (1 - k) + 0.8, 4, d.as_polar()[1]))
            else:
                sdraw.line(surf, color, self.pos + d * self.reach * ease * 0.45, tip, 1.5)


class Shards:
    """A dead enemy popping: a white flash, then its pieces, in its lit and shaded tones, flying apart and
    fading. The spread comes from the enemy's spin, not a random roll, so drawing stays repeatable."""

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
        if k < 0.25:  # the pop
            sdraw.circle(surf, (255, 255, 255, int(200 * (1 - k / 0.25))), self.pos, self.size * (1 + k))
        r = max(2.5, self.size * 0.55 * (1 - 0.4 * k))
        alpha = int(255 * (1 - k * k))
        tones = ((*mix(self.color, (255, 255, 255), 0.3), alpha), (*shade(self.color, 0.6), alpha))
        for i, (direction, speed) in enumerate(self.pieces):
            center = self.pos + direction * (self.size * 0.4 + 36 * speed * ease)
            sdraw.polygon(surf, tones[i % 2], regular_polygon(center, r, 3, direction.as_polar()[1] + 500 * k * speed))


class GooSpray:
    """Droplets flying from a summoner to where a minion it shot out lands, then a splat there."""

    duration = 0.3

    def __init__(self, a, b, color):
        self.a, self.b = pygame.Vector2(a), pygame.Vector2(b)
        self.color = color
        self.t = 0.0

    def update(self, dt):
        self.t += dt
        return self.t < self.duration

    def draw(self, surf):
        k = self.t / self.duration
        alpha = int(255 * (1 - k))
        for i in range(4):  # a string of droplets, the front one leading
            f = min(1.0, k * 1.6 - i * 0.12)
            if f > 0:
                sdraw.circle(surf, (*self.color, alpha), self.a.lerp(self.b, f), 2.4 - i * 0.4)
        if k > 0.5:
            sdraw.circle(surf, (*shade(self.color, 0.7), alpha), self.b, 4 + 6 * (k - 0.5), 2)


class GoldBurst:
    """A Looter's sack bursting at the end of the path: a golden flash, scraps of sacking, and a shower of
    coins thrown up and out that tumble (flipping edge-on and back), land, and fade. The throws come from
    where it burst, not a random roll, so drawing stays repeatable."""

    duration = 1.1
    COINS = 18
    GOLD, RIM, SACK = (255, 214, 80), (190, 135, 30), (150, 105, 45)

    def __init__(self, pos):
        self.pos = pygame.Vector2(pos)
        self.t = 0.0
        seed = int(self.pos.x * 7.3 + self.pos.y * 3.1)
        self.coins = []
        for i in range(self.COINS):
            j = (seed + i * 37) % 100 / 100
            d = pygame.Vector2(1, 0).rotate(seed + i * 360 / self.COINS + j * 18)
            self.coins.append((d * (16 + 24 * j), 34 + 30 * ((i * 53) % 10) / 10, 9 + 9 * j))  # out, up, spin

    def update(self, dt):
        self.t += dt
        return self.t < self.duration

    def draw(self, surf):
        k = self.t / self.duration
        if k < 0.2:  # the burst
            f = k / 0.2
            sdraw.circle(surf, (*mix((255, 250, 200), self.GOLD, f), int(220 * (1 - f))), self.pos, 8 + 14 * f)
        if k < 0.5:  # scraps of the sack
            f = k / 0.5
            for i in range(5):
                d = pygame.Vector2(1, 0).rotate(i * 72 + 20)
                at = self.pos + d * 22 * (1 - (1 - f) ** 2)
                sdraw.polygon(surf, (*self.SACK, int(230 * (1 - f))), regular_polygon(at, 3.2, 3, i * 50 + 400 * f))
        fade = int(255 * min(1.0, (1 - k) / 0.35))
        flight = 0.55  # seconds in the air
        for out, up, spin in self.coins:
            t = min(self.t, flight)
            ease = t / flight
            ground = self.pos + out * (1 - (1 - ease) ** 2)
            height = up * t - 0.5 * (2 * up / flight) * t * t  # up and back down by the time it lands
            sdraw.circle(surf, (0, 0, 0, fade // 4), ground + (1, 2), 2.2)
            at = ground - pygame.Vector2(0, height)
            turn = abs(math.cos(spin * self.t)) if self.t < flight else 0.9
            w, h = 3.0 * max(0.18, turn), 3.0
            edge = [at + (math.cos(a) * w, math.sin(a) * h) for a in (math.tau * n / 12 for n in range(12))]
            sdraw.polygon(surf, (*self.RIM, fade), edge)
            sdraw.polygon(surf, (*self.GOLD, fade), [at + (p - at) * 0.72 for p in edge])
            if turn > 0.5:
                sdraw.circle(surf, (255, 250, 220, fade), at + (-w * 0.3, -h * 0.35), 0.8)


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
