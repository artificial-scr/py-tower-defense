"""The top planning profiles (bot.py) on a fresh profile: only the start towers owned, the rest unlocked
by achievements as they play, run after run. Skip them with: uv run pytest -m "not slow".

Balance checks (2026-10-20, seed 0; the same on seeds 1-2): every first run falls on level 2. damage keeps
playing toward the towers it unlocks (Rifle, Sniper, then Minigun and Mortar) and wins the pass on its 4th
run, tall on its 5th or 6th, both with a discovered Railgun. crowd never gets past level 2: it unlocks the
Minigun, never the Sniper or Mortar. single never builds a Cannon, so the Rifle and everything past it
stays locked.
"""

import random

import pytest

from bot import bot_runs

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("profile, wins_by", [("damage", 5), ("tall", 7)])
def test_the_top_planners_unlock_their_way_to_a_won_pass(locked, profile, wins_by):
    """If it wins sooner, unlocking got easier (or the early game did); if later, harder."""
    random.seed(0)
    runs = bot_runs(locked, wins_by, profile)
    assert runs[0][0] == 2, "a fresh profile falls on level 2"
    assert runs[-1][0] == "won" and len(runs) >= 3, runs


@pytest.mark.parametrize("profile", ["crowd", "single"])
def test_the_others_stay_stuck_on_level_2(locked, profile):
    """Stuck on what they leave locked: if one gets past level 2, the unlocks or the early game changed."""
    random.seed(0)
    runs = bot_runs(locked, 4, profile)
    assert [end for end, _ in runs] == [2] * 4, runs
    assert "sniper" not in {k for _, kinds in runs for k in kinds}
