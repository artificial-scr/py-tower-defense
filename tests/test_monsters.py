"""monsters.json loading and validation, and the monster mechanics and abilities."""

import json

import pygame
import pytest

import monsters
from entities import Enemy, Tower, cast_ability, heal_auras
from helpers import dummy_enemy, put, run_wave
from levels import ALL_BOSS_LEVELS
from monsters import ABILITIES, ENEMY_TYPES, load_monsters


def line(length=2000, y=100):
    return [pygame.Vector2(0, y), pygame.Vector2(length, y)]


# ---- the shipped data ----------------------------------------------------------
def test_roster():
    drafts = {k: s["draft"] for k, s in ENEMY_TYPES.items()}
    assert [k for k, d in drafts.items() if d == "starter"] == ["basic", "fast", "tank", "elite"]
    assert sorted(k for k, d in drafts.items() if d == "unlock") == \
        ["armored", "healer", "juggernaut", "phantom", "splitter", "swarmling"]
    assert all(drafts[boss] == "boss" and ENEMY_TYPES[boss]["fatal"] for boss in ALL_BOSS_LEVELS.values())
    assert sorted(ABILITIES) == ["bulwark", "emp", "frenzy", "mend", "smoke"]


def test_original_costs_match_the_old_kill_rewards():
    assert {k: ENEMY_TYPES[k]["cost"] for k in ("basic", "fast", "tank", "elite", "warden", "overlord")} == \
        {"basic": 5, "fast": 6, "tank": 12, "elite": 80, "warden": 400, "overlord": 1000}


# ---- broken files --------------------------------------------------------------
def write(tmp_path, data):
    path = tmp_path / "monsters.json"
    path.write_text(json.dumps(data))
    return str(path)


