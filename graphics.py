"""Everything the tower defense draws: layout, colors, display scaling, shapes, visual
effects, and GameView, the drawing half of main.Game.

The game runs in fixed logical units (the WIDTH x HEIGHT layout below); only drawing and
mouse input go through SCALE. The window is WINDOW_SCALE times the layout, and fullscreen is as large
as the screen allows. Everything is drawn natively at that size, so there is no per-frame image
scaling: switching re-renders the map and fonts once.

This module doesn't import main (that would load the game twice when it's run as a
script); GameView reads the game state through `self`.
"""

import math
import os
from collections import Counter
from itertools import pairwise

import pygame

import ambience
import sprites
import terrain
from levels import COLS, LEVELS, ROWS, TILE, WAVES_PER_LEVEL, tile_center
from monsters import ABILITIES, ENEMY_TYPES, REWARDS, WARD_BREAK
from progress import UNLOCKS
from sprites import mix, regular_polygon
from towers import CROSS, EVOLVE, LINES, TARGETING, TOWER_ORDER, TOWERS

# --------------------------------------------------------------------------
# Layout and colors
# --------------------------------------------------------------------------
MAP_W, MAP_H = COLS * TILE, ROWS * TILE
PANEL_W = 220
WIDTH, HEIGHT = MAP_W + PANEL_W, MAP_H

# The window's size: twice the layout (2040 x 1280), or as large as fits on a smaller desktop.
WINDOW_SCALE = 2.0

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
BUTTON = (70, 70, 85)
BUTTON_HOVER = (90, 90, 108)
BUTTON_QUIET = (48, 48, 58)  # a button that's on offer but not the main action
BUTTON_OFF = (40, 40, 48)  # a button that can't be used right now
BOSS_ALERT = 3.0  # seconds a boss's alert shows when it walks in
GRAND_ALERT_EXTRA = 1.5  # and longer for a secret boss that follows another (monsters.json follows)
BANKRUPT_NOTICE = 5.0  # seconds the bankruptcy notice shows (the Chairman got through)


def boss_color(spec):
    """A boss's colour for its name and health bar: its own, or, if that's too dark to read on the dark bands
    (the Chairman's navy suit), its inner colour."""
    r, g, b = spec["color"]
    return spec["inner"][2] if 0.3 * r + 0.59 * g + 0.11 * b < 70 and "inner" in spec else spec["color"]
CARD = (38, 38, 48)  # cards and option tiles on the overlay screens
CARD_HOVER = (55, 55, 68)
TIER_RIM = {1: (78, 80, 94), 2: (176, 116, 64), 3: (205, 205, 220), 4: GOLD}
TIER_COLORS = {"weak": TEXT_DIM, "normal": TEXT, "strong": GOLD}  # record tiers on the reward screen
PREVIEW_KINDS = 4  # monster kinds the wave preview has room for (more show as a "+n")
PREVIEW_Y = 516  # the wave preview's row in the panel
TREE_COLS = (40, 230, 440)  # the evolution tree's tier 1, 2 and 3 columns
TREE_TOP, TREE_ROW = 100, 92  # the first line's row, and the space between rows
FINALS_TOP = 368  # the final forms' heading


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
_texts = {}  # (font, text, color) -> rendered line: most labels are the same every frame
TEXT_CACHE_SIZE = 1024  # past this many lines the cache starts over (counters keep making new ones)


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
    key = (font, s, tuple(color))
    img = _texts.get(key)
    if img is None:
        if len(_texts) >= TEXT_CACHE_SIZE:
            _texts.clear()
        img = _texts[key] = font.render(s, True, color)
    if alpha is not None:
        img = img.copy()  # the cached line stays opaque
        img.set_alpha(alpha)
    top, bottom = _caps[font]
    box = pygame.Rect(0, 0, img.get_width(), bottom - top)
    setattr(box, anchor, (round(pos[0] * SCALE), round(pos[1] * SCALE)))
    surf.blit(img, (box.x, box.y - top))
    return box


# --------------------------------------------------------------------------
# Display scale
# --------------------------------------------------------------------------
SCALE = 1.0  # read it as graphics.SCALE from other modules: set_scale rebinds it
OFFSET = (0, 0)  # where the game's picture starts on the display: centered in fullscreen, else the corner


def set_scale(scale):
    global SCALE  # noqa: PLW0603 - one module-wide scale, read as graphics.SCALE
    SCALE = scale


def window_size():
    return round(WIDTH * SCALE), round(HEIGHT * SCALE)


def sp(pos):
    """Logical point -> screen point."""
    return pos[0] * SCALE, pos[1] * SCALE


def srect(rect):
    """Logical rect -> screen rect; edges are rounded separately so neighbouring rects never leave gaps."""
    x, y, w, h = rect
    left, top = round(x * SCALE), round(y * SCALE)
    return pygame.Rect(left, top, round((x + w) * SCALE) - left, round((y + h) * SCALE) - top)


def set_offset(offset):
    global OFFSET  # noqa: PLW0603 - as SCALE
    OFFSET = tuple(offset)


def to_logical(pos):
    """Display point (mouse) -> logical point."""
    return int((pos[0] - OFFSET[0]) / SCALE), int((pos[1] - OFFSET[1]) / SCALE)


def mouse_pos():
    return to_logical(pygame.mouse.get_pos())


