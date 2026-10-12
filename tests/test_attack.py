"""The Monsters side: the defender from a tower record, drafting, abilities, winning and losing."""

import json
import os

import pygame
import pytest

import graphics
import main
from attack import DEFENDER_LIVES, QUEUE_MAX
from entities import Enemy
from graphics import SCALES
from helpers import key, mouse_down, scaled
from levels import LEVELS, WAVES_PER_LEVEL, wave_value
from monsters import BUDGET, ENEMY_TYPES, REWARDS, UPGRADES
from progress import UNLOCKS


def comp(*towers):
    """A tower record slot from (kind, tile, gold) triples."""
    return {"value": sum(g for _, _, g in towers),
            "towers": [{"kind": k, "tile": list(t), "gold_spent": g} for k, t, g in towers]}


@pytest.fixture
def attack(screen):
    """A Monsters-side game at level 1 against a two-wave tower record."""
    g = main.Game(screen, log_dir=None, side="monsters")
    g.profile.tower_records["1"] = {"1": comp(("gun", (6, 4), 50)),
                                    "3": comp(("rifle", (6, 4), 100), ("cannon", (7, 4), 90))}
    g.load_level(0)
    return g


def play_wave(g, max_frames=100_000):
    g.send_wave()
    for _ in range(max_frames):
        if g.state != "wave":
            return
        g.update(1 / 60)
    raise AssertionError("wave never ended")


# ---- the defender -----------------------------------------------------------------
def test_defender_grows_wave_by_wave(attack):
    g = attack
    assert [t.kind for t in g.towers.values()] == ["gun"] and g.lives == 20
    play_wave(g)  # nothing sent: the wave ends at once
    assert [t.kind for t in g.towers.values()] == ["gun"], "no slot for wave 2: wave 1's comp stays"
    play_wave(g)
    assert sorted(t.kind for t in g.towers.values()) == ["cannon", "rifle"]


