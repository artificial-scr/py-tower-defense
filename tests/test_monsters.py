"""monsters.json loading and validation, and the monster mechanics and abilities."""

import json

import pygame
import pytest

import monsters
from entities import Enemy, Tower, cast_ability, heal_auras, speed_auras
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
        ["armored", "bearer", "berserker", "healer", "juggernaut", "looter", "mirage", "phantom", "saboteur", "splitter", "swarmling", "thawling",
         "warded"]
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
    (lambda d: d["enemies"]["warded"].update(ward=0), "ward must be a positive number"),
    (lambda d: d["enemies"]["mirage"].update(decoy=[2, 40]), "decoy must be"),
    (lambda d: d["enemies"]["berserker"].update(enrage=-1), "enrage must be"),
    (lambda d: d["enemies"]["thawling"].update(rebound=[0.8]), "rebound must be"),
    (lambda d: d["enemies"]["saboteur"].update(sabotage=[60, -1]), "sabotage must be"),
    (lambda d: d["enemies"]["looter"].update(loot=[1.5, 2]), "loot must be"),
    (lambda d: d["enemies"]["bearer"].update(speed_aura=[80]), "speed_aura must be"),
    (lambda d: d["enemies"]["brood"]["summon"][3].pop(), "summon offsets need one per"),
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


# ---- Warded ---------------------------------------------------------------------------
def test_a_ward_absorbs_one_whole_hit_then_recharges():
    e = Enemy("warded", line(), 1)
    tower = Tower("gun", (0, 0))
    assert e.warded and not e.hit(40, (tower, "gun"))
    assert e.hp == e.max_hp and not e.warded and tower.stats["gun"]["warded"] == 1
    assert e.hit(10, (tower, "gun")) and e.hp == e.max_hp - 10, "the next hit lands"
    e.update(ENEMY_TYPES["warded"]["ward"])
    assert e.warded, "back up after its recharge time"


def test_a_ward_blocks_the_hits_slow_and_burn_but_not_burns():
    e = Enemy("warded", line(), 1)
    shatter = Tower("shatter", (0, 0))
    from entities import Projectile
    Projectile(shatter, e).strike(e, 40, "direct")
    assert e.hp == e.max_hp and not e.slowed, "the absorbed hit didn't slow it"
    e.apply_burn(10, 2)
    e.update(0.5)
    assert e.hp < e.max_hp, "burns go through"
    hp = e.hp
    Projectile(shatter, e).strike(e, 40, "direct")
    assert e.slowed and e.hp < hp


def test_a_wave_of_warded_plays_out(game):
    """Splash, chain and instant hits all respect the ward in a real wave."""
    for kind, tile in (("tesla", (6, 4)), ("railgun", (8, 4)), ("avalanche", (10, 4))):
        put(game, kind, tile)
    game.start_wave()
    game.spawn_queue = ["warded"] * 6
    run_wave(game)
    assert sum(t.stats[t.kind]["warded"] for t in game.towers.values()) >= 6


# ---- Mirage ---------------------------------------------------------------------------
def test_an_illusion_runs_ahead_pops_on_any_hit_and_fades():
    caster = Enemy("mirage", line(), 3)
    caster.advance(100)
    fake = caster.cast_illusion()
    every, ahead, life = ENEMY_TYPES["mirage"]["decoy"]
    assert fake.illusion and fake.travelled == caster.travelled + ahead and fake.hp == fake.max_hp == 1
    tower = Tower("sniper", (0, 0))
    assert not fake.hit(500, (tower, "sniper")) and not fake.alive
    assert tower.stats["sniper"]["decoyed"] == 1 and tower.stats["sniper"]["kills"] == 0
    other = caster.cast_illusion()
    other.update(life)
    assert not other.alive and not other.escaped, "faded away"


def test_illusions_draw_fire_but_give_nothing(game):
    gold, lives = game.gold, game.lives
    game.start_wave()
    game.spawn_queue = ["mirage"]
    while not any(e.illusion for e in game.enemies):  # the Sniper comes once the first illusion is out
        game.update(1 / 60)
    sniper = put(game, "sniper", (6, 4))
    fakes = 0
    for _ in range(4000):
        if game.state != "wave":
            break
        fakes = max(fakes, sum(e.illusion for e in game.enemies))
        game.update(1 / 60)
    assert fakes >= 1 and sniper.stats["sniper"]["decoyed"] >= 1
    killed = ENEMY_TYPES["mirage"]["cost"] if game.lives == lives else 0
    bonus = 20 + 5 * game.wave_idx
    assert game.gold == gold + killed + bonus, "only the real Mirage paid out"
    assert game.lives >= lives - ENEMY_TYPES["mirage"]["damage"], "illusions take no lives"
    assert game.wave_monsters == 1


# ---- Berserker ------------------------------------------------------------------------
def test_a_berserker_speeds_up_as_it_is_hurt_and_slows_still_apply():
    e = Enemy("berserker", line(), 2)
    base = ENEMY_TYPES["berserker"]["speed"]
    assert e.speed == base and e.rage == 0
    e.hit(e.max_hp / 2)
    assert e.speed == pytest.approx(base * 1.5)
    e.hp = e.max_hp * 0.01
    assert e.speed == pytest.approx(base * 1.99)
    e.apply_slow(0.5, 2)
    assert e.speed == pytest.approx(base * 1.99 * 0.5)
    e.heal(e.max_hp)
    assert e.rage == 0, "healing calms it down"


