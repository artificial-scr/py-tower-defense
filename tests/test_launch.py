"""main(): the launch scale and saved settings, and quitting through the event loop."""

import functools
import glob
import json
import os

import pygame
import pytest

import graphics
import main
import music
import sfx
from helpers import key


@pytest.fixture(autouse=True)
def no_stems(monkeypatch, tmp_path):
    """main() plays the soundtrack and sound effects from empty folders: the real players, nothing to decode."""
    monkeypatch.setattr(main.music, "Music", functools.partial(music.Music, folder=str(tmp_path / "music")))
    monkeypatch.setattr(main.sfx, "Sfx", functools.partial(sfx.Sfx, folder=str(tmp_path / "sfx")))


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


# saved settings file, desktop size -> window scale
LAUNCHES = {
    "first launch": (None, (2560, 1440), 2.0),
    "a scale saved by an older version is ignored": ('{"scale": 1.25}', (2560, 1440), 2.0),
    "corrupt file": ("not json", (2560, 1440), 2.0),
    "small desktop": (None, (1366, 768), 1.075),
}


@pytest.mark.parametrize("saved, desk, scale", LAUNCHES.values(), ids=LAUNCHES.keys())
def test_launch_scale(monkeypatch, saved, desk, scale):
    monkeypatch.setattr(pygame.display, "get_desktop_sizes", lambda: [desk])
    if saved is not None:
        with open(main.SETTINGS_FILE, "w", encoding="utf-8") as f:
            f.write(saved)
    assert run_main(monkeypatch, [key(pygame.K_RIGHT), key(pygame.K_RETURN)]) == scale
    assert graphics.SCALE == scale, "arrow keys don't resize"
    if saved is None:
        assert saved_settings() is None, "no scale saved"


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
        f.write('{"fullscreen": true}')
    seen = []
    monkeypatch.setattr(main.Game, "draw", lambda self: seen.append(self.fullscreen) or pygame.event.post(
        pygame.event.Event(pygame.QUIT)))
    monkeypatch.setattr("sys.argv", ["main.py", "--no-log"])
    with pytest.raises(SystemExit):
        main.main()
    pygame.init()
    assert seen == [True]


@pytest.mark.parametrize("argv, plays", [(["main.py", "--no-log"], True),
                                         (["main.py", "--no-log", "--no-music"], False)])
def test_launch_starts_the_soundtrack_unless_told_not_to(monkeypatch, argv, plays):
    seen = []
    monkeypatch.setattr(main.Game, "draw", lambda self: seen.append(self.soundtrack) or pygame.event.post(
        pygame.event.Event(pygame.QUIT)))
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit):
        main.main()
    pygame.init()
    assert (seen[0] is not None) == plays
