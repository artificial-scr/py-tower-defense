"""Helpers for driving the game the way a player would (events, drags) or directly."""

import random

import pygame

from entities import Enemy, Tower
from levels import COLS, ROWS, tile_center
from towers import TOWER_ORDER, TOWERS

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


def bot_play(game, until_level=None, max_frames=3_000_000, move_and_sell=False, buy=("gun", "cannon", "frost", "gun")):
    """A simple player: buy towers on the best spots (cycling through `buy`), fuse whatever can fuse, pick
    branches at random.

    Stops when the game is won or lost, or when level `until_level` (1-based) is reached.
    With move_and_sell, it also moves one tower mid-wave and sells one per level.
    """
    bought, spots, sold = 0, None, False
    for frame in range(max_frames):
        if game.state in ("game_over", "victory"):
            return
        if game.state == "level_complete":
            game.advance()
            bought, spots, sold = 0, None, False
            if until_level and game.level_idx + 1 >= until_level:
                return
            continue
        spots = spots or ranked_spots(game)
        if game.choice:
            game.choose(random.randrange(2))
            continue
        k = buy[bought % len(buy)]
        if game.gold >= TOWERS[k]["cost"]:
            free = [s for s in spots if s not in game.towers]
            if free:
                game.build_kind = k
                game.handle_event(mouse_down(px(free[0])))
                game.build_kind = None
                bought += 1
        if frame % 10 == 0:
            rank = {t: i for i, t in enumerate(spots)}
            towers = sorted(game.towers.values(), key=lambda t: rank[t.tile])
            for i, a in enumerate(towers):
                b = next((b for b in towers[i + 1:] if b.fusion_options(a)), None)
                if b:
                    game.dragging = b
                    game.drop_dragged(px(a.tile))
                    break
        if move_and_sell and frame == 3000 and game.towers:
            t = next(iter(game.towers.values()))
            free = [s for s in spots if s not in game.towers]
            game.dragging = t
            game.drop_dragged(px(free[0]))
        if move_and_sell and frame == 3500 and not sold and len(game.towers) > 1:
            game.selected = list(game.towers.values())[-1]
            game.sell_selected()
            sold = True
        if game.state == "build":
            game.start_wave()
        game.update(1 / 60)
    raise AssertionError(f"bot still playing after {max_frames} frames")


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
