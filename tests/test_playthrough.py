"""Long simulations with a simple bot player. Skip them with: uv run pytest -m "not slow".

These double as balance checks. The bot clears every regular level, but the bosses beat it
about half the time (3 wins out of seeds 0-5), so only the regular levels are asserted on
several seeds, and a full win on one seed known to win. On the Monsters side, scripted drafts
against the bot's own tower records check that the first levels stay winnable, and that how the
budget is spent matters.
"""

import random

import pytest

import main
from helpers import bot_play, free_tiles, put, scripted_attack
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
    assert game.state == "victory" and game.level_idx == len(main.LEVELS) - 1


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


@pytest.mark.parametrize("save_for_last, wins", [(True, False), (False, True)])
def test_monsters_level_2_is_won_by_pacing(records, screen, save_for_last, wins):
    """Level 2's record ends on Dragon + Absolute Zero, which melts one big push (not a single life taken)
    but not steady waves."""
    g = main.Game(screen, log_dir=None, side="monsters")
    g.monster_wins = 1  # as after winning level 1
    g.load_level(1)
    assert scripted_attack(g, ["tank", "basic", "elite"], save_for_last) == wins


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
