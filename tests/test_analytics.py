"""analytics/tower_stats.py: its numbers add up, and its model agrees with the real combat rules."""

import csv
import os
import sys

import pygame
import pytest

from entities import Enemy, Tower
from levels import TILE
from monsters import ENEMY_TYPES
from towers import TOWERS

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "analytics"))
import tower_stats  # noqa: E402


def test_fusing_keeps_the_gold():
    gold = tower_stats.tower_gold()
    for kind, (a, b) in tower_stats.parents_of().items():
        assert gold[kind] == gold[a] + gold[b]


def test_dps_grows_with_crowding_and_armor_takes_some():
    for spec in TOWERS.values():
        single, wave, swarm = (tower_stats.dps(spec, s) for s in tower_stats.SPACINGS.values())
        assert 0 < single <= wave <= swarm
        assert 0 < tower_stats.dps(spec, armor=tower_stats.REF_ARMOR) <= single


def test_plain_tower_dps_is_damage_times_rate():
    spec = TOWERS["gun"]
    assert tower_stats.dps(spec) == spec["damage"] * spec["rate"]


def test_writes_every_tower_to_csv(tmp_path, capsys):
    out = tmp_path / "towers.csv"
    tower_stats.main(["--csv", str(out), "--monsters", "all"])
    assert "Fusion" in capsys.readouterr().out
    with open(out, encoding="utf-8") as f:
        assert [row["kind"] for row in csv.DictReader(f)] == list(TOWERS)


def play_pass(kind, enemy_kind, hp_mult):
    """Damage a real tower does to one real monster walking past it on a straight path, TILE px away."""
    tower = Tower(kind, (8, 6))
    y = tower.pos.y + TILE
    path = [pygame.Vector2(tower.pos.x - 400, y), pygame.Vector2(tower.pos.x + 400, y)]
    enemy = Enemy(enemy_kind, path, hp_mult)
    projectiles, effects, dt = [], [], 1 / 60
    while enemy.alive:
        enemy.update(dt)
        tower.update(dt, [enemy], projectiles, effects)
        for p in projectiles:
            p.update(dt, [enemy], effects)
        projectiles = [p for p in projectiles if not p.done]
    return enemy.max_hp - enemy.hp


@pytest.mark.parametrize("kind", ["gun", "cannon", "frost", "shatter", "incinerator", "solar", "lance"])
def test_pass_damage_matches_the_game(kind):
    hp_mult = 1000  # so the monster lives through the pass
    elite = ENEMY_TYPES["elite"]
    expected = tower_stats.pass_damage(TOWERS[kind], elite, hp_mult) * elite["hp"] * hp_mult
    assert play_pass(kind, "elite", hp_mult) == pytest.approx(expected, rel=0.15)
