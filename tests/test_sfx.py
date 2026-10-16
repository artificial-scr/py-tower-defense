"""Sound effects (sfx.py): the player's gaps, limits and volumes, the game playing them when things happen,
the Sound setting, and sfx.json naming every sound the code plays."""

import json
import os
import re
import wave

import pygame
import pytest

import main
import sfx
from helpers import dummy_enemy, free_tiles, key, mouse_down, put, px
from monsters import ABILITIES
from towers import TOWERS

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = {"sounds": {"boom": {"volume": 0.5, "gap": 0.2, "max": 1}, "tick": {}, "unmade": {}}, "towers": {}}


class Recorder:
    """Stands in for sfx.Sfx: remembers what the game asked to play."""

    def __init__(self):
        self.volume = None
        self.played = []

    def play(self, name):
        self.played.append(name)


@pytest.fixture
def heard(screen):
    """A game whose sound effects are recorded, not played."""
    sounds = Recorder()
    return main.Game(screen, log_dir=None, sounds=sounds), sounds.played


# ---- the player -----------------------------------------------------------------------
@pytest.fixture
def folder(tmp_path):
    """Short silent files for "boom" (.ogg) and "tick" (.wav); "unmade" has none."""
    for name in ("boom.ogg", "tick.wav"):
        with wave.open(str(tmp_path / name), "wb") as w:  # SDL reads it by its content
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(bytes(4 * 4800))
    return tmp_path


def test_the_player_loads_what_exists(folder):
    player = sfx.Sfx(100, str(folder), CONFIG)
    assert set(player.sounds) == {"boom", "tick"}
    player.play("unmade")  # no file: nothing, and nothing breaks


def test_gap_and_max_keep_a_sound_from_piling_up(folder):
    now = [0.0]
    player = sfx.Sfx(100, str(folder), CONFIG, clock=lambda: now[0])
    player.play("boom")
    assert player.sounds["boom"].get_num_channels() == 1
    now[0] = 0.1
    player.play("boom")
    assert player.last["boom"] == 0.0, "too soon after the last one"
    player.sounds["boom"].stop()
    now[0] = 0.3
    player.play("boom")
    assert player.last["boom"] == 0.3
    now[0] = 0.6
    player.play("boom")
    assert player.last["boom"] == 0.3, "already sounding its max of once"
    player.play("tick")
    player.play("tick")
    assert player.sounds["tick"].get_num_channels() == sfx.DEFAULT_MAX, "no gap, the default max"


def test_volume_is_the_setting_times_the_sounds_own(folder):
    player = sfx.Sfx(50, str(folder), CONFIG)
    player.play("boom")
    channel = next(pygame.mixer.Channel(i) for i in range(pygame.mixer.get_num_channels())
                   if pygame.mixer.Channel(i).get_sound() is player.sounds["boom"])
    assert round(channel.get_volume(), 2) == 0.25
    player.sounds["boom"].stop()
    player.volume = 0
    player.play("boom")
    assert player.sounds["boom"].get_num_channels() == 0, "Off plays nothing"


def test_deaths_go_by_size():
    assert sfx.death_sound({"size": 7}) == "death_small"
    assert sfx.death_sound({"size": 13}) == "death_medium"
    assert sfx.death_sound({"size": 19}) == "death_large"
    assert sfx.death_sound({"size": 30, "boss": True}) == "boss_death"


# ---- the game playing them ---------------------------------------------------------------
def test_building_selling_and_failing_make_sounds(heard):
    game, played = heard
    game.pick_tower("gun")
    game.handle_click(px((2, 2)))
    assert played[-1] == "place"
    game.selected = game.towers[(2, 2)]
    game.sell_selected()
    assert played[-1] == "sell"
    game.build_kind, game.gold = None, 0
    game.pick_tower("gun")
    assert played[-1] == "no_gold"


def test_a_wave_fires_kills_and_pays(heard):
    game, played = heard
    tower = put(game, "gun", free_tiles(game)[0])
    game.start_wave()
    assert played[-1] == "wave_start"
    game.spawn_queue = []
    game.enemies = [dummy_enemy(tower.pos + pygame.Vector2(20, 0), hp=1)]
    for _ in range(200):
        game.update(1 / 60)
    assert "shot_light" in played
    assert "death_small" in played and "gold" in played, "a Basic is small"


def test_n_cycles_the_sound_volume_anywhere_and_its_saved(heard, screen):
    game, _ = heard
    assert game.sfx_volume == sfx.DEFAULT_VOLUME and game.sounds.volume == sfx.DEFAULT_VOLUME
    game.handle_event(key(pygame.K_n))
    assert game.sfx_volume == 100 and game.sounds.volume == 100
    game.handle_event(key(pygame.K_n))
    assert game.sfx_volume == 0, "Off after 100%"
    with open(main.SETTINGS_FILE, encoding="utf-8") as f:
        assert json.load(f) == {"sfx_volume": 0}
    assert main.Game(screen, log_dir=None).sfx_volume == 0, "remembered next launch"
    game.show_settings = True
    game.handle_event(mouse_down(game.sfx_button().center))
    assert game.sfx_volume == 25 and game.show_settings


def test_a_broken_setting_falls_back_to_the_default(screen):
    main.update_setting("sfx_volume", 33)
    assert main.Game(screen, log_dir=None).sfx_volume == sfx.DEFAULT_VOLUME


# ---- sfx.json ----------------------------------------------------------------------------
def played_in_code():
    """Every sound name the game's code plays: the literal ones and the ability_<id> ones."""
    names = set()
    for module in ("main.py", "attack.py"):
        with open(os.path.join(HERE, module), encoding="utf-8") as f:
            source = f.read()
        names |= set(re.findall(r'sound\("(\w+)"', source))
        names |= {n for pair in re.findall(r'sound\("(\w+)" if .*? else "(\w+)"\)', source) for n in pair}
    return names | {f"ability_{a}" for a in ABILITIES}


def test_every_sound_played_is_listed_and_hooked():
    sounds = sfx.load_config()["sounds"]
    assert played_in_code() - set(sounds) == set()
    assert {n for n, s in sounds.items() if s.get("hooked") is False} & played_in_code() <= {"click"}, \
        "a sound the game plays isn't marked unhooked (click only samples the Sound setting)"


def test_every_tower_has_a_listed_firing_sound():
    config = sfx.load_config()
    assert set(config["towers"]) == set(TOWERS)
    assert set(config["towers"].values()) <= set(config["sounds"])
