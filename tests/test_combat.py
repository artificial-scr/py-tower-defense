"""Tower mechanics and boss behavior."""

import pytest

from helpers import dummy_enemy, put, run_wave


def test_chain_lightning_and_slow(game):
    tesla = put(game, "tesla", (5, 5))
    enemies = [dummy_enemy((tesla.pos.x + 60 + i * 50, tesla.pos.y)) for i in range(8)]
    tesla.update(0.01, enemies, [], [])
    hit = [e for e in enemies if e.hp < e.max_hp]
    assert len(hit) == 7, "first target + 6 chain jumps"
    assert all(e.slowed for e in hit)


def test_bonus_vs_slowed(game):
    lance = put(game, "lance", (5, 5))
    e = dummy_enemy((lance.pos.x + 50, lance.pos.y))
    lance.update(0.01, [e], [], [])
    first = e.max_hp - e.hp
    lance.cooldown = 0
    lance.update(0.01, [e], [], [])
    second = e.max_hp - e.hp - first
    assert second == pytest.approx(3 * first)


def test_multishot(game):
    flak = put(game, "flak", (5, 5))
    enemies = [dummy_enemy((flak.pos.x + 20 + i * 25, flak.pos.y + 20)) for i in range(5)]
    projectiles = []
    flak.update(0.01, enemies, projectiles, [])
    assert len(projectiles) == 3


def test_burn_kills(game):
    solar = put(game, "solar", (5, 5))
    e = dummy_enemy((solar.pos.x + 50, solar.pos.y), hp=200)
    solar.update(0.01, [e], [], [])
    assert e.burn_timer > 0
    for _ in range(120):
        e.update(1 / 60)
    assert not e.alive and not e.escaped


def test_splash_hits_a_group(game):
    cannon = put(game, "cannon", (5, 5))
    enemies = [dummy_enemy((cannon.pos.x + 50 + i * 8, cannon.pos.y)) for i in range(3)]
    projectiles = []
    cannon.update(0.01, enemies, projectiles, [])
    while projectiles:
        for p in projectiles:
            p.update(1 / 60, enemies, [])
        projectiles = [p for p in projectiles if not p.done]
    assert all(e.hp < e.max_hp for e in enemies)


def test_kill_rewards_and_leak_costs(game):
    game.spawn_queue, game.hp_mult, game.state = ["basic"], 1, "wave"
    run_wave(game)
    assert game.lives == 19
    put(game, "railgun", (6, 4))
    gold = game.gold
    game.spawn_queue, game.state = ["basic"], "wave"
    run_wave(game)
    assert game.lives == 19 and game.gold > gold


def test_boss(game):
    game.load_level(9)
    assert game.is_boss_level
    game.spawn_queue, game.hp_mult, game.state = ["basic", "warden"], 1, "wave"
    for _ in range(60 * 3):
        game.update(1 / 60)
    assert not any(e.kind == "warden" for e in game.enemies), "a breather before the boss"
    for _ in range(60 * 2):
        game.update(1 / 60)
    boss = next(e for e in game.enemies if e.kind == "warden")
    assert game.boss_alert > 0
    for _ in range(60 * 7):
        game.update(1 / 60)
    minions = [e for e in game.enemies if e.kind == "fast"]
    assert len(minions) == 3 and all(m.travelled > 0 for m in minions), "summons 3 fast minions"
    boss.apply_slow(0.3, 2)
    assert boss.slow_factor == 0.6, "bosses resist slows"
    run_wave(game)
    assert game.state == "game_over" and game.lives == 0, "an escaped boss ends the game"


def test_turrets_turn_toward_their_target_and_kick_back_when_firing(game):
    """Drawing only: the turret is drawn turning at TURN_SPEED, not snapping, and kicked back after a shot."""
    gun = put(game, "gun", (5, 5))
    e = dummy_enemy((gun.pos.x, gun.pos.y + 60))  # straight below: aim 90, the turret starts at -90
    gun.update(0.1, [e], [], [])
    assert gun.aim == pytest.approx(90)
    assert abs(gun.facing - gun.aim) > 90, "still turning"
    assert gun.kick == 1.0
    for _ in range(30):
        gun.update(1 / 60, [e], [], [])
    assert gun.facing == pytest.approx(90)
    gun.cooldown = 99
    for _ in range(10):
        gun.update(1 / 60, [e], [], [])
    assert gun.kick == 0.0
