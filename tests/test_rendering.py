"""Drawing: every screen renders at every scale, and (optionally) pixel snapshots.

The snapshot test compares a hash of each screen against tests/snapshots.json, so a refactor
that changes a single pixel is caught. Font rendering can differ between pygame versions, so
it only runs with the pygame version the snapshots were recorded with. After an intended
visual change, re-record them:

    UPDATE_SNAPSHOTS=1 uv run pytest tests/test_rendering.py
"""

import hashlib
import json
import os

import pygame
import pytest

import ambience
import graphics
import levels
import main
import sprites
import terrain
from entities import Projectile
from graphics import HEIGHT, MAP_H, MAP_W, PANEL_W, SCALES, TILE, tile_center
from helpers import dummy_enemy, free_tiles, put, scaled
from monsters import ENEMY_TYPES
from towers import CROSS, EVOLVE, TOWERS

SNAPSHOTS = os.path.join(os.path.dirname(__file__), "snapshots.json")


def scenes(scale, mouse, monkeypatch):
    """Put a fresh game through every screen; yields (name, game) for each one to draw."""
    monkeypatch.setattr(main.Game, "scale_fits", staticmethod(lambda k: k <= 1.5))
    graphics.set_scale(scale)
    g = main.Game(pygame.display.set_mode(graphics.window_size()), log_dir=None)
    g.show_settings = True
    mouse[:] = scaled((400, 275), scale)
    yield "settings", g
    g.show_settings = False
    mouse[:] = 0, 0
    yield "banner", g
    g.banner_timer = 0
    free = free_tiles(g)
    kinds = [k for k, s in TOWERS.items() if s["tier"] < 4] + list(CROSS.values())
    for tile, kind in zip(free[::3], kinds):
        put(g, kind, tile)
    g.gold = 5000
    g.start_wave()
    for _ in range(400):
        g.update(1 / 60)
    yield "battle", g
    g.selected = next(iter(g.towers.values()))
    yield "selected", g
    g.selected = None
    g.build_kind = "gun"
    mouse[:] = scaled(tile_center(*free[1]), scale)
    yield "build", g
    mouse[:] = scaled(tile_center(*free[0]), scale)
    yield "build_fuse", g
    g.build_kind = None
    g.dragging = g.towers[free[3]]
    yield "drag", g
    g.dragging = None
    mouse[:] = 0, 0
    g.show_tree = True
    yield "tree", g
    g.show_tree = False
    g.choice = (g.towers[free[0]], EVOLVE["rifle"])
    yield "choice", g
    g.choice = None
    g.confirm_quit = True
    yield "quit", g
    g.confirm_quit = False
    g.paused = True
    yield "paused", g
    g.paused = False
    g.speed = 4
    yield "speed", g
    for state in ("level_complete", "game_over", "victory"):
        g.state = state
        yield state, g
    g.load_level(9)
    g.banner_timer = 0
    g.wave_idx = 4
    monkeypatch.setattr(main, "make_wave", lambda level_idx, wave_idx: (["warden"], 5))
    g.start_wave()
    for _ in range(300):
        g.update(1 / 60)
    yield "boss", g
    g.boss_alert = 0
    yield "boss_no_alert", g
    g.load_level(len(main.LEVELS) - 1)
    yield "last_level_banner", g


@pytest.mark.parametrize("scale", SCALES)
def test_every_screen_draws(scale, mouse, monkeypatch):
    for name, g in scenes(scale, mouse, monkeypatch):
        g.draw()
        assert g.screen.get_size() == graphics.window_size(scale), name
    # the panel's level header is drawn in the level's accent color
    assert g.screen.get_at(scaled((graphics.MAP_W + 20, 20), scale))[:3] == g.theme.accent


def test_every_tower_draws(screen):
    for spec in TOWERS.values():
        graphics.draw_tower_shape(screen, spec, pygame.Vector2(100, 100), 30)
        graphics.draw_tower_shape(screen, spec, pygame.Vector2(100, 100), 30, kick=1.0)


