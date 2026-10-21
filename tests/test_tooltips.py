"""Tooltips (tooltip_view.py): what a right click opens, what closes them, and what they say."""

import pygame

import main
from helpers import dummy_enemy, key, mouse_down, px, put
from levels import tile_center


def right_click(game, pos):
    game.handle_event(mouse_down(pos, 3))


def test_right_click_a_tower_opens_its_tooltip_and_a_left_click_closes_it(game):
    t = put(game, "gun", (2, 5))
    right_click(game, px((2, 5)))
    assert game.tooltip.what == "tower" and game.tooltip.obj is t
    assert game.selected is None, "a right click doesn't select"
    game.handle_event(mouse_down(px((2, 5))))
    assert game.tooltip is None and game.selected is t, "the left click closes it and still acts"


def test_right_click_on_nothing_closes_it_and_still_cancels(game):
    put(game, "gun", (2, 5))
    right_click(game, px((2, 5)))
    game.pick_tower("gun")
    right_click(game, px((2, 5)))
    assert game.build_kind == "gun", "a right click on a tower opens its tooltip instead of cancelling"
    right_click(game, (5, 5))
    assert game.tooltip is None and game.build_kind is None


def test_keys_close_it_and_esc_does_nothing_else(game):
    right_click(game, game.tower_buttons["cannon"].rect.center)
    assert game.tooltip.kind == "cannon" and game.tooltip.where == "panel"
    game.handle_event(key(pygame.K_ESCAPE))
    assert game.tooltip is None and not game.confirm_quit
    right_click(game, game.tower_buttons["cannon"].rect.center)
    game.handle_event(key(pygame.K_f))
    assert game.tooltip is None and game.speed == 2


def test_tooltips_leave_a_pause_alone(game):
    game.paused = True
    right_click(game, game.tower_buttons["gun"].rect.center)
    assert game.tooltip and game.paused
    game.handle_event(mouse_down((5, 5)))
    assert game.tooltip is None and game.paused
    right_click(game, game.tower_buttons["gun"].rect.center)
    game.handle_event(key(pygame.K_ESCAPE))
    assert game.tooltip is None and game.paused and not game.confirm_quit


def test_the_tree_closes_after_its_tooltip(game):
    game.show_tree = True
    kind, x, y, _ = game.tree_spots()[-1]
    right_click(game, (x + 10, y))
    assert game.tooltip.kind == kind and game.show_tree
    game.handle_event(mouse_down((x + 10, y)))
    assert game.tooltip is None and game.show_tree, "the first click closes the tooltip"
    game.handle_event(mouse_down((x + 10, y)))
    assert not game.show_tree


def test_esc_closes_the_tree_and_its_tooltip_together(game):
    game.show_tree = True
    _, x, y, _ = game.tree_spots()[0]
    right_click(game, (x + 10, y))
    game.handle_event(key(pygame.K_ESCAPE))
    assert game.tooltip is None and not game.show_tree and not game.confirm_quit


def test_a_monster_tooltip_follows_it_until_it_dies(game):
    game.start_wave()
    e = dummy_enemy(tile_center(4, 4), hp=100)
    game.enemies.append(e)
    right_click(game, e.pos)
    assert game.tooltip.obj is e and game.active_tooltip
    game.draw()
    e.alive = False
    assert game.active_tooltip is None
    game.draw()


def test_a_sold_towers_tooltip_goes(game):
    t = put(game, "gun", (2, 5))
    right_click(game, px((2, 5)))
    game.selected = t
    game.sell_selected()
    assert game.active_tooltip is None


def test_wave_preview_icons_open_monster_tooltips(game):
    kind, n, center = game.preview_icons()[0]
    right_click(game, center)
    assert game.tooltip.what == "monster" and game.tooltip.kind == kind and game.tooltip.count == n
    *_, lines = game.monster_tip(game.tooltip)
    assert any(f"{n} in this wave" in text for line in lines for text, _ in line)


def test_stats_include_the_cards_and_show_the_base(game):
    game.card_mods = {**game.card_mods, "damage": {**game.card_mods["damage"], "gun": 1.5}, "burn": 1.3}
    right_click(game, game.tower_buttons["gun"].rect.center)
    *_, lines = game.tower_tip(game.tooltip)
    assert lines[0] == [("Damage 15", lines[0][0][1]), ("  (10)", lines[0][1][1])]


def test_live_monster_stats(game):
    game.start_wave()
    e = dummy_enemy(tile_center(4, 4), hp=100)
    e.hp = 40
    e.apply_slow(0.5, 2)
    game.enemies.append(e)
    right_click(game, e.pos)
    texts = [text for line in game.monster_tip(game.tooltip)[-1] for text, _ in line]
    assert "HP 40 / 100" in texts and any(t.startswith("Slowed to 50%") for t in texts)


def test_monsters_side_draft_rows_open_tooltips_and_upgrades_still_refund(screen):
    m = main.Game(screen, log_dir=None, side="monsters")
    kind, rect = m.attack_rows()[0]
    right_click(m, rect.center)
    assert m.tooltip.kind == kind
    m.budget = 10_000
    key_, button = m.upgrade_buttons()[0]
    m.buy_upgrade(key_)
    right_click(m, button.center)
    assert m.upgrades[key_] == 0 and m.tooltip is None