# ---- Thawling -------------------------------------------------------------------------
def test_a_thawling_sprints_when_a_slow_wears_off():
    e = Enemy("thawling", line(), 1)
    base = ENEMY_TYPES["thawling"]["speed"]
    boost, seconds = ENEMY_TYPES["thawling"]["rebound"]
    e.apply_slow(0.5, 1.0)
    assert e.speed == pytest.approx(base * 0.5) and not e.rebounding
    e.update(1.0)
    assert e.rebounding and e.speed == pytest.approx(base * (1 + boost))
    e.update(seconds / 2)
    e.apply_slow(0.5, 1.0)
    assert not e.rebounding and e.speed == pytest.approx(base * 0.5), "a new slow ends the sprint"
    e.update(1.0)
    e.update(seconds + 0.01)
    assert not e.rebounding and e.speed == pytest.approx(base)


def test_slow_immune_thawlings_never_sprint():
    e = Enemy("thawling", line(), 1, {"thaw": 1.0})  # Thaw cards stacked to full: slows do nothing
    e.apply_slow(0.5, 1.0)
    e.update(1.0)
    assert not e.rebounding, "a slow that did nothing gives no sprint"


# ---- Saboteur -------------------------------------------------------------------------
def test_a_killed_saboteur_knocks_out_the_towers_next_to_it(game):
    radius, seconds = ENEMY_TYPES["saboteur"]["sabotage"]
    game.start_wave()
    game.spawn_queue = []
    e = Enemy("saboteur", game.path_pts, 1)
    e.advance(200)
    game.register_enemy(e, "wave")
    tile = (int(e.pos.x // 40), int(e.pos.y // 40))
    near = put(game, "gun", (tile[0], tile[1] - 1))
    far = put(game, "gun", (tile[0] + 5, tile[1] + 5))
    assert near.pos.distance_to(e.pos) <= radius < far.pos.distance_to(e.pos)
    e.hit(e.max_hp * 2)
    game.update(1 / 60)
    assert near.disabled and near.disabled_timer == pytest.approx(seconds, abs=0.05) and not far.disabled


def test_a_saboteur_that_gets_through_does_nothing(game):
    game.start_wave()
    game.spawn_queue = []
    e = Enemy("saboteur", game.path_pts, 1)
    game.register_enemy(e, "wave")
    tower = put(game, "gun", (0, 0))
    e.pos = tower.pos.copy()
    e.alive, e.escaped = False, True
    game.update(1 / 60)
    assert not tower.disabled


# ---- Looter ---------------------------------------------------------------------------
def leak(game, kind):
    """`kind` gets through, while another monster keeps the wave going."""
    game.register_enemy(Enemy("tank", game.path_pts, 1000), "wave")
    e = Enemy(kind, game.path_pts, 1)
    game.register_enemy(e, "wave")
    e.alive, e.escaped = False, True
    game.update(1 / 60)


def test_a_looter_steals_gold_not_lives(game):
    game.start_wave()
    game.spawn_queue = []
    game.gold, lives = 1000, game.lives
    leak(game, "looter")
    share = ENEMY_TYPES["looter"]["loot"][0]
    assert game.gold == 1000 - int(1000 * share) and game.lives == lives



# ---- Banner Bearer ----------------------------------------------------------------------
def test_a_banner_bearer_rallies_the_monsters_around_it_but_not_itself():
    radius, share = ENEMY_TYPES["bearer"]["speed_aura"]
    bearer = Enemy("bearer", line(), 1)
    near, far = Enemy("basic", line(), 1), Enemy("basic", line(), 1)
    bearer.advance(200)
    near.advance(200 + radius - 5)
    far.advance(200 + radius + 5)
    speed_auras([bearer, near, far])
    assert near.speed == pytest.approx(ENEMY_TYPES["basic"]["speed"] * (1 + share))
    assert far.speed == ENEMY_TYPES["basic"]["speed"] and bearer.rally == 0
    second = Enemy("bearer", line(), 1)
    second.advance(200)
    speed_auras([bearer, second, near])
    assert near.rally == share and bearer.rally == share, "auras don't stack, but bearers rally each other"
    bearer.alive = second.alive = False
    speed_auras([bearer, second, near])
    assert near.rally == 0, "a dead bearer rallies no one"


# ---- The Brood Mother ---------------------------------------------------------------------
def test_the_brood_mother_is_a_boss_no_level_uses_yet():
    spec = ENEMY_TYPES["brood"]
    assert spec["draft"] == "boss" and spec["fatal"] and "brood" not in ALL_BOSS_LEVELS.values()


def test_the_brood_mother_shoots_out_swarmlings_one_behind_two_in_front(game):
    kind, count, every, offsets = ENEMY_TYPES["brood"]["summon"]
    game.start_wave()
    game.spawn_queue = []
    brood = Enemy("brood", game.path_pts, 1)
    brood.advance(300)
    game.register_enemy(brood, "wave")
    brood.summon_timer = 1 / 120
    game.update(1 / 60)
    minions = [e for e in game.enemies if e.origin == "summon:brood"]
    assert len(minions) == count == 3 and all(m.kind == kind == "spiderling" for m in minions)
    assert sorted(round(m.travelled - brood.travelled) for m in minions) == sorted(offsets)
    assert sum(m.travelled < brood.travelled for m in minions) == 1, "one behind, two in front"
