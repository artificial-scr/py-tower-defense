"""The soundtrack (music.py): which cue plays when, how intense it is, the player fading between
cues, the Music setting, and the stem files music.json points at."""

import json
import os
import wave

import pygame
import pytest

import main
import music
from entities import Enemy
from helpers import key, mouse_down
from levels import ALL_LEVELS, LEVELS


def path_length(game):
    return sum(a.distance_to(b) for a, b in zip(game.path_pts, game.path_pts[1:]))


def walker(game, kind="basic", progress=0.0):
    """A monster `progress` of the way down the level's path."""
    e = Enemy(kind, game.path_pts, 1)
    e.travelled = progress * path_length(game)
    return e


def in_wave(game, *enemies):
    game.start_wave()
    game.spawn_queue = []
    game.enemies = list(enemies)
    return music.plan(game)


# ---- layers -------------------------------------------------------------------------
def test_each_intensity_has_its_layers():
    on = lambda i: [s for s, g in zip(music.STEMS, music.layer_gains(i)) if g == 1]  # noqa: E731
    assert on(0) == ["pads"]
    assert on(music.WAVE) == ["pads", "bass", "percussion"]
    assert on(music.BUILD) == on(music.PRESSED) == ["pads", "bass", "percussion", "lead"]
    assert on(music.DANGER) == list(music.STEMS)
    assert all(g == 0 for g in music.layer_gains(music.WAVE)[3:]), "the layers above are silent, not faint"


# ---- what plays when ----------------------------------------------------------------
def test_building_plays_the_build_cue(game):
    p = music.plan(game)
    assert p.cue == "meadow/build" and p.intensity == music.BUILD and not p.duck
    assert p.cues == {"meadow/build", "meadow/wave"}, "no boss cue to load on level 1"


def test_a_wave_plays_the_wave_cue_and_grows_with_the_threat(game):
    assert in_wave(game, walker(game, progress=0.1)) == music.Plan(
        frozenset({"meadow/build", "meadow/wave"}), "meadow/wave", music.WAVE)
    assert in_wave(game, walker(game, progress=0.6)).intensity == music.PRESSED, "front past half the path"
    crowd = [walker(game) for _ in range(music.CROWD + 1)]
    assert in_wave(game, *crowd).intensity == music.PRESSED
    assert in_wave(game, walker(game, progress=0.85)).intensity == music.DANGER, "nearly through"
    assert in_wave(game, walker(game, "elite")).intensity == music.DANGER


def test_illusions_dont_count(game):
    e = walker(game, progress=0.9)
    e.illusion = True
    assert in_wave(game, e).intensity == music.WAVE


def test_low_lives_bring_in_the_danger_layer(game):
    game.lives = int(game.lives_at_start * music.LOW_LIVES)
    assert in_wave(game, walker(game)).intensity == music.DANGER


def test_the_boss_cue_takes_over_when_the_boss_walks_in(game):
    game.load_level(len(LEVELS) - 1)
    assert music.plan(game).cues == {"keep/build", "keep/wave", "keep/boss"}
    assert in_wave(game, walker(game)).cue == "keep/wave"
    p = in_wave(game, walker(game, "warden"))
    assert p.cue == "keep/boss" and p.intensity == music.DANGER


def test_a_finale_level_loads_the_boss_cue(game):
    game.finale = (3, 5)  # the Warden joins level 3's last wave
    game.load_level(2)
    assert game.level_boss and "keep/boss" in music.plan(game).cues
    assert in_wave(game, walker(game, "warden")).cue == "keep/boss"


def test_panels_and_pause_duck_the_music(game):
    game.paused = True
    assert music.plan(game).duck
    game.paused = False
    game.show_tree = True
    assert music.plan(game).duck and music.plan(game).cue == "meadow/build"


@pytest.mark.parametrize("setup", [
    lambda g: setattr(g, "show_settings", True),
    lambda g: setattr(g, "picking_side", True),
    lambda g: setattr(g, "state", "game_over"),
    lambda g: setattr(g, "state", "victory"),
], ids=["settings", "side pick", "game over", "pass won"])
def test_menus_and_the_end_of_a_run_are_silent(game, setup):
    setup(game)
    assert music.plan(game).cue is None


def test_the_reward_cards_play_the_level_just_won(game):
    game.state = "victory"
    game.reward_cards = ["gold"]
    p = music.plan(game)
    assert p.cue == "meadow/build" and not p.duck
    game.reward_cards = []
    game.state = "level_complete"
    assert music.plan(game).cue == "meadow/build", "between levels, cards or not"


def test_no_music_for_a_theme_music_json_leaves_out(game):
    p = music.plan(game, {"levels": {}, "boss": {}})
    assert p.cue is None and not p.cues


# ---- the player -----------------------------------------------------------------------
@pytest.fixture
def stems(tmp_path):
    """A music folder with a short silent stem for each of meadow's cues and the boss."""
    for cue in ("meadow/build", "meadow/wave", "keep/boss"):
        os.makedirs(tmp_path / cue)
        for stem in music.STEMS:
            with wave.open(str(tmp_path / cue / f"{stem}.ogg"), "wb") as w:  # SDL reads it by its content
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(music.FREQUENCY)
                w.writeframes(bytes(4 * 4800))
    return tmp_path


