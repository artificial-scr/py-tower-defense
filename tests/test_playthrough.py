"""Long simulations with a simple bot player. Skip them with: uv run pytest -m "not slow".

These double as balance checks. The bot clears every regular level, but the bosses beat it
about half the time (3 wins out of seeds 0-5), so only the regular levels are asserted on
several seeds, and a full win on one seed known to win.
"""

import random

import pytest

from helpers import bot_play, free_tiles, put
from towers import TOWERS

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("seed", range(3))
def test_bot_clears_levels_before_first_boss(game, seed):
    random.seed(seed)
    bot_play(game, until_level=10)
    assert game.level_idx == 9 and game.state == "build" and game.lives == 20


def test_game_can_be_won(game):
    """Seed 1 is a known winning run; if it starts losing, the game got harder (or the bot worse)."""
    random.seed(1)
    bot_play(game)
    assert game.state == "victory" and game.level_idx == 19


def test_stress_at_10x(game):
    """Level 20's last wave against 40 final-form towers, updated and drawn at 10x until it ends."""
    game.load_level(19)
    game.speed = 10
    finals = [k for k, s in TOWERS.items() if s["tier"] == 4]
    for i, tile in enumerate(free_tiles(game)[:40]):
        put(game, finals[i % len(finals)], tile)
    game.wave_idx = 4
    game.start_wave()
    for _ in range(20000):
        if game.state != "wave":
            break
        for _ in range(game.speed):
            game.update(1 / 60)
        game.draw()
    assert game.state in ("victory", "game_over")
