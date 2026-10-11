"""Buying, fusing, branch choices, moving and selling, driven by real input events."""

import pygame

from helpers import build, drag, key, mouse_down, put


def test_buy_onto_matching_tower_fuses(game):
    build(game, "gun", (1, 1))
    build(game, "gun", (1, 1))
    t = game.towers[(1, 1)]
    assert t.kind == "rifle" and t.spent == 100


def test_branch_choice_by_click(game):
    for tile in ((1, 1), (3, 1)):
        build(game, "gun", tile)
        build(game, "gun", tile)
    drag(game, (3, 1), (1, 1))
    assert game.choice and game.frozen and (3, 1) not in game.towers
    game.handle_event(mouse_down(game.choice_cards()[1].center))
    assert not game.choice
    assert game.towers[(1, 1)].kind == "sniper" and game.towers[(1, 1)].spent == 200


def test_branch_choice_by_key_and_other_keys_ignored(game):
    put(game, "mortar", (5, 5))
    put(game, "mortar", (5, 7))
    drag(game, (5, 7), (5, 5))
    game.handle_event(key(pygame.K_3))  # would pick Frost outside the choice
    assert game.choice and game.towers[(5, 5)].kind == "mortar" and game.build_kind is None
    game.handle_event(key(pygame.K_2))
    assert game.towers[(5, 5)].kind == "incinerator" and game.build_kind is None


def test_cross_fusion_into_final(game):
    put(game, "sniper", (1, 1))
    put(game, "bombard", (8, 1))
    drag(game, (8, 1), (1, 1))
    t = game.towers[(1, 1)]
    assert t.kind == "railgun" and t.tier == 4 and (8, 1) not in game.towers


def test_invalid_fusions_leave_towers_alone(game):
    put(game, "sniper", (1, 1))
    put(game, "sniper", (3, 1))
    drag(game, (3, 1), (1, 1))
    assert game.towers[(1, 1)].kind == "sniper" and (3, 1) in game.towers
    game.towers[(1, 1)].kind = "railgun"
    put(game, "flak", (8, 1))
    drag(game, (8, 1), (1, 1))
    assert game.towers[(1, 1)].kind == "railgun" and (8, 1) in game.towers


def test_move_anytime(game):
    put(game, "gun", (1, 1))
    game.start_wave()
    for _ in range(60):
        game.update(1 / 60)
    drag(game, (1, 1), (1, 2))
    assert (1, 2) in game.towers and (1, 1) not in game.towers
    assert game.towers[(1, 2)].pos == pygame.Vector2(60, 100)


def test_cant_move_onto_path(game):
    put(game, "gun", (1, 1))
    path_tile = next(iter(game.path_cells))
    drag(game, (1, 1), path_tile)
    assert (1, 1) in game.towers and path_tile not in game.towers


def test_sell(game):
    build(game, "gun", (1, 1))
    gold = game.gold
    game.selected = game.towers[(1, 1)]
    game.handle_event(key(pygame.K_s))
    assert (1, 1) not in game.towers and game.gold == gold + 35


def test_level_change_refunds_towers(game):
    build(game, "cannon", (1, 1))
    build(game, "cannon", (1, 1))
    gold = game.gold
    game.next_level()
    assert game.level_idx == 1 and not game.towers and game.gold == gold + 180
