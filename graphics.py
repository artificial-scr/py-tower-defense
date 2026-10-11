"""Everything the tower defense draws: layout, colors, display scaling, shapes, visual
effects, and GameView, the drawing half of main.Game.

The game runs in fixed logical units (the WIDTH x HEIGHT layout below); only drawing and
mouse input go through SCALE. Everything is drawn natively at the chosen size, so there is
no per-frame image scaling: changing the scale re-renders the map and fonts once.

This module doesn't import main (that would load the game twice when it's run as a
script); GameView reads the game state through `self`.
"""

import pygame

from levels import BOSS_LEVELS, COLS, ENEMY_TYPES, LEVELS, ROWS, WAVES_PER_LEVEL
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

PANEL_BG = (28, 28, 34)
PANEL_LINE = (60, 60, 72)
TEXT = (235, 235, 240)
TEXT_DIM = (150, 150, 160)
GOOD = (90, 220, 110)
BAD = (235, 80, 80)
GOLD = (255, 210, 70)
TIER_RIM = {1: (15, 15, 20), 2: (176, 116, 64), 3: (205, 205, 220), 4: GOLD}


def shade(color, k):
    return tuple(min(255, int(c * k)) for c in color)


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


def draw_enemy(surf, enemy):
    spec = enemy.spec
    size = spec["size"]
    color = spec["color"]
    sides = spec["sides"]
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


def render_map(theme, waypoints):
    surf = pygame.Surface(sp((MAP_W, MAP_H)))
    for ty in range(ROWS):
        for tx in range(COLS):
            color = theme.ground if (tx + ty) % 2 == 0 else shade(theme.ground, 0.92)
            sdraw.fill(surf, color, (tx * TILE, ty * TILE, TILE, TILE))
    # Path: an edge-colored band with the path color inset, so corners join cleanly.
    for inset, color in ((0, shade(theme.path, 0.7)), (5, theme.path)):
        for (x0, y0), (x1, y1) in zip(waypoints, waypoints[1:]):
            left, right = min(x0, x1), max(x0, x1)
            top, bottom = min(y0, y1), max(y0, y1)
            rect = pygame.Rect(left * TILE + inset, top * TILE + inset,
                               (right - left + 1) * TILE - 2 * inset, (bottom - top + 1) * TILE - 2 * inset)
            sdraw.fill(surf, color, rect)
    return surf


# --------------------------------------------------------------------------
# Visual effects (they only age; they don't affect the game)
# --------------------------------------------------------------------------
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
                draw_tower_shape(screen, t.spec, t.pos, t.aim)
        for e in self.enemies:
            draw_enemy(screen, e)
        for p in self.projectiles:
            draw_projectile(screen, p)
        for ef in self.effects:
            ef.draw(fx)
        screen.blit(fx, (0, 0))
        mx, my = mouse_pos()
        hover = tile_center(mx // TILE, my // TILE)
        if self.build_kind and mx < MAP_W:
            draw_tower_shape(screen, TOWERS[self.build_kind], hover)
        if self.dragging:
            t = self.dragging
            draw_tower_shape(screen, t.spec, hover if mx < MAP_W else t.pos, t.aim)
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
            draw_tower_shape(self.screen, spec, pygame.Vector2(rect.centerx, rect.top + 38))
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
            spec = TOWERS[kind]
            draw_tower_shape(self.screen, spec, pygame.Vector2(x + 16, y))
            self.text(self.font, spec["name"], spec["color"], (x + 42, y - 16))
            self.text(self.font_s, f"{TOWERS[a]['name']} + {TOWERS[b]['name']}: {spec['desc']}", TEXT_DIM,
                      (x + 42, y + 3))
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
            draw_tower_shape(screen, spec, pygame.Vector2(b.rect.left + 28, b.rect.centery))
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
