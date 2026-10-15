"""Long simulations with a simple bot player. Skip them with: uv run pytest -m "not slow".

These double as balance checks. Since the early waves got their hp boost (levels.EARLY_HP) the bot
no longer wins: with its mixed buys (Gun, Cannon, Frost) it clears level 1 and falls on levels 2-4, and
buying only Guns, the strongest early line, takes it furthest (level 3-7, seeds 0-5). On the Monsters
side, scripted drafts against the bot's own tower records check that the first levels stay winnable.
"""

import random

import pytest

import main
from helpers import bot_play, free_tiles, put, scripted_attack
from towers import TOWERS

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("seed", range(3))
def test_mixed_bot_clears_level_1_then_falls(game, seed):
    """If it gets past level 4 the early game got easier; if it loses level 1, much harder."""
    random.seed(seed)
    bot_play(game, until_level=10)
    assert game.state == "game_over" and 1 <= game.level_idx <= 3


def test_gun_bot_goes_furthest(game):
    """Seed 1 buying only Guns reaches level 7; if it falls before level 6, the game got harder (or the bot
    worse)."""
    random.seed(1)
    bot_play(game, buy=("gun",))
    assert game.state == "game_over" and game.level_idx >= 5


def test_stress_at_10x(game):
    """The last level's last wave against 40 final-form towers, updated and drawn at 10x until it ends."""
    game.load_level(len(main.LEVELS) - 1)
    game.speed = 10
    finals = [k for k, s in TOWERS.items() if s["tier"] == 4]
    for i, tile in enumerate(free_tiles(game)[:40]):
        put(game, finals[i % len(finals)], tile)
    game.wave_idx = 4
    game.start_wave()
    for _ in range(20000):
        if game.state != "wave":
            break
        game.tick(1 / 60)
        game.draw()
    assert game.state in ("victory", "game_over")


# ---- the Monsters side -------------------------------------------------------------------
@pytest.fixture
def records(game):
    """Tower records for levels 1-2, set by the bot on a known seed (the same profile file is shared)."""
    random.seed(1)
    bot_play(game, until_level=3)
    assert game.profile.tower_record(2)


@pytest.mark.parametrize("save_for_last, outcome", [(True, "victory"), (False, "level_complete")])
def test_monsters_level_1_falls_to_both_plans(records, screen, save_for_last, outcome):
    """With no unlocks, even waves take a few lives (enough to clear the level), while one big push takes
    all 20 and wins the whole pass on its first level (there's no cap on lives per level). It must stay
    winnable: monster cards only come from Monsters wins."""
    g = main.Game(screen, log_dir=None, side="monsters")
    assert scripted_attack(g, ["tank", "basic", "elite"], save_for_last)
    assert g.state == outcome


@pytest.mark.parametrize("save_for_last", [True, False])
def test_monsters_level_2_falls_to_both_plans(records, screen, save_for_last):
    """Level 2's record ends on Railgun + Blizzard (990 gold: the harder Towers side leaves the bot less to
    spend), which falls to one big push and to steady waves alike."""
    g = main.Game(screen, log_dir=None, side="monsters")
    g.monster_wins = 1  # as after winning level 1
    g.load_level(1)
    assert scripted_attack(g, ["tank", "basic", "elite"], save_for_last)


def test_a_full_loop_towers_monsters_towers(records, screen):
    """Records from the Towers side feed the Monsters side, whose win feeds the Towers side again."""
    g = main.Game(screen, log_dir=None, side="monsters")
    assert scripted_attack(g, ["tank", "basic", "elite"], save_for_last=True)
    g.reward_cards = []
    push = g.profile.monster_record(1)
    assert list(push) == [5], "empty waves aren't recorded"
    towers = main.Game(screen, log_dir=None)
    towers.start_wave()
    assert "basic" in towers.spawn_queue and len(towers.spawn_queue) == 8, "no record for wave 1: the generated one"
    towers.state, towers.wave_idx = "build", 4
    towers.start_wave()
    assert towers.spawn_queue == push[5]["queue"]
