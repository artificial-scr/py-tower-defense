"""Runs: passes that switch sides after the last level, the run ending on a loss, picking a side for a new
run, and saving / continuing a run in progress."""

import pygame
import pytest

import graphics
import main
from helpers import SCALES, key, mouse_down, put, run_wave, scaled
from progress import Profile

LAST = len(main.LEVELS) - 1  # index of the last level of a pass


def win_towers_level(g):
    put(g, "railgun", (6, 4))
    g.wave_idx = main.WAVES_PER_LEVEL - 1
    g.start_wave()
    g.hp_mult = 0.01
    run_wave(g)
    g.reward_cards = []


def win_monsters_level(g):
    g.towers = {}
    g.budget = 500
    g.draft("basic", 25)
    g.send_wave()
    while g.state == "wave":
        g.update(1 / 60)
    g.reward_cards = []


def lose_monsters_level(g):
    while g.state in ("build", "wave"):
        g.send_wave()
        while g.state == "wave":
            g.update(1 / 60)


# ---- passes ---------------------------------------------------------------------------
def test_beating_the_last_towers_level_switches_to_the_monsters_side(game):
    game.load_level(LAST)
    win_towers_level(game)
    assert game.state == "victory" and game.levels_won == 1
    game.handle_event(key(pygame.K_SPACE))
    assert (game.side, game.pass_no, game.level_idx, game.state) == ("monsters", 2, 0, "build")
    assert game.lives == 20 and game.budget == 40
    assert main.load_save()["side"] == "monsters" and main.load_save()["pass"] == 2