@pytest.mark.parametrize("scale", (0.75, 1.5))
def test_every_enemy_draws_in_every_look(scale):
    """Every frame of every creature draws; a hit enemy is drawn wider and flatter, a phased one see-through."""
    graphics.set_scale(scale)
    for kind, spec in ENEMY_TYPES.items():
        for frame in range(sprites.FRAMES):
            normal = sprites.enemy_body(kind, 0, scale, frame=frame)
            assert normal.get_width() >= 2 * spec["size"] * scale, kind
        hit = sprites.enemy_body(kind, 0, scale, "hit")
        phased = sprites.enemy_body(kind, 0, scale, "phased")
        assert hit.get_width() > normal.get_width() > hit.get_height()
        assert phased.get_at(phased.get_rect().center).a < normal.get_at(normal.get_rect().center).a
        assert sprites.enemy_icon(kind, 8, scale).get_width() >= 16 * scale
        design = sprites.CREATURES.get(kind, {})
        if "face" in design:
            assert sprites.enemy_face(kind, 0, scale, "hit").get_width() > 0
        if "corona" in design:
            assert sprites.enemy_corona(kind, 0, scale).get_width() > normal.get_width() / 2
        r, style, eyes = sprites.eye_layout(kind, spec["size"], pygame.Vector2(1, 0))
        for k in (-1, 1):
            sprites.eye(r, 0, False, scale, style, k)
            sprites.eye(r, 0, True, scale, style, k)


def test_creatures_face_where_they_walk_and_step_as_they_go():
    """Drawing only: an enemy turns round a corner gradually, and walkers' animation follows the distance walked."""
    path = [pygame.Vector2(0, 0), pygame.Vector2(100, 0), pygame.Vector2(100, 300)]
    e = main.Enemy("basic", path, 1)
    frames = set()
    for _ in range(40):
        e.update(1 / 60)
        frames.add(graphics.enemy_frame(e))
    assert e.facing == 0 and len(frames) > 2
    while e.idx < 2:
        e.update(1 / 60)
    e.update(1 / 60)
    assert 0 < e.facing < 90, "turning"
    for _ in range(30):
        e.update(1 / 60)
    assert e.facing == 90
    still = graphics.enemy_frame(e)
    e.slow_factor, e.slow_timer = 0.0, 5.0
    e.update(1 / 60)
    assert graphics.enemy_frame(e) == still, "a frozen walker stops stepping"


def test_sprites_are_drawn_once_per_scale(screen):
    spec = TOWERS["gun"]
    assert sprites.tower_turret(spec, 5, 1.0) is sprites.tower_turret(spec, 5, 1.0)
    assert sprites.tower_turret(spec, 5, 1.0) is not sprites.tower_turret(spec, 6, 1.0)
    assert sprites.angle_step(-90) == sprites.angle_step(270) == 54
    g = main.Game(screen, log_dir=None)
    sprites.tower_turret(spec, 5, 1.0)
    g.apply_scale(1.5)
    assert ("turret", spec["name"], 5, 1.0) not in sprites._cache, "a scale change forgets the old pictures"


def test_every_projectile_and_effect_draws(game):
    """Each kind of shot (shell, fire, ice, bullet), and what it leaves behind when it lands."""
    fx = game.fx_layer
    for kind, spec in TOWERS.items():
        if spec.get("instant"):
            continue
        tower = put(game, kind, (5, 5))
        enemies = [dummy_enemy((tower.pos.x + 70, tower.pos.y))]
        p = Projectile(tower, enemies[0])
        p.update(0.02, enemies, game.effects)
        graphics.draw_projectile(game.screen, fx, p)
        while not p.done:
            p.update(1 / 60, enemies, game.effects)
        del game.towers[tower.tile]
    tesla = put(game, "tesla", (5, 5))
    tesla.update(0.01, [dummy_enemy((tesla.pos.x + 60 + i * 30, tesla.pos.y)) for i in range(3)], [], game.effects)
    kinds = {type(e).__name__ for e in game.effects}
    assert {"Explosion", "Sparks", "Ring", "Beam"} <= kinds
    for e in game.effects:
        for _ in range(3):
            e.draw(fx)
            e.update(0.07)
    graphics.draw_tower(game.screen, fx, tesla, 1.0)


