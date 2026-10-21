"""Long simulations with the bot player (bot.py). Skip them with: uv run pytest -m "not slow".

These double as balance checks (2026-10-20, seeds 0-5): the planning bot (profile damage) wins the
Towers pass on 5 seeds of 6, with Railguns and Absolute Zeros from level 2 on; the bot before the
planner (profile cycle) and the planner kept to tiers 1-2 or to the Gun line fall on level 2.
"""

import random

import pytest

import main
from bot import bot_play
from helpers import free_tiles, put, scripted_attack
from towers import TOWERS

pytestmark = pytest.mark.slow


def test_the_planning_bot_wins_the_pass(game):
    """Seed 0: if it stops winning, the game got harder (or the planner worse)."""
    random.seed(0)
    stats = bot_play(game)
    assert game.state == "victory" and len(stats["levels"]) == len(main.LEVELS)


@pytest.mark.parametrize("seed", range(3))
def test_the_bot_before_the_planner_clears_level_1_then_falls(game, seed):
    """Buying Gun, Cannon, Frost in turn: if it gets past level 3 the early game got easier; if it loses
    level 1, much harder."""
    random.seed(seed)
    bot_play(game, profile="cycle")
    assert game.state == "game_over" and 1 <= game.level_idx <= 2


@pytest.mark.parametrize("profile, lines", [("wide", None), ("damage", ("gun",))])
def test_without_finals_or_with_one_line_the_planner_falls_early(game, profile, lines):
    """Tiers 1-2 only, or the Gun line alone, isn't enough past level 2."""
    random.seed(0)
    bot_play(game, profile=profile, lines=lines)
    assert game.state == "game_over" and game.level_idx <= 2


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
    """Tower records for levels 1-2, set by the bot before the planner (profile cycle) on a known seed (the
    same profile file is shared)."""
    random.seed(1)
    bot_play(game, until_level=3)
    assert game.profile.tower_record(2)


def test_a_full_loop_towers_monsters_towers(records, screen):
    """Records from the Towers side feed the Monsters side, whose win feeds the Towers side again."""
    g = main.Game(screen, log_dir=None, side="monsters")
    assert scripted_attack(g, ["tank", "basic", "elite"], save_for_last=True)
    g.reward_cards = []
    push = g.profile.monster_record(1)
    assert list(push) == [5], "empty waves aren't recorded"
    towers = main.Game(screen, log_dir=None)
    towers.start_wave()
    assert "basic" in towers.spawn_queue and len(towers.spawn_queue) == 10, "no record for wave 1: the generated one"
    towers.state, towers.wave_idx = "build", 4
    towers.start_wave()
    assert towers.spawn_queue == push[5]["queue"]