def test_beating_the_last_monsters_level_switches_back_with_a_fresh_purse(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    g.profile.reach("tower_cards")
    g.profile.unlock("tower", "treasury")
    g.load_level(LAST)
    win_monsters_level(g)
    assert g.state == "victory"
    g.advance()
    assert (g.side, g.pass_no, g.level_idx) == ("towers", 2, 0)
    assert (g.gold, g.lives) == (200, 20)


def test_monsters_side_faces_the_records_set_on_the_towers_side(game):
    win_towers_level(game)  # level 1 cleared with a railgun on (6, 4)
    game.side, game.state = "towers", "victory"
    game.level_idx = LAST
    game.advance()
    assert game.side == "monsters" and game.towers == {}, "wave 1 had no towers in the record"
    game.place_defender(5)
    assert [t.kind for t in game.towers.values()] == ["railgun"]


def test_levels_won_counts_across_passes_and_sets_the_best_run(game):
    game.load_level(LAST)
    win_towers_level(game)
    game.advance()
    win_monsters_level(game)
    assert game.levels_won == 2 and Profile.load(main.PROFILE_FILE).best_run == 2


# ---- finales: a Towers pass ends where the Monsters pass before it was won ---------------
def win_monsters_pass(screen, level_idx=2, wave=3):
    """A Monsters pass won on wave `wave` of level `level_idx` (0-based), with 25 Basics."""
    g = main.Game(screen, log_dir=None, side="monsters")
    g.load_level(level_idx)
    g.towers, g.lives = {}, 1
    for _ in range(wave - 1):
        g.send_wave()
        run_wave(g)
    win_monsters_level(g)
    assert g.state == "victory" and g.finale == (level_idx + 1, wave)
    return g


def test_the_towers_pass_after_a_monsters_win_ends_on_the_wave_it_was_won(screen):
    g = win_monsters_pass(screen)
    g.advance()
    assert (g.side, g.finale, g.last_level_idx) == ("towers", (3, 3), 2)
    assert main.load_save()["finale"] == (3, 3)
    g.load_level(1)
    assert g.level_waves == main.WAVES_PER_LEVEL and not g.is_boss_level
    g.load_level(2)
    assert g.level_waves == 3 and g.level_boss == "warden"
    put(g, "railgun", (6, 4))
    for _ in range(3):
        g.start_wave()
        g.hp_mult = 0.01
        run_wave(g)
    assert g.state == "victory" and g.wave_idx == 3


def test_the_warden_joins_the_finale_wave_once(screen):
    g = win_monsters_pass(screen)
    g.advance()
    g.load_level(2)
    g.wave_idx = 1
    g.start_wave()
    assert g.spawn_queue[-1] != "warden", "only the finale wave"
    g.state, g.wave_idx = "build", 2
    g.start_wave()
    record = g.profile.monster_record(3)[3]["queue"]
    assert g.spawn_queue == record + ["warden"]
    g.profile.monster_records["3"]["3"]["queue"] = ["warden", "basic"]  # a record that drafted it already
    g.state, g.wave_idx = "build", 2
    g.start_wave()
    assert g.spawn_queue == ["basic", "warden"]


def test_a_finale_on_the_last_wave_of_the_last_level_is_the_full_pass_with_the_warden(screen):
    g = win_monsters_pass(screen, len(main.LEVELS) - 1, main.WAVES_PER_LEVEL)
    g.advance()
    assert g.last_level_idx == LAST and g.level_waves == main.WAVES_PER_LEVEL


def test_the_monsters_pass_after_a_finale_and_new_runs_have_none(screen):
    g = win_monsters_pass(screen)
    g.advance()
    g.level_idx, g.state = 2, "victory"
    g.advance()
    assert g.side == "monsters" and g.finale is None and g.last_level_idx == LAST
    g.finale = (3, 3)
    g.new_run("towers")
    assert g.finale is None and g.last_level_idx == LAST


def test_continue_keeps_the_finale(screen):
    main.write_save({"side": "towers", "pass": 2, "levels_won": 4, "level": 1, "gold": 150, "lives": 20,
                     "layout": [], "finale": [3, 2]})
    g = main.Game(screen, log_dir=None)
    g.continue_game()
    assert g.finale == (3, 2) and g.last_level_idx == 2


@pytest.mark.parametrize("finale", [[1, 2], [len(main.LEVELS) + 1, 1], [3, 0], [3, 6]])
def test_a_finale_that_doesnt_fit_the_save_is_dropped(finale):
    main.write_save({"side": "towers", "level": 1, "gold": 150, "lives": 20, "layout": [], "finale": finale})
    assert main.load_save()["finale"] is None


# ---- the run ending -------------------------------------------------------------------
def test_losing_on_the_monsters_side_ends_the_run(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    g.profile.tower_records["1"] = {"1": {"value": 1000, "towers": [{"kind": "railgun", "tile": [6, 4],
                                                                     "gold_spent": 1000}]}}
    g.load_level(0)
    g.checkpoint()
    lose_monsters_level(g)
    assert g.state == "game_over" and main.load_save() is None
    assert g.profile.tower_record(1), "the profile survives the run"


def test_new_run_is_on_the_towers_side_until_the_monsters_side_opens(game):
    game.state = "game_over"
    game.handle_event(key(pygame.K_r))
    assert not game.picking_side and (game.side, game.level_idx, game.state) == ("towers", 0, "build")


def test_new_run_lets_you_pick_a_side_once_it_opens(game):
    game.profile.reach("monsters_side")
    game.state = "game_over"
    game.handle_event(key(pygame.K_r))
    assert game.picking_side and game.frozen
    game.handle_event(key(pygame.K_2))
    assert not game.picking_side and (game.side, game.pass_no, game.levels_won) == ("monsters", 1, 0)


def test_side_pick_by_click(game):
    game.profile.reach("monsters_side")
    game.end_run()
    (_, towers_rect), _ = game.side_pick_rects()
    game.handle_event(mouse_down(towers_rect.center))
    assert game.side == "towers" and not game.picking_side


def test_launch_asks_for_a_side_once_it_opens(screen):
    Profile.load(main.PROFILE_FILE).reach("monsters_side")
    g = main.Game(screen, log_dir=None)
    g.show_settings = True
    g.handle_event(key(pygame.K_RETURN))
    assert g.picking_side
    g.handle_event(key(pygame.K_1))
    g.show_settings = True
    g.handle_event(key(pygame.K_RETURN))
    assert not g.picking_side, "only once per launch"


# ---- saving and continuing ----------------------------------------------------------------
def test_continue_resumes_side_pass_and_score(screen):
    main.write_save({"side": "monsters", "pass": 3, "levels_won": 45, "level": 4, "gold": 150, "lives": 20,
                     "layout": []})
    Profile.load(main.PROFILE_FILE).reach("monsters_side")
    g = main.Game(screen, log_dir=None)
    g.show_settings = True
    g.handle_event(key(pygame.K_c))
    assert (g.side, g.pass_no, g.levels_won, g.level_idx) == ("monsters", 3, 45, 4)
    assert not g.picking_side and g.lives == 20 and g.budget > 0


def test_old_saves_count_as_towers_pass_1():
    main.write_save({"level": 6, "gold": 500, "lives": 9, "layout": []})
    assert main.load_save() == {"side": "towers", "pass": 1, "levels_won": 6, "monster_wins": 0, "level": 6,
                                "gold": 500, "lives": 9, "layout": [], "upgrades": {}, "escort": 0,
                                "share_growth": 0.0, "finale": None}


def test_no_continue_once_the_run_on_screen_is_played(game):
    main.write_save({"level": 6, "gold": 500, "lives": 9, "layout": []})
    game.save = main.load_save()
    assert game.can_continue
    game.start_wave()
    assert not game.can_continue


# ---- drawing --------------------------------------------------------------------------------
@pytest.mark.parametrize("scale", SCALES)
def test_run_screens_draw(screen, scale, mouse):
    graphics.set_scale(scale)
    g = main.Game(pygame.display.set_mode(graphics.window_size()), log_dir=None)
    mouse[:] = scaled((300, 300), scale)
    g.pass_no = 3
    g.draw()  # banner with the pass
    for side in ("towers", "monsters"):
        g.side = side
        for state in ("game_over", "victory"):
            g.state = state
            g.draw()
    g.side, g.finale, g.state = "towers", (1, 3), "build"
    g.load_level(0)
    g.draw()  # finale banner
    g.banner_timer = 0
    for state in ("wave", "victory"):
        g.state = state
        g.draw()
    g.picking_side = True
    g.draw()
