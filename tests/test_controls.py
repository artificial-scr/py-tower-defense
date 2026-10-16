"""Keyboard and mouse controls: speed, Esc / quit prompt, settings overlay, input at every scale."""

import json
import os

import pygame
import pytest

import graphics
import main
from helpers import SCALES, key, mouse_down, mouse_up, put, scaled
from levels import tile_center


# ---- speed ----------------------------------------------------------------------
def test_speed_cycles_with_f(game, monkeypatch):
    seen = []
    for _ in range(4):
        game.handle_event(key(pygame.K_f))
        seen.append(game.speed)
    assert seen == [2, 4, 10, 1]
    monkeypatch.setattr(pygame.key, "get_mods", lambda: pygame.KMOD_SHIFT)
    game.handle_event(key(pygame.K_f, pygame.KMOD_SHIFT))
    assert game.speed == 10, "Shift+F goes back"


def test_speed_button(game):
    game.handle_event(mouse_down(game.speed_button.rect.center))
    game.handle_event(mouse_up(game.speed_button.rect.center))
    assert game.speed == 2


def test_banners_run_in_real_time(game):
    game.speed = 10
    game.start_wave()
    game.banner_timer = 1.0
    game.tick(1 / 60)  # one frame at 10x: ten updates
    assert game.banner_timer == pytest.approx(1.0 - 1 / 60)


def test_speed_only_applies_during_waves(game):
    """Building runs in real time whatever the speed; a wave runs `speed` updates a frame."""
    game.speed = 4
    game.tick(1 / 60)
    assert game.clock == pytest.approx(1 / 60) and game.pace == 1
    game.start_wave()
    assert game.pace == 4
    before = game.clock
    game.tick(1 / 60)
    assert game.clock - before == pytest.approx(4 / 60)
    game.spawn_queue, game.enemies = [], []
    before = game.clock
    game.tick(1 / 60)  # the wave ends on the first update: the rest of the frame isn't sped up
    assert game.state == "build" and game.clock - before == pytest.approx(1 / 60)


# ---- Esc and quitting ---------------------------------------------------------------
def test_esc_cancels_before_asking(game):
    game.pick_tower("gun")
    game.handle_event(key(pygame.K_ESCAPE))
    assert game.build_kind is None and not game.confirm_quit
    game.selected = put(game, "gun", (2, 5))
    game.handle_event(key(pygame.K_ESCAPE))
    assert game.selected is None and not game.confirm_quit
    game.show_tree = True
    game.handle_event(key(pygame.K_ESCAPE))
    assert not game.show_tree and not game.confirm_quit
    game.handle_event(key(pygame.K_ESCAPE))
    assert game.confirm_quit and game.frozen


@pytest.mark.parametrize("k", [pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_y])
def test_quit_prompt_confirms(game, k):
    game.confirm_quit = True
    game.handle_event(key(k))
    assert not game.confirm_quit and pygame.event.peek(pygame.QUIT)


@pytest.mark.parametrize("event", [key(pygame.K_a), mouse_down((5, 5))])
def test_quit_prompt_cancels(game, event):
    game.confirm_quit = True
    game.handle_event(event)
    assert not game.confirm_quit and not pygame.event.peek(pygame.QUIT)
    assert not game.towers, "the cancelling click doesn't also act on the map"


def test_quit_prompt_while_paused(game):
    game.paused = True
    game.handle_event(key(pygame.K_ESCAPE))
    assert game.confirm_quit


# ---- settings overlay ---------------------------------------------------------------
def desktop(monkeypatch, w, h):
    monkeypatch.setattr(pygame.display, "get_desktop_sizes", lambda: [(w, h)])


def test_the_window_is_200_percent_or_as_large_as_fits(monkeypatch):
    desktop(monkeypatch, 2560, 1440)
    assert main.Game.window_scale() == graphics.WINDOW_SCALE == 2.0
    desktop(monkeypatch, 1920, 1080)
    assert main.Game.window_scale() == 1.562, "1000 px of height left under the title bar and taskbar"
    assert round(graphics.HEIGHT * 1.562) <= 1080 - 80


