"""Shared fixtures. Tests run headless (SDL dummy video driver) and never touch the repo's
logs/, settings.json, savegame.json or profile.json: every test gets its own temporary copies.
"""

import os

os.environ["SDL_VIDEODRIVER"] = "dummy"  # before pygame is imported anywhere
os.environ["SDL_AUDIODRIVER"] = "dummy"

import json  # noqa: E402
import random  # noqa: E402

import pygame  # noqa: E402
import pytest  # noqa: E402

import graphics  # noqa: E402
import main  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Fresh pygame, 100% scale, a fixed random seed, and settings / logs in tmp_path."""
    pygame.init()
    pygame.event.clear()
    graphics.set_scale(1.0)
    random.seed(0)
    monkeypatch.setattr(main, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(main, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(main, "SAVE_FILE", str(tmp_path / "savegame.json"))
    monkeypatch.setattr(main, "PROFILE_FILE", str(tmp_path / "profile.json"))
    # The Monsters side's one-time starter cards would cover every Monsters-side test; tests of them remove this.
    (tmp_path / "profile.json").write_text(json.dumps({"version": 1, "milestones": {"starter_pack": True}}))
    yield
    graphics.set_scale(1.0)


@pytest.fixture
def mouse(monkeypatch):
    """The mouse position in screen pixels; assign to it (mouse[:] = x, y) to move the mouse."""
    pos = [0, 0]
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: tuple(pos))
    return pos


@pytest.fixture
def screen():
    return pygame.display.set_mode(graphics.window_size())


@pytest.fixture
def game(screen):
    """A game at level 1 with logging off."""
    return main.Game(screen, log_dir=None)


@pytest.fixture
def logged_game(screen, tmp_path):
    """A game writing balance logs to tmp_path/logs."""
    return main.Game(screen, log_dir=str(tmp_path / "logs"))
