"""Keyboard and mouse controls: speed, Esc / quit prompt, settings overlay, input at every scale."""

import json

import pygame
import pytest

import graphics
import main
from graphics import SCALES, tile_center
from helpers import key, mouse_down, mouse_up, put, scaled


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
    game.banner_timer = 1.0
    for _ in range(10):
        game.update(1 / 60)  # one frame at 10x
    assert game.banner_timer == pytest.approx(1.0 - 1 / 60)


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
def test_settings_keys_change_scale_and_save(game, monkeypatch):
    monkeypatch.setattr(main.Game, "scale_fits", staticmethod(lambda k: True))
    game.show_settings = True
    game.handle_event(key(pygame.K_RIGHT))
    assert graphics.SCALE == 1.25 and game.screen.get_size() == (1275, 800)
    game.handle_event(key(pygame.K_LEFT))
    game.handle_event(key(pygame.K_LEFT))
    assert graphics.SCALE == 0.75
    game.handle_event(key(pygame.K_LEFT))
    assert graphics.SCALE == 0.75, "stops at the smallest"
    game.handle_event(key(pygame.K_RETURN))
    assert not game.show_settings
    with open(main.SETTINGS_FILE, encoding="utf-8") as f:
        assert json.load(f) == {"scale": 0.75}


def test_settings_skip_sizes_that_dont_fit(game, monkeypatch):
    monkeypatch.setattr(main.Game, "scale_fits", staticmethod(lambda k: k <= 1.25))
    game.show_settings = True
    for _ in range(5):
        game.handle_event(key(pygame.K_RIGHT))
    assert graphics.SCALE == 1.25


def test_settings_click(game, monkeypatch):
    monkeypatch.setattr(main.Game, "scale_fits", staticmethod(lambda k: True))
    game.show_settings = True
    scale, rect = game.scale_buttons()[-1]
    game.handle_event(mouse_down(rect.center))
    assert graphics.SCALE == scale == 2.0
    game.handle_event(mouse_down(scaled(game.settings_close_button().center, 2.0)))
    assert not game.show_settings


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
    game.apply_scale(0.75)
    assert game.screen.get_size() == (765, 480)
    assert game.map_surface.get_size() == (600, 480)
    assert (len(game.enemies), game.gold, game.lives, list(game.towers)) == state