class FxLayer(pygame.Surface):
    """The see-through layer over the map (ranges, beams, flames, explosions). It remembers which CELL
    squares were drawn on, so each frame clears and shows only those: blending the whole layer costs
    about 2 ms at fullscreen scale even when it's empty. Draw on it with blit, fill or sdraw, which mark."""

    CELL = 64  # screen pixels

    def __init__(self, size):
        super().__init__(size, pygame.SRCALPHA)
        self.cells = set()  # (column, row) of the squares drawn on since the last clear

    def mark(self, rect):
        if rect.width and rect.height:
            c = self.CELL
            rows = range(rect.top // c, (rect.bottom - 1) // c + 1)
            self.cells.update((x, y) for x in range(rect.left // c, (rect.right - 1) // c + 1) for y in rows)
        return rect

    def blit(self, source, dest, area=None, special_flags=0):
        return self.mark(super().blit(source, dest, area, special_flags))

    def fill(self, color, rect=None, special_flags=0):
        return self.mark(super().fill(color, rect, special_flags))

    def spans(self):
        """The marked squares as rects, neighbours in a row joined, none overlapping (a spot shown twice
        would be blended twice)."""
        c = self.CELL
        runs = []
        for x, y in sorted(self.cells, key=lambda cell: (cell[1], cell[0])):
            if runs and runs[-1].y == y * c and runs[-1].right == x * c:
                runs[-1].width += c
            else:
                runs.append(pygame.Rect(x * c, y * c, c, c))
        bounds = self.get_rect()
        return [r.clip(bounds) for r in runs]

    def clear(self):
        for r in self.spans():
            super().fill((0, 0, 0, 0), r)
        self.cells.clear()

    def show(self, surf):
        for r in self.spans():
            surf.blit(self, r.topleft, r)


def _marked(surf, rect):
    """What pygame.draw changed on `surf`, noted if it's an FxLayer."""
    return surf.mark(rect) if isinstance(surf, FxLayer) else rect


class ScaledDraw:
    """pygame.draw (plus fill) taking logical coordinates and drawing at SCALE."""

    @staticmethod
    def width(w):
        return max(1, round(w * SCALE)) if w else 0

    def circle(self, surf, color, center, radius, width=0):
        return _marked(surf, pygame.draw.circle(surf, color, sp(center), radius * SCALE, self.width(width)))

    def line(self, surf, color, a, b, width=1):
        return _marked(surf, pygame.draw.line(surf, color, sp(a), sp(b), self.width(width)))

    def rect(self, surf, color, rect, width=0, border_radius=0):
        return _marked(surf, pygame.draw.rect(surf, color, srect(rect), self.width(width),
                                              round(border_radius * SCALE)))

    def polygon(self, surf, color, points, width=0):
        return _marked(surf, pygame.draw.polygon(surf, color, [sp(p) for p in points], self.width(width)))

    def ellipse(self, surf, color, rect, width=0):
        return _marked(surf, pygame.draw.ellipse(surf, color, srect(rect), self.width(width)))

    def fill(self, surf, color, rect):
        return surf.fill(color, srect(rect))


sdraw = ScaledDraw()


# --------------------------------------------------------------------------
# Shapes, towers, enemies, the map
# --------------------------------------------------------------------------
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


def blit_center(surf, img, pos):
    surf.blit(img, img.get_rect(center=sp(pos)))


KICK_BACK = 2.5  # how far a turret jumps back when it fires
MUZZLE_KICK = 0.6  # the muzzle flash shows while a shot's kick is above this


def draw_tower_shape(surf, spec, pos, aim=-90.0, kick=0.0):
    """Draw a tower from its spec (an entry of towers.TOWERS): plate, turret aimed at `aim`, tier pips.
    `kick` (1 just after a shot, down to 0) pushes the turret back."""
    tier = spec["tier"]
    pos = pygame.Vector2(pos)
    blit_center(surf, sprites.tower_plate(tier, TIER_RIM[tier], SCALE, TILE), pos)
    turret = sprites.tower_turret(spec, sprites.angle_step(aim), SCALE)
    blit_center(surf, turret, pos - pygame.Vector2(KICK_BACK * kick, 0).rotate(aim))
    blit_center(surf, sprites.tower_pips(tier, SCALE, TILE), pos)


def draw_tower(surf, fx, tower, clock):
    """A tower on the map: turning, kicking back and flashing when it fires; Tesla towers crackle and
    frost towers glint now and then (`clock` is the game time, so pauses freeze them)."""
    spec = tower.spec
    flame, laser = spec["look"]["flame"], spec["look"]["laser"]
    draw_tower_shape(surf, spec, tower.pos, tower.facing, 0.0 if flame or laser else tower.kick)
    count, length, width = spec["look"]["barrels"]
    if flame:
        if tower.flame > 0:
            draw_flame_stream(fx, tower, clock)
    elif laser:
        if tower.flame > 0:
            draw_laser(fx, tower, clock)
    elif tower.kick > MUZZLE_KICK:
        if count:
            d = pygame.Vector2(1, 0).rotate(tower.facing)
            tip = tower.pos + d * (length + 2 - KICK_BACK * tower.kick)
            blit_center(surf, sprites.muzzle_flash(sprites.angle_step(tower.facing), 3 + width / 2, SCALE), tip)
        else:  # no barrels: the core flares
            img = sprites.glow(mix(spec["look"]["layers"][0][2], (255, 255, 255), 0.6), 15, SCALE)
            img.set_alpha(round(255 * (tower.kick - MUZZLE_KICK) / (1 - MUZZLE_KICK)))
            blit_center(surf, img, tower.pos)
    seed = tower.tile[0] * 7 + tower.tile[1] * 13  # where it stands, so the same map always looks the same
    if "chain" in spec:
        tick = int(clock * 12)
        for i in range(2):
            a = (tick * 137 + seed * 53 + i * 160) % 360
            start = tower.pos + pygame.Vector2(6, 0).rotate(a)
            points = jagged(start, start + pygame.Vector2(10, 0).rotate(a + 30), tick + i, 2.5)
            for p, q in pairwise(points):
                sdraw.line(fx, (240, 240, 140, 220), p, q, 1)
    elif "slow" in spec and "burn" not in spec:
        s = (clock * 0.6 + seed * 0.37) % 1.0
        if s < 0.2:
            sparkle(fx, tower.pos + pygame.Vector2(8, 0).rotate(seed * 77 + 200), 5 * math.sin(math.pi * s / 0.2))


FLAME_PUFFS = 30  # puffs of fire in a flame stream
FLAME_SPREAD = 8  # how far a puff strays sideways by the time it reaches the target


def draw_flame_stream(fx, tower, clock):
    """A flame tower's fire: puffs pour from the nozzle to its target, widening, wavering and cooling as they
    go. Where each puff is comes from the game clock, so pauses freeze it. It grows out from the nozzle as the
    tower finds a target and draws back when it loses one (tower.flame). The fire pours as fast as the shells
    hidden in it fly: a puff crosses the tower's range in the time a shell does."""
    d = pygame.Vector2(1, 0).rotate(tower.facing)
    side = d.rotate(90)
    barrel = tower.spec["look"]["barrels"][1]
    nozzle = tower.pos + d * (barrel + 1)
    reach = max(0.0, tower.flame_reach - barrel) * tower.flame
    seed = tower.tile[0] * 7 + tower.tile[1] * 13
    life = tower.spec["range"] / tower.spec["proj_speed"]
    puffs = sorted(((clock / life + i / FLAME_PUFFS) % 1.0, i) for i in range(FLAME_PUFFS))
    for age, i in reversed(puffs):  # the oldest (widest, darkest) first, so the hot core stays on top
        stray = ((i * 37 + seed) % 11 - 5) / 5 + 0.5 * math.sin(clock * 17 + i * 2.3 + seed)
        img = sprites.flame_puff(round(age * (sprites.FLAME_STEPS - 1)), SCALE)
        img.set_alpha(round(255 * (1 - age) ** 0.5 * tower.flame))
        blit_center(fx, img, nozzle + d * reach * age + side * stray * FLAME_SPREAD * age)


def draw_laser(fx, tower, clock):
    """A laser tower's beam: one unbroken line from the lens to its target for as long as it has one, though
    its damage lands in ticks (the tower's rate). It shimmers with the game clock, so pauses freeze it, flares
    as each tick lands (tower.kick) and shoots out or draws back like a flame stream (tower.flame)."""
    d = pygame.Vector2(1, 0).rotate(tower.facing)
    barrel = tower.spec["look"]["barrels"][1]
    lens = tower.pos + d * (barrel + 1)
    end = lens + d * max(0.0, tower.flame_reach - barrel) * tower.flame
    color = tower.spec["color"]
    seed = tower.tile[0] * 7 + tower.tile[1] * 13
    flare = tower.kick
    bright = tower.flame * (0.85 + 0.15 * math.sin(clock * 40 + seed))
    halo, core = mix(color, (255, 90, 20), 0.4), mix(color, (255, 255, 255), 0.8)
    for c, width, k in ((halo, 9 + 3 * flare, 0.3), (color, 5 + 2 * flare, 0.75), (core, 2 + flare, 1.0)):
        sdraw.line(fx, (*c, round(255 * k * bright)), lens, end, round(width))
    for pos, r in ((lens, 6), (end, 8 + round(4 * flare))):
        img = sprites.glow(color, r, SCALE)
        img.set_alpha(round(255 * bright))
        blit_center(fx, img, pos)


def sparkle(surf, pos, r):
    """A four-pointed glint."""
    for axis in ((1, 0), (0, 1)):
        d = pygame.Vector2(axis) * r
        sdraw.line(surf, (255, 255, 255, 230), pos - d, pos + d, 1)
    sdraw.circle(surf, (255, 255, 255, 255), pos, max(1.0, r * 0.25))


def jagged(a, b, seed, wobble=4.0):
    """Points of a lightning bolt from a to b; the same seed gives the same bolt."""
    a, b = pygame.Vector2(a), pygame.Vector2(b)
    n = max(2, int(a.distance_to(b) / 12))
    across = (b - a).rotate(90)
    across = across.normalize() if across.length_squared() else across
    middle = [a + (b - a) * i / n + across * wobble * (((seed + i) * 37) % 9 - 4) / 4 for i in range(1, n)]
    return [a, *middle, b]


def draw_enemy_icon(surf, kind, pos, size):
    """A small still picture of an enemy type, for lists and the draft queue."""
    blit_center(surf, sprites.enemy_icon(kind, size, SCALE), pos)


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


BLINK_EVERY, BLINK_TIME = 3.2, 0.14  # seconds
ANGRY, FURIOUS = 0.25, 0.6  # a Berserker's face changes at these shares of its full rage


def enemy_lift(enemy):
    """How far above its shadow an enemy is drawn: hoppers bounce as they walk (bosses hardly at all),
    hoverers bob in the air."""
    design = sprites.CREATURES.get(enemy.kind, {})
    size = enemy.spec["size"]
    if enemy.phased or not design.get("move"):
        return 0.0
    if design["move"] == "hover":
        return 3 + 1.5 * math.sin(enemy.phase_t * 3 + enemy.spawn_t)
    height = 1.0 if "boss" in enemy.spec else min(2.5, size * 0.2)
    return abs(math.sin(enemy.travelled / (size * 0.9))) * height


def enemy_frame(enemy):
    """Which frame of its animation an enemy is at: walkers step with the distance they cover (so a
    slowed one slows down), the others play in time."""
    design = sprites.CREATURES.get(enemy.kind, {})
    clock = design.get("clock")
    if clock == "walk":
        cycles = enemy.travelled / (design["stride"] * enemy.spec["size"])
    elif clock == "time":
        cycles = enemy.phase_t * design["rate"] + enemy.spawn_t * 0.37
    else:
        return 0
    return int(cycles * sprites.FRAMES) % sprites.FRAMES


def draw_enemy(surf, enemy):
    spec = enemy.spec
    size = spec["size"]
    design = sprites.CREATURES.get(enemy.kind)
    if design is None:  # a plain shape: triangles point where they're going, others slowly spin
        angle = enemy.heading.as_polar()[1] if spec["sides"] == 3 and "shape" not in spec else enemy.spin
    else:
        angle = enemy.spin if design.get("spins") else enemy.facing
    look = "phased" if enemy.phased else "illusion" if enemy.illusion else "hit" if enemy.flash > 0 else "normal"
    pos = enemy.pos - pygame.Vector2(0, enemy_lift(enemy))
    if enemy.illusion:  # a shimmer, side to side
        pos += pygame.Vector2(math.sin(enemy.phase_t * 17) * 1.2, 0)
    if "rebound" in spec and enemy.slowed and enemy.slow_factor < 1:
        # a slowed Thawling shivers, harder as the slow runs out and its sprint gets near
        amp = 0.8 + 1.6 * max(0.0, 1 - enemy.slow_timer)
        pos += pygame.Vector2(math.sin(enemy.phase_t * 53), math.sin(enemy.phase_t * 41 + 1.3)) * amp
    if design and design.get("halo"):
        halo = sprites.glow(mix(spec["color"], (255, 255, 255), 0.3), size + 12, SCALE)
        halo.set_alpha(round(150 + 70 * math.sin(enemy.phase_t * 4)))
        blit_center(surf, halo, pos)
    if design and "corona" in design:
        blit_center(surf, sprites.enemy_corona(enemy.kind, sprites.angle_step(-enemy.spin * 0.5), SCALE), pos)
    if "speed_aura" in spec and not enemy.illusion:  # how far a Banner Bearer's rally reaches
        ring = sprites.rally_ring(spec["speed_aura"][0], SCALE)
        ring.set_alpha(round(190 + 65 * math.sin(enemy.phase_t * 3)))
        blit_center(surf, ring, enemy.pos)
    if enemy.rally > 0:  # rallied: gold speed streaks behind it
        side = enemy.heading.rotate(90) * size * 0.45
        for k in (-1, 1):
            start = pos - enemy.heading * (size + 2) + side * k
            sdraw.line(surf, (255, 205, 90), start, start - enemy.heading * 7, 2)
    if enemy.rebounding:  # a Thawling sprinting off its thaw trails steam
        for i in range(4):
            back = pos - enemy.heading * (size * 0.6 + 6 + i * 6)
            sway = enemy.heading.rotate(90) * math.sin(enemy.phase_t * 9 + i * 1.8) * 3
            puff = sprites.steam_puff(round(6 + i * 2), SCALE)
            puff.set_alpha(220 - 45 * i)
            blit_center(surf, puff, back + sway)
    if enemy.rage > 0.05:  # a Berserker burns hotter the angrier it gets
        aura = sprites.rage_aura(size, int(enemy.phase_t * 14) % sprites.FRAMES, SCALE)
        aura.set_alpha(round(255 * min(1.0, 0.25 + enemy.rage / spec["enrage"])))
        blit_center(surf, aura, pos)
    img = sprites.enemy_body(enemy.kind, sprites.angle_step(angle), SCALE, look, enemy_frame(enemy))
    blit_center(surf, img, pos)
    if design and "face" in design:
        blit_center(surf, sprites.enemy_face(enemy.kind, sprites.angle_step(enemy.facing), SCALE, look), pos)
    for i, (color, r) in enumerate(design.get("orbs", ()) if design else ()):
        orbit = pygame.Vector2(size * design["orbit"], 0).rotate(enemy.phase_t * 70 + i * 360 / len(design["orbs"]))
        blit_center(surf, sprites.orb(color, r, SCALE), pos + orbit)
    if not enemy.phased:
        draw_eyes(surf, enemy, pos)
    if "sabotage" in spec:  # the charge's light, blinking faster as the Saboteur nears death
        f = pygame.Vector2(1, 0).rotate(enemy.facing)
        tip = pos + (f * sprites.SABOTEUR_ANTENNA[0] + f.rotate(90) * sprites.SABOTEUR_ANTENNA[1]) * size
        rate = 1.5 + 6 * (1 - enemy.hp / enemy.max_hp)
        if (enemy.phase_t * rate + enemy.spawn_t) % 1 < 0.5:
            blit_center(surf, sprites.glow((255, 60, 40), 9, SCALE), tip)
            sdraw.circle(surf, (255, 90, 70), tip, max(1.6, size * 0.17))
    if enemy.burn_timer > 0:
        sdraw.circle(surf, (255, 120, 20), pos, max(3, size // 3))
    if enemy.slowed:
        sdraw.circle(surf, (150, 230, 255), pos, size + 4, 2)
    if "ward" in spec:
        draw_ward(surf, enemy, pos)
    if enemy.shield_timer > 0:
        sdraw.circle(surf, (240, 220, 120), pos, size + 7, 2)
    if enemy.barrier > 0:
        draw_barrier(surf, enemy, pos)
    if enemy.haste_timer > 0:
        tail = pos - enemy.heading * (size + 8)
        sdraw.line(surf, (255, 120, 60), pos - enemy.heading * size, tail, 3)
    if enemy.hp < enemy.max_hp:
        w = size * 2 + 4
        bar = pygame.Rect(0, 0, w, 4)
        bar.midbottom = (enemy.pos.x, enemy.pos.y - size - 5)
        sdraw.rect(surf, (40, 0, 0), bar)
        bar.width = max(1, int(w * enemy.hp / enemy.max_hp))
        sdraw.rect(surf, GOOD, bar)


WARD_COLOR = (150, 210, 255)


def draw_ward(surf, enemy, pos):
    """Warded: the bubble while the ward is up (shimmering), a shatter just after it absorbs a hit, and a
    thin arc filling round it as the ward comes back."""
    size = enemy.spec["size"]
    r = size + 6
    if enemy.warded:
        bubble = sprites.ward_bubble(size, SCALE)
        bubble.set_alpha(round(205 + 50 * math.sin(enemy.phase_t * 5 + enemy.spawn_t)))
        blit_center(surf, bubble, pos)
        return
    if enemy.ward_break > 0:  # the hexagon bursts outward in six shards
        k = 1 - enemy.ward_break / WARD_BREAK
        corners = regular_polygon(pygame.Vector2(), r * (1 + 0.6 * k), 6, 30 + 25 * k)
        for a, b in zip(corners, corners[1:] + corners[:1]):
            mid, half = (a + b) / 2, (b - a) * 0.3 * (1 - k)
            sdraw.line(surf, mix(WARD_COLOR, (255, 255, 255), 0.5 * (1 - k)), pos + mid - half, pos + mid + half,
                       2.5 * (1 - k) + 1)
    charge = 1 - enemy.ward_timer / enemy.spec["ward"]
    if charge > 0:
        steps = max(2, round(24 * charge))
        arc = [pos + pygame.Vector2(0, -r).rotate(360 * charge * i / steps) for i in range(steps + 1)]
        for a, b in pairwise(arc):
            sdraw.line(surf, mix(WARD_COLOR, (40, 60, 90), 0.35), a, b, 1.5)


def draw_barrier(surf, enemy, pos):
    """The Chairman's dividends: a ring of gold coins circling him, more of them the thicker his barrier
    (one per 5% of his max hp, up to 16), each flipping edge-on and back as it goes round."""
    size = enemy.spec["size"]
    coins = max(1, min(16, round(20 * enemy.barrier / enemy.max_hp)))
    r = size + 12
    for i in range(coins):
        a = enemy.phase_t * 60 + i * 360 / coins
        c = pos + pygame.Vector2(r, 0).rotate(a)
        w = max(1.5, 7 * abs(math.cos(enemy.phase_t * 4 + i)))
        sdraw.ellipse(surf, (190, 135, 30), (c.x - w / 2, c.y - 3.5, w, 7))
        sdraw.ellipse(surf, GOLD, (c.x - w / 2 + 0.6, c.y - 2.9, max(0.8, w - 1.2), 5.8))


def draw_eyes(surf, enemy, pos):
    """Two eyes looking where the enemy is going, blinking now and then."""
    ahead = pygame.Vector2(1, 0).rotate(enemy.facing)
    r, style, eyes = sprites.eye_layout(enemy.kind, enemy.spec["size"], ahead)
    look = round(enemy.facing * sprites.EYE_LOOKS / 360) % sprites.EYE_LOOKS
    # the spawn time staggers the blinks, so a wave doesn't blink all at once
    closed = (enemy.phase_t + enemy.spawn_t * 1.7) % BLINK_EVERY > BLINK_EVERY - BLINK_TIME
    fury = enemy.rage / enemy.spec["enrage"] if "enrage" in enemy.spec else 0
    if fury >= FURIOUS:  # a Berserker past FURIOUS glares, red-eyed, and snarls; it doesn't blink
        style, closed = "furious", False
        mouth = pos + ahead * enemy.spec["size"] * 0.86
        blit_center(surf, sprites.snarl(enemy.spec["size"], sprites.angle_step(enemy.facing), SCALE), mouth)
    elif fury >= ANGRY:
        style = "angry"
    if style == "queen" and enemy.hp < enemy.max_hp * 0.5:  # the Brood Mother, hurt: red-hot eyes
        style = "queen_rage"
    if sprites.CREATURES.get(enemy.kind, {}).get("maw"):  # her maw gapes in a shriek as she shoots out a brood
        since = enemy.spec["summon"][2] - enemy.summon_timer
        gape = 2 if since < 0.35 else 1 if since < 0.6 else 0
        mouth = pos + ahead * enemy.spec["size"] * 1.02
        blit_center(surf, sprites.maw(enemy.spec["size"], sprites.angle_step(enemy.facing), gape, SCALE), mouth)
    for offset, k in eyes:
        blit_center(surf, sprites.eye(r, look, closed, SCALE, style, k), pos + offset)


def draw_projectile(surf, fx, projectile):
    """Shells trail smoke, fire glows, frost flies as a shard of ice, bullets leave a tracer. A flame tower's
    shots aren't drawn: they fly inside its stream (draw_flame_stream)."""
    spec, color, pos = projectile.spec, projectile.color, projectile.pos
    if spec["look"]["flame"]:
        return
    to = projectile.dest - pos
    d = to.normalize() if to.length_squared() > 1e-6 else pygame.Vector2(1, 0)
    if spec.get("splash", 0) >= 50:
        for i in (3, 2, 1):
            sdraw.circle(fx, (170, 170, 170, 130 - 35 * i), pos - d * 5 * i, 4 - 0.6 * i)
        blit_center(surf, sprites.shell(color, 5, SCALE), pos)
    elif "burn" in spec:
        for i in (3, 2, 1):
            sdraw.circle(fx, (*color, 150 - 40 * i), pos - d * 4 * i, 3.2 - 0.6 * i)
        blit_center(surf, sprites.glow(color, 8, SCALE), pos)
        sdraw.circle(surf, mix(color, (255, 255, 255), 0.6), pos, 2.5)
    elif "slow" in spec:
        blit_center(surf, sprites.ice_shard(sprites.angle_step(d.as_polar()[1]), mix(color, (255, 255, 255), 0.3),
                                            SCALE), pos)
    else:
        sdraw.line(fx, (*color, 110), pos - d * 11, pos, 3)
        sdraw.line(fx, (*mix(color, (255, 255, 255), 0.6), 240), pos - d * 6, pos, 1.5)


def render_map(theme, waypoints):
    """The level's map at the display scale (see terrain.py)."""
    return terrain.render_map(theme, waypoints, SCALE)


# --------------------------------------------------------------------------
# Panel buttons
# --------------------------------------------------------------------------
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
        _texts.clear()
        sprites.clear()
        self.font_s = load_font(11)
        self.font = load_font(14)
        self.font_l = load_font(22, "bold")
        self.font_xl = load_font(36, "bold")
        self.fx_layer = FxLayer(srect((0, 0, MAP_W, MAP_H)).size)
        if hasattr(self, "theme"):
            self.build_map()

    def build_panel_buttons(self):
        """The Towers side panel's buttons, in logical units (so once, whatever the scale)."""
        x = MAP_W + 12
        w = PANEL_W - 24
        third = (w - 8) // 3
        self.tower_buttons = {k: Button((x, 196 + i * 58, w, 52), k) for i, k in enumerate(TOWER_ORDER)}
        self.sell_button = Button((x, 470, w - 84, 36), "Sell")
        self.target_button = Button((x + w - 80, 470, 80, 36), "Target")  # the selected tower's targeting mode
        self.rebuild_button = Button((x, 470, w, 36), "Rebuild")  # shown in the Sell spot when nothing is selected
        self.wave_button = Button((x, HEIGHT - 98, w, 40), "Next wave")
        self.speed_button = Button((x, HEIGHT - 50, third, 38), "Speed")
        self.pause_button = Button((x + third + 4, HEIGHT - 50, third, 38), "Pause")
        self.tree_button = Button((x + 2 * (third + 4), HEIGHT - 50, third, 38), "Tree")

    def build_map(self):
        """The level's map picture and its ambience (portal, gate, particles, glow)."""
        self.map_surface, accents = terrain.map_layers(self.theme, self.waypoints, SCALE)
        self.map_surface = self.map_surface.convert()  # the display's pixel format: blitted every frame
        self.scenery = ambience.Scenery(self.theme, terrain.PATH_STYLES[self.theme.name], self.waypoints, accents)

    def set_display(self, scale, fullscreen):
        """Draw at `scale`, in a window that size, or fullscreen (scale ignored): at the desktop's own
        resolution, the game drawn natively as large as the screen allows, centered (bars only where the
        screen's shape differs from the game's)."""
        self.fullscreen = fullscreen
        if fullscreen:
            display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            display_w, display_h = display.get_size()
            set_scale(math.floor(min(display_w / WIDTH, display_h / HEIGHT) * 1000) / 1000)
            area = pygame.Rect((0, 0), window_size())
            area.center = display.get_rect().center
            area = area.clip(display.get_rect())
            display.fill((0, 0, 0))
            self.screen = display.subsurface(area)  # the game draws straight onto its part of the display
            set_offset(area.topleft)
        else:
            set_scale(scale)
            self.screen = pygame.display.set_mode(window_size())
            set_offset((0, 0))
        self.build_view()

    @staticmethod
    def window_scale():
        """The window's scale: WINDOW_SCALE, or as large as fits on the desktop (leaving room for title bar
        and taskbar)."""
        try:
            desk_w, desk_h = pygame.display.get_desktop_sizes()[0]
        except (pygame.error, IndexError):
            return WINDOW_SCALE
        return min(WINDOW_SCALE, math.floor(min(desk_w / WIDTH, (desk_h - 80) / HEIGHT) * 1000) / 1000)

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
        self.scenery.draw_under(screen, self.clock, SCALE, self.ambient)

        fx = self.fx_layer
        fx.clear()
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
                draw_tower(screen, fx, t, self.clock)
                draw_tower_status(screen, fx, t)
        for e in self.enemies:
            draw_enemy(screen, e)
        for p in self.projectiles:
            draw_projectile(screen, fx, p)
        if self.ambient:
            self.scenery.draw_over(screen, self.clock, SCALE)
        for ef in self.effects:
            ef.draw(fx)
        if self.side == "monsters":
            self.draw_attack_map(fx)
        if self.build_kind or self.dragging:  # straight on the screen: on fx it would mark the whole map
            screen.blit(terrain.grid_lines(SCALE, (255, 255, 255), 50), (0, 0))
        fx.show(screen)
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
            draw_tower_shape(screen, t.spec, pos, t.facing)
        self.draw_fusion_label()
        for p in self.popups:
            blit_text(screen, self.font, p.text, p.color, p.pos, "center", int(255 * (1 - p.t / 0.8)))

        self.draw_boss_bar()
        self.draw_bankrupt_notice()
        overlay = self.overlay
        if overlay is None:
            self.draw_banner()
        if overlay not in ("quit", "rewards", "side_pick"):
            self.draw_state_message()  # level complete, game over...: stays under the screens above
        if overlay:
            {"settings": self.draw_settings, "quit": self.draw_quit_prompt, "side_pick": self.draw_side_pick,
             "rewards": self.draw_rewards, "choice": self.draw_choice, "unlock": self.draw_unlock,
             "tree": self.draw_tree}[overlay]()
        if overlay in (None, "tree"):
            self.draw_tooltip()  # tooltip_view.TooltipView
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
            if other is not t and self.can_fuse(t.kind, other.kind):
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
        elif other and self.can_fuse(t.kind, other.kind):
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
        if not options:
            label, color = "Can't fuse", BAD
        elif any(self.can_make(k) for k in options):
            names = [TOWERS[k]["name"] if self.profile.has_tower(k) else "??? (discovery!)" if self.can_make(k)
                     else TOWERS[k]["name"] + " (locked)" for k in options]
            label, color = "-> " + " / ".join(names), GOLD
        else:
            label, color = "Locked: " + " / ".join(TOWERS[k]["name"] for k in options) + " - see the tree (T)", BAD
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
        sdraw.rect(self.screen, boss_color(spec), (*bar.topleft, bar.width * boss.hp / boss.max_hp, bar.height))
        if boss.barrier > 0:  # the Chairman's dividends, a pale strip over his (gold) health
            sdraw.rect(self.screen, (255, 248, 215), (*bar.topleft, bar.width * min(1.0, boss.barrier / boss.max_hp), 5))
        self.text(self.font, spec["boss"].upper(), boss_color(spec), (bar.centerx, bar.top - 5), "midbottom")
        if self.boss_alert > 0 and self.alert_kind:
            alert = ENEMY_TYPES[self.alert_kind]
            if "follows" in alert:
                return self.draw_grand_alert(alert)
            band = pygame.Surface(sp((MAP_W, 90)), pygame.SRCALPHA)
            band.fill((0, 0, 0, 150))
            title = f"{alert['boss'].upper()} APPROACHES"
            blit_text(band, self.fit_font(title, MAP_W - 32, self.font_xl, self.font_l), title, boss_color(alert),
                      (MAP_W / 2, 45), "center")
            band.set_alpha(int(255 * min(1.0, self.boss_alert)))
            self.screen.blit(band, sp((0, MAP_H / 2 - 45)))

    def draw_bankrupt_notice(self):
        """The Chairman got through: a foreclosure notice drops onto the map, slightly askew, and a red
        BANKRUPT stamp slams onto it."""
        if self.bankrupt_notice <= 0:
            return
        t = BANKRUPT_NOTICE - self.bankrupt_notice  # seconds since he got through
        taken, boss = self.notice_taken
        paper, ink, red = (238, 228, 200), (60, 50, 40), (200, 30, 40)
        w, h = 420, 250
        note = pygame.Surface(sp((w, h)), pygame.SRCALPHA)
        sdraw.rect(note, paper, (0, 0, w, h), border_radius=4)
        sdraw.rect(note, sprites.shade(paper, 0.7), (6, 6, w - 12, h - 12), 2, border_radius=3)
        blit_text(note, self.font, "NOTICE OF FORECLOSURE", ink, (w / 2, 30), "center")
        sdraw.line(note, sprites.shade(paper, 0.7), (40, 48), (w - 40, 48), 1)
        blit_text(note, self.font, f"{boss} took every coin and every tower.", ink, (w / 2, 184), "center")
        blit_text(note, self.font, f"Assets seized: {taken:,} gold", ink, (w / 2, 210), "center")
        slam = min(1.0, max(0.0, (t - 0.5) / 0.15))  # the stamp comes down half a second in
        if slam > 0:
            stamp = pygame.Surface(sp((300, 76)), pygame.SRCALPHA)
            sdraw.rect(stamp, red, (3, 3, 294, 70), 5, border_radius=8)
            blit_text(stamp, self.font_xl, "BANKRUPT", red, (150, 40), "center")
            k = 1 + 0.6 * (1 - slam)  # big, then down onto the paper
            stamp = pygame.transform.rotozoom(stamp, 12, k)
            stamp.set_alpha(round(230 * slam))
            note.blit(stamp, stamp.get_rect(center=sp((w / 2, 104))))
        drop = max(0.0, 1 - t / 0.3)  # the notice drops in from above
        note = pygame.transform.rotozoom(note, -3, 1)
        note.set_alpha(int(255 * min(1.0, self.bankrupt_notice)))
        self.screen.blit(note, note.get_rect(center=sp((MAP_W / 2, MAP_H / 2 - 120 * drop ** 2))))

    def draw_grand_alert(self, spec):
        """A secret boss that follows another walks in: a taller band lit in its colour, edged in light, that
        flashes as it opens; its name, bright and pulsing, over its `announce` line."""
        t = BOSS_ALERT + GRAND_ALERT_EXTRA - self.boss_alert  # seconds since it came
        color, h = boss_color(spec), 150
        bright = tuple(min(255, c + 70) for c in color)
        band = pygame.Surface(sp((MAP_W, h)), pygame.SRCALPHA)
        band.fill((*[c // 4 for c in color], 200))
        flash = max(0.0, 1 - t / 0.5)  # a white-gold flash as the band opens
        if flash:
            band.fill((255, 245, 210, round(200 * flash)), special_flags=pygame.BLEND_RGBA_MAX)
        for y in (2, h - 4):
            sdraw.rect(band, bright, (0, y, MAP_W, 3))
        for i in range(24):  # rays fanning out from behind the name
            d = pygame.Vector2(1, 0).rotate(i * 15 + t * 10)
            center = pygame.Vector2(MAP_W / 2, h / 2)
            sdraw.line(band, (*color, 50), center + d * 60, center + d * MAP_W, 2)
        pulse = 0.5 + 0.5 * math.sin(t * 6)
        title = f"{spec['boss'].upper()} HAS COME"
        title_color = tuple(round(b + (255 - b) * pulse * 0.6) for b in bright)
        blit_text(band, self.fit_font(title, MAP_W - 32, self.font_xl, self.font_l), title, title_color,
                  (MAP_W / 2, h / 2 - 12), "center")
        blit_text(band, self.font_l, spec["follows"]["announce"], bright, (MAP_W / 2, h / 2 + 32), "center")
        band.set_alpha(int(255 * min(1.0, self.boss_alert)))
        self.screen.blit(band, sp((0, MAP_H / 2 - h / 2)))

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
        def make():
            shade = pygame.Surface(sp((MAP_W, MAP_H)), pygame.SRCALPHA).convert_alpha()
            shade.fill((0, 0, 0, alpha))
            return shade

        self.screen.blit(sprites.cached(("shade", alpha, SCALE), make), (0, 0))

    def draw_state_message(self):
        """The message for the level's state: level complete, run over, pass won."""
        run_over = [(f"Levels won this run: {self.levels_won}   (best: {self.profile.best_run})", TEXT, self.font_l),
                    ("Records and unlocks are kept. Press R or click for a new run.", TEXT, self.font)]
        if self.state == "level_complete" and self.side == "monsters":
            lines = [(f"{self.theme.name} breached!", self.theme.accent, self.font_xl),
                     ((f"The towers lost {self.lives_taken} lives here: {self.lives} left for "
                       f"{self.levels_left} more levels"), TEXT, self.font_l),
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
                     ((f"Their last life went at level {self.level_idx + 1}, wave {self.wave_idx}. "
                       f"Pass {self.pass_no} complete."), TEXT, self.font_l),
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
        for s, color, wanted in lines:
            font = wanted
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
            sdraw.rect(self.screen, CARD_HOVER if rect.collidepoint(mouse) else CARD, rect, border_radius=12)
            sdraw.rect(self.screen, self.theme.accent, rect, 3, border_radius=12)
            icon = pygame.Vector2(rect.centerx, rect.top + 46)
            if side == "towers":
                draw_tower_shape(self.screen, TOWERS["railgun"], icon)
            else:
                draw_enemy_icon(self.screen, "juggernaut", icon, 16)
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
            if not self.can_make(kind):  # a branch the player hasn't unlocked: shown, can't be picked
                sdraw.rect(self.screen, CARD, rect, border_radius=10)
                sdraw.rect(self.screen, PANEL_LINE, rect, 2, border_radius=10)
                self.draw_locked_shape(self.screen, kind, pygame.Vector2(rect.centerx, rect.top + 38))
                self.text(self.font_l, spec["name"], TEXT_DIM, (rect.centerx, rect.top + 66), "midtop")
                y = rect.top + 100
                for line in wrap(self.how_to_unlock(kind), 34)[:4]:
                    self.text(self.font_s, line, TEXT_DIM, (rect.centerx, y), "midtop")
                    y += 18
                self.text(self.font, "LOCKED", BAD, (rect.centerx, rect.bottom - 12), "midbottom")
                continue
            hover = rect.collidepoint(mouse)
            sdraw.rect(self.screen, CARD_HOVER if hover else CARD, rect, border_radius=10)
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
            sdraw.rect(self.screen, CARD_HOVER if hover else CARD, rect, border_radius=10)
            sdraw.rect(self.screen, GOLD if card["rare"] else PANEL_LINE, rect, 4 if card["rare"] else 2,
                       border_radius=10)
            icon = pygame.Vector2(rect.centerx, rect.top + 44)
            if card["effect"] == "type":
                draw_enemy_icon(self.screen, card["type"], icon, 16)
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

    @staticmethod
    def tree_spots():
        """(kind, x, y, width) of every tower on the evolution tree, in logical units: the lines' towers (by
        their row, tier 3 branches above and below it), then the finals. A tower's box is (x, y - 18, width, 36)."""
        spots = []
        for row, (t1, t2, branches) in enumerate(LINES.values()):
            y = TREE_TOP + row * TREE_ROW
            spots += [(t1, TREE_COLS[0], y, 180), (t2, TREE_COLS[1], y, 180),
                      (branches[0], TREE_COLS[2], y - 22, 180), (branches[1], TREE_COLS[2], y + 22, 180)]
        for i, kind in enumerate(CROSS.values()):
            spots.append((kind, 30 + (i // 6) * 390, FINALS_TOP + 44 + (i % 6) * 38, 380))
        return spots

    def draw_tree(self):
        """Full-screen evolution chart over the map."""
        self.shade_map(225)
        self.text(self.font_l, "EVOLUTION TREE", GOLD, (MAP_W / 2, 14), "midtop")
        self.text(self.font_s, "Fuse two identical towers to evolve them. Tier 2 -> 3 lets you pick a branch.",
                  TEXT_DIM, (MAP_W / 2, 46), "midtop")
        for row in range(len(LINES)):
            y = TREE_TOP + row * TREE_ROW
            self.text(self.font_s, "x2 ->", TEXT_DIM, (TREE_COLS[1] - 66, y), "midleft")
            self.text(self.font_s, "x2 ->", TEXT_DIM, (TREE_COLS[2] - 66, y), "midleft")
        self.text(self.font, "FINAL FORMS: fuse two tier 3 towers from different lines", GOLD, (MAP_W / 2, FINALS_TOP),
                  "midtop")
        self.tree_hint = None  # how to unlock the locked tower under the mouse
        for kind, x, y, w in self.tree_spots():
            (self.tree_final if TOWERS[kind]["tier"] == 4 else self.tree_node)(kind, x, y)
            if not self.profile.has_tower(kind) and pygame.Rect(x, y - 18, w, 36).collidepoint(mouse_pos()):
                self.tree_hint = (kind, self.how_to_unlock(kind))
        discovery = self.profile.discoveries_left > 0  # locked finals can still be found by fusing them
        if self.tree_hint:
            kind, hint = self.tree_hint
            name = "???" if TOWERS[kind]["tier"] == 4 and discovery else TOWERS[kind]["name"]
            label = f"{name}: {hint}"
            self.text(self.fit_font(label, MAP_W - 32, self.font_s), label, GOLD, (MAP_W / 2, 326), "midtop")
        elif len(self.profile.towers_unlocked) < len(TOWERS):
            self.text(self.font_s, "Point at a locked tower to see how to unlock it", TEXT_DIM, (MAP_W / 2, 326),
                      "midtop")
        self.text(self.font_s, "Right click a tower for its stats.  T, Esc or click to close", TEXT_DIM,
                  (MAP_W - 10, MAP_H - 8), "bottomright")

    def tree_node(self, kind, x, y):
        spec = TOWERS[kind]
        if self.profile.has_tower(kind):
            draw_tower_shape(self.screen, spec, pygame.Vector2(x + 16, y))
            self.text(self.font, spec["name"], spec["color"], (x + 42, y), "midleft")
            return
        self.draw_locked_shape(self.screen, kind, pygame.Vector2(x + 16, y))
        self.text(self.font, spec["name"], TEXT_DIM, (x + 42, y), "midleft")
        goal, progress = self.unlock_goals(kind)[0]
        if goal["target"] > 1 and self.tracker.available(kind):  # under the name, clear of the arrows and branch
            self.text(self.font_s, f"{min(int(progress), goal['target'])}/{goal['target']}", GOLD, (x + 42, y + 9))

    def tree_final(self, kind, x, y):
        """A final form's row: its name, its parents and its line (or, while locked, how to get it)."""
        spec = TOWERS[kind]
        a, b = sorted(next(pair for pair, k in CROSS.items() if k == kind), key=list(TOWERS).index)
        parents = f"{TOWERS[a]['name']} + {TOWERS[b]['name']}"
        if self.profile.has_tower(kind):
            draw_tower_shape(self.screen, spec, pygame.Vector2(x + 16, y))
            r = self.text(self.font, spec["name"], spec["color"], (x + 42, y - 14))
            self.text(self.font_s, parents, TEXT, (r.right / SCALE + 10, r.bottom / SCALE), "bottomleft")
            self.text(self.font_s, spec["desc"], TEXT_DIM, (x + 42, y + 3))
            return
        discovery = self.profile.discoveries_left > 0  # locked finals can still be found by fusing them
        self.draw_locked_shape(self.screen, kind, pygame.Vector2(x + 16, y))
        r = self.text(self.font, "???" if discovery else spec["name"], TEXT_DIM, (x + 42, y - 14))
        self.text(self.font_s, parents, TEXT, (r.right / SCALE + 10, r.bottom / SCALE), "bottomleft")
        goal, progress = self.unlock_goals(kind)[0]
        line = self.needs_first(kind) or ("Fuse them to discover it" if discovery else self.goal_text(goal, progress))
        self.text(self.fit_font(line, 340, self.font_s), line, TEXT_DIM, (x + 42, y + 3))

    @staticmethod
    def ambient_button():
        return pygame.Rect(MAP_W / 2 - 385, 300, 185, 40)

    @staticmethod
    def fullscreen_button():
        return pygame.Rect(MAP_W / 2 - 190, 300, 185, 40)

    @staticmethod
    def music_button():
        return pygame.Rect(MAP_W / 2 + 5, 300, 185, 40)

    @staticmethod
    def sfx_button():
        return pygame.Rect(MAP_W / 2 + 200, 300, 185, 40)

    @staticmethod
    def settings_close_button():
        return pygame.Rect(MAP_W / 2 - 110, 380, 220, 50)

    @staticmethod
    def settings_continue_button():
        return pygame.Rect(MAP_W / 2 - 150, 442, 300, 50)

    def draw_settings(self):
        self.shade_map(225)
        self.text(self.font_xl, "SETTINGS", GOLD, (MAP_W / 2, 150), "midtop")
        mouse = mouse_pos()
        w, h = window_size()
        size = f"Window {w} x {h}"
        if self.fullscreen:
            size = "Fullscreen {} x {}, game {} x {}".format(*pygame.display.get_surface().get_size(), w, h)
        self.text(self.font, size, TEXT, (MAP_W / 2, 255), "midtop")
        on_off = lambda on: "On" if on else "Off"
        percent = lambda v: f"{v}%" if v else "Off"
        for rect, on, label in (
                (self.ambient_button(), self.ambient, f"Ambient: {on_off(self.ambient)}  [A]"),
                (self.fullscreen_button(), self.fullscreen, f"Fullscreen: {on_off(self.fullscreen)}  [F11]"),
                (self.music_button(), self.music_volume > 0, f"Music: {percent(self.music_volume)}  [M]"),
                (self.sfx_button(), self.sfx_volume > 0, f"Sound: {percent(self.sfx_volume)}  [N]")):
            sdraw.rect(self.screen, BUTTON_HOVER if rect.collidepoint(mouse) else CARD_HOVER, rect, border_radius=8)
            sdraw.rect(self.screen, GOLD if on else PANEL_LINE, rect, 2 if on else 1, border_radius=8)
            self.text(self.font, label, TEXT if on else TEXT_DIM, rect.center, "center")
        b = self.settings_close_button()
        sdraw.rect(self.screen, BUTTON_HOVER if b.collidepoint(mouse) else BUTTON, b, border_radius=8)
        sdraw.rect(self.screen, self.theme.accent, b, 3, border_radius=8)
        label = "Play  [Enter]" if self.untouched else "Resume  [Enter]"
        hint_y = 460
        if self.can_continue:
            label = "New game  [Enter]"
            c = self.settings_continue_button()
            theme = LEVELS[self.save["level"]][0]
            sdraw.rect(self.screen, BUTTON_HOVER if c.collidepoint(mouse) else BUTTON, c, border_radius=8)
            sdraw.rect(self.screen, theme.accent, c, 3, border_radius=8)
            self.text(self.font, f"Continue: level {self.save['level'] + 1}, {theme.name}  [C]", TEXT, c.center,
                      "center")
            hint_y = 520
        self.text(self.font, label, TEXT, b.center, "center")
        self.text(self.font_s, "Press O in game to come back here. The choice is saved for next time.",
                  TEXT_DIM, (MAP_W / 2, hint_y), "midtop")

    def draw_button(self, b, label, enabled=True, active=False, font=None):
        hover = b.rect.collidepoint(mouse_pos())
        bg = BUTTON if enabled else BUTTON_OFF
        if enabled and hover:
            bg = BUTTON_HOVER
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
            if not self.profile.has_tower(kind):
                sdraw.rect(screen, BUTTON_OFF, b.rect, border_radius=6)
                sdraw.rect(screen, PANEL_LINE, b.rect, 1, border_radius=6)
                self.draw_locked_shape(screen, kind, pygame.Vector2(b.rect.left + 28, b.rect.centery))
                self.text(self.font, f"{spec['name']} [{i + 1}]", TEXT_DIM, (b.rect.left + 56, b.rect.centery - 8),
                          "midleft")
                self.text(self.font_s, "Locked - press T", TEXT_DIM, (b.rect.left + 56, b.rect.centery + 10),
                          "midleft")
                continue
            affordable = self.gold >= spec["cost"]
            active = self.build_kind == kind
            bg = BUTTON if b.rect.collidepoint(mouse_pos()) else BUTTON_QUIET
            sdraw.rect(screen, bg, b.rect, border_radius=6)
            sdraw.rect(screen, self.theme.accent if active else PANEL_LINE, b.rect,
                       3 if active else 1, border_radius=6)
            draw_tower_shape(screen, spec, pygame.Vector2(b.rect.left + 28, b.rect.centery))
            self.text(self.font, f"{spec['name']} [{i + 1}]", TEXT if affordable else TEXT_DIM,
                      (b.rect.left + 56, b.rect.centery - 8), "midleft")
            self.text(self.font_s, f"{spec['cost']}g - {spec['desc']}", GOLD if affordable else TEXT_DIM,
                      (b.rect.left + 56, b.rect.centery + 10), "midleft")
            if kind in self.profile.new_towers:
                self.text(self.font_s, "NEW", GOLD, (b.rect.right - 6, b.rect.top + 5), "topright")

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
            self.draw_button(self.target_button, f"{TARGETING[t.targeting]} [G]", True)
        elif self.draw_next_goal(x, 374):
            pass  # a tower still to unlock: its goal takes the hints' place
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

        self.draw_wave_preview(x)
        self.draw_panel_footer()

    def wave_preview(self):
        """(label, [(kind, count)] most first, the scouts' counters) for the wave preview: the next wave in the
        build phase, what's still to come of it during a wave, None otherwise."""
        if self.state == "build":
            _, wave = self.next_wave()
            label, kinds, counter = "Next", wave.kinds, wave.counter
        elif self.state == "wave":
            label, kinds, counter = "Coming", self.spawn_queue, self.wave_counter
        else:
            return None
        return label, sorted(Counter(kinds).items(), key=lambda kc: -kc[1]), counter

    def preview_icons(self, preview=None):
        """(kind, count, center) of each monster icon the wave preview shows (the rest show as a "+n")."""
        preview = preview or self.wave_preview()
        if not preview:
            return []
        label, counts, _ = preview
        left = MAP_W + 12 + self.font_s.size(label)[0] / SCALE + 14
        shown = counts if len(counts) <= PREVIEW_KINDS else counts[:PREVIEW_KINDS - 1]
        return [(kind, n, pygame.Vector2(left + i * 38, PREVIEW_Y)) for i, (kind, n) in enumerate(shown)]

    def draw_wave_preview(self, x):
        """The next wave's monsters in the build phase (those still to come during a wave), most first, and
        what the scouts countered."""
        preview = self.wave_preview()
        if not preview:
            return
        label, counts, counter = preview
        self.text(self.font_s, label, TEXT_DIM, (x, PREVIEW_Y), "midleft")
        icons = self.preview_icons(preview)
        for kind, n, center in icons:
            draw_enemy_icon(self.screen, kind, center, 7)
            self.text(self.font_s, str(n), TEXT, (center.x + 10, PREVIEW_Y), "midleft")
        if len(icons) < len(counts):
            more = sum(n for _, n in counts[len(icons):])
            left = x + self.font_s.size(label)[0] / SCALE + 14
            self.text(self.font_s, f"+{more}", TEXT_DIM, (left + len(icons) * 38 - 6, PREVIEW_Y), "midleft")
        if counter:
            reasons = counter["reasons"]
            note = "Scouts: " + ", ".join(reasons)
            if self.font_s.size(note)[0] > (PANEL_W - 24) * SCALE:
                note = f"Scouts: {reasons[0]} +{len(reasons) - 1}"
            self.text(self.font_s, note, BAD, (x, PREVIEW_Y + 17), "midleft")

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
            left = sum(1 for e in self.enemies if not e.illusion) + len(self.spawn_queue)
            label, enabled = f"{left} {'enemy' if left == 1 else 'enemies'} left", False
        self.draw_button(self.wave_button, label, enabled, active=enabled)
        self.draw_button(self.speed_button, f"F:{self.speed}x", True, active=self.speed > 1, font=self.font_s)
        locked = self.profile.pause_locked and not self.paused  # a pause_trap boss (main.Game.press_pause)
        self.draw_button(self.pause_button, "P:Locked" if locked else "P:Pause", not locked, active=self.paused,
                         font=self.font_s)
        self.draw_button(self.tree_button, "T:Tree", True, active=self.show_tree, font=self.font_s)
