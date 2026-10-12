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

import graphics
import levels
import main
from graphics import HEIGHT, MAP_H, MAP_W, PANEL_W, SCALES, tile_center
from helpers import free_tiles, put, scaled
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


def test_level_maps_use_their_theme(screen):
    for theme, waypoints in main.LEVELS:
        surf = graphics.render_map(theme, waypoints)
        x, y = waypoints[1]
        assert surf.get_at(graphics.tile_center(x, y))[:3] == theme.path
        # tiles are the ground color, a little lighter or darker (a faint checkerboard with some variation)
        corner = surf.get_at((2, 2))[:3]
        assert all(0.9 * g - 1 <= c <= 1.03 * g + 1 for c, g in zip(corner, theme.ground)), (theme.name, corner)


def test_maps_look_the_same_every_time(screen):
    theme, waypoints = main.LEVELS[0]
    first = pygame.image.tobytes(graphics.render_map(theme, waypoints), "RGB")
    assert pygame.image.tobytes(graphics.render_map(theme, waypoints), "RGB") == first


def test_every_theme_has_decoration():
    assert {theme.name for theme, _ in levels.ALL_LEVELS} <= set(graphics.DECOR)


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