def shipped():
    with open(monsters.MONSTERS_FILE, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("change, message", [
    (lambda d: d["enemies"]["basic"].pop("hp"), "missing fields ['hp']"),
    (lambda d: d["enemies"]["basic"].update(wings=2), "unknown fields ['wings']"),
    (lambda d: d["enemies"]["basic"].update(draft="sometimes"), "draft must be one of"),
    (lambda d: d["enemies"]["basic"].update(cost=0), "must be positive"),
    (lambda d: d["enemies"]["basic"].update(shape="blob"), "unknown shape 'blob'"),
    (lambda d: d["enemies"]["splitter"].update(split=["ghost", 2]), "split makes 'ghost'"),
    (lambda d: d["enemies"]["warden"].pop("boss"), "bosses need both"),
    (lambda d: d["abilities"]["emp"].update(effect="explode"), "effect must be one of"),
    (lambda d: d["abilities"]["emp"].pop("radius"), "disable on area needs ['radius']"),
    (lambda d: d["abilities"]["frenzy"].pop("duration"), "haste on all needs ['duration']"),
    (lambda d: d["budget"].pop("share_start"), "budget: missing fields ['share_start']"),
    (lambda d: d["budget"].update(pace_max=-1), "must be numbers, 0 or more"),
    (lambda d: d["rewards"]["tiers"].update(towers=[3, 1]), "tiers.towers must be"),
    (lambda d: d["rewards"]["strong"].pop("rare"), "missing fields ['rare']"),
    (lambda d: d["rewards"]["weak"].update(cards=0), "cards must be a whole number"),
    (lambda d: d["budget"].pop("upgrade_price"), "budget: missing fields ['upgrade_price']"),
    (lambda d: d["upgrades"]["vitality"].update(stat="luck"), "stat must be one of"),
    (lambda d: d["upgrades"]["plating"].update(max=0), "max a whole number"),
    (lambda d: d["upgrades"]["stride"].update(max=6), "speed can go up by 50% at most"),
])
def test_broken_monsters_file(tmp_path, change, message):
    data = shipped()
    change(data)
    with pytest.raises(ValueError, match=message.replace("[", r"\[").replace("]", r"\]")):
        load_monsters(write(tmp_path, data))


# ---- monster mechanics -----------------------------------------------------------
def test_armor_blunts_small_hits_more_than_big_ones():
    e = Enemy("armored", line(), 100)
    e.hit(10)
    e.hit(100)
    assert e.max_hp - e.hp == pytest.approx(4 + 94)
    e.hit(5)
    assert e.max_hp - e.hp == pytest.approx(98 + 1), "at least 20% of a hit gets through"
    e.burn_timer, e.burn_dps = 1, 10
    hp = e.hp
    e.update(0.5)
    assert hp - e.hp == pytest.approx(5), "burns ignore armor"


def test_armor_modifier_halves_armor():
    e = Enemy("armored", line(), 100, {"armor": 0.5})
    e.hit(10)
    assert e.max_hp - e.hp == pytest.approx(7)


def test_buffs():
    plain, buffed = Enemy("basic", line(), 1), Enemy("basic", line(), 1, {"hp": 1.2, "speed": 1.5})
    assert buffed.max_hp == pytest.approx(36)
    plain.update(1)
    buffed.update(1)
    assert buffed.travelled == pytest.approx(plain.travelled * 1.5)


def test_thaw_weakens_slows_and_insulation_weakens_burns():
    e = Enemy("basic", line(), 1, {"thaw": 0.5, "burn": 0.5})
    e.apply_slow(0.4, 2)
    assert e.slow_factor == pytest.approx(0.7)
    e.apply_burn(20, 1)
    assert e.burn_dps == 10


def test_juggernaut_ignores_slows():
    e = Enemy("juggernaut", line(), 1)
    e.apply_slow(0.3, 5)
    assert e.slow_factor == 1.0


def test_healer_heals_others_but_not_itself():
    healer, friend = Enemy("healer", line(), 1), Enemy("basic", line(), 1)
    far = Enemy("basic", line(y=500), 1)
    for e in (healer, friend, far):
        e.hp = e.max_hp / 2
    heal_auras([healer, friend, far], 1.0)
    assert friend.hp == pytest.approx(15 + 30 * 0.06)
    assert healer.hp == healer.max_hp / 2 and far.hp == far.max_hp / 2


def test_splitter_splits_when_killed_but_not_when_escaping(game):
    s = Enemy("splitter", game.path_pts, 2, {"hp": 1.5})
    s.advance(300)
    s.hit(10_000)
    children = s.split()
    assert [c.kind for c in children] == ["swarmling"] * 3
    assert all(c.hp_mult == 2 and c.mods["hp"] == 1.5 for c in children), "children keep the wave's strength"
    assert [round(c.travelled) for c in children] == [300, 310, 320]
    escaped = Enemy("splitter", game.path_pts, 1)
    escaped.advance(100_000)
    assert escaped.escaped and escaped.split() == []


def test_split_children_join_the_wave(game):
    put(game, "sniper", (6, 4))
    game.spawn_queue, game.hp_mult, game.state = ["splitter"], 1, "wave"
    run_wave(game)
    assert game.state == "build"
    assert game.gold > 150 + 12, "children were killed for gold too"


def test_phantoms_cant_be_targeted_while_phased():
    e = Enemy("phantom", line(), 1)
    tower = Tower("gun", (2, 2))
    e.pos = tower.pos + pygame.Vector2(30, 0)
    every, duration = e.spec["phase"]
    e.phase_t = every - duration / 2
    assert e.phased and not tower.can_target(e)
    tower.update(0.1, [e], [], [])
    assert tower.stats["gun"]["shots"] == 0
    tower.mods = {**tower.mods, "detector": True}
    tower.update(0.1, [e], [], [])
    assert tower.stats["gun"]["shots"] == 1
    e.phase_t = 0
    assert not e.phased


def test_splash_still_hits_phased_monsters(game):
    victim = dummy_enemy((300, 300))
    victim.spec = ENEMY_TYPES["phantom"]
    victim.phase_t = 3.5
    assert victim.phased
    bait = dummy_enemy((300, 300))
    cannon = put(game, "cannon", (7, 7))
    cannon.update(0.1, [bait, victim], game.projectiles, game.effects)
    for _ in range(200):
        for p in game.projectiles:
            p.update(1 / 60, [bait, victim], game.effects)
    assert victim.hp < victim.max_hp


# ---- abilities ------------------------------------------------------------------
def test_emp_disables_towers_in_its_area():
    near, far = Tower("gun", (2, 2)), Tower("gun", (15, 2))
    cast_ability(ABILITIES["emp"], near.pos, [near, far], [], [])
    assert near.disabled and not far.disabled
    e = dummy_enemy(near.pos + pygame.Vector2(20, 0))
    near.update(1.0, [e], [], [])
    assert near.stats["gun"]["shots"] == 0
    near.update(2.5, [e], [], [])
    assert not near.disabled
    near.update(0.1, [e], [], [])
    assert near.stats["gun"]["shots"] == 1


def test_grounding_halves_area_durations():
    t = Tower("gun", (2, 2))
    cast_ability(ABILITIES["emp"], t.pos, [t], [], [], area_duration=0.5)
    assert t.disabled_timer == pytest.approx(1.5)


def test_smokescreen_shrinks_range():
    t = Tower("gun", (2, 2))
    cast_ability(ABILITIES["smoke"], t.pos, [t], [], [])
    assert t.range == pytest.approx(110 * 0.6)
    t.update(6.1, [], [], [])
    assert t.range == 110


def test_frenzy_mend_bulwark():
    e = Enemy("basic", line(), 1)
    cast_ability(ABILITIES["frenzy"], None, [], [e], [])
    assert e.speed == pytest.approx(90)
    e.hp = 10
    cast_ability(ABILITIES["mend"], None, [], [e], [])
    assert e.hp == pytest.approx(17.5)
    cast_ability(ABILITIES["bulwark"], None, [], [e], [])
    e.hit(10)
    assert e.hp == pytest.approx(12.5)
    e.update(5)
    assert e.speed == 60 and e.shield_timer <= 0