def test_settings_keys_no_longer_resize(game):
    game.show_settings = True
    for k in (pygame.K_RIGHT, pygame.K_LEFT, pygame.K_MINUS, pygame.K_EQUALS):
        game.handle_event(key(k))
    assert graphics.SCALE == 1.0 and game.show_settings
    game.handle_event(mouse_down(game.settings_close_button().center))
    assert not game.show_settings and not os.path.exists(main.SETTINGS_FILE), "no scale to save"


def test_ambient_effects_toggle_is_saved(game, screen):
    game.show_settings = True
    assert game.ambient, "on by default"
    game.handle_event(key(pygame.K_a))
    assert not game.ambient
    with open(main.SETTINGS_FILE, encoding="utf-8") as f:
        assert json.load(f) == {"ambient": False}
    assert not main.Game(screen, log_dir=None).ambient, "remembered next launch"
    game.handle_event(mouse_down(game.ambient_button().center))
    assert game.ambient and main.Game(screen, log_dir=None).ambient
    game.handle_event(key(pygame.K_RETURN))
    assert not game.show_settings


def test_fullscreen_centers_the_game_and_clicks_still_land(game):
    """F11: the whole screen, the game drawn as large as it allows, in the middle; clicks are measured
    from the game's corner. F11 again: back to the window."""
    game.handle_event(key(pygame.K_F11))
    display = pygame.display.get_surface()
    assert game.fullscreen and game.screen.get_parent() is display
    (w, h), (display_w, display_h) = game.screen.get_size(), display.get_size()
    assert w <= display_w and h <= display_h and (display_w - w <= 2 or display_h - h <= 2), "fills one way"
    area = game.screen.get_abs_offset()
    assert area == graphics.OFFSET
    assert abs(area[0] * 2 + w - display_w) <= 1 and abs(area[1] * 2 + h - display_h) <= 1  # centered
    game.draw()  # draws onto its part of the screen
    target = pygame.Vector2(game.speed_button.rect.center) * graphics.SCALE + pygame.Vector2(area)
    game.handle_event(mouse_down(target))
    game.handle_event(mouse_up(target))
    assert game.speed == 2
    with open(main.SETTINGS_FILE, encoding="utf-8") as f:
        assert json.load(f) == {"fullscreen": True}
    game.handle_event(key(pygame.K_F11))
    assert not game.fullscreen and graphics.OFFSET == (0, 0)
    assert pygame.display.get_surface().get_size() == graphics.window_size() == game.screen.get_size()


def test_fullscreen_button_and_back_to_the_window(game, monkeypatch):
    """The settings button toggles it too; leaving fullscreen goes back to the 200% window (or as large
    as fits)."""
    desktop(monkeypatch, 4000, 3000)
    game.show_settings = True
    game.handle_event(mouse_down(game.fullscreen_button().center))
    assert game.fullscreen
    at = pygame.Vector2(game.fullscreen_button().center) * graphics.SCALE + pygame.Vector2(graphics.OFFSET)
    game.handle_event(mouse_down(at))
    assert not game.fullscreen and graphics.SCALE == 2.0 and game.screen.get_size() == (2040, 1280)


def test_o_opens_settings(game):
    game.handle_event(key(pygame.K_o))
    assert game.show_settings and game.frozen


# ---- input at every display scale ------------------------------------------------------
@pytest.mark.parametrize("scale", SCALES)
def test_clicks_at_scale(scale):
    graphics.set_scale(scale)
    game = main.Game(pygame.display.set_mode(graphics.window_size()), log_dir=None)
    assert game.screen.get_size() == (round(1020 * scale), round(640 * scale))
    game.pick_tower("gun")
    game.handle_event(mouse_down(scaled(tile_center(2, 5), scale)))
    assert (2, 5) in game.towers
    game.handle_event(mouse_down(scaled(game.speed_button.rect.center, scale)))
    assert game.speed == 2


def test_rescale_mid_game_keeps_state(game):
    put(game, "gun", (2, 5))
    game.start_wave()
    for _ in range(300):
        game.update(1 / 60)
    state = (len(game.enemies), game.gold, game.lives, list(game.towers))
    game.set_display(0.75, False)
    assert game.screen.get_size() == (765, 480)
    assert game.map_surface.get_size() == (600, 480)
    assert (len(game.enemies), game.gold, game.lives, list(game.towers)) == state