def average(surf, rect):
    """The average color of a logical rect of a 1x surface."""
    return pygame.transform.average_color(surf, pygame.Rect(rect))[:3]


def test_level_maps_use_their_theme(screen):
    """The ground stays close to the theme's ground color, and the path's floor to its path color (both are
    textured, so it's the averages that are compared; crust paths are mostly dark plates)."""
    for theme, waypoints in levels.ALL_LEVELS:
        surf = graphics.render_map(theme, waypoints)
        x, y = waypoints[1]
        floor = average(surf, (x * TILE + 10, y * TILE + 10, TILE - 20, TILE - 20))
        ground = average(surf, (0, 0, MAP_W, MAP_H))
        style = terrain.PATH_STYLES[theme.name]
        expected = {"neon": terrain.mix(theme.ground, theme.path, 0.12), "crust": terrain.shade(theme.path, 0.4)}.get(
            style, theme.path)
        assert all(abs(c - e) <= 60 for c, e in zip(floor, expected)), (theme.name, floor)
        assert all(abs(c - g) <= 30 for c, g in zip(ground, theme.ground)), (theme.name, ground)


def test_every_theme_has_its_ground_path_and_props():
    names = {theme.name for theme, _ in levels.ALL_LEVELS}
    assert names <= set(terrain.PATCHES) and names <= set(terrain.PATH_STYLES) and names <= set(terrain.DECOR)
    assert set(terrain.PATH_STYLES.values()) <= set(terrain.DETAIL)
    for kind in terrain.PROPS:
        for variant in range(terrain.PROP_VARIANTS):
            assert terrain.prop(kind, (120, 120, 120), variant, 1.0).get_bounding_rect().width > 0, kind


def test_every_theme_has_its_ambience():
    """Particles for every theme: inside the map, fading in and out, the same at the same moment."""
    assert set(ambience.AMBIENT) == {t.name for t in levels.THEMES}
    assert ambience.GLOWING <= set(ambience.AMBIENT)
    for theme in levels.THEMES:
        for t in (0.0, 3.7, 125.2):
            now = ambience.particles(theme, t)
            assert now and now == ambience.particles(theme, t)
            for look, color, size, turn, center, alpha in now:
                assert 0 <= center.x < MAP_W and 0 <= center.y < MAP_H
                assert 0 <= alpha <= 1
                img = ambience.particle(look, color, size, turn, 1.0)
                assert img.get_bounding_rect().width > 0
        assert ambience.particles(theme, 1.0) != ambience.particles(theme, 1.5), "they move"


