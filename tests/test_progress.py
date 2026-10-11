"""Moving between levels: the wave lock after a level change, Rebuild, and the saved checkpoint."""

import json

import pygame

import main
from helpers import build, key, mouse_down, put, run_wave


def finish_level(game):
    """Fake the end of the level so that the next Space press moves on."""
    game.state = "level_complete"


# ---- wave lock --------------------------------------------------------------------
def test_double_space_after_level_change_doesnt_send_a_wave(game):
    build(game, "gun", (1, 1))
    finish_level(game)
    game.handle_event(key(pygame.K_SPACE))
    game.handle_event(key(pygame.K_SPACE))
    assert game.level_idx == 1 and game.state == "build" and game.wave_idx == 0


def test_wave_lock_runs_out_in_real_time(game):
    finish_level(game)
    game.advance()
    game.speed = 10
    for _ in range(round(main.WAVE_LOCK * 60) + 1):
        for _ in range(game.speed):  # frames at 10x, as main() runs them
            game.update(1 / 60)
    game.handle_event(key(pygame.K_SPACE))
    assert game.state == "wave"


def test_first_level_has_no_wave_lock(game):
    game.handle_event(key(pygame.K_SPACE))
    assert game.state == "wave"


# ---- rebuild ----------------------------------------------------------------------
def test_rebuild_buys_back_the_same_towers(logged_game):
    game = logged_game
    build(game, "gun", (1, 1))
    build(game, "gun", (1, 1))  # fuses into a rifle worth 100
    build(game, "frost", (2, 1))
    game.start_wave()
    run_wave(game)
    finish_level(game)
    game.advance()
    gold = game.gold
    game.handle_event(key(pygame.K_b))
    assert sorted((t.kind, t.spent) for t in game.towers.values()) == [("frost", 70), ("rifle", 100)]
    assert game.gold == gold - 170 and not game.rebuild_layout
    assert not any(t.tile in game.path_cells for t in game.towers.values())
    assert [e["kind"] for e in game.log.events if e["type"] == "rebuild"] == ["rifle", "frost"]
    assert game.log.spent["towers"] == 170


def test_rebuild_puts_towers_next_to_the_path(game):
    put(game, "sniper", (0, 0)).spent = 400
    finish_level(game)
    game.advance()
    game.rebuild()
    (tower,) = game.towers.values()
    near = sum(1 for c in game.path_cells if main.tile_center(*c).distance_to(tower.pos) <= tower.range)
    assert near >= 10


def test_rebuild_keeps_what_it_cant_afford(game):
    put(game, "bombard", (1, 1)).spent = 360
    put(game, "gun", (2, 2))
    finish_level(game)
    game.advance()
    game.gold = 100
    game.rebuild()
    assert [t.kind for t in game.towers.values()] == ["gun"]
    assert [e["kind"] for e in game.rebuild_layout] == ["bombard"]
    assert game.gold == 50


def test_rebuild_button_only_without_a_selection(game, mouse):
    put(game, "gun", (1, 1))
    finish_level(game)
    game.advance()
    assert game.can_rebuild
    game.selected = put(game, "cannon", (0, 0))
    assert not game.can_rebuild
    game.selected = None
    game.handle_event(mouse_down(game.rebuild_button.rect.center))
    assert any(t.kind == "gun" for t in game.towers.values())


# ---- checkpoint -------------------------------------------------------------------
def test_level_change_saves_a_checkpoint(game):
    put(game, "rifle", (1, 1)).spent = 100
    finish_level(game)
    game.advance()
    with open(main.SAVE_FILE, encoding="utf-8") as f:
        data = json.load(f)
    assert data == {"side": "towers", "pass": 1, "levels_won": 0, "monster_wins": 0, "level": 1, "gold": game.gold, "lives": game.lives,
                    "layout": [{"kind": "rifle", "spent": 100, "tile": [1, 1]}]}


def test_continue_from_the_start_screen(screen):
    first = main.Game(screen, log_dir=None)
    put(first, "rifle", (1, 1)).spent = 100
    finish_level(first)
    first.advance()
    gold = first.gold

    game = main.Game(screen, log_dir=None)  # a new launch
    game.show_settings = True
    assert game.can_continue
    game.draw()
    game.handle_event(key(pygame.K_c))
    assert not game.show_settings
    assert (game.level_idx, game.gold) == (1, gold)
    assert [e["kind"] for e in game.rebuild_layout] == ["rifle"]


def test_continue_button_on_the_start_screen(screen):
    main.write_save({"level": 4, "gold": 900, "lives": 12, "layout": []})
    game = main.Game(screen, log_dir=None)
    game.show_settings = True
    game.handle_event(mouse_down(game.settings_continue_button().center))
    assert (game.level_idx, game.gold, game.lives) == (4, 900, 12)


def test_game_over_ends_the_run_and_its_save(screen):
    main.write_save({"level": 6, "gold": 3000, "lives": 15, "layout": []})
    game = main.Game(screen, log_dir=None)
    game.continue_game()
    game.lives = 1
    game.start_wave()
    run_wave(game)
    assert game.state == "game_over" and main.load_save() is None and not game.can_continue
    game.draw()
    game.handle_event(key(pygame.K_c))
    assert game.state == "game_over"


def test_no_continue_mid_game(screen):
    main.write_save({"level": 6, "gold": 3000, "lives": 15, "layout": []})
    game = main.Game(screen, log_dir=None)
    game.start_wave()
    game.handle_event(key(pygame.K_c))
    assert game.level_idx == 0


def test_broken_saves_are_ignored(tmp_path):
    for content in ("not json", "[]", '{"level": -1, "gold": 1, "lives": 1, "layout": []}',
                    '{"level": 3, "gold": 1, "lives": 1, "layout": [], "side": "wizards"}',
                    '{"level": 3, "gold": 1, "lives": 1, "layout": [], "pass": 0}',
                    '{"level": 99, "gold": 1, "lives": 1, "layout": []}',
                    '{"level": 3, "gold": "x", "lives": 1, "layout": []}'):
        with open(main.SAVE_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        assert main.load_save() is None, content


def test_unknown_tower_kinds_are_dropped_from_a_save():
    main.write_save({"level": 2, "gold": 10, "lives": 5,
                     "layout": [{"kind": "removed", "spent": 9, "tile": [1, 1]},
                                {"kind": "gun", "spent": 50, "tile": [2, 2]}]})
    assert main.load_save()["layout"] == [{"kind": "gun", "spent": 50, "tile": (2, 2)}]