def test_no_record_means_no_towers(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    assert g.towers == {}


# ---- budget and draft ----------------------------------------------------------------
def test_budget_is_the_generated_wave_value_and_carries_over(attack):
    g = attack
    assert g.budget == wave_value(0, 0) == 40
    g.draft("basic", 2)
    play_wave(g)
    assert g.budget == 40 - 10 + wave_value(0, 1)


def test_war_chest_raises_the_budget(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    g.profile.unlock("monster", "war_chest")
    g.profile.unlock("monster", "war_chest")
    g.load_level(0)
    assert g.budget == round(40 * 1.3)


def test_draft_and_undraft(attack):
    g = attack
    g.draft("tank", 5)
    assert g.queue == ["tank"] * 3 and g.budget == 4, "stops when the budget runs out"
    g.undraft()
    assert g.queue == ["tank"] * 2 and g.budget == 16
    g.draft("armored")
    assert "armored" not in g.queue, "locked kinds can't be drafted"


def test_draft_keys(attack, monkeypatch):
    g = attack
    g.handle_event(key(pygame.K_2))
    assert g.queue == ["fast"]
    monkeypatch.setattr(pygame.key, "get_mods", lambda: pygame.KMOD_SHIFT)
    g.handle_event(key(pygame.K_1))
    assert g.queue == ["fast"] + ["basic"] * 5
    g.handle_event(key(pygame.K_BACKSPACE))
    assert len(g.queue) == 5


def test_draft_by_clicking_the_panel(attack):
    g = attack
    (kind, rect), *_ = g.attack_rows()
    g.handle_event(mouse_down(rect.center))
    assert g.queue == [kind]


def test_clicking_a_queue_icon_removes_it(attack):
    g = attack
    g.draft("basic")
    g.draft("fast")
    (_, center), _ = g.queue_icons()
    g.handle_event(mouse_down((int(center.x), int(center.y))))
    assert g.queue == ["fast"]


def test_unlocked_kinds_join_the_draft(attack):
    g = attack
    g.profile.unlock("monster", "armored")
    assert "armored" in g.draftable()


def test_boss_only_in_a_boss_levels_last_wave(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    g.load_level(9)
    assert "warden" not in g.draftable()
    g.wave_idx = WAVES_PER_LEVEL - 1
    assert "warden" in g.draftable()
    g.budget = 10_000
    g.draft("warden", 2)
    assert g.queue == ["warden"], "one boss per wave"


def test_queue_is_capped(attack):
    g = attack
    g.budget = 10_000
    g.draft("basic", QUEUE_MAX + 5)
    assert len(g.queue) == QUEUE_MAX


# ---- waves --------------------------------------------------------------------------
def test_sent_wave_uses_buffs_and_the_wave_strength(attack):
    g = attack
    g.profile.unlock("monster", "thick_hide")
    g.draft("basic")
    g.send_wave()
    g.update(1 / 60)
    (e,) = g.enemies
    assert e.max_hp == pytest.approx(30 * 1.0 * 1.1)
    assert g.sent_waves[1]["queue"] == ["basic"] and g.sent_waves[1]["value"] == 5


def test_monsters_side_earns_no_gold(attack):
    g = attack
    gold = g.gold
    g.draft("basic", 8)
    play_wave(g)
    assert g.gold == gold


# ---- abilities ----------------------------------------------------------------------
def test_area_ability_aims_then_casts_on_click(attack):
    g = attack
    g.profile.unlock("monster", "emp")
    g.load_level(0)
    g.draft("tank")
    g.send_wave()
    for _ in range(90):
        g.update(1 / 60)
    g.handle_event(key(pygame.K_1))
    assert g.aiming == "emp"
    gun = g.towers[(6, 4)]
    g.handle_event(mouse_down((int(gun.pos.x), int(gun.pos.y))))
    assert gun.disabled and g.aiming is None and g.cooldowns["emp"] == 20
    (cast,) = g.sent_waves[1]["casts"]
    assert cast["ability"] == "emp" and cast["t"] == pytest.approx(1.5) and cast["pos"] == [260, 180]
    g.handle_event(key(pygame.K_1))
    assert g.aiming is None, "still cooling down"


def test_right_click_cancels_aiming(attack):
    g = attack
    g.profile.unlock("monster", "smoke")
    g.load_level(0)
    g.draft("basic")
    g.send_wave()
    g.cast("smoke")
    g.handle_event(mouse_down((100, 100), button=3))
    assert g.aiming is None and g.cooldowns["smoke"] == 0


def test_instant_ability_and_cooldown_in_game_time(attack):
    g = attack
    g.profile.unlock("monster", "frenzy")
    g.profile.unlock("monster", "frenzy")  # rank 2: 15% shorter cooldown
    g.load_level(0)
    g.draft("basic", 3)
    g.send_wave()
    for _ in range(60):
        g.update(1 / 60)
    g.handle_event(key(pygame.K_1))
    assert all(e.haste_timer > 0 for e in g.enemies)
    assert g.cooldowns["frenzy"] == pytest.approx(25 * 0.85)
    g.speed = 10
    for _ in range(60):
        g.update(1 / 60)
    assert g.cooldowns["frenzy"] == pytest.approx(25 * 0.85 - 1)


def test_no_abilities_outside_a_wave(attack):
    g = attack
    g.profile.unlock("monster", "mend")
    g.load_level(0)
    g.cast("mend")
    assert g.cooldowns["mend"] == 0


# ---- winning and losing ---------------------------------------------------------------
def leak(g, count):
    """Send `count` Basics past an empty map in the next wave."""
    g.towers = {}
    g.budget += 5 * count
    g.draft("basic", count)
    play_wave(g)


def test_draining_the_lives_wins_the_pass_at_once(attack):
    g = attack
    leak(g, 20)
    assert g.state == "victory" and g.lives == 0 and g.level_idx == 0, "on level 1, with 9 levels to spare"
    assert g.profile.milestones["tower_cards"] and g.monster_wins == 1 and g.levels_won == 1
    record = g.profile.monster_record(1)
    assert list(record) == [1] and record[1]["value"] == 100 and record[1]["queue"] == ["basic"] * 20
    assert g.enemies == [] and g.spawn_queue == []
    g.reward_cards = []
    g.advance()
    assert (g.side, g.pass_no, g.level_idx) == ("towers", 2, 0)


def test_one_life_clears_the_level_and_the_rest_carry_over(attack):
    g = attack
    leak(g, 3)
    assert g.state == "build" and g.lives == 17 and g.lives_taken == 3, "the level plays on to wave 5"
    for _ in range(WAVES_PER_LEVEL - 1):
        play_wave(g)
    assert g.state == "level_complete" and g.monster_wins == 1 and g.profile.monster_record(1)
    g.reward_cards = []
    g.advance()
    assert g.level_idx == 1 and g.lives == 17 and g.lives_taken == 0 and g.budget == wave_value(1, 0)
    assert main.load_save()["lives"] == 17
    g.continue_game()
    assert g.lives == 17


def test_a_level_without_a_life_taken_loses(attack):
    g = attack
    for _ in range(WAVES_PER_LEVEL):
        play_wave(g)
    assert g.state == "game_over" and g.profile.monster_record(1) == {}


def test_the_last_level_must_take_every_life(attack):
    g = attack
    g.load_level(len(LEVELS) - 1)
    leak(g, 4)
    for _ in range(WAVES_PER_LEVEL - 1):
        play_wave(g)
    assert g.state == "game_over" and g.lives == 16


def test_the_pace_line(attack):
    g = attack
    assert g.pace_line()[0] == f"Take 1 to clear ({len(LEVELS) - 1} to go)"
    leak(g, 2)
    assert g.pace_line()[0].startswith("-2 here: clear (")
    g.load_level(len(LEVELS) - 1)
    assert g.pace_line()[0] == "Last level: take them all"


def test_lives_reset_with_each_monsters_pass(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    g.lives = 5
    g.side = "towers"
    g.next_pass()
    assert g.side == "monsters" and g.lives == DEFENDER_LIVES
    g.lives = 5
    g.end_run()
    g.pick_side("monsters")
    assert g.lives == DEFENDER_LIVES


# ---- stat upgrades ------------------------------------------------------------------------
def test_upgrade_prices_grow_with_the_rank(attack):
    g = attack
    level = sum(g.wave_budget(w) for w in range(1, WAVES_PER_LEVEL + 1))
    assert g.level_budget == level
    assert g.upgrade_price("vitality") == round(BUDGET["upgrade_price"] * level)
    g.budget = 10_000
    g.buy_upgrade("vitality")
    assert g.upgrade_price("vitality") == round(BUDGET["upgrade_price"] * 2 * level)
    assert g.upgrade_price("stride") == round(BUDGET["upgrade_price"] * level), "each upgrade has its own ranks"


def test_buying_an_upgrade_sends_an_escort_worth_its_price(attack):
    g = attack
    price = g.upgrade_price("plating")
    g.budget = price + 6
    g.handle_event(key(pygame.K_e))
    assert g.upgrades["plating"] == 1 and g.budget == 6
    assert g.escort == price // ENEMY_TYPES["basic"]["cost"]
    assert not g.can_upgrade("plating"), "can't afford rank 2"
    g.draft("fast")
    escort = g.escort
    g.send_wave()
    assert g.spawn_queue == ["basic"] * escort + ["fast"] and g.escort == 0
    assert g.sent_waves[1]["value"] == 5 * escort + 6, "the record (and the towers' kill gold) counts the escort"


def test_the_escort_spreads_over_waves(attack):
    g = attack
    g.escort = BUDGET["escort_per_wave"] + 7
    g.send_wave()
    assert len(g.spawn_queue) == BUDGET["escort_per_wave"] and g.escort == 7


def test_upgrades_change_every_monster_sent(attack):
    g = attack
    g.budget = 100_000
    for k in ("vitality", "vitality", "stride", "plating", "plating"):
        g.buy_upgrade(k)
    g.draft("armored")
    mods = g.upgrade_mods()
    assert mods["hp"] == pytest.approx(1.3) and mods["speed"] == pytest.approx(1.1) and mods["armor_flat"] == 4
    g.send_wave()
    assert g.sent_waves[1]["mods"]["armor_flat"] == 4
    e = Enemy("armored", g.path_pts, 1.0, g.wave_mods)
    assert e.max_hp == pytest.approx(70 * 1.3) and e.speed == pytest.approx(45 * 1.1) and e.armor == 6 + 4
    assert Enemy("basic", g.path_pts, 1.0, g.wave_mods).armor == 4, "Plating armors monsters with none"


def test_upgrades_max_out(attack):
    g = attack
    g.budget = 10**9
    for _ in range(10):
        g.buy_upgrade("stride")
    assert g.upgrades["stride"] == UPGRADES["stride"]["max"]
    assert g.upgrade_mods()["speed"] == pytest.approx(1.5), "the speed cap: +50%"


def test_a_rank_bought_this_draft_can_be_sold_back(attack, mouse):
    g = attack
    g.budget = 10_000
    (_, rect), *_ = g.upgrade_buttons()
    g.handle_event(mouse_down(rect.center))
    assert g.upgrades["vitality"] == 1 and g.escort > 0
    g.handle_event(mouse_down(rect.center, button=3))
    assert g.upgrades["vitality"] == 0 and g.escort == 0 and g.budget == 10_000
    g.buy_upgrade("vitality")
    g.send_wave()
    g.state = "build"
    g.sell_upgrade("vitality")
    assert g.upgrades["vitality"] == 1, "only ranks bought in this draft phase"


def test_no_upgrades_during_a_wave(attack):
    g = attack
    g.budget = 10_000
    g.send_wave()
    g.handle_event(key(pygame.K_q))
    assert g.upgrades["vitality"] == 0


def test_upgrades_last_the_pass_and_are_saved(attack):
    g = attack
    g.budget = 10_000
    g.buy_upgrade("stride")
    g.escort = 0
    leak(g, 1)
    for _ in range(WAVES_PER_LEVEL - 1):
        play_wave(g)
    g.reward_cards = []
    g.escort = 75
    g.advance()
    assert g.level_idx == 1 and g.upgrades["stride"] == 1
    save = main.load_save()
    assert save["upgrades"]["stride"] == 1 and save["escort"] == g.escort == 75
    g.upgrades["stride"] = 0
    g.continue_game()
    assert g.upgrades["stride"] == 1
    g.side = "towers"
    g.next_pass()
    assert g.upgrades == {k: 0 for k in UPGRADES} and g.escort == 0, "a new pass starts without them"


def test_no_tower_actions_on_the_monsters_side(attack, mouse):
    g = attack
    gun = g.towers[(6, 4)]
    g.handle_event(mouse_down((int(gun.pos.x), int(gun.pos.y))))
    assert g.selected is gun and g.dragging is None
    g.handle_event(key(pygame.K_s))
    assert (6, 4) in g.towers, "can't sell the defender's towers"
    for b in g.tower_buttons.values():
        g.handle_event(mouse_down((b.rect.right - 2, b.rect.bottom - 2)))
    assert g.build_kind is None


def test_monsters_side_logs(screen, tmp_path):
    g = main.Game(screen, log_dir=str(tmp_path / "logs"), side="monsters")
    g.towers = {}
    g.budget = 200
    g.draft("basic", 20)
    play_wave(g)
    (name,) = os.listdir(g.log_session.dir)
    assert name == "run01_monsters_level01_meadow_cleared.json"
    with open(os.path.join(g.log_session.dir, name), encoding="utf-8") as f:
        d = json.load(f)
    assert d["level"]["side"] == "monsters" and d["waves"][0]["composition"] == {"basic": 20}


# ---- drawing --------------------------------------------------------------------------
@pytest.mark.parametrize("scale", SCALES)
def test_monsters_side_screens_draw(screen, scale, mouse):
    graphics.set_scale(scale)
    g = main.Game(pygame.display.set_mode(graphics.window_size()), log_dir=None, side="monsters")
    for card in ("armored", "healer", "phantom", "emp", "frenzy"):
        g.profile.unlock("monster", card)
    g.profile.tower_records["1"] = {"1": comp(("gun", (6, 4), 50))}
    g.load_level(0)
    mouse[:] = scaled((300, 200), scale)
    g.draft("armored")
    g.draft("phantom")
    g.draw()
    g.send_wave()
    for _ in range(200):
        g.update(1 / 60)
    g.cast("emp")
    g.draw()
    g.cast("emp", pygame.Vector2(260, 180))
    g.cast("frenzy")
    g.draw()
    for state in ("level_complete", "game_over", "victory"):
        g.state = state
        g.draw()


# ---- budget share and starter pack ---------------------------------------------------------
def test_budget_claims_a_share_of_the_defenders_comp(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    g.profile.tower_records["1"] = {"1": comp(("railgun", (6, 4), 1000))}
    g.load_level(0)
    assert g.share == pytest.approx(main.BUDGET["share_start"])
    assert g.budget == round(1000 * g.share), "the share beats the generated wave's 40"


def test_each_monsters_win_grows_the_share_for_the_run(attack):
    g = attack
    g.towers = {}
    g.budget = 200
    g.draft("basic", 20)
    play_wave(g)
    g.reward_cards = []
    assert g.record_tier == "weak", "a 190 gold record against a par of 310"
    assert g.monster_wins == 1 and g.share == pytest.approx(BUDGET["share_start"] + REWARDS["weak"]["share"])
    g.advance()
    assert main.load_save()["monster_wins"] == 1
    g.end_run()
    assert g.monster_wins == 0, "a new run starts over"


def test_starter_pack_the_first_time_only(screen):
    with open(main.PROFILE_FILE, "w", encoding="utf-8") as f:
        f.write('{"version": 1}')
    g = main.Game(screen, log_dir=None, side="monsters")
    picks = 0
    while g.reward_cards:
        assert g.reward_pool == "monster" and g.frozen
        g.handle_event(key(pygame.K_1))
        picks += 1
    assert picks == main.BUDGET["starter_picks"] and sum(g.profile.unlocks["monster"].values()) == picks
    assert g.profile.milestones["starter_pack"]
    g.load_level(1)
    assert g.reward_cards == []


# ---- pace and record tiers ------------------------------------------------------------------
def test_the_share_follows_the_pace(attack):
    g = attack
    assert g.pace_bonus == 0, "level 1: nothing expected yet"
    g.lives = 15  # 5 taken by the start of level 2, where 2 were expected: 3 ahead
    g.load_level(1)
    assert g.pace_bonus == pytest.approx(-min(3 * BUDGET["pace_per_life"], BUDGET["pace_min"]))
    assert BUDGET["pace_min"] == 0 and g.share == BUDGET["share_start"], "being ahead never lowers the share"
    g.lives = 19  # 1 taken by level 2: 1 behind
    g.load_level(1)
    assert g.pace_bonus == pytest.approx(BUDGET["pace_per_life"])
    g.lives = 20  # none taken by level 6, where 10 were expected: capped
    g.load_level(5)
    assert g.pace_bonus == pytest.approx(BUDGET["pace_max"])
    assert g.budget == g.wave_budget(1)


@pytest.mark.parametrize("value, tier", [(300, "weak"), (900, "normal"), (1300, "strong")])
def test_monsters_record_tiers(screen, value, tier):
    """Level 1's par (its generated waves) is 310: tiers at 2x and 4x that."""
    g = main.Game(screen, log_dir=None, side="monsters")
    g.profile.tower_records["1"] = {"2": comp(("railgun", (6, 4), value))}
    g.load_level(0)
    assert sum(wave_value(0, w) for w in range(WAVES_PER_LEVEL)) == 310
    assert g.record_ratio == pytest.approx(value / 310) and g.record_tier == tier


def test_a_strong_record_pays_more(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    g.profile.tower_records["1"] = {"1": comp(("railgun", (6, 4), 1300))}
    g.load_level(0)
    leak(g, 20)
    assert g.state == "victory" and len(g.reward_cards) == 3
    assert UNLOCKS["monster"][g.reward_cards[0]]["rare"], "a sure rare"
    assert g.share_growth == pytest.approx(REWARDS["strong"]["share"])
    g.draw()  # the reward screen says what the tier gave


def test_old_saves_grow_the_share_like_normal_records(screen):
    main.write_save({"side": "monsters", "pass": 2, "levels_won": 13, "monster_wins": 3, "level": 3, "gold": 150,
                     "lives": 12, "layout": []})
    g = main.Game(screen, log_dir=None)
    g.continue_game()
    assert g.share_growth == pytest.approx(3 * REWARDS["normal"]["share"]) and g.lives == 12
