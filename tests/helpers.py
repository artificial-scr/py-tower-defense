"""Helpers for driving the game the way a player would (events, drags) or directly."""

import pygame

from entities import Enemy, Tower
from levels import COLS, ROWS, tile_center
from towers import TOWER_ORDER

E = pygame.event.Event
# Scales the game is drawn at in tests: the window is 200%, or smaller on a small desktop, and fullscreen
# lands anywhere.
SCALES = (0.75, 1.0, 1.25, 1.5, 1.75, 2.0)


def px(tile):
    """Logical pixel at the center of a tile."""
    c = tile_center(*tile)
    return int(c.x), int(c.y)


def scaled(pos, scale):
    """Logical point -> screen pixel at a display scale."""
    return int(pos[0] * scale), int(pos[1] * scale)


def key(k, mod=0):
    return E(pygame.KEYDOWN, key=k, mod=mod, unicode="")


def mouse_down(pos, button=1):
    return E(pygame.MOUSEBUTTONDOWN, button=button, pos=pos)


def mouse_up(pos, button=1):
    return E(pygame.MOUSEBUTTONUP, button=button, pos=pos)


def drag(game, a, b):
    """Drag the tower on tile a onto tile b with real mouse events."""
    game.handle_event(mouse_down(px(a)))
    game.handle_event(mouse_up(px(b)))


def build(game, kind, tile):
    """Buy a tower onto a tile with a real click (gold is topped up first)."""
    game.gold += 1000
    game.build_kind = kind
    game.handle_event(mouse_down(px(tile)))
    game.build_kind = None


def put(game, kind, tile):
    """Place a tower of any kind directly, without paying."""
    t = Tower(TOWER_ORDER[0], tile)  # any buyable kind, then swapped
    t.kind = kind
    game.towers[tile] = t
    return t


def dummy_enemy(pos, hp=10000):
    """A basic enemy with lots of HP walking right from pos."""
    e = Enemy("basic", [pygame.Vector2(pos), pygame.Vector2(pos) + (1000, 0)], 1)
    e.hp = e.max_hp = hp
    return e


def free_tiles(game):
    return [(x, y) for x in range(COLS) for y in range(ROWS) if game.is_free((x, y))]


def ranked_spots(game):
    """Free tiles, the ones covering the most path first."""
    res = []
    for tx in range(COLS):
        for ty in range(ROWS):
            if (tx, ty) in game.path_cells:
                continue
            c = tile_center(tx, ty)
            res.append((sum(1 for p in game.path_cells if tile_center(*p).distance_to(c) <= 110), (tx, ty)))
    res.sort(reverse=True)
    return [t for _, t in res]


def run_wave(game, max_frames=200_000):
    """Update until the current wave ends."""
    for _ in range(max_frames):
        if game.state != "wave":
            return
        game.update(1 / 60)
    raise AssertionError("wave never ended")


def scripted_attack(game, kinds, save_for_last):
    """Play the current Monsters level drafting `kinds` in turn with all the budget, either every wave or
    only the last one (sending the first four empty to save up). No abilities. Returns whether it won."""
    while game.state in ("build", "wave"):
        if game.state == "build":
            if not save_for_last or game.wave_idx == 4:
                i = 0
                while any(game.can_draft(k) for k in kinds):
                    kind = kinds[i % len(kinds)]
                    i += 1
                    if game.can_draft(kind):
                        game.draft(kind)
            game.send_wave()
        else:
            game.update(1 / 60)
    return game.state in ("level_complete", "victory")
