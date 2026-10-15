"""Unlock cards: unlocks.json, drawing and picking cards after wins, milestones, and what tower cards do."""

import json
import random

import pygame
import pytest

import graphics
import main
import progress
from entities import Enemy, Tower
from graphics import SCALES
from helpers import key, mouse_down, put, run_wave, scaled
from monsters import REWARDS
from progress import UNLOCKS, Profile, load_unlocks
from towers import NO_TOWER_MODS


def win_towers_level(game):
    put(game, "railgun", (6, 4))
    game.wave_idx = main.WAVES_PER_LEVEL - 1
    game.start_wave()
    game.hp_mult = 0.01
    run_wave(game)
    assert game.state in ("level_complete", "victory")


def win_monsters_level(game):
    game.towers = {}
    game.budget = 500
    game.draft("basic", 25)
    game.send_wave()
    while game.state == "wave":
        game.update(1 / 60)
    assert game.state in ("level_complete", "victory")


# ---- unlocks.json ---------------------------------------------------------------------
def test_pools():
    assert len(UNLOCKS["monster"]) == 23 and len(UNLOCKS["tower"]) == 10
    assert {c["effect"] for c in UNLOCKS["monster"].values()} == {"type", "ability", "buff", "budget"}
    assert all(c["max"] >= 1 for pool in UNLOCKS.values() for c in pool.values())


@pytest.mark.parametrize("side, card, change, message", [
    ("monster", "emp", {"effect": "teleport"}, "effect must be one of"),
    ("monster", "armored", {"type": "basic"}, "isn't an enemy with draft: unlock"),
    ("monster", "emp", {"ability": "nuke"}, "isn't an ability"),
    ("monster", "thaw", {"mod": "luck"}, "mod must be one of"),
    ("tower", "sharp_gun", {"line": "laser"}, "isn't a tower line"),
    ("tower", "salvage", {"colour": 1}, "unknown fields"),
])
def test_broken_unlocks_file(tmp_path, side, card, change, message):
    with open(progress.UNLOCKS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    data[side][card].update(change)
    path = tmp_path / "unlocks.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=message):
        load_unlocks(str(path))


# ---- drawing cards -----------------------------------------------------------------------
def test_draws_are_distinct_and_skip_maxed_cards(tmp_path):
    p = Profile(str(tmp_path / "p.json"))
    for key_ in UNLOCKS["monster"]:
        if key_ != "emp":
            for _ in range(UNLOCKS["monster"][key_]["max"]):
                p.unlock("monster", key_)
    assert p.draw_cards("monster", random.Random(1)) == ["emp"]
    p.unlock("monster", "emp")
    p.unlock("monster", "emp")
    p.unlock("monster", "emp")
    assert p.draw_cards("monster", random.Random(1)) == []
    fresh = Profile(None)
    cards = fresh.draw_cards("tower", random.Random(5))
    assert len(cards) == 3 == len(set(cards))


def test_rare_cards_are_rarer():
    p = Profile(None)
    rng = random.Random(0)
    firsts = [p.draw_cards("monster", rng, 1)[0] for _ in range(3000)]
    assert firsts.count("war_chest") < firsts.count("thick_hide") / 2


def test_profile_drops_unknown_cards_and_caps_ranks(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"version": 1, "unlocks": {"monster": {"emp": 9, "gone": 1}, "tower": {}}}))
    assert Profile.load(str(path)).unlocks["monster"] == {"emp": 3}


# ---- rewards after wins ---------------------------------------------------------------------
def test_towers_wins_give_no_cards_until_monsters_level_20_is_beaten(game):
    win_towers_level(game)
    assert game.reward_cards == [] and not game.frozen


def test_towers_wins_give_tower_cards_after_that(game):
    game.profile.reach("tower_cards")
    win_towers_level(game)
    assert game.record_tier == "normal", "generated waves are par"
    assert len(game.reward_cards) == 3 and game.reward_pool == "tower" and game.frozen