def test_portal_and_gate_sit_on_the_ends_of_the_path():
    for theme, waypoints in levels.ALL_LEVELS:
        on_path = terrain.path_tiles(waypoints)
        for center, heading in ambience.ends(waypoints):
            tile = (int(center.x // TILE), int(center.y // TILE))
            assert tile in on_path and 0 <= tile[0] < levels.COLS and 0 <= tile[1] < levels.ROWS
            assert heading.length() == pytest.approx(1)


def test_ambient_effects_move_and_can_be_turned_off(screen):
    """The pulse, the particles and the portal's swirl follow the game clock; with Ambient effects off,
    the map stands still (the portal and gate stay)."""
    g = main.Game(screen, log_dir=None)
    g.load_level(3)  # Volcano: embers, glowing cracks
    g.banner_timer = 0
    frames = {}
    for ambient in (True, False):
        g.ambient = ambient
        for t in (1.0, 2.3):
            g.clock = t
            g.draw()
            frames[ambient, t] = pygame.image.tobytes(screen.subsurface(graphics.srect((0, 0, MAP_W, MAP_H))), "RGB")
    assert frames[True, 1.0] != frames[True, 2.3]
    assert frames[False, 1.0] == frames[False, 2.3]
    portal, _ = ambience.ends(g.waypoints)[0]
    plain = terrain.render_map(g.theme, g.waypoints, 1.0)
    assert screen.get_at((int(portal.x), int(portal.y))) != plain.get_at((int(portal.x), int(portal.y)))


def test_the_grid_shows_clearly_while_placing_a_tower(game, mouse):
    """A faint grid is always there; placing a tower lays a clearer one over the map."""
    tile = next(t for t in free_tiles(game) if t[0] > 0)
    corner = (tile[0] * TILE, tile[1] * TILE + 15)  # on a grid line, between two tiles
    game.banner_timer = 0
    game.draw()
    before = game.screen.get_at(corner)
    game.build_kind = "gun"
    mouse[:] = 700, 600
    game.draw()
    assert sum(game.screen.get_at(corner)[:3]) > sum(before[:3])


def test_maps_look_the_same_every_time(screen):
    theme, waypoints = main.LEVELS[0]
    first = pygame.image.tobytes(graphics.render_map(theme, waypoints), "RGB")
    assert pygame.image.tobytes(graphics.render_map(theme, waypoints), "RGB") == first


@pytest.mark.parametrize("scale", (0.75, 1.0))
def test_text_stays_on_its_side(scale, mouse, monkeypatch):
    """Orbitron is a wide font: no text may run off the map, or off the panel, on either side's screens."""
    spills = []
    text = graphics.GameView.text

    def checked(self, font, s, color, pos, anchor="topleft"):
        rect = text(self, font, s, color, pos, anchor)
        area = (0, 0, MAP_W, MAP_H) if pos[0] < MAP_W else (MAP_W, 0, PANEL_W - 6, HEIGHT)
        if not graphics.srect(area).contains(rect):
            spills.append(s)
        return rect

    monkeypatch.setattr(graphics.GameView, "text", checked)
    for _, g in scenes(scale, mouse, monkeypatch):
        g.draw()
    m = main.Game(g.screen, log_dir=None, side="monsters")
    m.draft("basic", 5)
    m.draw()
    m.send_wave()
    m.draw()
    for state in ("level_complete", "game_over", "victory"):
        m.state = state
        m.draw()
    assert not spills


def frame_hashes(mouse, monkeypatch):
    hashes = {}
    for scale in (1.0, 1.5):
        for name, g in scenes(scale, mouse, monkeypatch):
            g.draw()
            hashes[f"{scale:g}x {name}"] = hashlib.sha1(pygame.image.tobytes(g.screen, "RGB")).hexdigest()[:16]
    return hashes


def test_snapshots(mouse, monkeypatch):
    hashes = frame_hashes(mouse, monkeypatch)
    if os.environ.get("UPDATE_SNAPSHOTS"):
        with open(SNAPSHOTS, "w", encoding="utf-8") as f:
            json.dump({"pygame": pygame.version.ver, "frames": hashes}, f, indent=1)
            f.write("\n")
        pytest.skip(f"recorded {len(hashes)} snapshots")
    if not os.path.exists(SNAPSHOTS):
        pytest.skip("no snapshots recorded; run with UPDATE_SNAPSHOTS=1")
    with open(SNAPSHOTS, encoding="utf-8") as f:
        recorded = json.load(f)
    if recorded["pygame"] != pygame.version.ver:
        pytest.skip(f"snapshots were recorded with pygame {recorded['pygame']}, this is {pygame.version.ver}")
    changed = [name for name, h in hashes.items() if recorded["frames"].get(name) != h]
    assert not changed, f"screens that look different: {changed} (UPDATE_SNAPSHOTS=1 if intended)"