def settle(player, plan, seconds, dt=0.05):
    """Play `plan` for `seconds`, once its stems are decoded."""
    player.update(0, plan)
    if player.loading:
        player.loading.join()
    for _ in range(int(seconds / dt)):
        player.update(dt, plan)


def volumes(playing):
    return [round(c.get_volume(), 2) for c in playing.channels]


MEADOW = frozenset({"meadow/build", "meadow/wave"})


def test_the_player_fades_layers_and_crossfades_cues(stems):
    player = music.Music(100, str(stems))
    settle(player, music.Plan(MEADOW, "meadow/build", music.BUILD), 3)
    assert player.current == "meadow/build"
    assert volumes(player.playing[-1]) == [1, 1, 1, 1, 0]
    settle(player, music.Plan(MEADOW, "meadow/wave", music.WAVE), 0.5)
    assert [(p.cue, p.out) for p in player.playing] == [("meadow/build", True), ("meadow/wave", False)]
    assert volumes(player.playing[-1]) == [1, 1, 1, 0, 0], "the wave cue is in quickly"
    settle(player, music.Plan(MEADOW, "meadow/wave", music.DANGER), 2.5)
    assert [p.cue for p in player.playing] == ["meadow/wave"], "the build cue has faded out"
    assert volumes(player.playing[-1]) == [1, 1, 1, 1, 1]
    assert len(player.free) == (player.SLOTS - 1) * len(music.STEMS)
    settle(player, music.Plan(MEADOW, "meadow/wave", music.WAVE), 1)
    assert 0 < volumes(player.playing[-1])[4] < 1, "layers drop slowly"


def test_the_player_ducks_mutes_and_falls_silent(stems):
    player = music.Music(50, str(stems))
    settle(player, music.Plan(MEADOW, "meadow/build", music.BUILD, duck=True), 3)
    assert volumes(player.playing[-1])[0] == 0.5 * music.DUCK
    player.volume = 0
    settle(player, music.Plan(MEADOW, "meadow/build", music.BUILD), 0.1)
    assert volumes(player.playing[-1])[0] == 0
    settle(player, music.Plan(MEADOW, None), music.FADE_OUT + 0.1)
    assert not player.playing and player.current is None


def test_quick_switches_never_run_out_of_channels(stems):
    player = music.Music(100, str(stems))
    for _ in range(5):
        for cue in ("meadow/build", "meadow/wave"):
            settle(player, music.Plan(MEADOW, cue, music.WAVE), 0.1)
    assert len(player.playing) <= player.SLOTS and player.current == "meadow/wave"


def test_a_new_level_frees_the_last_ones_stems(stems):
    player = music.Music(100, str(stems))
    settle(player, music.Plan(MEADOW, "meadow/build", music.BUILD), 1)
    keep = frozenset({"keep/boss"})
    settle(player, music.Plan(keep, "keep/boss", music.BOSS), music.FADE_OUT + 0.2)
    assert set(player.sounds) == {"keep/boss"}


def test_missing_files_leave_the_game_silent(tmp_path):
    player = music.Music(100, str(tmp_path))
    settle(player, music.Plan(MEADOW, "meadow/build", music.BUILD), 1)
    assert not player.playing


# ---- the Music setting ---------------------------------------------------------------
def test_m_cycles_the_music_volume_anywhere_and_its_saved(game, screen):
    assert game.music_volume == music.DEFAULT_VOLUME
    game.handle_event(key(pygame.K_m))
    assert game.music_volume == 100
    game.handle_event(key(pygame.K_m))
    assert game.music_volume == 0, "Off after 100%"
    with open(main.SETTINGS_FILE, encoding="utf-8") as f:
        assert json.load(f) == {"music_volume": 0}
    assert main.Game(screen, log_dir=None).music_volume == 0, "remembered next launch"
    game.show_settings = True
    game.handle_event(mouse_down(game.music_button().center))
    assert game.music_volume == 25 and game.show_settings


def test_the_setting_reaches_the_player(screen, tmp_path):
    player = music.Music(100, str(tmp_path))
    game = main.Game(screen, log_dir=None, soundtrack=player)
    assert player.volume == music.DEFAULT_VOLUME
    game.cycle_music_volume()
    assert player.volume == 100
    game.update_music(0.016)  # no stems in tmp_path: silent, but nothing breaks


def test_a_broken_setting_falls_back_to_the_default(screen):
    main.update_setting("music_volume", 33)
    assert main.Game(screen, log_dir=None).music_volume == music.DEFAULT_VOLUME


# ---- the files -------------------------------------------------------------------------
def test_every_level_has_its_music():
    config = music.load_config()
    assert set(config["levels"]) >= {theme.name for theme, _ in LEVELS}
    assert set(config["levels"]) <= {theme.name for theme, _ in ALL_LEVELS}
    cues = {cue for theme, _ in LEVELS for cue in music.level_cues(theme.name, True, config).values()}
    for cue in cues:
        for stem in music.STEMS:
            assert os.path.isfile(os.path.join(music.MUSIC_DIR, cue, f"{stem}.ogg")), f"{cue}: {stem}"
