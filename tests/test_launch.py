"""main(): the launch scale and saved settings, and quitting through the event loop."""

import glob
import json
import os

import pygame
import pytest

import graphics
import main
from helpers import key


def run_main(monkeypatch, events, argv=("main.py", "--no-log")):
    """Run main() on a queue of events (QUIT is appended); returns the scale the game started at."""
    monkeypatch.setattr("sys.argv", list(argv))
    started = []
    init = main.Game.__init__

    def spy(self, *args, **kwargs):
        init(self, *args, **kwargs)
        started.append(graphics.SCALE)

    monkeypatch.setattr(main.Game, "__init__", spy)
    for e in events:
        pygame.event.post(e)
    pygame.event.post(pygame.event.Event(pygame.QUIT))
    with pytest.raises(SystemExit):
        main.main()
    pygame.init()  # main() shut pygame down
    return started[0]


def saved_settings():
    if not os.path.exists(main.SETTINGS_FILE):
        return None
    with open(main.SETTINGS_FILE, encoding="utf-8") as f:
        return json.load(f)


# saved settings file, keys pressed on the settings screen -> start scale, scale after, settings file after
LAUNCHES = {
    "first launch": (None, [], 1.0, 1.0, None),
    "pick and save": (None, [pygame.K_RIGHT, pygame.K_RETURN], 1.0, 1.25, {"scale": 1.25}),
    "remembered": ('{"scale": 1.25}', [], 1.25, 1.25, {"scale": 1.25}),
    "too big for the screen": ('{"scale": 2.0}', [], 1.75, 1.75, {"scale": 2.0}),
    "not an offered size": ('{"scale": 1.3}', [], 1.25, 1.25, {"scale": 1.3}),
    "junk value": ('{"scale": "big"}', [], 1.0, 1.0, {"scale": "big"}),
    "corrupt file": ("not json", [pygame.K_LEFT, pygame.K_o], 1.0, 0.75, {"scale": 0.75}),
    "largest fitting": ('{"scale": 1.75}', [pygame.K_RIGHT, pygame.K_RETURN], 1.75, 1.75, {"scale": 1.75}),
}


@pytest.mark.parametrize("saved, keys, start, end, after", LAUNCHES.values(), ids=LAUNCHES.keys())
def test_launch_scale(monkeypatch, saved, keys, start, end, after):
    monkeypatch.setattr(main.Game, "scale_fits", staticmethod(lambda k: k <= 1.75))
    if saved is not None:
        with open(main.SETTINGS_FILE, "w", encoding="utf-8") as f:
            f.write(saved)
    assert run_main(monkeypatch, [key(k) for k in keys]) == start
    assert graphics.SCALE == end
    assert saved_settings() == after


def test_starts_on_settings_screen(monkeypatch):
    shown = []

    def first_frame(self):
        shown.append(self.show_settings)
        pygame.event.post(pygame.event.Event(pygame.QUIT))

    monkeypatch.setattr(main.Game, "draw", first_frame)
    monkeypatch.setattr("sys.argv", ["main.py", "--no-log"])
    with pytest.raises(SystemExit):
        main.main()
    pygame.init()
    assert shown == [True]


def test_esc_esc_quits_and_writes_log(monkeypatch):
    """Play: close settings, start a wave, let it run a little, then Esc twice."""
    events = [key(pygame.K_RETURN), key(pygame.K_SPACE)] + [pygame.event.Event(pygame.USEREVENT)] * 30
    run_main(monkeypatch, events + [key(pygame.K_ESCAPE), key(pygame.K_ESCAPE)], argv=["main.py"])
    logs = [os.path.basename(f) for f in glob.glob(os.path.join(main.LOG_DIR, "*", "*.json"))]
    assert logs == ["run01_level01_meadow_quit.json"]


def test_no_log_flag(monkeypatch):
    events = [key(pygame.K_RETURN), key(pygame.K_SPACE)] + [pygame.event.Event(pygame.USEREVENT)] * 30
    run_main(monkeypatch, events)
    assert not os.path.exists(main.LOG_DIR)


def test_launches_fullscreen_if_saved(monkeypatch):
    with open(main.SETTINGS_FILE, "w", encoding="utf-8") as f:
        f.write('{"scale": 1.0, "fullscreen": true}')
    seen = []
    monkeypatch.setattr(main.Game, "draw", lambda self: seen.append(self.fullscreen) or pygame.event.post(
        pygame.event.Event(pygame.QUIT)))
    monkeypatch.setattr("sys.argv", ["main.py", "--no-log"])
    with pytest.raises(SystemExit):
        main.main()
    pygame.init()
    assert seen == [True]