def test_monsters_wins_give_monster_cards_and_a_key_picks_one(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    win_monsters_level(g)
    assert g.record_tier == "weak", "no tower record at all"
    assert g.reward_pool == "monster" and len(g.reward_cards) == REWARDS["weak"]["cards"] == 2
    second = g.reward_cards[1]
    g.handle_event(key(pygame.K_2))
    assert g.reward_cards == [] and g.profile.rank("monster", second) == 1
    assert Profile.load(main.PROFILE_FILE).rank("monster", second) == 1, "picks are permanent"


def test_clicking_a_card_picks_it(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    win_monsters_level(g)
    first = g.reward_cards[0]
    g.handle_event(mouse_down(g.reward_card_rects()[0].center))
    assert g.profile.rank("monster", first) == 1


def test_space_doesnt_skip_the_card_screen(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    win_monsters_level(g)
    g.handle_event(key(pygame.K_SPACE))
    assert g.level_idx == 0 and g.reward_cards


# ---- milestones -------------------------------------------------------------------------------
def test_last_level_victories_reach_the_milestones(game, screen):
    game.load_level(len(main.LEVELS) - 1)
    win_towers_level(game)
    assert game.state == "victory" and game.profile.milestones["monsters_side"]
    g = main.Game(screen, log_dir=None, side="monsters")
    g.load_level(len(main.LEVELS) - 1)
    win_monsters_level(g)
    assert g.state == "victory" and g.profile.milestones["tower_cards"]


# ---- tower card effects ------------------------------------------------------------------------
def unlock(profile, card, ranks=1):
    for _ in range(ranks):
        profile.unlock("tower", card)


def test_damage_cards_by_line(game):
    unlock(game.profile, "sharp_gun", 2)
    unlock(game.profile, "sharp_cannon")
    mods = game.profile.tower_mods()
    gun, cannon, frost, flak = (Tower(k, (1, 1)) for k in ("gun", "cannon", "frost", "flak"))
    for t in (gun, cannon, frost, flak):
        t.mods = mods
    assert gun.damage == pytest.approx(10 * 1.16)
    assert cannon.damage == pytest.approx(26 * 1.08)
    assert frost.damage == 4
    assert flak.damage == pytest.approx(45 * 1.24), "Flak = Minigun (gun line) + Bombard (cannon line)"


def test_new_towers_carry_the_cards(game):
    unlock(game.profile, "long_barrels", 2)
    game.load_level(0)
    game.gold = 1000
    game.build_kind = "gun"
    game.place_tower((1, 1))
    assert game.towers[(1, 1)].range == pytest.approx(110 * 1.1)


def test_gold_and_lives_cards_on_a_new_game(game):
    unlock(game.profile, "treasury", 2)
    unlock(game.profile, "fortify")
    game.reset()
    assert (game.gold, game.lives) == (250, 22)


def test_salvage_raises_the_refund(game):
    unlock(game.profile, "salvage", 3)
    game.load_level(0)
    game.build_kind = "cannon"
    game.place_tower((1, 1))
    assert game.towers[(1, 1)].sell_value == int(90 * 0.85)


def test_detector_and_piercing(game):
    unlock(game.profile, "detector")
    unlock(game.profile, "piercing")
    game.load_level(0)
    game.build_kind = "gun"
    game.place_tower((1, 1))
    assert game.towers[(1, 1)].mods["detector"]
    game.start_wave()
    assert game.wave_mods["armor"] == 0.5


def test_grounding_shortens_replayed_area_abilities(game):
    unlock(game.profile, "grounding")
    game.load_level(0)
    gun = put(game, "gun", (6, 4))
    gun.mods = game.card_mods
    game.profile.monster_records["1"] = {"1": {"value": 12, "queue": ["tank"], "hp_mult": 1, "mods": {},
                                               "casts": [{"ability": "emp", "t": 0.5, "pos": [260, 180]}]}}
    game.start_wave()
    for _ in range(31):
        game.update(1 / 60)
    assert gun.disabled_timer == pytest.approx(1.5, abs=0.05)


def test_defender_fights_with_its_recorded_cards(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    mods = {**NO_TOWER_MODS, "range": 1.2, "armor": 0.5, "grounding": 0.5}
    g.profile.tower_records["1"] = {"1": {"value": 50, "mods": mods,
                                          "towers": [{"kind": "gun", "tile": [6, 4], "gold_spent": 50}]}}
    g.load_level(0)
    assert g.towers[(6, 4)].range == pytest.approx(132)
    g.draft("basic")
    g.send_wave()
    assert g.wave_mods["armor"] == 0.5
    assert g.sent_waves[1]["mods"].get("armor") is None, "the defender's cards aren't part of the monster record"


def test_records_store_the_cards_they_were_won_with(game):
    unlock(game.profile, "long_barrels")
    game.load_level(0)
    win_towers_level(game)
    assert game.profile.tower_record(1)[5]["mods"]["range"] == pytest.approx(1.05)


def test_enemy_mods_dont_leak_between_waves(screen):
    e = Enemy("armored", [pygame.Vector2(0, 0), pygame.Vector2(100, 0)], 1, {"armor": 0.5})
    assert e.armor == 3 and Enemy("armored", e.path, 1).armor == 6


# ---- drawing ------------------------------------------------------------------------------------
@pytest.mark.parametrize("scale", SCALES)
def test_card_screen_draws(screen, scale, mouse):
    graphics.set_scale(scale)
    g = main.Game(pygame.display.set_mode(graphics.window_size()), log_dir=None)
    mouse[:] = scaled((400, 330), scale)
    for pool, cards in (("monster", ["juggernaut", "thick_hide", "emp"]), ("tower", ["detector", "salvage"])):
        g.reward_pool, g.reward_cards = pool, cards
        g.draw()


def test_a_sure_rare_comes_first_while_any_are_left(game):
    rares = [k for k, c in UNLOCKS["monster"].items() if c["rare"]]
    for seed in range(5):
        cards = game.profile.draw_cards("monster", random.Random(seed), 3, rare=True)
        assert cards[0] in rares and len(set(cards)) == 3
    for k in rares:
        for _ in range(UNLOCKS["monster"][k]["max"]):
            game.profile.unlock("monster", k)
    assert len(game.profile.draw_cards("monster", random.Random(0), 3, rare=True)) == 3, "none left: just 3 cards"


def test_towers_side_record_tiers(game):
    """Generated waves are par (normal); a big monster record is strong."""
    assert game.record_ratio == pytest.approx(1.0) and game.record_tier == "normal"
    game.profile.monster_records["1"] = {"5": {"value": 900, "queue": ["tank"] * 75, "hp_mult": 1.0, "mods": {},
                                               "casts": []}}
    game.load_level(0)
    assert game.record_tier == "strong"
